defmodule Mana.Skills.PromptBuilderTest do
  use ExUnit.Case, async: true

  alias Mana.Skills.PromptBuilder

  describe "build_available_skills_xml/1" do
    test "builds XML with skill entries" do
      skills = [
        %{name: "elixir-dev", description: "Elixir development expertise"},
        %{name: "rust-api", description: "Rust API design patterns"}
      ]

      xml = PromptBuilder.build_available_skills_xml(skills)

      assert xml =~ "<available_skills>"
      assert xml =~ "</available_skills>"
      assert xml =~ "<name>elixir-dev</name>"
      assert xml =~ "<description>Elixir development expertise</description>"
      assert xml =~ "<name>rust-api</name>"
      assert xml =~ "<description>Rust API design patterns</description>"
    end

    test "returns empty container for no skills" do
      xml = PromptBuilder.build_available_skills_xml([])

      assert xml =~ "<available_skills>"
      assert xml =~ "</available_skills>"
      refute xml =~ "<skill>"
    end

    test "escapes XML special characters" do
      skills = [
        %{name: "test", description: "Use <script> & "}
      ]

      xml = PromptBuilder.build_available_skills_xml(skills)

      assert xml =~ "&lt;script&gt;"
      assert xml =~ "&amp;"
      refute xml =~ "<script>"
    end
  end

  describe "build_skills_guidance/0" do
    test "returns guidance text" do
      guidance = PromptBuilder.build_skills_guidance()

      assert is_binary(guidance)
      assert guidance =~ "available_skill"
      assert guidance =~ "activate_skill"
      assert guidance =~ "SKILL.md"
    end
  end
end
