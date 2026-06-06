from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from code_puppy.round_robin_model import RoundRobinModel


class MockModel:
    """A simple mock model that implements the required interface."""

    def __init__(self, name, settings=None):
        self._name = name
        self._settings = settings
        self.request = AsyncMock(return_value=f"response_from_{name}")
        self._stream_response = MagicMock()
        self.customize_request_parameters = lambda x: x

    @property
    def model_name(self):
        return self._name

    @property
    def settings(self):
        return self._settings

    @property
    def system(self):
        return f"system_{self._name}"

    @property
    def base_url(self):
        return f"https://api.{self._name}.com"

    def model_attributes(self, model):
        return {"model_name": self._name}

    def prepare_request(self, model_settings, model_request_parameters):
        return model_settings, model_request_parameters

    @asynccontextmanager
    async def request_stream(self, messages, settings, params, run_context=None):
        yield self._stream_response


class TestRoundRobinModel:
    def test_initialization(self):
        """Basic initialization sets defaults."""
        rrm = RoundRobinModel(MockModel("model1"), MockModel("model2"))
        assert len(rrm.models) == 2
        assert rrm._current_index == 0
        assert rrm._request_count == 0
        assert rrm._rotate_every == 1

    def test_initialization_with_settings(self):
        settings = {"temperature": 0.7}
        rrm = RoundRobinModel(MockModel("model1"), settings=settings)
        assert rrm.settings == settings

    def test_initialization_single_model(self):
        rrm = RoundRobinModel(MockModel("single_model"))
        assert len(rrm.models) == 1
        assert rrm._current_index == 0
        assert rrm.model_name == "round_robin:single_model"

    @pytest.mark.parametrize(
        "kwargs, match",
        [
            ({}, "At least one model must be provided"),  # no models
            ({"rotate_every": 0}, "rotate_every must be at least 1"),
            ({"rotate_every": -5}, "rotate_every must be at least 1"),
        ],
    )
    def test_initialization_validation_errors(self, kwargs, match):
        models = () if "rotate_every" not in kwargs else (MockModel("m"),)
        with pytest.raises(ValueError, match=match):
            RoundRobinModel(*models, **kwargs)

    @pytest.mark.parametrize(
        "names, rotate_every, calls, expected",
        [
            # rotate_every=1: alternate every call, cycling
            (["model1", "model2"], 1, 3, ["model1", "model2", "model1"]),
            # three models cycle
            (["m1", "m2", "m3"], 1, 6, ["m1", "m2", "m3", "m1", "m2", "m3"]),
            # rotate_every=2: two of each before rotating
            (["model1", "model2"], 2, 4, ["model1", "model1", "model2", "model2"]),
            # single model never rotates regardless of rotate_every
            (["single"], 3, 5, ["single"] * 5),
        ],
    )
    def test_rotation_sequence(self, names, rotate_every, calls, expected):
        rrm = RoundRobinModel(*(MockModel(n) for n in names), rotate_every=rotate_every)
        actual = [rrm._get_next_model().model_name for _ in range(calls)]
        assert actual == expected

    def test_rotation_updates_index_and_count(self):
        """Index advances after rotate threshold, count resets."""
        rrm = RoundRobinModel(MockModel("model1"), MockModel("model2"), rotate_every=3)
        # First two calls increment count without rotating
        rrm._get_next_model()
        assert rrm._request_count == 1 and rrm._current_index == 0
        rrm._get_next_model()
        assert rrm._request_count == 2 and rrm._current_index == 0
        # Third call triggers rotation and resets count
        rrm._get_next_model()
        assert rrm._request_count == 0 and rrm._current_index == 1

    def test_single_model_index_never_changes(self):
        model = MockModel("single")
        rrm = RoundRobinModel(model, rotate_every=3)
        for _ in range(10):
            assert rrm._get_next_model() is model
            assert rrm._current_index == 0

    def test_large_rotate_every_value(self):
        rrm = RoundRobinModel(MockModel("m1"), MockModel("m2"), rotate_every=100)
        for _ in range(99):
            assert rrm._get_next_model().model_name == "m1"
        assert rrm._request_count == 99
        assert rrm._current_index == 0
        # 100th call returns m1 but rotates after
        assert rrm._get_next_model().model_name == "m1"
        assert rrm._current_index == 1
        assert rrm._request_count == 0
        assert rrm._get_next_model().model_name == "m2"

    @pytest.mark.parametrize(
        "rotate_every, expected",
        [
            (1, "round_robin:m1,m2,m3"),
            (5, "round_robin:m1,m2,m3:rotate_every=5"),
        ],
    )
    def test_model_name_property(self, rotate_every, expected):
        rrm = RoundRobinModel(
            MockModel("m1"),
            MockModel("m2"),
            MockModel("m3"),
            rotate_every=rotate_every,
        )
        assert rrm.model_name == expected

    def test_properties_delegate_to_current_model(self):
        rrm = RoundRobinModel(MockModel("model1"), MockModel("model2"))
        assert rrm.system == "system_model1"
        assert rrm.base_url == "https://api.model1.com"
        rrm._get_next_model()  # rotate to model2
        assert rrm.system == "system_model2"
        assert rrm.base_url == "https://api.model2.com"

    @pytest.mark.asyncio
    async def test_request_method_uses_rotation(self):
        models = [MockModel("model1"), MockModel("model2")]
        rrm = RoundRobinModel(*models)
        for _ in range(3):
            await rrm.request([], None, MagicMock())
        assert models[0].request.call_count == 2
        assert models[1].request.call_count == 1

    @pytest.mark.asyncio
    async def test_request_propagates_exception(self):
        """request() re-raises model errors without trying other models."""
        model = MockModel("model1")
        model.request = AsyncMock(side_effect=RuntimeError("boom"))
        rrm = RoundRobinModel(model)
        with pytest.raises(RuntimeError, match="boom"):
            await rrm.request([], None, MagicMock())


