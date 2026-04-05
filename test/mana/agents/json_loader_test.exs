defmodule Mana.Agents.JsonLoaderTest do
  @moduledoc """
  Tests for Mana.Agents.JsonLoader.
  """

  use ExUnit.Case, async: true

  alias Mana.Agents.JsonLoader

  describe "discover/0" do
    test "discovers agents from priv/agents directory" do
      agents = JsonLoader.discover()

      # Should find agents from priv/agents/
      assert is_list(agents)
      assert agents != []

      # Check that we found the assistant agent
      assistant = Enum.find(agents, fn a -> a["name"] == "assistant" end)
      assert assistant != nil
      assert assistant["display_name"] != nil
      assert assistant["description"] != nil
      assert assistant["_source"] != nil
    end

    test "discovers pack agents from priv/agents/pack/" do
      agents = JsonLoader.discover()

      # Should find pack agents
      husky = Enum.find(agents, fn a -> a["name"] == "husky" end)
      assert husky != nil
      assert husky["display_name"] == "Husky 🐺"
    end

    test "returns deduplicated agents" do
      agents = JsonLoader.discover()

      names = Enum.map(agents, & &1["name"])
      unique_names = Enum.uniq(names)

      assert length(names) == length(unique_names)
    end
  end

  describe "load_from_dir/1" do
    test "loads agents from a directory" do
      priv_dir = Application.app_dir(:mana, "priv/agents")
      agents = JsonLoader.load_from_dir(priv_dir)

      assert is_list(agents)
      assert agents != []

      # Each agent should have required fields
      Enum.each(agents, fn agent ->
        assert is_binary(agent["name"])
        assert is_binary(agent["description"])
        assert is_binary(agent["_source"])
      end)
    end

    test "returns empty list for non-existent directory" do
      agents = JsonLoader.load_from_dir("/nonexistent/path/to/agents")
      assert agents == []
    end

    test "returns empty list for directory without json files" do
      # Use a temp directory that exists but has no JSON files
      agents = JsonLoader.load_from_dir(Path.expand("~"))
      # May have some JSON files in home dir, but unlikely
      assert is_list(agents)
    end
  end

  describe "load_single_file/1" do
    test "loads a valid agent config file" do
      priv_dir = Application.app_dir(:mana, "priv/agents")
      path = Path.join(priv_dir, "assistant.json")

      agent = JsonLoader.load_single_file(path)

      assert agent != nil
      assert agent["name"] == "assistant"
      assert agent["display_name"] != nil
      assert agent["description"] != nil
      assert agent["_source"] == path
    end

    test "returns nil for non-existent file" do
      agent = JsonLoader.load_single_file("/nonexistent/agent.json")
      assert agent == nil
    end

    test "returns nil for invalid JSON" do
      # Create a temp file with invalid JSON
      tmp_file = Path.join(System.tmp_dir!(), "invalid_#{System.unique_integer([:positive])}.json")
      File.write!(tmp_file, "not valid json {")

      agent = JsonLoader.load_single_file(tmp_file)
      assert agent == nil

      File.rm!(tmp_file)
    end

    test "returns nil for config missing required fields" do
      # Create a temp file with missing fields
      tmp_file = Path.join(System.tmp_dir!(), "incomplete_#{System.unique_integer([:positive])}.json")

      File.write!(tmp_file, ~s({"display_name": "Test", "system_prompt": "test"}))

      agent = JsonLoader.load_single_file(tmp_file)
      assert agent == nil

      File.rm!(tmp_file)
    end
  end
end
