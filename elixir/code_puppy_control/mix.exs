defmodule CodePuppyControl.MixProject do
  use Mix.Project

  def project do
    [
      app: :code_puppy_control,
      version: "0.1.0",
      elixir: "~> 1.15",
      elixirc_paths: elixirc_paths(Mix.env()),
      start_permanent: Mix.env() == :prod,
      aliases: aliases(),
      deps: deps()
    ]
  end

  def application do
    [
      mod: {CodePuppyControl.Application, []},
      extra_applications: [:logger, :runtime_tools]
    ]
  end

  defp elixirc_paths(:test), do: ["lib", "test/support"]
  defp elixirc_paths(_), do: ["lib"]

  defp deps do
    [
      {:phoenix, "~> 1.7"},
      {:phoenix_ecto, "~> 4.5"},
      {:phoenix_pubsub, "~> 2.1"},
      {:jason, "~> 1.4"},
      {:oban, "~> 2.17"},
      {:crontab, "~> 1.1"},
      {:plug_cowboy, "~> 2.7"},
      {:ecto_sqlite3, "~> 0.13"},
      {:telemetry, "~> 1.2"},
      {:rustler, "~> 0.34.0", runtime: false},
      {:benchee, "~> 1.1", only: :dev, runtime: false},
      {:benchee_markdown, "~> 0.3", only: :dev, runtime: false},
      # MessagePack for session serialization (bd-47)
      {:msgpax, "~> 2.4"}
    ]
  end

  defp aliases do
    [
      setup: ["deps.get", "ecto.setup"],
      "ecto.setup": ["ecto.create", "ecto.migrate", "run priv/repo/seeds.exs"],
      "ecto.reset": ["ecto.drop", "ecto.setup"],
      test: ["ecto.create --quiet", "ecto.migrate --quiet", "test"]
    ]
  end
end