class TestRequestStream:
    @pytest.mark.anyio
    async def test_request_stream_rotates(self):
        m1, m2 = MockModel("model1"), MockModel("model2")
        rrm = RoundRobinModel(m1, m2)
        async with rrm.request_stream([], None, MagicMock()) as r1:
            pass
        async with rrm.request_stream([], None, MagicMock()) as r2:
            pass
        assert r1 == m1._stream_response
        assert r2 == m2._stream_response

    @pytest.mark.anyio
    async def test_request_stream_with_run_context(self):
        m1 = MockModel("model1")
        rrm = RoundRobinModel(m1)
        ctx = MagicMock()
        async with rrm.request_stream([], None, MagicMock(), run_context=ctx) as r:
            assert r == m1._stream_response


class TestSetSpanAttributes:
    @pytest.mark.parametrize(
        "is_recording, attributes, expect_set",
        [
            # recording + matching model name -> attributes set
            (True, "match", True),
            # recording + non-matching model name -> not set
            (True, {"gen_ai.request.model": "something_else"}, False),
            # not recording -> not set
            (False, None, False),
        ],
    )
    def test_set_span_attributes(self, is_recording, attributes, expect_set):
        m1 = MockModel("model1")
        rrm = RoundRobinModel(m1)
        mock_span = MagicMock()
        mock_span.is_recording.return_value = is_recording
        if attributes == "match":
            attributes = {"gen_ai.request.model": rrm.model_name}
        if attributes is not None:
            mock_span.attributes = attributes
        with patch(
            "code_puppy.round_robin_model.get_current_span", return_value=mock_span
        ):
            rrm._set_span_attributes(m1)
        if expect_set:
            mock_span.set_attributes.assert_called_once_with({"model_name": "model1"})
        else:
            mock_span.set_attributes.assert_not_called()

    def test_set_span_attributes_no_attributes_does_not_crash(self):
        rrm = RoundRobinModel(MockModel("model1"))
        mock_span = MagicMock()
        mock_span.is_recording.return_value = True
        del mock_span.attributes
        with patch(
            "code_puppy.round_robin_model.get_current_span", return_value=mock_span
        ):
            rrm._set_span_attributes(MockModel("model1"))  # should not raise

    def test_set_span_attributes_exception_suppressed(self):
        rrm = RoundRobinModel(MockModel("model1"))
        with patch(
            "code_puppy.round_robin_model.get_current_span",
            side_effect=Exception("boom"),
        ):
            rrm._set_span_attributes(MockModel("model1"))  # should not raise
