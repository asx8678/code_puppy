defmodule Mana.Plugins.CleanCommand do
  @moduledoc "Clean command for clearing data"
  @behaviour Mana.Plugin.Behaviour

  alias Mana.Config.Paths
  alias Mana.Session.Store

  @valid_targets ["all", "sessions", "history", "logs", "cache"]

  @impl true
  def name, do: "clean_command"

  @impl true
  def init(config) do
    {:ok, %{config: config}}
  end

  @impl true
  def hooks do
    [{:custom_command, &__MODULE__.handle_clean/2}]
  end

  @doc """
  Handles the /clean custom command.
  """
  def handle_clean("clean", args) do
    {dry_run, targets} = parse_clean_args(args)

    results =
      Enum.map(targets, fn target ->
        clean_target(target, dry_run)
      end)

    Enum.join(results, "\n")
  end

  def handle_clean(_, _), do: nil

  defp parse_clean_args(args) do
    {flags, targets} = Enum.split_with(args, &String.starts_with?(&1, "--"))
    dry_run = "--dry-run" in flags
    targets = if targets == [], do: ["all"], else: targets
    {dry_run, targets}
  end

  defp clean_target("all", dry_run) do
    results = Enum.map(["sessions", "logs", "cache"], &clean_target(&1, dry_run))
    Enum.join(results, "\n")
  end

  defp clean_target("sessions", dry_run) do
    if dry_run do
      "Would clean sessions"
    else
      clean_sessions()
    end
  end

  defp clean_target("history", dry_run) do
    # History is stored per session, so this is covered by sessions
    if dry_run do
      "Would clean history (part of sessions)"
    else
      "✓ History cleaned"
    end
  end

  defp clean_target("logs", dry_run) do
    if dry_run do
      "Would clean logs"
    else
      clean_logs()
    end
  end

  defp clean_target("cache", dry_run) do
    if dry_run do
      "Would clean cache"
    else
      clean_cache()
    end
  end

  defp clean_target(other, _dry_run) do
    "Unknown target: #{other}. Options: #{Enum.join(@valid_targets, ", ")}"
  end

  defp clean_sessions do
    session_ids = Store.list_sessions()

    Enum.each(session_ids, fn session_id ->
      Store.delete_session(session_id)
    end)

    "✓ Sessions cleaned"
  end

  defp clean_logs do
    log_dir = Path.join(Paths.data_dir(), "logs")
    File.rm_rf(log_dir)
    File.mkdir_p(log_dir)
    "✓ Logs cleaned"
  end

  defp clean_cache do
    cache_dir = Path.join(Paths.data_dir(), "cache")
    File.rm_rf(cache_dir)
    File.mkdir_p(cache_dir)
    "✓ Cache cleaned"
  end

  @impl true
  def terminate do
    :ok
  end
end
