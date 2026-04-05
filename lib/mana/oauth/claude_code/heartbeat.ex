defmodule Mana.OAuth.ClaudeCode.Heartbeat do
  @moduledoc """
  GenServer for periodic token refresh during long agent runs.

  This module provides a heartbeat mechanism that periodically checks
  if the Claude Code OAuth token is expired and refreshes it if needed.
  This is particularly important during long-running agent sessions to
  ensure the token remains valid throughout the session.

  ## Usage

  Start the heartbeat:

      Mana.OAuth.ClaudeCode.Heartbeat.start_heartbeat()

  Stop the heartbeat:

      Mana.OAuth.ClaudeCode.Heartbeat.stop_heartbeat()

  The GenServer is designed to be started as part of the supervision tree
  and can be controlled via the public API functions.
  """

  use GenServer

  require Logger

  @refresh_interval 5 * 60 * 1000
  @provider_id "claude_code"

  # Client API

  @doc """
  Starts the Heartbeat GenServer.

  ## Options

  - `:name` - The name to register the GenServer under (default: `__MODULE__`)

  ## Examples

      {:ok, pid} = Mana.OAuth.ClaudeCode.Heartbeat.start_link([])
      {:ok, pid} = Mana.OAuth.ClaudeCode.Heartbeat.start_link(name: :my_heartbeat)
  """
  @spec start_link(keyword()) :: GenServer.on_start()
  def start_link(opts \\ []) do
    name = Keyword.get(opts, :name, __MODULE__)
    GenServer.start_link(__MODULE__, opts, name: name)
  end

  @doc """
  Starts the heartbeat timer.

  This will begin periodic token refresh checks every 5 minutes.
  If a timer is already running, it will be cancelled and a new one started.

  ## Examples

      :ok = Mana.OAuth.ClaudeCode.Heartbeat.start_heartbeat()
  """
  @spec start_heartbeat() :: :ok
  def start_heartbeat do
    start_heartbeat(__MODULE__)
  end

  @doc """
  Starts the heartbeat timer for a specific process.

  This variant is useful for testing with custom-named processes.
  """
  @spec start_heartbeat(atom() | pid()) :: :ok
  def start_heartbeat(name_or_pid) do
    GenServer.cast(name_or_pid, :start)
  end

  @doc """
  Stops the heartbeat timer.

  This will cancel any pending timer and stop periodic refresh checks.

  ## Examples

      :ok = Mana.OAuth.ClaudeCode.Heartbeat.stop_heartbeat()
  """
  @spec stop_heartbeat() :: :ok
  def stop_heartbeat do
    stop_heartbeat(__MODULE__)
  end

  @doc """
  Stops the heartbeat timer for a specific process.

  This variant is useful for testing with custom-named processes.
  """
  @spec stop_heartbeat(atom() | pid()) :: :ok
  def stop_heartbeat(name_or_pid) do
    GenServer.cast(name_or_pid, :stop)
  end

  @doc """
  Checks if the heartbeat is currently active.

  Returns `true` if the heartbeat timer is running, `false` otherwise.

  ## Examples

      true = Mana.OAuth.ClaudeCode.Heartbeat.active?()
  """
  @spec active?() :: boolean()
  def active? do
    active?(__MODULE__)
  end

  @doc """
  Checks if the heartbeat is currently active for a specific process.

  This variant is useful for testing with custom-named processes.
  """
  @spec active?(atom() | pid()) :: boolean()
  def active?(name_or_pid) do
    GenServer.call(name_or_pid, :is_active)
  end

  @doc """
  Performs an immediate token refresh check.

  This can be called to trigger a refresh check outside of the normal
  heartbeat interval.

  ## Examples

      :ok = Mana.OAuth.ClaudeCode.Heartbeat.refresh_now()
  """
  @spec refresh_now() :: :ok
  def refresh_now do
    refresh_now(__MODULE__)
  end

  @doc """
  Performs an immediate token refresh check for a specific process.

  This variant is useful for testing with custom-named processes.
  """
  @spec refresh_now(atom() | pid()) :: :ok
  def refresh_now(name_or_pid) do
    GenServer.cast(name_or_pid, :refresh)
  end

  # Server Callbacks

  @impl true
  def init(_opts) do
    {:ok, %{timer: nil, active: false}}
  end

  @impl true
  def handle_cast(:start, state) do
    if state.timer do
      Logger.debug("Cancelling existing Claude Code heartbeat timer")
      Process.cancel_timer(state.timer)
    end

    timer = Process.send_after(self(), :check_refresh, @refresh_interval)
    Logger.info("Started Claude Code token refresh heartbeat")
    {:noreply, %{state | timer: timer, active: true}}
  end

  @impl true
  def handle_cast(:stop, state) do
    if state.timer do
      Process.cancel_timer(state.timer)
    end

    Logger.info("Stopped Claude Code token refresh heartbeat")
    {:noreply, %{state | timer: nil, active: false}}
  end

  @impl true
  def handle_cast(:refresh, state) do
    perform_refresh_check()
    {:noreply, state}
  end

  @impl true
  def handle_call(:is_active, _from, state) do
    {:reply, state.active, state}
  end

  @impl true
  def handle_info(:check_refresh, %{active: false} = state) do
    # Heartbeat was stopped, don't schedule another check
    {:noreply, %{state | timer: nil}}
  end

  @impl true
  def handle_info(:check_refresh, state) do
    perform_refresh_check()

    # Schedule next check
    timer = Process.send_after(self(), :check_refresh, @refresh_interval)
    {:noreply, %{state | timer: timer}}
  end

  @impl true
  def handle_info(_msg, state) do
    # Ignore unknown messages
    {:noreply, state}
  end

  # Private functions

  defp perform_refresh_check do
    alias Mana.OAuth.{ClaudeCode, TokenStore}

    Logger.debug("Performing Claude Code token refresh check")

    case TokenStore.load(@provider_id) do
      {:ok, tokens} ->
        maybe_refresh(tokens)

      {:error, :not_found} ->
        Logger.debug("No Claude Code tokens found, skipping refresh")
    end
  end

  defp maybe_refresh(tokens) do
    alias Mana.OAuth.{ClaudeCode, TokenStore}

    if TokenStore.expired?(tokens) do
      Logger.info("Claude Code token expired, attempting refresh")
      do_refresh(tokens)
    else
      Logger.debug("Claude Code token still valid")
    end
  end

  defp do_refresh(tokens) do
    alias Mana.OAuth.ClaudeCode

    case ClaudeCode.refresh_token(tokens) do
      {:ok, _new_token} ->
        Logger.info("Successfully refreshed Claude Code token")

      {:error, reason} ->
        Logger.warning("Failed to refresh Claude Code token: #{inspect(reason)}")
    end
  end
end
