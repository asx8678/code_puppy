"""Tests for code_puppy/api/routers/config.py."""

from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

from code_puppy.api.app import create_app


@pytest.fixture
def mock_config():
    with (
        patch(
            "code_puppy.api.routers.config.get_config_keys", create=True
        ) as mock_keys,
        patch("code_puppy.api.routers.config.get_value", create=True) as mock_get,
        patch("code_puppy.api.routers.config.set_value", create=True) as mock_set,
        patch("code_puppy.api.routers.config.reset_value", create=True) as mock_reset,
    ):
        mock_keys.return_value = [
            "model",
            "yolo_mode",
            "api_key",
            "puppy_token",
        ]
        mock_get.side_effect = lambda k: {
            "model": "gpt-4o",
            "yolo_mode": "false",
            "api_key": "sk-12345-secret-key",
            "puppy_token": "pup_abcdef_token",
        }.get(k)
        yield {"keys": mock_keys, "get": mock_get, "set": mock_set, "reset": mock_reset}


@pytest.fixture
async def client(mock_config):
    # Need to patch imports at the point they're used in the endpoint functions
    with (
        patch("code_puppy.config.get_config_keys", mock_config["keys"], create=True),
        patch("code_puppy.config.get_value", mock_config["get"], create=True),
        patch("code_puppy.config.set_value", mock_config["set"], create=True),
        patch("code_puppy.config.reset_value", mock_config["reset"], create=True),
    ):
        app = create_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


@pytest.mark.asyncio
async def test_list_config(client: AsyncClient) -> None:
    resp = await client.get("/api/config/")
    assert resp.status_code == 200
    data = resp.json()
    assert "config" in data


@pytest.mark.asyncio
async def test_get_config_keys(client: AsyncClient) -> None:
    resp = await client.get("/api/config/keys")
    assert resp.status_code == 200
    assert "model" in resp.json()


@pytest.mark.asyncio
async def test_get_config_value(client: AsyncClient) -> None:
    resp = await client.get("/api/config/model")
    assert resp.status_code == 200
    assert resp.json()["key"] == "model"


@pytest.mark.asyncio
async def test_get_config_value_not_found(client: AsyncClient) -> None:
    resp = await client.get("/api/config/nonexistent")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_set_config_value(client: AsyncClient) -> None:
    resp = await client.put("/api/config/model", json={"value": "gpt-4"})
    assert resp.status_code == 200
    assert resp.json()["key"] == "model"


@pytest.mark.asyncio
async def test_set_config_value_not_found(client: AsyncClient) -> None:
    resp = await client.put("/api/config/nonexistent", json={"value": "x"})
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_reset_config_value(client: AsyncClient) -> None:
    resp = await client.delete("/api/config/model")
    assert resp.status_code == 200
    assert "reset" in resp.json()["message"]


@pytest.mark.asyncio
async def test_list_config_redacts_sensitive_keys(client: AsyncClient) -> None:
    """Verify that api_key and token values show '********' in list response."""
    resp = await client.get("/api/config/")
    assert resp.status_code == 200
    data = resp.json()
    assert "config" in data
    # Sensitive keys should be redacted
    assert data["config"]["api_key"] == "********"
    assert data["config"]["puppy_token"] == "********"


@pytest.mark.asyncio
async def test_get_config_value_redacts_token(client: AsyncClient) -> None:
    """Verify that token values are redacted in GET response."""
    resp = await client.get("/api/config/puppy_token")
    assert resp.status_code == 200
    data = resp.json()
    assert data["key"] == "puppy_token"
    assert data["value"] == "********"


@pytest.mark.asyncio
async def test_set_config_value_redacts_response(client: AsyncClient) -> None:
    """Verify that PUT response redacts sensitive values."""
    resp = await client.put("/api/config/api_key", json={"value": "new-secret-key"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["key"] == "api_key"
    assert data["value"] == "********"


@pytest.mark.asyncio
async def test_non_sensitive_keys_not_redacted(client: AsyncClient) -> None:
    """Verify that normal keys like 'model' show actual value, not redacted."""
    resp = await client.get("/api/config/model")
    assert resp.status_code == 200
    data = resp.json()
    assert data["key"] == "model"
    assert data["value"] == "gpt-4o"
