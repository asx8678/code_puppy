defmodule CodePuppyControl.Tools.StagedChanges.Tools do
  @moduledoc """
  Tool modules for the staged changes system.

  Split from staged_changes.ex to keep the main module under the 600-line cap.
  These tools are registered by `StagedChanges.register_all/0`.
  """

  alias CodePuppyControl.Tools.StagedChanges

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
      StagedChanges.add_create(
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
      StagedChanges.add_replace(
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
      StagedChanges.add_delete_snippet(
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
      changes = StagedChanges.get_staged_changes()
      diff = StagedChanges.get_combined_diff()

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
      case StagedChanges.apply_all() do
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
      n = StagedChanges.reject_all()
      {:ok, %{rejected: n}}
    end
  end
end
