defmodule CodePuppyControl.Tools.SkillsTest do
  @moduledoc "Tests for the Skills tools."

  use ExUnit.Case, async: true

  alias CodePuppyControl.Tools.Skills.{ListSkills, ActivateSkill}

  describe "ListSkills" do
    test "name/0 returns :list_skills" do
      assert ListSkills.name() == :list_skills
    end

    test "description/0 returns non-empty string" do
      assert is_binary(ListSkills.description())
      assert String.length(ListSkills.description()) > 0
    end

    test "parameters/0 has optional query" do
      schema = ListSkills.parameters()
      assert schema["type"] == "object"
      assert Map.has_key?(schema["properties"], "query")
      assert schema["required"] == []
    end

    test "invoke/2 returns skills list" do
      assert {:ok, result} = ListSkills.invoke(%{}, %{})
      assert Map.has_key?(result, :skills)
      assert Map.has_key?(result, :total_count)
      assert is_list(result.skills)
      assert is_integer(result.total_count)
    end

    test "invoke/2 with query filters results" do
      assert {:ok, result} = ListSkills.invoke(%{"query" => "nonexistent_skill_xyz"}, %{})
      assert result.skills == []
      assert result.total_count == 0
    end
  end

  describe "ActivateSkill" do
    test "name/0 returns :activate_skill" do
      assert ActivateSkill.name() == :activate_skill
    end

    test "description/0 returns non-empty string" do
      assert is_binary(ActivateSkill.description())
      assert String.length(ActivateSkill.description()) > 0
    end

    test "parameters/0 requires skill_name" do
      schema = ActivateSkill.parameters()
      assert "skill_name" in schema["required"]
    end

    test "invoke/2 fails for non-existent skill" do
      args = %{"skill_name" => "nonexistent_skill_xyz"}
      assert {:error, reason} = ActivateSkill.invoke(args, %{})
      assert reason =~ "not found"
    end
  end

  describe "register_all/0" do
    test "registers both skill tools" do
      {:ok, count} = CodePuppyControl.Tools.Skills.register_all()
      assert count >= 0
    end
  end
end
