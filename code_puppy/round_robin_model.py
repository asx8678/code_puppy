import asyncio
import logging
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

from pydantic_ai._run_context import RunContext
from pydantic_ai.models import (
    Model,
    ModelMessage,
    ModelRequestParameters,
    ModelResponse,
    ModelSettings,
    StreamedResponse,
)

from code_puppy.model_availability import model_availability_service

logger = logging.getLogger(__name__)

try:
    from opentelemetry.context import get_current_span
except ImportError:
    # If opentelemetry is not installed, provide a dummy implementation
    def get_current_span():
        class DummySpan:
            def is_recording(self):
                return False

            def set_attributes(self, attributes):
                pass

        return DummySpan()


@dataclass(init=False)
class RoundRobinModel(Model):
    """A model that cycles through multiple models in a round-robin fashion.

    This model distributes requests across multiple candidate models to help
    overcome rate limits or distribute load.
    """

    models: list[Model]
    _current_index: int = field(default=0, repr=False)
    _model_name: str = field(repr=False)
    _rotate_every: int = field(default=1, repr=False)
    _request_count: int = field(default=0, repr=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)

    def __init__(
        self,
        *models: Model,
        rotate_every: int = 1,
        settings: ModelSettings | None = None,
    ):
        """Initialize a round-robin model instance.

        Args:
            models: The model instances to cycle through.
            rotate_every: Number of requests before rotating to the next model (default: 1).
            settings: Model settings that will be used as defaults for this model.
        """
        super().__init__(settings=settings)
        if not models:
            raise ValueError("At least one model must be provided")
        if rotate_every < 1:
            raise ValueError("rotate_every must be at least 1")
        self.models = list(models)
        self._current_index = 0
        self._request_count = 0
        self._rotate_every = rotate_every
        self._lock = asyncio.Lock()

    @property
    def model_name(self) -> str:
        """The model name showing this is a round-robin model with its candidates."""
        base_name = f"round_robin:{','.join(model.model_name for model in self.models)}"
        if self._rotate_every != 1:
            return f"{base_name}:rotate_every={self._rotate_every}"
        return base_name

    @property
    def system(self) -> str:
        """System prompt from the current model."""
        return self.models[self._current_index].system

    @property
    def base_url(self) -> str | None:
        """Base URL from the current model."""
        return self.models[self._current_index].base_url

    async def _get_next_model(self) -> Model:
        """Get the next available model in the round-robin sequence.

        Consults :data:`~code_puppy.model_availability.model_availability_service`
        and skips models that are currently unavailable (terminal or sticky_retry
        with consumed attempt).  If *all* models are unavailable the method falls
        back to the plain round-robin choice so callers always receive a model.
        """
        async with self._lock:
            n = len(self.models)
            # Build a candidate list: starting at _current_index, wrap around.
            ordered_names = [
                self.models[(self._current_index + i) % n].model_name for i in range(n)
            ]

            result = model_availability_service.select_first_available(ordered_names)

            if result.selected_model is not None:
                # Find the Model object that matches the selected name.
                for m in self.models:
                    if m.model_name == result.selected_model:
                        if result.skipped:
                            logger.debug(
                                "round_robin: skipped %d unavailable model(s), using %s",
                                len(result.skipped),
                                result.selected_model,
                            )
                        # Advance index by the number of models we skipped + 1.
                        skip_count = len(result.skipped)
                        self._request_count += 1
                        if self._request_count >= self._rotate_every:
                            self._current_index = (
                                self._current_index + skip_count + 1
                            ) % n
                            self._request_count = 0
                        return m

            # All models unavailable – fall back to plain round-robin to avoid
            # a hard failure.  The upstream caller can still raise if needed.
            logger.warning(
                "round_robin: all %d model(s) marked unavailable; falling back to "
                "plain round-robin selection",
                len(self.models),
            )
            model = self.models[self._current_index]
            self._request_count += 1
            if self._request_count >= self._rotate_every:
                self._current_index = (self._current_index + 1) % n
                self._request_count = 0
            return model

    async def request(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> ModelResponse:
        """Make a request using the next available model in the round-robin sequence."""
        from code_puppy.model_availability import availability_service

        current_model = await self._get_next_model()
        merged_settings, prepared_params = current_model.prepare_request(
            model_settings, model_request_parameters
        )

        try:
            response = await current_model.request(
                messages, merged_settings, prepared_params
            )
            availability_service.mark_healthy(current_model.model_name)
            self._set_span_attributes(current_model)
            return response
        except Exception as e:
            self._track_failure(current_model.model_name, e)
            raise

    @asynccontextmanager
    async def request_stream(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
        run_context: RunContext[Any] | None = None,
    ) -> AsyncIterator[StreamedResponse]:
        """Make a streaming request using the next model in the round-robin sequence."""
        from code_puppy.model_availability import availability_service

        current_model = await self._get_next_model()
        # Use prepare_request to merge settings and customize parameters
        merged_settings, prepared_params = current_model.prepare_request(
            model_settings, model_request_parameters
        )

        try:
            async with current_model.request_stream(
                messages, merged_settings, prepared_params, run_context
            ) as response:
                self._set_span_attributes(current_model)
                yield response
            availability_service.mark_healthy(current_model.model_name)
        except Exception as e:
            self._track_failure(current_model.model_name, e)
            raise

    @staticmethod
    def _track_failure(model_name: str, error: Exception) -> None:
        """Mark a model based on the type of failure."""
        from code_puppy.model_availability import availability_service

        err_str = str(error).lower()
        status_code = getattr(error, "status_code", getattr(error, "status", None))

        if status_code == 429 or "quota" in err_str or "rate limit" in err_str:
            availability_service.mark_terminal(model_name, "quota")
        elif isinstance(status_code, int) and 500 <= status_code < 600:
            availability_service.mark_sticky_retry(model_name)
        elif "overloaded" in err_str or "capacity" in err_str:
            availability_service.mark_sticky_retry(model_name)

    def _set_span_attributes(self, model: Model):
        """Set span attributes for observability."""
        with suppress(Exception):
            span = get_current_span()
            if span.is_recording():
                attributes = getattr(span, "attributes", {})
                if attributes.get("gen_ai.request.model") == self.model_name:
                    span.set_attributes({"gen_ai.response.model": model.model_name})
