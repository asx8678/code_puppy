defmodule CodePuppyControl.Tools.StagedChanges do
  @moduledoc "Staged changes sandbox — diff-preview gatekeeper system."

  use GenServer
  require Logger
  alias CodePuppyControl.Text.{Diff, ReplaceEngine}
  alias CodePuppyControl.Tool.Registry

  @table :staged_changes

  defmodule StagedChange do
    @moduledoc false
    @derive Jason.Encoder
    @enforce_keys [:change_id, :change_type, :file_path]
    defstruct [
      :change_id,
      :change_type,
      :file_path,
      :content,
      :old_str,
      :new_str,
      :snippet,
      :description,
      created_at: nil,
      applied: false,
      rejected: false
    ]
  end

  def start_link(opts \\ []), do: GenServer.start_link(__MODULE__, opts, name: __MODULE__)
  def enabled?, do: GenServer.call(__MODULE__, :enabled?)
  def enable, do: GenServer.call(__MODULE__, :enable)
  def disable, do: GenServer.call(__MODULE__, :disable)

  def add_create(fp, content, desc \\ ""),
    do: GenServer.call(__MODULE__, {:add_create, fp, content, desc})

  def add_replace(fp, old, new, desc \\ ""),
    do: GenServer.call(__MODULE__, {:add_replace, fp, old, new, desc})

  def add_delete_snippet(fp, snip, desc \\ ""),
    do: GenServer.call(__MODULE__, {:add_delete_snippet, fp, snip, desc})

  def get_staged_changes do
    case :ets.whereis(@table) do
      :undefined ->
        []

      _ ->
        @table
        |> :ets.tab2list()
        |> Enum.map(fn {_, c} -> c end)
        |> Enum.reject(&(&1.applied or &1.rejected))
        |> Enum.sort_by(& &1.created_at)
    end
  end

  def count, do: get_staged_changes() |> length()
  def remove_change(id), do: GenServer.call(__MODULE__, {:remove_change, id})
  def clear, do: GenServer.call(__MODULE__, :clear)

  def get_combined_diff do
    get_staged_changes()
    |> Enum.map(fn c ->
      d = gen_diff(c)
      if d == "", do: nil, else: "# #{c.description || c.change_type} (#{c.change_id})\n#{d}"
    end)
    |> Enum.reject(&is_nil/1)
    |> Enum.join("\n\n")
  end

  def apply_all, do: GenServer.call(__MODULE__, :apply_all, 30_000)
  def reject_all, do: GenServer.call(__MODULE__, :reject_all)

  defmodule StageCreateTool do
    @moduledoc false
    use CodePuppyControl.Tool
    @impl true
    def name, do: :stage_create
    @impl true
    def description, do: "Stage a file creation."
    @impl true
    def parameters do
      %{
        "type" => "object",
        "properties" => %{
          "file_path" => %{"type" => "string"},
          "content" => %{"type" => "string"},
          "description" => %{"type" => "string"}
        },
        "required" => ["file_path", "content"]
      }
    end

    @impl true
    def invoke(args, _ctx) do
      CodePuppyControl.Tools.StagedChanges.add_create(
        Map.get(args, "file_path", ""),
        Map.get(args, "content", ""),
        Map.get(args, "description", "")
      )
    end
  end

  defmodule StageReplaceTool do
    @moduledoc false
    use CodePuppyControl.Tool
    @impl true
    def name, do: :stage_replace
    @impl true
    def description, do: "Stage a replacement."
    @impl true
    def parameters do
      %{
        "type" => "object",
        "properties" => %{
          "file_path" => %{"type" => "string"},
          "old_str" => %{"type" => "string"},
          "new_str" => %{"type" => "string"},
          "description" => %{"type" => "string"}
        },
        "required" => ["file_path", "old_str", "new_str"]
      }
    end

    @impl true
    def invoke(args, _ctx) do
      CodePuppyControl.Tools.StagedChanges.add_replace(
        Map.get(args, "file_path", ""),
        Map.get(args, "old_str", ""),
        Map.get(args, "new_str", ""),
        Map.get(args, "description", "")
      )
    end
  end

  defmodule StageDeleteSnippetTool do
    @moduledoc false
    use CodePuppyControl.Tool
    @impl true
    def name, do: :stage_delete_snippet
    @impl true
    def description, do: "Stage a snippet deletion."
    @impl true
    def parameters do
      %{
        "type" => "object",
        "properties" => %{
          "file_path" => %{"type" => "string"},
          "snippet" => %{"type" => "string"},
          "description" => %{"type" => "string"}
        },
        "required" => ["file_path", "snippet"]
      }
    end

    @impl true
    def invoke(args, _ctx) do
      CodePuppyControl.Tools.StagedChanges.add_delete_snippet(
        Map.get(args, "file_path", ""),
        Map.get(args, "snippet", ""),
        Map.get(args, "description", "")
      )
    end
  end

  defmodule GetStagedDiffTool do
    @moduledoc false
    use CodePuppyControl.Tool
    @impl true
    def name, do: :get_staged_diff
    @impl true
    def description, do: "Get combined diff for pending changes."
    @impl true
    def parameters, do: %{"type" => "object", "properties" => %{}, "required" => []}
    @impl true
    def invoke(_args, _ctx) do
      changes = CodePuppyControl.Tools.StagedChanges.get_staged_changes()
      diff = CodePuppyControl.Tools.StagedChanges.get_combined_diff()

      {:ok,
       %{
         total_changes: length(changes),
         diff: diff,
         changes:
           Enum.map(changes, &Map.take(&1, [:change_id, :change_type, :file_path, :description]))
       }}
    end
  end

  defmodule ApplyStagedTool do
    @moduledoc false
    use CodePuppyControl.Tool
    @impl true
    def name, do: :apply_staged_changes
    @impl true
    def description, do: "Apply pending changes."
    @impl true
    def parameters, do: %{"type" => "object", "properties" => %{}, "required" => []}
    @impl true
    def invoke(_args, _ctx) do
      case CodePuppyControl.Tools.StagedChanges.apply_all() do
        {:ok, n} -> {:ok, %{applied: n}}
        e -> e
      end
    end
  end

  defmodule RejectStagedTool do
    @moduledoc false
    use CodePuppyControl.Tool
    @impl true
    def name, do: :reject_staged_changes
    @impl true
    def description, do: "Reject pending changes."
    @impl true
    def parameters, do: %{"type" => "object", "properties" => %{}, "required" => []}
    @impl true
    def invoke(_args, _ctx) do
      n = CodePuppyControl.Tools.StagedChanges.reject_all()
      {:ok, %{rejected: n}}
    end
  end

  @impl true
  def init(_opts) do
    table =
      try do
        :ets.new(@table, [
          :named_table,
          :set,
          :public,
          read_concurrency: true,
          write_concurrency: true
        ])
      rescue
        ArgumentError -> @table
      end

    {:ok, %{table: table, enabled: false}}
  end

  @impl true
  def handle_call(:enabled?, _, s), do: {:reply, s.enabled, s}
  @impl true
  def handle_call(:enable, _, s), do: {:reply, :ok, %{s | enabled: true}}
  @impl true
  def handle_call(:disable, _, s), do: {:reply, :ok, %{s | enabled: false}}
  @impl true
  def handle_call({:add_create, fp, content, desc}, _, s) do
    c = mk(:create, fp, content: content, description: desc)
    :ets.insert(@table, {c.change_id, c})
    {:reply, {:ok, c}, s}
  end

  @impl true
  def handle_call({:add_replace, fp, old, new, desc}, _, s) do
    c = mk(:replace, fp, old_str: old, new_str: new, description: desc)
    :ets.insert(@table, {c.change_id, c})
    {:reply, {:ok, c}, s}
  end

  @impl true
  def handle_call({:add_delete_snippet, fp, snip, desc}, _, s) do
    c = mk(:delete_snippet, fp, snippet: snip, description: desc)
    :ets.insert(@table, {c.change_id, c})
    {:reply, {:ok, c}, s}
  end

  @impl true
  def handle_call({:remove_change, id}, _, s),
    do:
      (
        :ets.delete(@table, id)
        {:reply, :ok, s}
      )

  @impl true
  def handle_call(:clear, _, s),
    do:
      (
        :ets.delete_all_objects(@table)
        {:reply, :ok, s}
      )

  @impl true
  def handle_call(:reject_all, _, s) do
    changes = get_staged_changes()
    for c <- changes, do: :ets.insert(@table, {c.change_id, %{c | rejected: true}})
    {:reply, length(changes), s}
  end

  @impl true
  def handle_call(:apply_all, _, s) do
    changes = get_staged_changes()

    if changes == [] do
      {:reply, {:ok, 0}, s}
    else
      result =
        Enum.reduce_while(changes, {:ok, 0}, fn c, {:ok, acc} ->
          case do_apply(c) do
            :ok ->
              :ets.insert(@table, {c.change_id, %{c | applied: true}})
              {:cont, {:ok, acc + 1}}

            {:error, r} ->
              {:halt, {:error, "Failed #{c.change_id}: #{r}"}}
          end
        end)

      {:reply, result, s}
    end
  end

  @impl true
  def handle_info(_, s), do: {:noreply, s}

  defp mk(type, fp, opts) do
    %StagedChange{
      change_id: id(),
      change_type: type,
      file_path: Path.expand(fp),
      content: opts[:content],
      old_str: opts[:old_str],
      new_str: opts[:new_str],
      snippet: opts[:snippet],
      description: opts[:description] || "",
      created_at: System.system_time(:millisecond)
    }
  end

  defp id, do: :crypto.strong_rand_bytes(16) |> Base.encode16(case: :lower)

  defp do_apply(%StagedChange{change_type: :create} = c) do
    File.mkdir_p(Path.dirname(c.file_path))
    File.write(c.file_path, c.content || "")
  end

  defp do_apply(%StagedChange{change_type: :replace} = c) do
    case File.read(c.file_path) do
      {:ok, content} ->
        case ReplaceEngine.replace_in_content(content, [{c.old_str || "", c.new_str || ""}]) do
          {:ok, %{modified: m}} -> File.write(c.file_path, m)
          {:error, %{reason: r}} -> {:error, r}
        end

      e ->
        e
    end
  end

  defp do_apply(%StagedChange{change_type: :delete_snippet} = c) do
    case File.read(c.file_path) do
      {:ok, content} ->
        snip = c.snippet || ""

        if String.contains?(content, snip),
          do: File.write(c.file_path, String.replace(content, snip, "", global: false)),
          else: {:error, "Snippet not found"}

      e ->
        e
    end
  end

  defp do_apply(_), do: {:error, "Unsupported"}

  defp gen_diff(%StagedChange{change_type: :create} = c) do
    Diff.unified_diff("", c.content || "",
      from_file: "/dev/null",
      to_file: "b/#{Path.basename(c.file_path)}"
    )
  end

  defp gen_diff(%StagedChange{change_type: :replace} = c) do
    case File.read(c.file_path) do
      {:ok, orig} ->
        if String.contains?(orig, c.old_str || ""),
          do:
            Diff.unified_diff(
              orig,
              String.replace(orig, c.old_str, c.new_str || "", global: false),
              from_file: "a/#{Path.basename(c.file_path)}",
              to_file: "b/#{Path.basename(c.file_path)}"
            ),
          else: ""

      _ ->
        ""
    end
  end

  defp gen_diff(%StagedChange{change_type: :delete_snippet} = c) do
    case File.read(c.file_path) do
      {:ok, orig} ->
        if String.contains?(orig, c.snippet || ""),
          do:
            Diff.unified_diff(orig, String.replace(orig, c.snippet, "", global: false),
              from_file: "a/#{Path.basename(c.file_path)}",
              to_file: "b/#{Path.basename(c.file_path)}"
            ),
          else: ""

      _ ->
        ""
    end
  end

  defp gen_diff(_), do: ""

  def register_all do
    [
      StageCreateTool,
      StageReplaceTool,
      StageDeleteSnippetTool,
      GetStagedDiffTool,
      ApplyStagedTool,
      RejectStagedTool
    ]
    |> Enum.reduce({:ok, 0}, fn m, {:ok, acc} ->
      case Registry.register(m) do
        :ok -> {:ok, acc + 1}
        _ -> {:ok, acc}
      end
    end)
  end
end
