"""Configuration management API endpoints."""

import re
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

# Patterns that indicate a sensitive key whose value should be redacted.
_SENSITIVE_PATTERNS = re.compile(
    r"(api_key|token|secret|password|credential|auth_key|private_key)",
    re.IGNORECASE,
)
_REDACTED = "********"


def _redact(key: str, value: Any) -> Any:
    """Return ``********`` for values whose key name looks sensitive."""
    if isinstance(key, str) and _SENSITIVE_PATTERNS.search(key):
        return _REDACTED
    return value

router = APIRouter()


class ConfigValue(BaseModel):
    key: str
    value: Any


class ConfigUpdate(BaseModel):
    value: Any


@router.get("/")
async def list_config() -> dict[str, Any]:
    """List all configuration keys and their current values."""
    from code_puppy.config import get_config_keys, get_value

    config = {}
    for key in get_config_keys():
        config[key] = _redact(key, get_value(key))
    return {"config": config}


@router.get("/keys")
async def get_config_keys_list() -> list[str]:
    """Get list of all valid configuration keys."""
    from code_puppy.config import get_config_keys

    return get_config_keys()


@router.get("/{key}")
async def get_config_value(key: str) -> ConfigValue:
    """Get a specific configuration value."""
    from code_puppy.config import get_config_keys, get_value

    valid_keys = get_config_keys()
    if key not in valid_keys:
        raise HTTPException(
            404, f"Config key '{key}' not found. Valid keys: {valid_keys}"
        )

    value = get_value(key)
    return ConfigValue(key=key, value=_redact(key, value))


@router.put("/{key}")
async def set_config_value(key: str, update: ConfigUpdate) -> ConfigValue:
    """Set a configuration value."""
    from code_puppy.config import get_config_keys, get_value, set_value

    valid_keys = get_config_keys()
    if key not in valid_keys:
        raise HTTPException(
            404, f"Config key '{key}' not found. Valid keys: {valid_keys}"
        )

    set_value(key, str(update.value))
    return ConfigValue(key=key, value=_redact(key, get_value(key)))


@router.delete("/{key}")
async def reset_config_value(key: str) -> dict[str, str]:
    """Reset a configuration value to default (remove from config file)."""
    from code_puppy.config import reset_value

    reset_value(key)
    return {"message": f"Config key '{key}' reset to default"}
