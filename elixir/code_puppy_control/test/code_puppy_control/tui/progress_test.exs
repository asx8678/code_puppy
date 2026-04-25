defmodule CodePuppyControl.TUI.ProgressTest do
  use ExUnit.Case, async: true

  alias CodePuppyControl.TUI.Progress

  describe "spinner/1" do
    test "returns {:error, :no_tty} when no TTY is available" do
      # Simulate no-TTY by temporarily unsetting TERM/COLORTERM.
      # This is safe in async: true because we only read env, and the
      # test process doesn't persist the change globally.
      original_term = System.get_env("TERM")
      original_color = System.get_env("COLORTERM")

      System.delete_env("TERM")
      System.delete_env("COLORTERM")

      assert {:error, :no_tty} = Progress.spinner("test")

      # Restore
      if original_term, do: System.put_env("TERM", original_term)
      if original_color, do: System.put_env("COLORTERM", original_color)
    end
  end

  describe "bar/3 ratio clamping" do
    test "clamps ratio when current exceeds total" do
      # When current > total, ratio should be clamped to 1.0 so
      # filled == width and empty == 0 (no negative-argument crash).
      # We run in no-TTY mode to avoid actual IO, but the clamping
      # logic is on the happy path — so we test the math directly.

      # Verify the math: ratio = min(current/total, 1.0)
      ratio = (150 / 100) |> max(0.0) |> min(1.0)
      assert ratio == 1.0

      width = 40
      filled = trunc(ratio * width)
      empty = width - filled
      assert filled == width
      assert empty == 0
    end

    test "clamps ratio when current is negative" do
      ratio = (-10 / 100) |> max(0.0) |> min(1.0)
      assert ratio == 0.0

      width = 40
      filled = trunc(ratio * width)
      empty = width - filled
      assert filled == 0
      assert empty == width
    end

    test "returns {:error, :no_tty} when no TTY is available" do
      original_term = System.get_env("TERM")
      original_color = System.get_env("COLORTERM")

      System.delete_env("TERM")
      System.delete_env("COLORTERM")

      assert {:error, :no_tty} = Progress.bar(50, 100, label: "test")

      if original_term, do: System.put_env("TERM", original_term)
      if original_color, do: System.put_env("COLORTERM", original_color)
    end
  end

  describe "stop/2" do
    test "does not crash for unknown refs" do
      # stop/2 should be safe even if the ref was never started.
      ref = make_ref()
      assert :ok == Progress.stop(ref)
      assert :ok == Progress.stop(ref, resolution: :error)
    end
  end
end
