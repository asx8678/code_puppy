defmodule CodePuppyControl.Config do
  @moduledoc """
  Centralized configuration management for CodePuppyControl.

  This module provides typed accessor functions for all application configuration,
  validates required values at startup, and handles environment variable migration
  from legacy names to the standardized `PUP_` prefix.

  ## Environment Variables

  The following environment variables are recognized:

  | Variable | Legacy Name | Required in Prod | Description |
  |----------|-------------|-------------------|-------------|
  | `PUP_SECRET_KEY_BASE` | `SECRET_KEY_BASE` | Yes | Phoenix endpoint secret key (min 64 bytes) |
  | `PUP_DATABASE_PATH` | `DATABASE_PATH` | Yes | Path to SQLite database file |
  | `PUP_PYTHON_WORKER_SCRIPT` | `PYTHON_WORKER_SCRIPT` | Yes | Path to Python worker entry point |
  | `PUP_HISTORY_LIMIT` | - | No | Max events stored in history (default: 1000) |
  | `PUP_WEBSOCKET_SECRET` | - | No | Secret for WebSocket authentication (optional) |

  ## Migration Guide

  If you are currently using the legacy environment variable names, migrate by:

  1. Renaming `SECRET_KEY_BASE` to `PUP_SECRET_KEY_BASE`
  2. Renaming `DATABASE_PATH` to `PUP_DATABASE_PATH`
  3. Renaming `PYTHON_WORKER_SCRIPT` to `PUP_PYTHON_WORKER_SCRIPT`

  Legacy names are supported with deprecation warnings during a transition period.

  ## Usage

  Use the typed accessor functions rather than directly calling `Application.get_env/3`:

      # Preferred
      CodePuppyControl.Config.secret_key_base()
      CodePuppyControl.Config.database_path()

      # Avoid
      Application.get_env(:code_puppy_control, :secret_key_base)

  ## Validation

  In production environments (`MIX_ENV=prod`), required configuration values are
  validated at startup. Missing required configuration will cause the application
  to fail fast with a descriptive error message.

  Validation is relaxed in development and test environments to support zero-config
  local development.
  """

  require Logger

  @typedoc "Application environment atom"
  @type env :: :dev | :test | :prod

  @typedoc "Configuration key"
  @type key :: atom()

  @typedoc "Configuration value"
  @type value :: term()

  @doc """
  Returns the current application environment.

  ## Examples

      iex> CodePuppyControl.Config.config_env() in [:dev, :test, :prod]
      true
  """
  @spec config_env() :: env()
  def config_env do
    Application.get_env(:code_puppy_control, :env) ||
      if Mix.env() == :test, do: :test, else: Mix.env()
  catch
    # Handle cases where Mix is not available (releases)
    _, _ ->
      case System.get_env("MIX_ENV", "prod") do
        "dev" -> :dev
        "test" -> :test
        _ -> :prod
      end
  end

  @doc """
  Returns true if running in production environment.

  ## Examples

      iex> CodePuppyControl.Config.prod?()
      false
  """
  @spec prod?() :: boolean()
  def prod? do
    config_env() == :prod
  end

  @doc """
  Gets the secret key base for Phoenix endpoint.

  Required in production. Must be at least 64 bytes.

  ## Examples

      iex> CodePuppyControl.Config.secret_key_base()
      "secret_key_base_for_dev_only_..."
  """
  @spec secret_key_base() :: String.t()
  def secret_key_base do
    get_required_string(:secret_key_base, "PUP_SECRET_KEY_BASE", "SECRET_KEY_BASE")
  end

  @doc """
  Gets the database path for SQLite.

  Required in production. Defaults to in-memory or temp paths in dev/test.

  ## Examples

      iex> CodePuppyControl.Config.database_path()
      "priv/dev.db"
  """
  @spec database_path() :: String.t()
  def database_path do
    if prod?() do
      get_required_string(:database_path, "PUP_DATABASE_PATH", "DATABASE_PATH")
    else
      Application.get_env(:code_puppy_control, CodePuppyControl.Repo)[:database] ||
        get_string_with_legacy("PUP_DATABASE_PATH", "DATABASE_PATH", "priv/dev.db")
    end
  end

  @doc """
  Gets the path to the Python worker script.

  Required in production. In test, defaults to a mock path.

  ## Examples

      iex> CodePuppyControl.Config.python_worker_script()
      "/path/to/worker.py"
  """
  @spec python_worker_script() :: String.t()
  def python_worker_script do
    if prod?() do
      get_required_string(
        :python_worker_script,
        "PUP_PYTHON_WORKER_SCRIPT",
        "PYTHON_WORKER_SCRIPT"
      )
    else
      Application.get_env(:code_puppy_control, :python_worker_script) ||
        get_string_with_legacy(
          "PUP_PYTHON_WORKER_SCRIPT",
          "PYTHON_WORKER_SCRIPT",
          "/tmp/mock_python_worker.py"
        )
    end
  end

  @doc """
  Gets the history limit for event storage.

  This controls how many events are kept in the in-memory history.
  Defaults to 1000. Set to 0 for unlimited.

  ## Examples

      iex> CodePuppyControl.Config.history_limit()
      1000
  """
  @spec history_limit() :: non_neg_integer()
  def history_limit do
    value =
      Application.get_env(:code_puppy_control, :history_limit) ||
        parse_integer_env("PUP_HISTORY_LIMIT", 1000)

    if is_integer(value) and value >= 0 do
      value
    else
      Logger.warning("Invalid PUP_HISTORY_LIMIT value: #{inspect(value)}, using default 1000")
      1000
    end
  end

  @doc """
  Gets the WebSocket secret for authentication.

  Optional. If not set, WebSocket connections are accepted without authentication.
  Future versions will use this for token-based auth.

  ## Examples

      iex> CodePuppyControl.Config.websocket_secret()
      nil
  """
  @spec websocket_secret() :: String.t() | nil
  def websocket_secret do
    System.get_env("PUP_WEBSOCKET_SECRET")
  end

  @doc """
  Validates all required configuration.

  Called during application startup to fail fast if required configuration
  is missing in production environments.

  ## Raises

  - `RuntimeError` if required configuration is missing in production

  ## Examples

      iex> CodePuppyControl.Config.validate!()
      :ok
  """
  @spec validate!() :: :ok
  def validate! do
    if prod?() do
      _ = secret_key_base()
      _ = database_path()
      _ = python_worker_script()
      :ok
    else
      :ok
    end
  end

  @doc """
  Loads configuration from environment variables at runtime.

  This function should be called from `config/runtime.exs` to ensure
  environment variables are read and validated.

  Returns a keyword list of config values that can be passed to `config/2`.

  ## Examples

      iex> CodePuppyControl.Config.load_from_env()
      [secret_key_base: "...", database_path: "...", ...]
  """
  @spec load_from_env() :: keyword()
  def load_from_env do
    if prod?() do
      # In production, validate everything upfront
      validate!()

      [
        {CodePuppyControlWeb.Endpoint, [secret_key_base: secret_key_base()]},
        {CodePuppyControl.Repo, [database: database_path()]},
        {:python_worker_script, python_worker_script()},
        {:history_limit, history_limit()}
      ]
    else
      # In dev/test, use relaxed loading
      [
        {:python_worker_script, python_worker_script()},
        {:history_limit, history_limit()}
      ]
    end
  end

  # ============================================================================
  # Private Functions
  # ============================================================================

  # Gets a required string configuration value with legacy support
  defp get_required_string(config_key, new_var, legacy_var) do
    # First check if already loaded into application env
    case Application.get_env(:code_puppy_control, config_key) do
      nil ->
        # Load from env with legacy fallback
        value = get_string_with_legacy(new_var, legacy_var, nil)

        if is_nil(value) or value == "" do
          raise """
          Required environment variable #{new_var} is missing.

          You can set it via:
            export #{new_var}="your-value"

          #{if legacy_var != new_var, do: "Note: The legacy name #{legacy_var} is also supported but deprecated.", else: ""}
          """
        end

        # Store for future access
        Application.put_env(:code_puppy_control, config_key, value)
        value

      value ->
        value
    end
  end

  # Gets a string env var with legacy fallback and deprecation warning
  defp get_string_with_legacy(new_var, legacy_var, default) do
    case System.get_env(new_var) do
      nil ->
        case System.get_env(legacy_var) do
          nil ->
            default

          value ->
            # Only log deprecation warning in production to reduce noise
            if prod?() do
              Logger.warning(
                "Environment variable #{legacy_var} is deprecated. " <>
                  "Please migrate to #{new_var}."
              )
            end

            value
        end

      value ->
        value
    end
  end

  # Parses an integer environment variable
  defp parse_integer_env(var_name, default) do
    case System.get_env(var_name) do
      nil ->
        default

      "" ->
        default

      value ->
        case Integer.parse(value) do
          {int, ""} ->
            int

          _ ->
            Logger.warning(
              "Invalid integer value for #{var_name}: #{value}, using default #{default}"
            )

            default
        end
    end
  end
end
