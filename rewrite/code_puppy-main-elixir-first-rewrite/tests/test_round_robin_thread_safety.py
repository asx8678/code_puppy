"""Tests for async concurrency safety of RoundRobinModel._get_next_model."""

import asyncio
from collections import Counter
from unittest.mock import AsyncMock, MagicMock

import pytest

from code_puppy.round_robin_model import RoundRobinModel


class MockModel:
    def __init__(self, name, settings=None):
        self._name = name
        self._settings = settings
        self.request = AsyncMock(return_value=f"response_from_{name}")
        self.request_stream = MagicMock()
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


@pytest.mark.asyncio
async def test_get_next_model_concurrent_access():
    """Verify _get_next_model distributes evenly under concurrent access."""
    models = [MockModel(f"model{i}") for i in range(3)]
    rrm = RoundRobinModel(*models)

    num_concurrent = 10
    calls_per_task = 300

    async def worker():
        local = []
        for _ in range(calls_per_task):
            model = await rrm._get_next_model()
            local.append(model.model_name)
        return local

    # Run all workers concurrently
    results = await asyncio.gather(*[worker() for _ in range(num_concurrent)])

    # Flatten results
    all_results = [name for worker_results in results for name in worker_results]

    total = num_concurrent * calls_per_task  # 3000
    assert len(all_results) == total

    counts = Counter(all_results)
    expected = total // len(models)  # 1000 each
    # Each model should get exactly 1/3 of requests
    for name, count in counts.items():
        assert count == expected, (
            f"{name} got {count} requests, expected {expected}. "
            f"Distribution: {dict(counts)}"
        )


@pytest.mark.asyncio
async def test_get_next_model_concurrent_with_rotate_every():
    """Async concurrency safety with rotate_every > 1."""
    models = [MockModel(f"model{i}") for i in range(2)]
    rrm = RoundRobinModel(*models, rotate_every=3)

    num_concurrent = 6
    calls_per_task = 300  # 1800 total, divisible by 6 (rotate_every*num_models)

    async def worker():
        local = []
        for _ in range(calls_per_task):
            model = await rrm._get_next_model()
            local.append(model.model_name)
        return local

    # Run all workers concurrently
    results = await asyncio.gather(*[worker() for _ in range(num_concurrent)])

    # Flatten results
    all_results = [name for worker_results in results for name in worker_results]

    total = num_concurrent * calls_per_task
    assert len(all_results) == total

    counts = Counter(all_results)
    # Each model should get exactly half
    expected = total // len(models)
    for name, count in counts.items():
        assert count == expected, (
            f"{name} got {count} requests, expected {expected}. "
            f"Distribution: {dict(counts)}"
        )
