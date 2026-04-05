defmodule Mana.Config.Paths do
  @moduledoc """
  Pure functions for managing Mana configuration paths.

  Provides XDG Base Directory specification compliance with a fallback
  to ~/.mana/ for configuration and data storage.

  ## Path Resolution

  - Config directory: `XDG_CONFIG_HOME/mana/` or `~/.mana/`
  - Data directory: `XDG_DATA_HOME/mana/` or `~/.mana/data/`

  ## Examples

      iex> Mana.Config.Paths.config_dir()
      "/home/user/.mana"

      iex> Mana.Config.Paths.config_file()
      "/home/user/.mana/config.json"
  """

  @doc """
  Returns the home configuration directory path (alias for config_dir/0).
  """
  @spec home_dir() :: String.t()
  def home_dir, do: config_dir()

  @doc """
  Returns the configuration directory path.

  Uses `XDG_CONFIG_HOME/mana` if set, otherwise falls back to `~/.mana/`.
  """
  @spec config_dir() :: String.t()
  def config_dir do
    case System.get_env("XDG_CONFIG_HOME") do
      nil -> Path.join(System.get_env("HOME", ""), ".mana")
      xdg_config -> Path.join(xdg_config, "mana")
    end
  end

  @doc """
  Returns the data directory path.

  Uses `XDG_DATA_HOME/mana` if set, otherwise falls back to `~/.mana/data/`.
  """
  @spec data_dir() :: String.t()
  def data_dir do
    case System.get_env("XDG_DATA_HOME") do
      nil -> Path.join(config_dir(), "data")
      xdg_data -> Path.join(xdg_data, "mana")
    end
  end

  @doc """
  Returns the path to the main configuration file.
  """
  @spec config_file() :: String.t()
  def config_file do
    Path.join(config_dir(), "config.json")
  end

  @doc """
  Returns the path to the models configuration file.
  """
  @spec models_file() :: String.t()
  def models_file do
    Path.join(config_dir(), "models.json")
  end

  @doc """
  Returns the path to the agents data directory.
  """
  @spec agents_dir() :: String.t()
  def agents_dir do
    Path.join(data_dir(), "agents")
  end

  @doc """
  Returns the path to the sessions data directory.
  """
  @spec sessions_dir() :: String.t()
  def sessions_dir do
    Path.join(data_dir(), "sessions")
  end

  @doc """
  Ensures all configuration directories exist.

  Creates the config directory, data directory, agents directory, and
  sessions directory if they don't already exist.

  Returns `:ok` on success.
  """
  @spec ensure_dirs() :: :ok
  def ensure_dirs do
    File.mkdir_p!(config_dir())
    File.mkdir_p!(data_dir())
    File.mkdir_p!(agents_dir())
    File.mkdir_p!(sessions_dir())
    :ok
  end
end
