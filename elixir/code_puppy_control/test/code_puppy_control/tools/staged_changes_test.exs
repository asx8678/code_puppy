defmodule CodePuppyControl.Tools.StagedChangesTest do
  @moduledoc "Tests for the StagedChanges tools."

  use ExUnit.Case, async: false

  alias CodePuppyControl.Tools.StagedChanges

  alias CodePuppyControl.Tools.StagedChanges.{
    StageCreateTool,
    StageReplaceTool,
    StageDeleteSnippetTool,
    GetStagedDiffTool,
    ApplyStagedTool,
    RejectStagedTool
  }

  @tmp_dir System.tmp_dir!()

  setup do
    # Ensure StagedChanges GenServer is started
    case StagedChanges.start_link([]) do
      {:ok, _pid} ->
        :ok

      {:error, {:already_started, _pid}} ->
        StagedChanges.clear()
        :ok
    end
  end

  describe "enable/disable" do
    test "starts disabled by default" do
      assert StagedChanges.enabled?() == false
    end

    test "can be enabled and disabled" do
      StagedChanges.enable()
      assert StagedChanges.enabled?() == true

      StagedChanges.disable()
      assert StagedChanges.enabled?() == false
    end
  end

  describe "staging operations" do
    test "add_create stages a file creation" do
      assert {:ok, change} = StagedChanges.add_create("/tmp/test.txt", "content", "test")
      assert change.change_type == :create
      assert change.content == "content"
      assert StagedChanges.count() == 1
    end

    test "add_replace stages a replacement" do
      assert {:ok, change} = StagedChanges.add_replace("/tmp/test.txt", "old", "new", "test")
      assert change.change_type == :replace
      assert change.old_str == "old"
      assert change.new_str == "new"
    end

    test "add_delete_snippet stages a snippet deletion" do
      assert {:ok, change} =
               StagedChanges.add_delete_snippet("/tmp/test.txt", "remove me", "test")

      assert change.change_type == :delete_snippet
      assert change.snippet == "remove me"
    end

    test "count returns pending changes" do
      StagedChanges.add_create("/tmp/a.txt", "a", "a")
      StagedChanges.add_create("/tmp/b.txt", "b", "b")
      assert StagedChanges.count() == 2
    end

    test "get_staged_changes returns pending changes" do
      StagedChanges.add_create("/tmp/test.txt", "content", "test")
      changes = StagedChanges.get_staged_changes()
      assert length(changes) == 1
      assert hd(changes).change_type == :create
    end

    test "clear removes all changes" do
      StagedChanges.add_create("/tmp/test.txt", "content", "test")
      StagedChanges.clear()
      assert StagedChanges.count() == 0
    end

    test "remove_change removes specific change" do
      {:ok, change} = StagedChanges.add_create("/tmp/test.txt", "content", "test")
      StagedChanges.remove_change(change.change_id)
      assert StagedChanges.count() == 0
    end
  end

  describe "get_combined_diff" do
    test "returns empty string when no changes" do
      assert StagedChanges.get_combined_diff() == ""
    end

    test "returns diff for staged create" do
      StagedChanges.add_create("/tmp/test.txt", "hello\nworld\n", "create test")
      diff = StagedChanges.get_combined_diff()
      assert diff =~ "+hello"
      assert diff =~ "+world"
    end

    test "includes change description" do
      StagedChanges.add_create("/tmp/test.txt", "content", "My important change")
      diff = StagedChanges.get_combined_diff()
      assert diff =~ "My important change"
    end
  end

  describe "reject_all" do
    test "marks all changes as rejected" do
      StagedChanges.add_create("/tmp/a.txt", "a", "a")
      StagedChanges.add_create("/tmp/b.txt", "b", "b")

      count = StagedChanges.reject_all()
      assert count == 2

      # Pending changes should be empty
      assert StagedChanges.count() == 0
    end
  end

  describe "StageCreateTool" do
    test "name/0 returns :stage_create" do
      assert StageCreateTool.name() == :stage_create
    end

    test "invoke/2 stages a create" do
      args = %{"file_path" => "/tmp/test.txt", "content" => "data", "description" => "test"}
      assert {:ok, change} = StageCreateTool.invoke(args, %{})
      assert change.change_type == :create
    end
  end

  describe "StageReplaceTool" do
    test "name/0 returns :stage_replace" do
      assert StageReplaceTool.name() == :stage_replace
    end

    test "invoke/2 stages a replacement" do
      args = %{"file_path" => "/tmp/test.txt", "old_str" => "a", "new_str" => "b"}
      assert {:ok, change} = StageReplaceTool.invoke(args, %{})
      assert change.change_type == :replace
    end
  end

  describe "StageDeleteSnippetTool" do
    test "name/0 returns :stage_delete_snippet" do
      assert StageDeleteSnippetTool.name() == :stage_delete_snippet
    end

    test "invoke/2 stages a snippet deletion" do
      args = %{"file_path" => "/tmp/test.txt", "snippet" => "remove"}
      assert {:ok, change} = StageDeleteSnippetTool.invoke(args, %{})
      assert change.change_type == :delete_snippet
    end
  end

  describe "GetStagedDiffTool" do
    test "name/0 returns :get_staged_diff" do
      assert GetStagedDiffTool.name() == :get_staged_diff
    end

    test "invoke/2 returns diff summary" do
      StagedChanges.add_create("/tmp/test.txt", "hello", "test")
      assert {:ok, result} = GetStagedDiffTool.invoke(%{}, %{})
      assert result.total_changes == 1
      assert result.diff =~ "+hello"
    end
  end

  describe "RejectStagedTool" do
    test "name/0 returns :reject_staged_changes" do
      assert RejectStagedTool.name() == :reject_staged_changes
    end

    test "invoke/2 rejects all pending" do
      StagedChanges.add_create("/tmp/a.txt", "a", "a")
      StagedChanges.add_create("/tmp/b.txt", "b", "b")

      assert {:ok, result} = RejectStagedTool.invoke(%{}, %{})
      assert result.rejected == 2
      assert StagedChanges.count() == 0
    end
  end

  describe "ApplyStagedTool" do
    test "name/0 returns :apply_staged_changes" do
      assert ApplyStagedTool.name() == :apply_staged_changes
    end

    test "invoke/2 applies creates to disk" do
      path = Path.join(@tmp_dir, "staged_apply_test_#{:rand.uniform(10000)}.txt")

      StagedChanges.add_create(path, "staged content", "create test")
      assert {:ok, result} = ApplyStagedTool.invoke(%{}, %{})
      assert result.applied == 1
      assert File.exists?(path)
      assert File.read!(path) == "staged content"

      File.rm(path)
    end

    test "invoke/2 with no changes returns 0" do
      assert {:ok, result} = ApplyStagedTool.invoke(%{}, %{})
      assert result.applied == 0
    end
  end

  describe "register_all/0" do
    test "registers all staged changes tools" do
      {:ok, count} = StagedChanges.register_all()
      assert count >= 0
    end
  end
end
