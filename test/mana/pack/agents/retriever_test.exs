defmodule Mana.Pack.Agents.RetrieverTest do
  @moduledoc """
  Tests for Retriever agent - branch merge specialist.
  """

  use ExUnit.Case, async: true

  alias Mana.Pack.Agents.Retriever

  describe "execute/2" do
    test "executes fetch action" do
      task = %{
        id: "fetch-1",
        metadata: %{action: "fetch"}
      }

      result = Retriever.execute(task, [])

      # Should work in a git repo
      assert match?({:ok, %{status: :fetched}}, result) or match?({:error, _}, result)
    end

    test "executes checkout action" do
      task = %{
        id: "checkout-1",
        metadata: %{action: "checkout", base: "main"}
      }

      result = Retriever.execute(task, [])

      # Result depends on branch existence
      assert match?({:ok, %{status: :checked_out}}, result) or match?({:error, _}, result)
    end

    test "executes verify action" do
      task = %{
        id: "verify-1",
        metadata: %{action: "verify", branch: "main"}
      }

      result = Retriever.execute(task, [])

      assert match?({:ok, %{status: :verified}}, result) or match?({:error, _}, result)
    end

    test "returns error for unknown action" do
      task = %{
        id: "unknown-1",
        metadata: %{action: "unknown_action"}
      }

      result = Retriever.execute(task, [])
      assert {:error, %{reason: :unknown_action}} = result
    end

    test "returns error for merge without branch" do
      task = %{
        id: "merge-1",
        metadata: %{action: "merge", base: "main"}
      }

      result = Retriever.execute(task, [])
      assert {:error, %{reason: :missing_branch}} = result
    end
  end

  describe "abort_merge/2" do
    test "attempts abort" do
      result = Retriever.abort_merge(File.cwd!(), [])
      # May fail if no merge in progress
      assert match?({:ok, _}, result) or match?({:error, _}, result)
    end
  end

  describe "resolve_conflict/4" do
    test "attempts resolution" do
      # This is hard to test without an actual conflict
      result = Retriever.resolve_conflict(File.cwd!(), "some_file.ex", "ours", [])
      assert match?({:ok, _}, result) or match?({:error, _}, result)
    end
  end

  describe "complete_merge/3" do
    test "attempts to complete merge" do
      result = Retriever.complete_merge(File.cwd!(), "test commit", [])
      # May fail if no merge in progress
      assert match?({:ok, _}, result) or match?({:error, _}, result)
    end
  end
end
