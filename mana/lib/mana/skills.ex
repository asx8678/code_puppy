defmodule Mana.Skills do
  @moduledoc """
  Agent Skills System — hot-loadable domain expertise.

  This module provides the core Skills API: loading, querying, and
  formatting skills. It is consumed by `Mana.Plugins.AgentSkills`,
  which wires the skills system into the plugin lifecycle.
  """

  alias Mana.Skills.Loader
  alias Mana.Skills.PromptBuilder

  @skills_key {__MODULE__, :skills}

  @doc """
  Loads skills from all configured directories into persistent_term.
  Returns the list of loaded skills.
  """
  @spec load() :: [map()]
  def load do
    skills = Loader.load()
    :persistent_term.put(@skills_key, skills)
    skills
  end

  @doc """
  Returns all loaded skills from persistent_term.
  """
  @spec all() :: [map()]
  def all do
    :persistent_term.get(@skills_key, [])
  end

  @doc """
  Finds a skill by name (exact match).
  """
  @spec find(String.t()) :: map() | nil
  def find(name) do
    Enum.find(all(), fn s -> s.name == name end)
  end

  @doc """
  Searches skills by keyword (case-insensitive, matches name or description).
  """
  @spec search(String.t()) :: [map()]
  def search(query) do
    q = String.downcase(query)

    Enum.filter(all(), fn s ->
      String.contains?(String.downcase(s.name), q) or
        String.contains?(String.downcase(s.description), q)
    end)
  end

  @doc """
  Clears loaded skills from persistent_term.
  """
  @spec clear() :: :ok
  def clear do
    :persistent_term.erase(@skills_key)
    :ok
  end

  @doc """
  Delegates to `PromptBuilder.build_available_skills_xml/1`.
  """
  defdelegate build_available_skills_xml(skills), to: PromptBuilder

  @doc """
  Delegates to `PromptBuilder.build_skills_guidance/0`.
  """
  defdelegate build_skills_guidance, to: PromptBuilder
end
