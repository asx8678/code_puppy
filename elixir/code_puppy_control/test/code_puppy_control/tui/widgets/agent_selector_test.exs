defmodule CodePuppyControl.TUI.Widgets.AgentSelectorTest do
  use ExUnit.Case, async: true

  alias CodePuppyControl.TUI.Widgets.AgentSelector

  describe "list_agents/1" do
    test "returns a list of agent_entry maps with required keys" do
      agents = AgentSelector.list_agents()

      assert is_list(agents)

      for agent <- agents do
        assert Map.has_key?(agent, :name)
        assert Map.has_key?(agent, :slug)
        assert Map.has_key?(agent, :display_name)
        assert Map.has_key?(agent, :description)
        assert Map.has_key?(agent, :module)
        assert is_binary(agent.name)
        assert is_binary(agent.slug)
        assert is_binary(agent.display_name)
        assert is_binary(agent.description)
      end
    end

    test "slugs are kebab-case (no underscores)" do
      agents = AgentSelector.list_agents()

      for agent <- agents do
        refute agent.slug =~ "_",
               "Expected kebab-case slug but got: #{agent.slug}"
      end
    end

    test "slug is derived from catalogue name via underscore-to-hyphen" do
      agents = AgentSelector.list_agents()

      for agent <- agents do
        expected_slug = String.replace(agent.name, "_", "-")

        assert agent.slug == expected_slug,
               "Slug #{agent.slug} doesn't match expected #{expected_slug} from name #{agent.name}"
      end
    end

    test "results are sorted by name" do
      agents = AgentSelector.list_agents()
      names = Enum.map(agents, & &1.name)
      assert names == Enum.sort(names)
    end

    test "filter option narrows results by name substring (case-insensitive)" do
      all = AgentSelector.list_agents()

      if all != [] do
        sample = hd(all)
        # Use a unique fragment of the display name
        fragment = String.slice(sample.display_name, 0, 3)
        filtered = AgentSelector.list_agents(filter: fragment)

        assert is_list(filtered)

        for agent <- filtered do
          assert String.downcase(agent.display_name) =~ String.downcase(fragment) or
                   String.downcase(agent.slug) =~ String.downcase(fragment) or
                   String.downcase(agent.name) =~ String.downcase(fragment)
        end

        # Filtered should be a subset
        filtered_slugs = Enum.map(filtered, & &1.slug)
        all_slugs = Enum.map(all, & &1.slug)
        assert MapSet.new(filtered_slugs) |> MapSet.subset?(MapSet.new(all_slugs))
      end
    end

    test "filter with no matches returns empty list" do
      agents = AgentSelector.list_agents(filter: "zzz_no_such_agent_xyz_999")
      assert agents == []
    end

    test "filter is case-insensitive" do
      all = AgentSelector.list_agents()

      if all != [] do
        name = hd(all).name
        lower = AgentSelector.list_agents(filter: String.downcase(name))
        upper = AgentSelector.list_agents(filter: String.upcase(name))
        # Both should return at least the matching agent
        assert length(lower) >= 1
        assert length(upper) >= 1
      end
    end

    test "filter matches on slug (kebab-case)" do
      all = AgentSelector.list_agents()

      if all != [] do
        # Take the slug of the first agent and filter by a fragment of it
        slug = hd(all).slug

        # Only test if slug has a dash (most do: "code-puppy")
        if slug =~ "-" do
          fragment = String.split(slug, "-") |> hd()
          filtered = AgentSelector.list_agents(filter: fragment)

          assert is_list(filtered)
          assert length(filtered) >= 1
        end
      end
    end
  end

  describe "agent_entry structure" do
    test "display_name is human-friendly (not snake_case or kebab-case)" do
      agents = AgentSelector.list_agents()

      for agent <- agents do
        # display_name should have spaces, not underscores or hyphens
        # (derived from the catalogue's derive_display_name)
        refute agent.display_name =~ "_",
               "display_name should not contain underscores: #{agent.display_name}"
      end
    end

    test "module is nil or an atom" do
      agents = AgentSelector.list_agents()

      for agent <- agents do
        assert agent.module == nil or is_atom(agent.module)
      end
    end
  end
end
