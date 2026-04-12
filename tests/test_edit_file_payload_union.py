"""Regression test: EditFilePayload must be a three-way union type.

This guards against accidental collapse of the union (e.g. reverting to a
single type) which would break discriminated-union dispatch in model
transports (antigravity, gemini) and schema generation.
"""

import types
import typing
from typing import get_args

import pytest
from pydantic import TypeAdapter

from code_puppy.tools.file_modifications import (
    ContentPayload,
    DeleteSnippetPayload,
    EditFilePayload,
    Replacement,
    ReplacementsPayload,
)


# ---------------------------------------------------------------------------
# 1. Structural checks
# ---------------------------------------------------------------------------


def test_edit_file_payload_is_three_way_union():
    """EditFilePayload must be a Union with exactly 3 members."""
    origin = typing.get_origin(EditFilePayload)
    assert origin is types.UnionType, (
        f"EditFilePayload origin should be types.UnionType, got {origin}"
    )

    args = get_args(EditFilePayload)
    assert len(args) == 3, (
        f"EditFilePayload should have 3 union members, got {len(args)}: {args}"
    )

    expected = {DeleteSnippetPayload, ReplacementsPayload, ContentPayload}
    assert set(args) == expected, (
        f"Union members mismatch. Expected {expected}, got {set(args)}"
    )


# ---------------------------------------------------------------------------
# 2. TypeAdapter round-trip for each payload form
# ---------------------------------------------------------------------------

_ADAPTER = TypeAdapter(EditFilePayload)


def _valid_delete_snippet() -> dict:
    return {"file_path": "/tmp/dog.go", "delete_snippet": "bark()\n"}


def _valid_replacements() -> dict:
    return {
        "file_path": "/tmp/dog.go",
        "replacements": [{"old_str": "bark", "new_str": "woof"}],
    }


def _valid_content() -> dict:
    return {"file_path": "/tmp/dog.go", "content": "woof()\n", "overwrite": True}


@pytest.mark.parametrize(
    "payload_fn, expected_type",
    [
        (_valid_delete_snippet, DeleteSnippetPayload),
        (_valid_replacements, ReplacementsPayload),
        (_valid_content, ContentPayload),
    ],
    ids=["delete_snippet", "replacements", "content"],
)
def test_type_adapter_validates_each_form(payload_fn, expected_type):
    """Each payload variant must validate through the union TypeAdapter."""
    data = payload_fn()
    result = _ADAPTER.validate_python(data)
    assert isinstance(result, expected_type), (
        f"Expected {expected_type.__name__}, got {type(result).__name__}"
    )


def test_type_adapter_rejects_invalid_payload():
    """A dict missing required fields must raise ValidationError."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        _ADAPTER.validate_python({"file_path": "/tmp/bad.go"})


def test_replacements_payload_rejects_malformed_replacement():
    """A Replacement with missing fields must raise ValidationError."""
    from pydantic import ValidationError

    adapter = TypeAdapter(ReplacementsPayload)
    with pytest.raises(ValidationError):
        adapter.validate_python(
            {"file_path": "/tmp/bad.go", "replacements": [{"old_str": "x"}]}
        )
