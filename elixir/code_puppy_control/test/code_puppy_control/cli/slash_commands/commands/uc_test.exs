defmodule CodePuppyControl.CLI.SlashCommands.Commands.UCTest do
  use ExUnit.Case, async: false

  alias CodePuppyControl.CLI.SlashCommands.{CommandInfo, Dispatcher, Registry}
  alias CodePuppyControl.CLI.SlashCommands.Commands.UC
  alias CodePuppyControl.Tools.UniversalConstructor.Registry, as: UCRegistry

  @tmp_dir System.tmp_dir!()
  @test_uc_dir Path.join(@tmp_dir, "uc_test_#{:erlang.unique_integer([:positive])}")

  setup do
    File.mkdir_p!(@test_uc_dir)

    # Start the UC Registry GenServer with our test tools dir
    case Process.whereis(UCRegistry) do
      nil ->
        start_supervised!({UCRegistry, tools_dir: @test_uc_dir})

      _pid ->
        :ok
    end

    # Start the Slash Commands Registry GenServer if not already running
    case Process.whereis(Registry) do
      nil -> start_supervised!({Registry, []})
      _pid -> :ok
    end

    Registry.clear()

    # Register /uc command
    :ok =
      Registry.register(
        CommandInfo.new(
          name: "uc",
          description: "Browse and manage Universal Constructor tools",
          handler: &UC.handle_uc/2,
          usage: "/uc [toggle <name> | info <name>]",
          aliases: ["universal_constructor"],
          category: "context"
        )
      )

    on_exit(fn ->
      Registry.clear()
      Registry.register_builtin_commands()
      File.rm_rf!(@test_uc_dir)
    end)

    :ok
  end

  describe "/uc (no args) — empty tools dir" do
    test "shows Universal Constructor Tools header" do
      output =
        ExUnit.CaptureIO.capture_io(fn ->
          assert {:continue, _} = UC.handle_uc("/uc", %{})
        end)

      assert output =~ "Universal Constructor Tools"
    end

    test "shows 'no tools found' when empty" do
      output =
        ExUnit.CaptureIO.capture_io(fn ->
          assert {:continue, _} = UC.handle_uc("/uc", %{})
        end)

      assert output =~ "No UC tools found"
    end

    test "shows usage hint" do
      output =
        ExUnit.CaptureIO.capture_io(fn ->
          assert {:continue, _} = UC.handle_uc("/uc", %{})
        end)

      assert output =~ "/uc toggle"
      assert output =~ "/uc info"
    end

    test "returns continue" do
      ExUnit.CaptureIO.capture_io(fn ->
        assert {:continue, %{}} = UC.handle_uc("/uc", %{})
      end)
    end
  end

  describe "/uc (no args) — with tools" do
    setup do
      # Create a test UC tool file
      tool_content = """
      defmodule TestGreeter do
        @uc_tool %{
          name: "greeter",
          namespace: "",
          description: "Says hello to someone",
          enabled: true,
          version: "1.0.0",
          author: "test"
        }

        def run(args) do
          "Hello, \#{Map.get(args, "name", "World")}!"
        end
      end
      """

      File.write!(Path.join(@test_uc_dir, "greeter.ex"), tool_content)

      # Create a disabled tool
      disabled_content = """
      defmodule TestDisabled do
        @uc_tool %{
          name: "disabled_tool",
          namespace: "",
          description: "A disabled tool",
          enabled: false,
          version: "1.0.0",
          author: "test"
        }

        def run(_args) do
          :ok
        end
      end
      """

      File.write!(Path.join(@test_uc_dir, "disabled_tool.ex"), disabled_content)

      # Reload registry to pick up new tools
      UCRegistry.reload()

      :ok
    end

    test "lists tools with enabled count" do
      output =
        ExUnit.CaptureIO.capture_io(fn ->
          assert {:continue, _} = UC.handle_uc("/uc", %{})
        end)

      assert output =~ "1 enabled of 2 total"
    end

    test "shows tool names with on/off status" do
      output =
        ExUnit.CaptureIO.capture_io(fn ->
          assert {:continue, _} = UC.handle_uc("/uc", %{})
        end)

      assert output =~ "[on]"
      assert output =~ "[off]"
      assert output =~ "greeter"
      assert output =~ "disabled_tool"
    end
  end

  describe "/uc info <tool_name>" do
    setup do
      tool_content = """
      defmodule TestInfoTool do
        @uc_tool %{
          name: "infotool",
          namespace: "",
          description: "A tool for testing info display",
          enabled: true,
          version: "2.1.0",
          author: "test_author"
        }

        def run(args) do
          Map.get(args, "key", "default")
        end
      end
      """

      File.write!(Path.join(@test_uc_dir, "infotool.ex"), tool_content)
      UCRegistry.reload()

      :ok
    end

    test "shows tool details" do
      output =
        ExUnit.CaptureIO.capture_io(fn ->
          assert {:continue, _} = UC.handle_uc("/uc info infotool", %{})
        end)

      assert output =~ "Tool:"
      assert output =~ "infotool"
      assert output =~ "A tool for testing info display"
      assert output =~ "ENABLED"
      assert output =~ "2.1.0"
      assert output =~ "test_author"
    end

    test "shows source path" do
      output =
        ExUnit.CaptureIO.capture_io(fn ->
          assert {:continue, _} = UC.handle_uc("/uc info infotool", %{})
        end)

      assert output =~ "infotool.ex"
    end

    test "shows signature" do
      output =
        ExUnit.CaptureIO.capture_io(fn ->
          assert {:continue, _} = UC.handle_uc("/uc info infotool", %{})
        end)

      assert output =~ "Signature:"
    end

    test "shows error for unknown tool" do
      output =
        ExUnit.CaptureIO.capture_io(fn ->
          assert {:continue, _} = UC.handle_uc("/uc info nonexistent", %{})
        end)

      assert output =~ "Unknown tool"
      assert output =~ "nonexistent"
    end
  end

  describe "/uc toggle <tool_name>" do
    setup do
      tool_content = """
      defmodule TestToggleTool do
        @uc_tool %{
          name: "toggleme",
          namespace: "",
          description: "A tool for testing toggle",
          enabled: true,
          version: "1.0.0",
          author: "test"
        }

        def run(_args) do
          :ok
        end
      end
      """

      File.write!(Path.join(@test_uc_dir, "toggleme.ex"), tool_content)
      UCRegistry.reload()

      :ok
    end

    test "toggles enabled tool to disabled" do
      output =
        ExUnit.CaptureIO.capture_io(fn ->
          assert {:continue, _} = UC.handle_uc("/uc toggle toggleme", %{})
        end)

      assert output =~ "disabled"

      # Verify the file was actually modified
      content = File.read!(Path.join(@test_uc_dir, "toggleme.ex"))
      assert content =~ "enabled: false"
    end

    test "toggles disabled tool back to enabled" do
      # First toggle: enabled → disabled
      ExUnit.CaptureIO.capture_io(fn ->
        assert {:continue, _} = UC.handle_uc("/uc toggle toggleme", %{})
      end)

      # Second toggle: disabled → enabled
      output =
        ExUnit.CaptureIO.capture_io(fn ->
          assert {:continue, _} = UC.handle_uc("/uc toggle toggleme", %{})
        end)

      assert output =~ "enabled"

      content = File.read!(Path.join(@test_uc_dir, "toggleme.ex"))
      assert content =~ "enabled: true"
    end

    test "shows error for unknown tool" do
      output =
        ExUnit.CaptureIO.capture_io(fn ->
          assert {:continue, _} = UC.handle_uc("/uc toggle unknown_tool", %{})
        end)

      assert output =~ "Unknown tool"
    end
  end

  describe "/uc with invalid usage" do
    test "shows usage for unknown subcommand" do
      output =
        ExUnit.CaptureIO.capture_io(fn ->
          assert {:continue, _} = UC.handle_uc("/uc delete something", %{})
        end)

      assert output =~ "Usage"
      assert output =~ "/uc"
    end

    test "shows usage for toggle without tool name" do
      output =
        ExUnit.CaptureIO.capture_io(fn ->
          assert {:continue, _} = UC.handle_uc("/uc toggle", %{})
        end)

      assert output =~ "Usage"
    end

    test "shows usage for info without tool name" do
      output =
        ExUnit.CaptureIO.capture_io(fn ->
          assert {:continue, _} = UC.handle_uc("/uc info", %{})
        end)

      assert output =~ "Usage"
    end
  end

  describe "registration and dispatch" do
    test "/uc is registered and dispatchable" do
      assert {:ok, _} = Registry.get("uc")
    end

    test "/uc dispatches via Dispatcher" do
      output =
        ExUnit.CaptureIO.capture_io(fn ->
          assert {:ok, {:continue, _}} = Dispatcher.dispatch("/uc", %{})
        end)

      assert output =~ "Universal Constructor Tools"
    end

    test "/uc appears in all_names for tab completion" do
      names = Registry.all_names()
      assert "uc" in names
    end

    test "/uc is in context category" do
      commands = Registry.list_by_category("context")
      uc_cmd = Enum.find(commands, &(&1.name == "uc"))
      assert uc_cmd != nil
      assert uc_cmd.category == "context"
    end

    test "/uc has alias 'universal_constructor'" do
      assert {:ok, cmd} = Registry.get("universal_constructor")
      assert cmd.name == "uc"
    end

    test "/uc usage is correct" do
      {:ok, cmd} = Registry.get("uc")
      assert cmd.usage =~ "/uc"
    end
  end
end
