"""Tests for adversarial planning slash commands and session lifecycle."""

import pytest
from unittest.mock import Mock, patch

from code_puppy.plugins.adversarial_planning.commands import (
    register_session,
    unregister_session,
    _active_sessions,
    _handle_status,
    _handle_abort,
)


class TestSessionLifecycle:
    """Tests for session registration and cleanup."""
    
    def setup_method(self):
        """Clear active sessions before each test."""
        _active_sessions.clear()
    
    def test_register_session_adds_to_registry(self):
        """Session should appear in registry after registration."""
        mock_orchestrator = Mock()
        mock_orchestrator.session_id = "test-session-123"
        mock_orchestrator.session = Mock()
        
        register_session(mock_orchestrator)
        
        assert "test-session-123" in _active_sessions
        # The orchestrator is stored, not just the session
        assert _active_sessions["test-session-123"] is mock_orchestrator
    
    def test_unregister_session_removes_from_registry(self):
        """Session should be removed from registry after unregistration."""
        mock_orchestrator = Mock()
        mock_orchestrator.session_id = "test-session-456"
        mock_orchestrator.session = Mock()
        
        register_session(mock_orchestrator)
        assert "test-session-456" in _active_sessions
        
        unregister_session("test-session-456")
        assert "test-session-456" not in _active_sessions
    
    def test_unregister_nonexistent_session_no_error(self):
        """Unregistering a missing session should not raise."""
        # Should not raise
        unregister_session("nonexistent-session")


class TestStatusCommand:
    """Tests for /ap-status command."""
    
    def setup_method(self):
        _active_sessions.clear()
    
    def test_status_shows_no_sessions(self):
        """Status should indicate no active sessions."""
        # Patch at the messaging module level since functions import from there
        with patch("code_puppy.messaging.emit_info") as mock_emit:
            result = _handle_status()
            assert result is True
            # Check that emit_info was called with "no active" message
            mock_emit.assert_called_once()
            call_args = mock_emit.call_args[0][0]
            assert "no active" in call_args.lower() or "0" in call_args
    
    def test_status_shows_active_session(self):
        """Status should list active sessions."""
        # Create mock orchestrator with session
        mock_session = Mock()
        mock_session.mode_selected = "standard"
        mock_session.current_phase = "1_planning"
        mock_session.global_stop_reason = None
        
        mock_orchestrator = Mock()
        mock_orchestrator.session = mock_session
        
        _active_sessions["session-789"] = mock_orchestrator
        
        with patch("code_puppy.messaging.emit_info") as mock_emit:
            result = _handle_status()
            assert result is True
            mock_emit.assert_called_once()
            call_args = mock_emit.call_args[0][0]
            # Should contain session ID or session info
            assert "session-789" in call_args or "STANDARD" in call_args


class TestAbortCommand:
    """Tests for /ap-abort command."""
    
    def setup_method(self):
        _active_sessions.clear()
    
    def test_abort_sets_stop_reason(self):
        """Abort should set global_stop_reason on session."""
        mock_session = Mock()
        mock_session.global_stop_reason = None
        
        mock_orchestrator = Mock()
        mock_orchestrator.session = mock_session
        
        _active_sessions["abort-test-session"] = mock_orchestrator
        
        with patch("code_puppy.messaging.emit_warning"):
            _handle_abort()
        
        assert mock_session.global_stop_reason is not None
        assert "abort" in mock_session.global_stop_reason.lower()
    
    def test_abort_removes_session(self):
        """Abort should remove session from registry."""
        mock_session = Mock()
        mock_session.global_stop_reason = None
        
        mock_orchestrator = Mock()
        mock_orchestrator.session = mock_session
        
        _active_sessions["abort-cleanup-test"] = mock_orchestrator
        
        with patch("code_puppy.messaging.emit_warning"):
            _handle_abort()
        
        # Session should be removed from registry
        assert "abort-cleanup-test" not in _active_sessions
    
    def test_abort_no_sessions(self):
        """Abort with no sessions should emit info message."""
        with patch("code_puppy.messaging.emit_info") as mock_emit:
            result = _handle_abort()
            assert result is True
            mock_emit.assert_called_once()
            call_args = mock_emit.call_args[0][0]
            assert "no active" in call_args.lower() or "abort" in call_args.lower()
