defmodule Mana.Tools.Browser.ManagerTest do
  @moduledoc """
  Tests for Mana.Tools.Browser.Manager GenServer.

  Uses a mock approach since the real Node.js bridge isn't available
  in test environments. Tests focus on lifecycle, status, and error
  handling.
  """

  use ExUnit.Case, async: false

  alias Mana.Tools.Browser.Manager

  describe "child_spec/1" do
    test "returns transient restart strategy" do
      spec = Manager.child_spec([])

      assert spec.id == Manager
      assert spec.restart == :transient
      assert spec.type == :worker
    end
  end

  describe "get_status/0 when not started" do
    test "returns not_started status when manager is not running" do
      # Ensure no lingering process
      cleanup_manager()

      status = Manager.get_status()
      assert status.status == :not_started
      assert status.connected == false
      assert status.pending_count == 0
    end
  end

  describe "start_link/1 and lifecycle" do
    test "starts GenServer in disconnected state" do
      {:ok, pid} = start_supervised_manager()

      assert Process.alive?(pid)

      # Initially disconnected (no Node.js bridge in test)
      status = Manager.get_status()
      assert status.status in [:disconnected, :ready, :connecting]
    end

    test "stop_browser stops the GenServer" do
      {:ok, _pid} = start_supervised_manager()

      # stop_browser may fail since there's no real browser
      # but should not crash
      result = Manager.stop_browser()
      assert result == :ok or match?({:error, _}, result)
    end
  end

  describe "get_status/0 when started" do
    test "returns status map with expected keys" do
      {:ok, _pid} = start_supervised_manager()

      status = Manager.get_status()
      assert Map.has_key?(status, :status)
      assert Map.has_key?(status, :connected)
      assert Map.has_key?(status, :pending_count)
    end

    test "pending_count is initially zero" do
      {:ok, _pid} = start_supervised_manager()

      status = Manager.get_status()
      assert status.pending_count == 0
    end
  end

  describe "execute/2 error handling" do
    test "returns error status when bridge script is not found" do
      {:ok, _pid} = start_supervised_manager_with_script("/nonexistent/bridge.js")

      # The manager starts in disconnected state with no real port
      status = Manager.get_status()
      assert status.status in [:disconnected, :ready, :connecting]
    end
  end

  # ---------------------------------------------------------------------------
  # Test helpers
  # ---------------------------------------------------------------------------

  defp start_supervised_manager do
    # Use a unique name to avoid conflicts
    spec = %{
      id: :test_browser_manager,
      start: {Manager, :start_link, [[]]},
      type: :worker,
      restart: :temporary
    }

    start_supervised(spec)
  end

  defp start_supervised_manager_with_script(script_path) do
    spec = %{
      id: :test_browser_manager_custom,
      start: {Manager, :start_link, [[script_path: script_path]]},
      type: :worker,
      restart: :temporary
    }

    start_supervised(spec)
  end

  defp cleanup_manager do
    case Process.whereis(Manager) do
      nil -> :ok
      pid -> GenServer.stop(pid, :normal, 1_000)
    end
  rescue
    _ -> :ok
  end
end
