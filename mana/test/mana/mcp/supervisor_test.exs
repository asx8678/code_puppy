defmodule Mana.MCP.SupervisorTest do
  @moduledoc """
  Tests for Mana.MCP.Supervisor module.

  Uses a StubMcpServer test double to verify actual lifecycle operations
  (start, stop, lookup) work correctly through the DynamicSupervisor + Registry.
  """

  use ExUnit.Case, async: false

  alias Mana.MCP.Supervisor, as: MCPSupervisor

  # ---------------------------------------------------------------------------
  # StubMcpServer — minimal test double implementing ServerBehaviour
  # ---------------------------------------------------------------------------
  defmodule StubMcpServer do
    @moduledoc "Minimal test double implementing ServerBehaviour for supervisor tests"

    @behaviour Mana.MCP.ServerBehaviour

    use GenServer

    @impl true
    def start_link(config, opts \\ []) do
      name = Keyword.get(opts, :name)
      GenServer.start_link(__MODULE__, config, if(name, do: [name: name], else: []))
    end

    @impl true
    def get_state(pid), do: GenServer.call(pid, :get_state)

    @impl true
    def stop(pid), do: GenServer.stop(pid)

    @impl true
    def list_tools(_pid), do: {:ok, []}

    @impl true
    def call_tool(_pid, _name, _args), do: {:error, :not_found}

    @impl true
    def enable(_pid), do: :ok

    @impl true
    def disable(_pid), do: :ok

    @impl true
    def quarantine(_pid, _ms), do: :ok

    @impl true
    def get_status(_pid), do: %{state: :running}

    # GenServer callbacks
    @impl true
    def init(config), do: {:ok, %{config: config, state: :running}}

    @impl true
    def handle_call(:get_state, _from, state), do: {:reply, :running, state}
  end

  # ---------------------------------------------------------------------------
  # Helper: start a fresh supervisor + registry pair for each test
  # ---------------------------------------------------------------------------
  defp fresh_supervisor(_context) do
    tag = :erlang.unique_integer([:positive])
    reg_name = :"mcp_reg_#{tag}"
    sup_name = :"mcp_sup_#{tag}"

    {:ok, _} = start_supervised({Registry, keys: :unique, name: reg_name})
    {:ok, sup} = start_supervised({MCPSupervisor, [name: sup_name, registry: reg_name]})

    {:ok, sup: sup, reg: reg_name}
  end

  defp make_config(id, opts \\ []) do
    %Mana.MCP.ServerConfig{
      id: id,
      name: Keyword.get(opts, :name, "Test #{id}"),
      type: :stdio,
      command: Keyword.get(opts, :command, "echo"),
      args: Keyword.get(opts, :args, [])
    }
  end

  # ---------------------------------------------------------------------------
  # Tests: start_link/1
  # ---------------------------------------------------------------------------
  describe "start_link/1" do
    setup :fresh_supervisor

    test "starts the supervisor with default name", %{sup: pid} do
      assert Process.alive?(pid)
      assert DynamicSupervisor.which_children(pid) == []
    end
  end

  # ---------------------------------------------------------------------------
  # Tests: which_servers/1 (with Registry)
  # ---------------------------------------------------------------------------
  describe "which_servers/1" do
    setup :fresh_supervisor

    test "returns empty list when no servers running", %{reg: reg} do
      assert MCPSupervisor.which_servers(registry: reg) == []
    end
  end

  # ---------------------------------------------------------------------------
  # Tests: server_running?/2 (with Registry)
  # ---------------------------------------------------------------------------
  describe "server_running?/2" do
    setup :fresh_supervisor

    test "returns false when server is not running", %{reg: reg} do
      refute MCPSupervisor.server_running?("nonexistent", registry: reg)
    end
  end

  # ---------------------------------------------------------------------------
  # Tests: count_servers/1
  # ---------------------------------------------------------------------------
  describe "count_servers/1" do
    setup :fresh_supervisor

    test "returns 0 when no servers running", %{sup: sup} do
      assert MCPSupervisor.count_servers(supervisor: sup) == 0
    end
  end

  # ---------------------------------------------------------------------------
  # Tests: stop_server/2
  # ---------------------------------------------------------------------------
  describe "stop_server/2" do
    setup :fresh_supervisor

    test "returns error when server not found", %{sup: sup, reg: reg} do
      assert {:error, :not_found} = MCPSupervisor.stop_server("nonexistent", supervisor: sup, registry: reg)
    end
  end

  # ---------------------------------------------------------------------------
  # Tests: not-yet-implemented path (without module override)
  # ---------------------------------------------------------------------------
  describe "not-yet-implemented path" do
    setup :fresh_supervisor

    test "start_server returns {:error, :not_yet_implemented} for :stdio type without module override", %{
      sup: sup,
      reg: reg
    } do
      config = %Mana.MCP.ServerConfig{
        id: "nyi-stdio-test",
        name: "Not Yet Implemented STDIO",
        type: :stdio,
        command: "/usr/bin/echo"
      }

      # NO :module override — should hit the production server_module_for_type/1 lookup
      assert {:error, :not_yet_implemented} =
               MCPSupervisor.start_server(config, supervisor: sup, registry: reg)

      # Verify nothing was registered
      assert [] = MCPSupervisor.which_servers(supervisor: sup, registry: reg)
    end

    test "start_server returns {:error, :not_yet_implemented} for :sse type without module override", %{
      sup: sup,
      reg: reg
    } do
      config = %Mana.MCP.ServerConfig{
        id: "nyi-sse-test",
        name: "Not Yet Implemented SSE",
        type: :sse,
        url: "http://example.com"
      }

      # NO :module override — should hit the production server_module_for_type/1 lookup
      assert {:error, :not_yet_implemented} =
               MCPSupervisor.start_server(config, supervisor: sup, registry: reg)

      # Verify nothing was registered
      assert [] = MCPSupervisor.which_servers(supervisor: sup, registry: reg)
    end

    test "start_server returns {:error, :not_yet_implemented} for :http type without module override", %{
      sup: sup,
      reg: reg
    } do
      config = %Mana.MCP.ServerConfig{
        id: "nyi-http-test",
        name: "Not Yet Implemented HTTP",
        type: :http,
        url: "http://example.com"
      }

      # NO :module override — should hit the production server_module_for_type/1 lookup
      assert {:error, :not_yet_implemented} =
               MCPSupervisor.start_server(config, supervisor: sup, registry: reg)

      # Verify nothing was registered
      assert [] = MCPSupervisor.which_servers(supervisor: sup, registry: reg)
    end
  end

  # ---------------------------------------------------------------------------
  # Tests: lifecycle with StubMcpServer (the critical regression tests)
  # ---------------------------------------------------------------------------
  describe "lifecycle with stub server" do
    setup :fresh_supervisor

    test "start_server adds a child and makes it discoverable", %{sup: sup, reg: reg} do
      config = make_config("lifecycle-1")
      {:ok, pid} = MCPSupervisor.start_server(config, supervisor: sup, registry: reg, module: StubMcpServer)

      assert Process.alive?(pid)
      assert [{"lifecycle-1", ^pid}] = MCPSupervisor.which_servers(registry: reg)
      assert MCPSupervisor.server_running?("lifecycle-1", registry: reg)
      assert MCPSupervisor.count_servers(supervisor: sup) == 1
    end

    test "stop_server terminates the child and removes from registry", %{sup: sup, reg: reg} do
      config = make_config("lifecycle-2")
      {:ok, pid} = MCPSupervisor.start_server(config, supervisor: sup, registry: reg, module: StubMcpServer)

      # Verify it's alive first
      assert Process.alive?(pid)

      # Stop it
      :ok = MCPSupervisor.stop_server("lifecycle-2", supervisor: sup, registry: reg)

      # Give it a moment to terminate
      Process.sleep(50)

      # Verify it's dead and gone from lookup
      refute Process.alive?(pid)
      assert [] = MCPSupervisor.which_servers(registry: reg)
      refute MCPSupervisor.server_running?("lifecycle-2", registry: reg)
    end

    test "which_servers returns all running children", %{sup: sup, reg: reg} do
      for i <- 1..3 do
        config = make_config("srv#{i}")
        {:ok, _} = MCPSupervisor.start_server(config, supervisor: sup, registry: reg, module: StubMcpServer)
      end

      servers = MCPSupervisor.which_servers(registry: reg)
      assert length(servers) == 3
      assert Enum.sort(Enum.map(servers, fn {id, _} -> id end)) == ["srv1", "srv2", "srv3"]
    end

    test "start_server returns error for duplicate id", %{sup: sup, reg: reg} do
      config = make_config("dup-test")
      {:ok, _pid1} = MCPSupervisor.start_server(config, supervisor: sup, registry: reg, module: StubMcpServer)

      # Second start with same id should fail — Registry :via rejects duplicate keys
      assert {:error, {:already_started, _}} =
               MCPSupervisor.start_server(config, supervisor: sup, registry: reg, module: StubMcpServer)
    end
  end
end
