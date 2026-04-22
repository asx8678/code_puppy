defmodule CodePuppyControl.Plugins.GitAutoCommitTest do
  use ExUnit.Case, async: false

  alias CodePuppyControl.{Callbacks, Plugins}
  alias CodePuppyControl.Plugins.GitAutoCommit

  setup do
    Callbacks.clear()
    :ok
  end

  describe "name/0" do
    test "returns string identifier" do
      assert GitAutoCommit.name() == "git_auto_commit"
    end
  end

  describe "description/0" do
    test "returns a non-empty description" do
      assert is_binary(GitAutoCommit.description())
      assert GitAutoCommit.description() != ""
    end
  end

  describe "register/0" do
    test "registers custom_command and custom_command_help callbacks" do
      assert :ok = GitAutoCommit.register()
      assert Callbacks.count_callbacks(:custom_command) >= 1
      assert Callbacks.count_callbacks(:custom_command_help) >= 1
    end
  end

  describe "command_help/0" do
    test "returns help entries for commit commands" do
      help = GitAutoCommit.command_help()
      assert is_list(help)
      assert length(help) == 4
      commands = Enum.map(help, fn {cmd, _desc} -> cmd end)
      assert "/commit" in commands
      assert "/commit status" in commands
      assert "/commit preview" in commands
    end
  end

  describe "handle_command/2" do
    test "returns nil for unknown command name" do
      assert GitAutoCommit.handle_command("/foo", "foo") == nil
    end
  end

  describe "loading via Plugins API" do
    test "can be loaded through the plugin system" do
      Plugins.load_plugin(GitAutoCommit)
      assert Callbacks.count_callbacks(:custom_command) >= 1
    end
  end
end
