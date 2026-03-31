"""Tests for HealthMonitor wiring in MCPManager."""

from unittest.mock import MagicMock
from code_puppy.mcp_.manager import MCPManager
from code_puppy.mcp_.health_monitor import HealthMonitor


class TestHealthMonitorWiring:
    def test_health_monitor_starts_as_none(self):
        """MCPManager starts with no health monitor."""
        manager = MCPManager()
        assert manager._health_monitor is None

    def test_get_health_monitor_lazy_init(self):
        """_get_health_monitor() creates HealthMonitor on first call."""
        manager = MCPManager()
        monitor = manager._get_health_monitor()
        assert isinstance(monitor, HealthMonitor)
        assert monitor.check_interval == 30

    def test_get_health_monitor_singleton(self):
        """_get_health_monitor() returns same instance on subsequent calls."""
        manager = MCPManager()
        monitor1 = manager._get_health_monitor()
        monitor2 = manager._get_health_monitor()
        assert monitor1 is monitor2

    def test_get_server_health_returns_none_when_no_monitor(self):
        """get_server_health() returns None when health monitor not initialized."""
        manager = MCPManager()
        result = manager.get_server_health("some-server")
        assert result is None

    def test_get_server_health_returns_none_on_exception(self):
        """get_server_health() returns None if monitor raises."""
        manager = MCPManager()
        manager._health_monitor = MagicMock()
        # Make .get() on health_history raise to trigger the except block
        manager._health_monitor.health_history.get.side_effect = RuntimeError("boom")
        result = manager.get_server_health("some-server")
        assert result is None

    def test_get_server_health_returns_dict_for_unmonitored_server(self):
        """get_server_health() returns dict with is_healthy=None for unknown server."""
        manager = MCPManager()
        manager._health_monitor = HealthMonitor(check_interval=30)
        result = manager.get_server_health("unknown-server-id")
        assert result is not None
        assert result["server_id"] == "unknown-server-id"
        assert result["is_monitoring"] is False
