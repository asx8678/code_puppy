defmodule Mana.RunContextTest do
  @moduledoc """
  Tests for Mana.RunContext module.
  """

  use ExUnit.Case

  alias Mana.RunContext

  describe "new/1" do
    test "creates context with required fields" do
      ctx = RunContext.new(agent_name: "test_agent", model_name: "gpt-4")

      assert ctx.agent_name == "test_agent"
      assert ctx.model_name == "gpt-4"
      assert is_binary(ctx.id)
      assert ctx.parent_id == nil
      assert ctx.session_id == nil
      assert ctx.metadata == %{}
      assert %DateTime{} = ctx.started_at
    end

    test "accepts optional fields" do
      ctx =
        RunContext.new(
          agent_name: "agent",
          model_name: "model",
          id: "custom_id",
          parent_id: "parent_123",
          session_id: "session_456",
          metadata: %{key: "value"}
        )

      assert ctx.id == "custom_id"
      assert ctx.parent_id == "parent_123"
      assert ctx.session_id == "session_456"
      assert ctx.metadata == %{key: "value"}
    end

    test "auto-generates id when not provided" do
      ctx1 = RunContext.new(agent_name: "a", model_name: "b")
      ctx2 = RunContext.new(agent_name: "a", model_name: "b")

      assert ctx1.id != ctx2.id
      assert is_binary(ctx1.id)
      # 16 bytes = 32 hex chars
      assert byte_size(ctx1.id) == 32
    end

    test "raises on missing required fields" do
      assert_raise KeyError, fn ->
        RunContext.new(model_name: "gpt-4")
      end

      assert_raise KeyError, fn ->
        RunContext.new(agent_name: "agent")
      end
    end

    test "sets started_at to current time" do
      before = DateTime.utc_now()
      ctx = RunContext.new(agent_name: "a", model_name: "b")
      after_time = DateTime.utc_now()

      assert DateTime.compare(ctx.started_at, before) != :lt
      assert DateTime.compare(ctx.started_at, after_time) != :gt
    end
  end

  describe "put/1 and current/0" do
    test "stores context in process dictionary" do
      ctx = RunContext.new(agent_name: "a", model_name: "b")
      RunContext.put(ctx)

      assert RunContext.current() == ctx
    end

    test "returns the context for chaining" do
      ctx = RunContext.new(agent_name: "a", model_name: "b")
      assert RunContext.put(ctx) == ctx
    end

    test "current/0 returns nil when no context set" do
      # Clear any existing context
      RunContext.clear()
      assert RunContext.current() == nil
    end

    test "context is isolated to process" do
      ctx = RunContext.new(agent_name: "parent", model_name: "gpt-4")
      RunContext.put(ctx)

      # Spawn a new process - should not see parent's context
      task =
        Task.async(fn ->
          RunContext.current()
        end)

      assert Task.await(task) == nil
    end
  end

  describe "clear/0" do
    test "removes context from process dictionary" do
      ctx = RunContext.new(agent_name: "a", model_name: "b")
      RunContext.put(ctx)

      RunContext.clear()
      assert RunContext.current() == nil
    end

    test "returns the previous context" do
      ctx = RunContext.new(agent_name: "a", model_name: "b")
      RunContext.put(ctx)

      assert RunContext.clear() == ctx
    end

    test "returns nil when no context existed" do
      RunContext.clear()
      assert RunContext.clear() == nil
    end
  end

  describe "child/2" do
    test "creates child with parent_id set" do
      parent = RunContext.new(agent_name: "parent", model_name: "gpt-4")
      child = RunContext.child(parent)

      assert child.parent_id == parent.id
      assert child.id != parent.id
    end

    test "inherits fields from parent" do
      parent =
        RunContext.new(
          agent_name: "parent",
          model_name: "gpt-4",
          session_id: "session_123",
          metadata: %{key: "value"}
        )

      child = RunContext.child(parent)

      assert child.agent_name == "parent"
      assert child.model_name == "gpt-4"
      assert child.session_id == "session_123"
      assert child.metadata == %{key: "value"}
    end

    test "allows overriding fields" do
      parent = RunContext.new(agent_name: "parent", model_name: "gpt-4")
      child = RunContext.child(parent, agent_name: "child", model_name: "claude")

      assert child.agent_name == "child"
      assert child.model_name == "claude"
      assert child.parent_id == parent.id
    end

    test "merges metadata with overrides" do
      parent =
        RunContext.new(
          agent_name: "parent",
          model_name: "gpt-4",
          metadata: %{a: 1, b: 2}
        )

      child = RunContext.child(parent, metadata: %{b: 3, c: 4})

      assert child.metadata == %{a: 1, b: 3, c: 4}
    end

    test "generates new id for child" do
      parent = RunContext.new(agent_name: "parent", model_name: "gpt-4")
      child = RunContext.child(parent)

      assert child.id != parent.id
      assert is_binary(child.id)
    end

    test "generates new started_at for child" do
      parent = RunContext.new(agent_name: "parent", model_name: "gpt-4")
      :timer.sleep(5)
      child = RunContext.child(parent)

      assert child.started_at != parent.started_at
    end
  end

  describe "elapsed_ms/1" do
    test "returns elapsed time in milliseconds" do
      ctx = RunContext.new(agent_name: "a", model_name: "b")
      :timer.sleep(50)
      elapsed = RunContext.elapsed_ms(ctx)

      assert elapsed >= 50
      assert elapsed < 200
    end

    test "returns 0 for freshly created context" do
      ctx = RunContext.new(agent_name: "a", model_name: "b")
      elapsed = RunContext.elapsed_ms(ctx)

      assert elapsed >= 0
      assert elapsed < 100
    end
  end

  describe "has_parent?/1" do
    test "returns false for root context" do
      root = RunContext.new(agent_name: "root", model_name: "gpt-4")
      assert RunContext.has_parent?(root) == false
    end

    test "returns true for child context" do
      root = RunContext.new(agent_name: "root", model_name: "gpt-4")
      child = RunContext.child(root)
      assert RunContext.has_parent?(child) == true
    end
  end

  describe "to_map/1" do
    test "converts context to map" do
      ctx =
        RunContext.new(
          id: "test_id",
          agent_name: "agent",
          model_name: "gpt-4",
          parent_id: "parent_id",
          session_id: "session_id",
          metadata: %{key: "value"}
        )

      map = RunContext.to_map(ctx)

      assert map.id == "test_id"
      assert map.agent_name == "agent"
      assert map.model_name == "gpt-4"
      assert map.parent_id == "parent_id"
      assert map.session_id == "session_id"
      assert map.metadata == %{key: "value"}
      assert is_binary(map.started_at)
    end

    test "started_at is ISO8601 string" do
      ctx = RunContext.new(agent_name: "a", model_name: "b")
      map = RunContext.to_map(ctx)

      assert {:ok, _, _} = DateTime.from_iso8601(map.started_at)
    end
  end

  describe "from_map/1" do
    test "creates context from map with string keys" do
      map = %{
        "id" => "test_id",
        "agent_name" => "agent",
        "model_name" => "gpt-4",
        "parent_id" => "parent_id",
        "session_id" => "session_id",
        "started_at" => "2024-01-15T10:30:00Z",
        "metadata" => %{key: "value"}
      }

      ctx = RunContext.from_map(map)

      assert ctx.id == "test_id"
      assert ctx.agent_name == "agent"
      assert ctx.model_name == "gpt-4"
      assert ctx.parent_id == "parent_id"
      assert ctx.session_id == "session_id"
      assert ctx.metadata == %{key: "value"}
    end

    test "creates context from map with atom keys" do
      map = %{
        id: "test_id",
        agent_name: "agent",
        model_name: "gpt-4",
        started_at: "2024-01-15T10:30:00Z"
      }

      ctx = RunContext.from_map(map)

      assert ctx.id == "test_id"
      assert ctx.agent_name == "agent"
    end

    test "handles DateTime struct for started_at" do
      dt = DateTime.utc_now()
      map = %{"agent_name" => "a", "model_name" => "b", "started_at" => dt}

      ctx = RunContext.from_map(map)
      assert ctx.started_at == dt
    end

    test "generates id when not provided" do
      map = %{"agent_name" => "a", "model_name" => "b"}
      ctx = RunContext.from_map(map)

      assert is_binary(ctx.id)
      assert ctx.id != ""
    end

    test "defaults missing fields" do
      map = %{"agent_name" => "a", "model_name" => "b"}
      ctx = RunContext.from_map(map)

      assert ctx.parent_id == nil
      assert ctx.session_id == nil
      assert ctx.metadata == %{}
      assert %DateTime{} = ctx.started_at
    end

    test "handles invalid started_at gracefully" do
      map = %{"agent_name" => "a", "model_name" => "b", "started_at" => "invalid"}
      ctx = RunContext.from_map(map)

      assert %DateTime{} = ctx.started_at
    end
  end
end
