defmodule CodePuppyControl.Tools.StagedChangesToolsTest do
  @moduledoc """
  Tests for the StagedChanges tool modules.

  Split from staged_changes_test.exs for 600-line cap compliance.
  """

  use ExUnit.Case, async: false

  alias CodePuppyControl.Tools.StagedChanges
  alias CodePuppyControl.Tools.StagedChanges.Tools

  alias Tools.{
    StageCreateTool,
    StageReplaceTool,
    StageDeleteSnippetTool,
    GetStagedDiffTool,
    ApplyStagedTool,
    RejectStagedTool
  }

  @tmp_dir System.tmp_dir!()

  setup do
    case StagedChanges.start_link([]) do
      {:ok, _pid} -> :ok
      {:error, {:already_started, _pid}} -> StagedChanges.clear(); StagedChanges.disable(); :ok
    end

    on_exit(fn ->
      StagedChanges.clear()
      StagedChanges.disable()
    end)
  end

  describe "StageCreateTool" do
    test "name/0 returns :stage_create", do: assert(StageCreateTool.name() == :stage_create)

    test "invoke/2 stages a create" do
      args = %{"file_path" => "/tmp/test.txt", "content" => "data", "description" => "test"}
      assert {:ok, c} = StageCreateTool.invoke(args, %{})
      assert c.change_type == :create
    end
  end

  describe "StageReplaceTool" do
    test "name/0 returns :stage_replace", do: assert(StageReplaceTool.name() == :stage_replace)

    test "invoke/2 stages a replacement" do
      args = %{"file_path" => "/tmp/test.txt", "old_str" => "a", "new_str" => "b"}
      assert {:ok, c} = StageReplaceTool.invoke(args, %{})
      assert c.change_type == :replace
    end
  end

  describe "StageDeleteSnippetTool" do
    test "name/0 returns :stage_delete_snippet", do: assert(StageDeleteSnippetTool.name() == :stage_delete_snippet)

    test "invoke/2 stages a snippet deletion" do
      args = %{"file_path" => "/tmp/test.txt", "snippet" => "remove"}
      assert {:ok, c} = StageDeleteSnippetTool.invoke(args, %{})
      assert c.change_type == :delete_snippet
    end
  end

  describe "GetStagedDiffTool" do
    test "name/0 returns :get_staged_diff", do: assert(GetStagedDiffTool.name() == :get_staged_diff)

    test "invoke/2 returns diff summary" do
      StagedChanges.add_create("/tmp/test.txt", "hello", "test")
      assert {:ok, r} = GetStagedDiffTool.invoke(%{}, %{})
      assert r.total_changes == 1 and r.diff =~ "+hello"
    end
  end

  describe "RejectStagedTool" do
    test "name/0 returns :reject_staged_changes", do: assert(RejectStagedTool.name() == :reject_staged_changes)

    test "invoke/2 rejects all pending" do
      StagedChanges.add_create("/tmp/a.txt", "a", "a")
      StagedChanges.add_create("/tmp/b.txt", "b", "b")
      assert {:ok, r} = RejectStagedTool.invoke(%{}, %{})
      assert r.rejected == 2 and StagedChanges.count() == 0
    end
  end

  describe "ApplyStagedTool" do
    test "name/0 returns :apply_staged_changes", do: assert(ApplyStagedTool.name() == :apply_staged_changes)

    test "invoke/2 applies creates to disk" do
      path = Path.join(@tmp_dir, "staged_apply_#{:rand.uniform(100_000)}.txt")
      StagedChanges.add_create(path, "staged content", "create test")
      assert {:ok, r} = ApplyStagedTool.invoke(%{}, %{})
      assert r.applied == 1 and File.exists?(path)
      File.rm(path)
    end

    test "invoke/2 with no changes returns 0" do
      assert {:ok, r} = ApplyStagedTool.invoke(%{}, %{})
      assert r.applied == 0
    end
  end

  describe "register_all/0" do
    test "registers all staged changes tools" do
      {:ok, count} = StagedChanges.register_all()
      assert count >= 0
    end
  end
end
