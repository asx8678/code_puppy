"""Tests for Elixir transport wiring in code_puppy/utils/hashline.py (bd-119).

Covers the integration between hashline.py and the Elixir transport layer:
- is_using_elixir() reflects transport availability
- compute_line_hash / format_hashlines / strip_hashline_prefixes route to Elixir
- Fallback to Python on transport errors (for non-validate operations)
- validate_hashline_anchor raises RuntimeError when Elixir hashes were used
  but the backend is now unavailable (backend-mixing guard)
- The _ELIXIR_HASH_USED flag is set on successful Elixir hash operations
"""

from __future__ import annotations

import re

import pytest

import code_puppy.utils.hashline as hashline_mod
from code_puppy.utils.hashline import (
    NIBBLE_STR,
    compute_line_hash,
    format_hashlines,
    strip_hashline_prefixes,
    validate_hashline_anchor,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class MockTransport:
    """Mock Elixir transport for testing Elixir routing path."""

    def __init__(
        self,
        responses: dict[str, dict] | None = None,
        raise_on: str | None = None,
    ) -> None:
        self.calls: list[dict] = []
        self.responses = responses or {}
        self.raise_on = raise_on

    def _send_request(self, method: str, params: dict) -> dict:
        self.calls.append({"method": method, "params": params})
        if self.raise_on == method:
            raise RuntimeError("Transport error")
        return self.responses.get(method, {})


@pytest.fixture(autouse=True)
def _reset_elixir_hash_flag() -> None:
    """Reset the backend-mixing guard and disable real transport before each test."""
    hashline_mod._ELIXIR_HASH_USED = False
    hashline_mod._get_transport = lambda: None
    yield
    hashline_mod._ELIXIR_HASH_USED = False


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestElixirTransportWiring:
    """Tests for Elixir transport wiring (bd-119)."""

    def test_is_using_elixir_returns_true_when_transport_available(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """is_using_elixir() returns True when transport is accessible."""
        mock_transport = MockTransport()
        monkeypatch.setattr(hashline_mod, "_get_transport", lambda: mock_transport)
        assert hashline_mod.is_using_elixir() is True

    def test_is_using_elixir_returns_false_when_transport_unavailable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """is_using_elixir() returns False when transport is not accessible."""
        monkeypatch.setattr(hashline_mod, "_get_transport", lambda: None)
        assert hashline_mod.is_using_elixir() is False

    def test_compute_line_hash_uses_elixir_when_available(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """compute_line_hash routes to Elixir when transport is available."""
        mock_transport = MockTransport(responses={"hashline_compute": {"hash": "EL"}})
        monkeypatch.setattr(hashline_mod, "_get_transport", lambda: mock_transport)

        result = hashline_mod.compute_line_hash(5, "test line")

        assert result == "EL"
        assert mock_transport.calls == [
            {
                "method": "hashline_compute",
                "params": {"idx": 5, "line": "test line"},
            }
        ]

    def test_compute_line_hash_falls_back_on_exception(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """compute_line_hash falls back to Python when Elixir raises."""
        mock_transport = MockTransport(raise_on="hashline_compute")
        monkeypatch.setattr(hashline_mod, "_get_transport", lambda: mock_transport)

        result = hashline_mod.compute_line_hash(1, "hello")

        assert len(result) == 2
        assert result[0] in NIBBLE_STR
        assert result[1] in NIBBLE_STR

    def test_format_hashlines_uses_elixir_when_available(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """format_hashlines routes to Elixir when transport is available."""
        mock_transport = MockTransport(
            responses={"hashline_format": {"formatted": "1#EL:hello\n2#IX:world"}}
        )
        monkeypatch.setattr(hashline_mod, "_get_transport", lambda: mock_transport)

        result = hashline_mod.format_hashlines("hello\nworld", start_line=1)

        assert result == "1#EL:hello\n2#IX:world"
        assert mock_transport.calls == [
            {
                "method": "hashline_format",
                "params": {"text": "hello\nworld", "start_line": 1},
            }
        ]

    def test_format_hashlines_falls_back_on_exception(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """format_hashlines falls back to Python when Elixir raises."""
        mock_transport = MockTransport(raise_on="hashline_format")
        monkeypatch.setattr(hashline_mod, "_get_transport", lambda: mock_transport)

        result = hashline_mod.format_hashlines("hello")

        assert re.match(r"^1#[A-Z]{2}:hello$", result)

    def test_strip_hashlines_uses_elixir_when_available(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """strip_hashline_prefixes routes to Elixir when transport is available."""
        mock_transport = MockTransport(
            responses={"hashline_strip": {"stripped": "hello\nworld"}}
        )
        monkeypatch.setattr(hashline_mod, "_get_transport", lambda: mock_transport)

        result = hashline_mod.strip_hashline_prefixes("1#AB:hello\n2#CD:world")

        assert result == "hello\nworld"
        assert mock_transport.calls == [
            {
                "method": "hashline_strip",
                "params": {"text": "1#AB:hello\n2#CD:world"},
            }
        ]

    def test_strip_hashlines_falls_back_on_exception(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """strip_hashline_prefixes falls back to Python when Elixir raises."""
        mock_transport = MockTransport(raise_on="hashline_strip")
        monkeypatch.setattr(hashline_mod, "_get_transport", lambda: mock_transport)

        text = "1#AB:hello"
        result = hashline_mod.strip_hashline_prefixes(text)

        assert result == "hello"

    def test_validate_hashline_anchor_uses_elixir_when_available(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """validate_hashline_anchor routes to Elixir when transport is available."""
        mock_transport = MockTransport(responses={"hashline_validate": {"valid": True}})
        monkeypatch.setattr(hashline_mod, "_get_transport", lambda: mock_transport)

        result = hashline_mod.validate_hashline_anchor(5, "test", "AB")

        assert result is True
        assert mock_transport.calls == [
            {
                "method": "hashline_validate",
                "params": {"idx": 5, "line": "test", "expected_hash": "AB"},
            }
        ]

    def test_validate_raises_when_elixir_used_but_now_unavailable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """validate_hashline_anchor raises RuntimeError when Elixir was used
        for hashing but is now unavailable (backend-mixing guard)."""
        mock_transport = MockTransport(responses={"hashline_compute": {"hash": "EL"}})
        monkeypatch.setattr(hashline_mod, "_get_transport", lambda: mock_transport)

        # Use Elixir to generate a hash -> _ELIXIR_HASH_USED = True
        compute_line_hash(1, "hello")
        assert hashline_mod._ELIXIR_HASH_USED is True

        # Now Elixir goes away
        monkeypatch.setattr(hashline_mod, "_get_transport", lambda: None)

        with pytest.raises(RuntimeError, match="Elixir backend was used"):
            validate_hashline_anchor(1, "hello", "EL")

    def test_validate_falls_back_when_elixir_never_used(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """validate falls back to Python when Elixir was never used for hashing."""
        assert hashline_mod._ELIXIR_HASH_USED is False
        monkeypatch.setattr(hashline_mod, "_get_transport", lambda: None)

        # Compute hash via Python fallback
        h = hashline_mod._py_compute_line_hash(3, "content")
        result = validate_hashline_anchor(3, "content", h)

        assert result is True

    def test_strip_does_not_set_elixir_hash_used(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """strip_hashline_prefixes does NOT set _ELIXIR_HASH_USED."""
        mock_transport = MockTransport(
            responses={"hashline_strip": {"stripped": "hello"}}
        )
        monkeypatch.setattr(hashline_mod, "_get_transport", lambda: mock_transport)

        strip_hashline_prefixes("1#AB:hello")

        assert hashline_mod._ELIXIR_HASH_USED is False

    def test_elixir_methods_return_none_when_no_transport(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """All Elixir try functions return None when transport is unavailable."""
        monkeypatch.setattr(hashline_mod, "_get_transport", lambda: None)

        assert hashline_mod._try_elixir_compute_line_hash(1, "test") is None
        assert hashline_mod._try_elixir_format_hashlines("test", 1) is None
        assert hashline_mod._try_elixir_strip_hashline_prefixes("test") is None
        assert (
            hashline_mod._try_elixir_validate_hashline_anchor(1, "test", "AB") is None
        )

    def test_elixir_methods_catch_all_exceptions(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """All Elixir try functions catch exceptions and return None."""

        class BrokenTransport:
            def _send_request(self, method: str, params: dict) -> dict:
                raise RuntimeError("Transport broken")

        monkeypatch.setattr(hashline_mod, "_get_transport", lambda: BrokenTransport())

        assert hashline_mod._try_elixir_compute_line_hash(1, "test") is None
        assert hashline_mod._try_elixir_format_hashlines("test", 1) is None
        assert hashline_mod._try_elixir_strip_hashline_prefixes("test") is None
        assert (
            hashline_mod._try_elixir_validate_hashline_anchor(1, "test", "AB") is None
        )

    def test_compute_line_hash_uses_start_line_in_elixir(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """compute_line_hash passes correct idx to Elixir."""
        calls: list[tuple[str, dict]] = []

        class CapturingTransport:
            def _send_request(self, method: str, params: dict) -> dict:
                calls.append((method, params))
                return {"hash": "ZZ"}

        monkeypatch.setattr(
            hashline_mod, "_get_transport", lambda: CapturingTransport()
        )

        hashline_mod.compute_line_hash(42, "line content")

        assert calls == [("hashline_compute", {"idx": 42, "line": "line content"})]

    def test_validate_returns_elixir_result_false(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """validate_hashline_anchor returns False from Elixir when hash mismatch."""
        mock_transport = MockTransport(
            responses={"hashline_validate": {"valid": False}}
        )
        monkeypatch.setattr(hashline_mod, "_get_transport", lambda: mock_transport)

        result = hashline_mod.validate_hashline_anchor(1, "content", "WRONG")

        assert result is False

    def test_elixir_hash_used_flag_set_on_compute_success(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """_ELIXIR_HASH_USED is set to True after a successful Elixir compute."""
        mock_transport = MockTransport(responses={"hashline_compute": {"hash": "XX"}})
        monkeypatch.setattr(hashline_mod, "_get_transport", lambda: mock_transport)

        assert hashline_mod._ELIXIR_HASH_USED is False
        compute_line_hash(1, "hello")
        assert hashline_mod._ELIXIR_HASH_USED is True

    def test_elixir_hash_used_flag_set_on_format_success(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """_ELIXIR_HASH_USED is set to True after a successful Elixir format."""
        mock_transport = MockTransport(
            responses={"hashline_format": {"formatted": "1#XX:hello"}}
        )
        monkeypatch.setattr(hashline_mod, "_get_transport", lambda: mock_transport)

        assert hashline_mod._ELIXIR_HASH_USED is False
        format_hashlines("hello")
        assert hashline_mod._ELIXIR_HASH_USED is True

    def test_elixir_hash_used_flag_set_on_validate_success(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """_ELIXIR_HASH_USED is set to True after a successful Elixir validate."""
        mock_transport = MockTransport(responses={"hashline_validate": {"valid": True}})
        monkeypatch.setattr(hashline_mod, "_get_transport", lambda: mock_transport)

        assert hashline_mod._ELIXIR_HASH_USED is False
        validate_hashline_anchor(1, "test", "AB")
        assert hashline_mod._ELIXIR_HASH_USED is True

    def test_elixir_compute_failure_does_not_set_flag(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """_ELIXIR_HASH_USED stays False when Elixir compute fails."""
        mock_transport = MockTransport(raise_on="hashline_compute")
        monkeypatch.setattr(hashline_mod, "_get_transport", lambda: mock_transport)

        compute_line_hash(1, "hello")

        assert hashline_mod._ELIXIR_HASH_USED is False
