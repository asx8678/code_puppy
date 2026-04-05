defmodule Mana.TTSR.WatcherCleanup do
  @moduledoc """
  Periodic cleanup process for TTSR StreamWatcher processes.

  Monitors all active StreamWatcher processes and terminates any that
  have been inactive for longer than the configured threshold (default 1 hour).
  """

  use GenServer

  require Logger

  alias Mana.TTSR.StreamWatcher

  # 1 hour in seconds
  @default_inactivity_threshold 60 * 60
  # Check every 5 minutes
  @cleanup_interval :timer.minutes(5)

  defstruct [
    :inactivity_threshold_seconds
  ]

  @typedoc "Cleanup server state"
  @type t :: %__MODULE__{
          inactivity_threshold_seconds: non_neg_integer()
        }

  # Client API

  @doc """
  Starts the WatcherCleanup process.
  """
  @spec start_link(keyword()) :: GenServer.on_start()
  def start_link(opts \\ []) do
    GenServer.start_link(__MODULE__, opts, name: __MODULE__)
  end

  @doc """
  Returns the child spec for supervision.
  """
  @spec child_spec(keyword()) :: Supervisor.child_spec()
  def child_spec(opts) do
    %{
      id: __MODULE__,
      start: {__MODULE__, :start_link, [opts]},
      restart: :permanent
    }
  end

  @doc """
  Triggers an immediate cleanup check.
  """
  @spec cleanup_now() :: :ok
  def cleanup_now do
    GenServer.cast(__MODULE__, :cleanup_now)
  end

  @doc """
  Returns statistics about active watchers.
  """
  @spec stats() :: %{active: non_neg_integer(), stale: non_neg_integer()}
  def stats do
    GenServer.call(__MODULE__, :stats)
  end

  # Server Callbacks

  @impl true
  def init(opts) do
    threshold = Keyword.get(opts, :inactivity_threshold_seconds, @default_inactivity_threshold)

    # Schedule first cleanup
    schedule_cleanup()

    {:ok, %__MODULE__{inactivity_threshold_seconds: threshold}}
  end

  @impl true
  def handle_cast(:cleanup_now, state) do
    perform_cleanup(state.inactivity_threshold_seconds)
    {:noreply, state}
  end

  @impl true
  def handle_info(:cleanup, state) do
    perform_cleanup(state.inactivity_threshold_seconds)
    schedule_cleanup()
    {:noreply, state}
  end

  @impl true
  def handle_call(:stats, _from, state) do
    stats = gather_stats(state.inactivity_threshold_seconds)
    {:reply, stats, state}
  end

  # Private Functions

  defp schedule_cleanup do
    Process.send_after(self(), :cleanup, @cleanup_interval)
  end

  defp perform_cleanup(threshold_seconds) do
    stale_sessions = find_stale_watchers(threshold_seconds)
    terminate_stale_watchers(stale_sessions)
    :ok
  end

  defp find_stale_watchers(threshold_seconds) do
    now = DateTime.utc_now()

    Registry.select(Mana.TTSR.Registry, [
      {{:"$1", :"$2", :"$3"}, [], [{{:"$1", :"$2"}}]}
    ])
    |> Enum.filter(fn {_session_id, pid} ->
      stale_pid?(pid, now, threshold_seconds)
    end)
    |> Enum.map(fn {session_id, _pid} -> session_id end)
  end

  defp stale_pid?(pid, now, threshold_seconds) do
    case Process.alive?(pid) do
      true ->
        last_activity = StreamWatcher.get_last_activity(pid)
        stale?(last_activity, now, threshold_seconds)

      false ->
        true
    end
  end

  defp terminate_stale_watchers(stale_sessions) do
    Enum.each(stale_sessions, fn session_id ->
      Logger.info("TTSR cleanup: terminating stale watcher for session #{session_id}")
      StreamWatcher.stop(session_id)
    end)

    if stale_sessions != [] do
      Logger.info("TTSR cleanup: terminated #{length(stale_sessions)} stale watcher(s)")
    end
  end

  defp stale?(nil, _now, _threshold) do
    # No activity recorded, consider stale
    true
  end

  defp stale?(last_activity, now, threshold_seconds) do
    case DateTime.diff(now, last_activity, :second) do
      diff when is_integer(diff) and diff > threshold_seconds -> true
      _ -> false
    end
  end

  defp gather_stats(threshold_seconds) do
    now = DateTime.utc_now()

    entries =
      Registry.select(Mana.TTSR.Registry, [
        {{:"$1", :"$2", :"$3"}, [], [{{:"$1", :"$2"}}]}
      ])

    {active, stale} = Enum.reduce(entries, {0, 0}, &count_watcher(&1, &2, now, threshold_seconds))

    %{active: active, stale: stale}
  end

  defp count_watcher({_session_id, pid}, {active_acc, stale_acc}, now, threshold_seconds) do
    case Process.alive?(pid) do
      true ->
        count_active_watcher(pid, active_acc, stale_acc, now, threshold_seconds)

      false ->
        {active_acc, stale_acc + 1}
    end
  end

  defp count_active_watcher(pid, active_acc, stale_acc, now, threshold_seconds) do
    last_activity = StreamWatcher.get_last_activity(pid)

    if stale?(last_activity, now, threshold_seconds) do
      {active_acc, stale_acc + 1}
    else
      {active_acc + 1, stale_acc}
    end
  end
end
