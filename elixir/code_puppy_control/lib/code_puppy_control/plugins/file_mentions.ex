defmodule CodePuppyControl.Plugins.FileMentions do
  @moduledoc """
  Auto-read file mentions from user prompts.
  Ported from Python: code_puppy/plugins/file_mentions/register_callbacks.py
  """

  use CodePuppyControl.Plugins.PluginBehaviour
  alias CodePuppyControl.Callbacks
  require Logger

  @default_max_file_size 5 * 1024 * 1024
  @default_max_files 10
  @default_max_dir_entries 500
  @state_key :code_puppy_file_mentions_state

  defp get_state do
    Process.get(@state_key, %{enabled: true, stats: %{mentions_found: 0, files_resolved: 0, files_failed: 0}})
  end
  defp put_state(state), do: Process.put(@state_key, state)

  @doc false
  @spec reset_state() :: :ok
  def reset_state do
    Process.delete(@state_key)
    :ok
  end

  @doc false
  @spec enabled?() :: boolean()
  def enabled?, do: get_state().enabled

  @doc false
  @spec stats() :: map()
  def stats, do: get_state().stats

  @impl true
  def name, do: "file_mentions"
  @impl true
  def description, do: "Auto-read @file mentions from user prompts"
  @impl true
  def register do
    Callbacks.register(:load_prompt, &__MODULE__.on_load_prompt/0)
    Callbacks.register(:custom_command, &__MODULE__.handle_custom_command/2)
    Callbacks.register(:custom_command_help, &__MODULE__.custom_command_help/0)
    :ok
  end

  @file_mention_regex ~r/@((?:[a-zA-Z0-9_\-.][\w\-.]*/)*[\w\-]+(?:\.\w+)?)/
  @leading_punct_regex ~r/^`\"'(\[{<]+/
  @trailing_punct_regex ~r/[)\]}>.,;:!\"'`]+$/
  @mention_boundary_regex ~r/[\s(\[{<\"'`]/

  @doc "Extract @filepath mentions from text."
  @spec extract_file_mentions(String.t()) :: [String.t()]
  def extract_file_mentions(text) do
    Regex.scan(@file_mention_regex, text, return: :index)
    |> Enum.reduce({[], MapSet.new()}, fn [{start, _len}, [raw_start, raw_len]], {acc, seen} ->
      if mention_boundary?(text, start) do
        raw = String.slice(text, raw_start, raw_len)
        cleaned = sanitize_mention_path(raw)
        if cleaned && path_like?(cleaned) and not MapSet.member?(seen, cleaned) do
          {[cleaned | acc], MapSet.put(seen, cleaned)}
        else
          {acc, seen}
        end
      else
        {acc, seen}
      end
    end)
    |> elem(0)
    |> Enum.reverse()
  end

  defp path_like?(s), do: String.contains?(s, ".") or String.contains?(s, "/")

  @doc "Resolve a mention path to an absolute path if the file exists."
  @spec resolve_mention_path(String.t(), String.t() | nil) :: String.t() | nil
  def resolve_mention_path(file_path, cwd \ nil) do
    cwd = cwd || File.cwd!()
    candidate = Path.join(cwd, file_path)
    cond do
      File.exists?(candidate) -> Path.expand(candidate)
      Path.type(file_path) == :absolute and File.exists?(file_path) -> file_path
      true -> nil
    end
  end

  @doc "Generate context from @file mentions in text."
  @spec generate_file_mention_context(String.t(), String.t() | nil, keyword()) :: String.t() | nil
  def generate_file_mention_context(text, cwd \ nil, opts \ []) do
    state = get_state()
    if not state.enabled, do: nil, else: do_generate_context(text, cwd, opts, state)
  end

  defp do_generate_context(text, cwd, opts, state) do
    max_files = Keyword.get(opts, :max_files, @default_max_files)
    mentions = extract_file_mentions(text)
    if mentions == [], do: nil, else: do_build_parts(mentions, cwd, max_files, state)
  end

  defp do_build_parts(mentions, cwd, max_files, state) do
    put_state(%{state | stats: Map.update!(state.stats, :mentions_found, &(&1 + length(mentions)))})
    parts = mentions |> Enum.take(max_files) |> Enum.flat_map(&build_for_mention(&1, cwd))
    if parts == [], do: nil, else:
      '\n\n## Auto-loaded @file mentions\n\nThe following files were referenced with @path syntax ' <>
        'and auto-loaded for context:\n\n' <> Enum.join(parts, '\n\n')
  end

  defp build_for_mention(mention, cwd) do
    case resolve_mention_path(mention, cwd) do
      nil -> update_stats(:files_failed); []
      resolved -> update_stats(:files_resolved); build_mention_part(mention, resolved)
    end
  end

  defp build_mention_part(mention, resolved) do
    if File.dir?(resolved) do
      case list_directory(resolved) do
        nil -> []
        listing -> ['<file_mention path="' <> mention <> '" type="directory">\n' <> listing <> '\n</file_mention>']
      end
    else
      case read_file_content(resolved) do
        nil -> []
        content ->
          ['<file_mention path="' <> mention <> '" lines="' <> to_string(count_lines(content)) <> '">\n' <> content <> '\n</file_mention>']
      end
    end
  end
