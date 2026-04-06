defmodule Mana.Streaming.PartTrackerTest do
  @moduledoc """
  Tests for Mana.Streaming.PartTracker module.
  """

  use ExUnit.Case, async: true

  alias Mana.Streaming.PartTracker

  describe "new/0" do
    test "creates an empty PartTracker" do
      tracker = PartTracker.new()

      assert tracker.active_parts == %{}
      assert tracker.token_counts == %{}
      assert tracker.tool_names == %{}
      assert tracker.total_input_tokens == 0
      assert tracker.total_output_tokens == 0
      assert tracker.part_counter == 0
    end
  end

  describe "start_part/3" do
    test "adds a new part to active_parts" do
      tracker =
        PartTracker.new()
        |> PartTracker.start_part("part_1", :text)

      assert tracker.active_parts["part_1"].type == :text
      assert is_integer(tracker.active_parts["part_1"].started_at)
      assert tracker.part_counter == 1
    end

    test "tracks multiple parts independently" do
      tracker =
        PartTracker.new()
        |> PartTracker.start_part("part_1", :text)
        |> PartTracker.start_part("part_2", :thinking)
        |> PartTracker.start_part("part_3", :tool)

      assert tracker.part_counter == 3
      assert tracker.active_parts["part_1"].type == :text
      assert tracker.active_parts["part_2"].type == :thinking
      assert tracker.active_parts["part_3"].type == :tool
    end

    test "overwrites existing part with same id" do
      tracker =
        PartTracker.new()
        |> PartTracker.start_part("part_1", :text)
        |> PartTracker.start_part("part_1", :tool)

      assert tracker.part_counter == 2
      assert tracker.active_parts["part_1"].type == :tool
    end
  end

  describe "end_part/2" do
    test "removes part from active_parts" do
      tracker =
        PartTracker.new()
        |> PartTracker.start_part("part_1", :text)
        |> PartTracker.end_part("part_1")

      assert tracker.active_parts == %{}
    end

    test "only removes specified part" do
      tracker =
        PartTracker.new()
        |> PartTracker.start_part("part_1", :text)
        |> PartTracker.start_part("part_2", :thinking)
        |> PartTracker.end_part("part_1")

      assert map_size(tracker.active_parts) == 1
      assert tracker.active_parts["part_2"].type == :thinking
    end

    test "handles non-existent part gracefully" do
      tracker =
        PartTracker.new()
        |> PartTracker.end_part("nonexistent")

      assert tracker.active_parts == %{}
    end
  end

  describe "update_tokens/4" do
    test "updates token counts for a part" do
      tracker =
        PartTracker.new()
        |> PartTracker.start_part("part_1", :text)
        |> PartTracker.update_tokens("part_1", 10, 5)

      assert tracker.token_counts["part_1"].input == 10
      assert tracker.token_counts["part_1"].output == 5
    end

    test "accumulates token counts across multiple updates" do
      tracker =
        PartTracker.new()
        |> PartTracker.start_part("part_1", :text)
        |> PartTracker.update_tokens("part_1", 10, 5)
        |> PartTracker.update_tokens("part_1", 5, 3)
        |> PartTracker.update_tokens("part_1", 2, 1)

      assert tracker.token_counts["part_1"].input == 17
      assert tracker.token_counts["part_1"].output == 9
    end

    test "tracks tokens independently for different parts" do
      tracker =
        PartTracker.new()
        |> PartTracker.start_part("part_1", :text)
        |> PartTracker.start_part("part_2", :thinking)
        |> PartTracker.update_tokens("part_1", 10, 5)
        |> PartTracker.update_tokens("part_2", 20, 10)

      assert tracker.token_counts["part_1"].input == 10
      assert tracker.token_counts["part_1"].output == 5
      assert tracker.token_counts["part_2"].input == 20
      assert tracker.token_counts["part_2"].output == 10
    end

    test "updates total token counts" do
      tracker =
        PartTracker.new()
        |> PartTracker.start_part("part_1", :text)
        |> PartTracker.start_part("part_2", :thinking)
        |> PartTracker.update_tokens("part_1", 10, 5)
        |> PartTracker.update_tokens("part_2", 20, 10)

      assert tracker.total_input_tokens == 30
      assert tracker.total_output_tokens == 15
    end
  end

  describe "set_tool_name/3" do
    test "sets tool name for a part" do
      tracker =
        PartTracker.new()
        |> PartTracker.start_part("part_1", :tool)
        |> PartTracker.set_tool_name("part_1", "shell_command")

      assert tracker.tool_names["part_1"] == "shell_command"
    end

    test "allows updating tool name" do
      tracker =
        PartTracker.new()
        |> PartTracker.start_part("part_1", :tool)
        |> PartTracker.set_tool_name("part_1", "shell_command")
        |> PartTracker.set_tool_name("part_1", "file_read")

      assert tracker.tool_names["part_1"] == "file_read"
    end

    test "tracks tool names independently for different parts" do
      tracker =
        PartTracker.new()
        |> PartTracker.start_part("part_1", :tool)
        |> PartTracker.start_part("part_2", :tool)
        |> PartTracker.set_tool_name("part_1", "shell_command")
        |> PartTracker.set_tool_name("part_2", "file_read")

      assert tracker.tool_names["part_1"] == "shell_command"
      assert tracker.tool_names["part_2"] == "file_read"
    end
  end

  describe "active_type?/2" do
    test "returns true when type is active" do
      tracker =
        PartTracker.new()
        |> PartTracker.start_part("part_1", :text)

      assert PartTracker.active_type?(tracker, :text) == true
    end

    test "returns false when type is not active" do
      tracker =
        PartTracker.new()
        |> PartTracker.start_part("part_1", :text)

      assert PartTracker.active_type?(tracker, :thinking) == false
    end

    test "returns true when any part has the type" do
      tracker =
        PartTracker.new()
        |> PartTracker.start_part("part_1", :text)
        |> PartTracker.start_part("part_2", :thinking)

      assert PartTracker.active_type?(tracker, :text) == true
      assert PartTracker.active_type?(tracker, :thinking) == true
    end

    test "returns false when all parts of that type have ended" do
      tracker =
        PartTracker.new()
        |> PartTracker.start_part("part_1", :text)
        |> PartTracker.start_part("part_2", :thinking)
        |> PartTracker.end_part("part_1")

      assert PartTracker.active_type?(tracker, :text) == false
      assert PartTracker.active_type?(tracker, :thinking) == true
    end
  end

  describe "active_parts/1" do
    test "returns map of active parts" do
      tracker =
        PartTracker.new()
        |> PartTracker.start_part("part_1", :text)
        |> PartTracker.start_part("part_2", :thinking)

      parts = PartTracker.active_parts(tracker)
      assert map_size(parts) == 2
      assert parts["part_1"].type == :text
      assert parts["part_2"].type == :thinking
    end
  end

  describe "total_tokens/1" do
    test "returns zero for new tracker" do
      tracker = PartTracker.new()
      assert PartTracker.total_tokens(tracker) == {0, 0}
    end

    test "returns correct totals after updates" do
      tracker =
        PartTracker.new()
        |> PartTracker.start_part("part_1", :text)
        |> PartTracker.start_part("part_2", :thinking)
        |> PartTracker.update_tokens("part_1", 10, 5)
        |> PartTracker.update_tokens("part_2", 20, 10)

      assert PartTracker.total_tokens(tracker) == {30, 15}
    end
  end

  describe "complex workflow" do
    test "full streaming workflow" do
      tracker =
        PartTracker.new()
        # Start thinking
        |> PartTracker.start_part("thinking_1", :thinking)
        |> PartTracker.update_tokens("thinking_1", 0, 50)
        # End thinking, start text response
        |> PartTracker.end_part("thinking_1")
        |> PartTracker.start_part("text_1", :text)
        |> PartTracker.update_tokens("text_1", 10, 20)
        # Tool call
        |> PartTracker.start_part("tool_1", :tool)
        |> PartTracker.set_tool_name("tool_1", "shell_command")
        |> PartTracker.update_tokens("tool_1", 15, 5)
        |> PartTracker.end_part("tool_1")
        # Finish text
        |> PartTracker.update_tokens("text_1", 0, 30)
        |> PartTracker.end_part("text_1")

      assert tracker.part_counter == 3
      assert tracker.total_input_tokens == 25
      assert tracker.total_output_tokens == 105
      assert tracker.active_parts == %{}
      assert tracker.tool_names["tool_1"] == "shell_command"
    end
  end
end
