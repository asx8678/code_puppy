defmodule Mana.MixProject do
  use Mix.Project

  @version "0.1.0"
  @source_url "https://github.com/adam2/code_puppy"

  def project do
    [
      app: :mana,
      version: @version,
      elixir: "~> 1.15",
      elixirc_paths: elixirc_paths(Mix.env()),
      start_permanent: Mix.env() == :prod,
      deps: deps(),
      aliases: aliases(),

      # Hex.pm package info
      package: package(),

      # Docs
      name: "Mana",
      description: "Plugin system for agent orchestration",
      source_url: @source_url,
      homepage_url: @source_url,
      docs: docs()
    ]
  end

  def application do
    [
      extra_applications: [:logger],
      mod: {Mana.Application, []}
    ]
  end

  defp elixirc_paths(:test), do: ["lib", "test/support"]
  defp elixirc_paths(_), do: ["lib"]

  defp deps do
    [
      # Core dependencies
      {:jason, "~> 1.4"},

      # Development dependencies
      {:ex_doc, "~> 0.31", only: :dev, runtime: false},
      {:credo, "~> 1.7", only: [:dev, :test], runtime: false},
      {:dialyxir, "~> 1.4", only: [:dev, :test], runtime: false},

      # Test dependencies
      {:ex_unit_notifier, "~> 1.3", only: :test},
      {:mock, "~> 0.3", only: :test}
    ]
  end

  defp aliases do
    [
      setup: ["deps.get"],
      "lint.all": ["format --check-formatted", "credo --strict", "dialyzer"],
      test: ["test"]
    ]
  end

  defp package do
    [
      maintainers: ["Code Puppy Team"],
      licenses: ["MIT"],
      links: %{
        "GitHub" => @source_url
      }
    ]
  end

  defp docs do
    [
      main: "Mana",
      source_ref: "v#{@version}",
      source_url: @source_url,
      extras: [
        "README.md": [title: "Overview"]
      ],
      groups_for_modules: [
        Plugin: [
          Mana.Plugin.Behaviour,
          Mana.Plugin.Manager,
          Mana.Plugin.Hook
        ],
        "Built-in Plugins": ~r/Mana\.Plugins\.*/
      ]
    ]
  end
end
