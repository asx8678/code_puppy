defmodule Mana.TUI.ScreenTest do
  @moduledoc """
  Tests for Mana.TUI.Screen behaviour.

  Verifies the behaviour is compilable and that example implementations
  correctly implement all callbacks.
  """

  use ExUnit.Case, async: true

  # ---------------------------------------------------------------------------
  # Test screen implementations
  # ---------------------------------------------------------------------------

  defmodule MinimalScreen do
    @moduledoc false
    @behaviour Mana.TUI.Screen

    @impl true
    def render(state) do
      "Minimal screen – count: #{Map.get(state, :count, 0)}"
    end

    @impl true
    def handle_input(":q", _state), do: :exit

    def handle_input(line, state) do
      {:ok, Map.update(state, :count, 1, &(&1 + 1))}
    end
  end

  defmodule ScreenWithInit do
    @moduledoc false
    @behaviour Mana.TUI.Screen

    @impl true
    def init(opts) do
      initial = Keyword.get(opts, :initial_count, 0)
      {:ok, %{count: initial, label: Keyword.get(opts, :label, "test")}}
    end

    @impl true
    def render(state) do
      "#{state.label}: #{state.count}"
    end

    @impl true
    def handle_input("done", state), do: {:done, state}

    def handle_input("err", _state), do: {:error, "test error"}

    def handle_input(_line, state), do: {:ok, state}
    # Deliberately do NOT return :error — we test that the behaviour allows it
  end

  defmodule ScreenWithInitError do
    @moduledoc false
    @behaviour Mana.TUI.Screen

    @impl true
    def init(_opts) do
      {:error, :screen_init_failed}
    end

    @impl true
    def render(_state), do: ""

    @impl true
    def handle_input(_input, state), do: {:ok, state}
  end

  # ---------------------------------------------------------------------------
  # Behaviour compliance tests
  # ---------------------------------------------------------------------------

  describe "behaviour callbacks" do
    test "defines required callbacks" do
      callbacks = Mana.TUI.Screen.behaviour_info(:callbacks)

      assert {:render, 1} in callbacks
      assert {:handle_input, 2} in callbacks
    end

    test "init/1 is optional" do
      # Verify that a module can implement the behaviour without init/1
      Code.ensure_loaded(MinimalScreen)
      assert not function_exported?(MinimalScreen, :init, 1)
      # The module still compiles — init is optional
      assert function_exported?(MinimalScreen, :render, 1)
    end

    test "minimal screen can be compiled" do
      Code.ensure_loaded(MinimalScreen)
      assert function_exported?(MinimalScreen, :render, 1)
      assert function_exported?(MinimalScreen, :handle_input, 2)
    end

    test "screen with init can be compiled" do
      Code.ensure_loaded(ScreenWithInit)
      assert function_exported?(ScreenWithInit, :init, 1)
      assert function_exported?(ScreenWithInit, :render, 1)
      assert function_exported?(ScreenWithInit, :handle_input, 2)
    end
  end

  # ---------------------------------------------------------------------------
  # Minimal screen tests
  # ---------------------------------------------------------------------------

  describe "MinimalScreen" do
    test "render/1 returns string output" do
      output = MinimalScreen.render(%{})
      assert is_binary(output)
      assert output =~ "Minimal screen"
    end

    test "render/1 shows count from state" do
      output = MinimalScreen.render(%{count: 5})
      assert output =~ "count: 5"
    end

    test "handle_input/2 returns :exit for :q" do
      assert MinimalScreen.handle_input(":q", %{}) == :exit
    end

    test "handle_input/2 returns {:ok, updated_state} for normal input" do
      assert {:ok, state} = MinimalScreen.handle_input("hello", %{})
      assert state.count == 1

      assert {:ok, state2} = MinimalScreen.handle_input("world", state)
      assert state2.count == 2
    end
  end

  # ---------------------------------------------------------------------------
  # Screen with init tests
  # ---------------------------------------------------------------------------

  describe "ScreenWithInit" do
    test "init/1 returns {:ok, state} with defaults" do
      assert {:ok, state} = ScreenWithInit.init([])
      assert state.count == 0
      assert state.label == "test"
    end

    test "init/1 accepts custom options" do
      assert {:ok, state} = ScreenWithInit.init(initial_count: 42, label: "my-screen")
      assert state.count == 42
      assert state.label == "my-screen"
    end

    test "render/1 uses state from init" do
      {:ok, state} = ScreenWithInit.init(initial_count: 10, label: "demo")
      output = ScreenWithInit.render(state)
      assert output == "demo: 10"
    end

    test "handle_input/2 returns {:done, result} for 'done'" do
      state = %{count: 5, label: "x"}
      assert {:done, ^state} = ScreenWithInit.handle_input("done", state)
    end

    test "handle_input/2 returns {:ok, state} for other input" do
      state = %{count: 5, label: "x"}
      assert {:ok, ^state} = ScreenWithInit.handle_input("anything", state)
    end
  end

  # ---------------------------------------------------------------------------
  # Screen init error
  # ---------------------------------------------------------------------------

  describe "ScreenWithInitError" do
    test "init/1 returns {:error, reason}" do
      assert {:error, :screen_init_failed} = ScreenWithInitError.init([])
    end
  end

  describe "handle_input return values" do
    test ":exit is a valid return" do
      result = MinimalScreen.handle_input(":q", %{})
      assert result == :exit
    end

    test "{:ok, state} is a valid return" do
      result = MinimalScreen.handle_input("test", %{})
      assert match?({:ok, _}, result)
    end

    test "{:done, term} is a valid return" do
      state = %{count: 1}
      result = ScreenWithInit.handle_input("done", state)
      assert match?({:done, _}, result)
    end
  end
end
