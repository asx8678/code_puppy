defmodule CodePuppyControl.CLI.SlashCommands.Commands.AddModelPersistence do
  @moduledoc """
  Persistence layer for /add_model command.

  Handles reading and writing extra_models.json, including atomic writes
  and directory creation. Separated from the command module for testability.
  """

  alias CodePuppyControl.Config.Paths

  @doc """
  Persist a model config into extra_models.json.

  - Creates the file if it doesn't exist.
  - Merges into the existing dict (not a list).
  - Atomic write via temp file + rename.
  - Returns `{:ok, model_key}` on success.
  - Returns `{:error, :already_exists}` if the key is already present.
  - Returns `{:error, reason}` on other failures.
  """
  @spec persist(String.t(), map()) :: {:ok, String.t()} | {:error, term()}
  def persist(model_key, config) when is_binary(model_key) and is_map(config) do
    path = Paths.extra_models_file()

    with {:ok, existing} <- read_existing(path),
         :ok <- check_duplicate(existing, model_key),
         updated <- Map.put(existing, model_key, config),
         {:ok, _} <- atomic_write_json(path, updated) do
      {:ok, model_key}
    end
  end

  @doc """
  Read the current extra_models.json as a map.
  Returns an empty map if the file doesn't exist.
  Returns an error if the file is not a valid JSON object.
  """
  @spec read_existing(String.t()) :: {:ok, map()} | {:error, term()}
  def read_existing(path) do
    case File.read(path) do
      {:ok, content} ->
        case Jason.decode(content) do
          {:ok, data} when is_map(data) ->
            {:ok, data}

          {:ok, _other} ->
            {:error, "extra_models.json must be a dictionary, not a list"}

          {:error, reason} ->
            {:error, "Error parsing extra_models.json: #{inspect(reason)}"}
        end

      {:error, :enoent} ->
        {:ok, %{}}

      {:error, reason} ->
        {:error, "Error reading extra_models.json: #{inspect(reason)}"}
    end
  end

  @doc """
  Check if a model_key already exists in the config map.
  """
  @spec check_duplicate(map(), String.t()) :: :ok | {:error, :already_exists}
  def check_duplicate(existing, model_key) do
    if Map.has_key?(existing, model_key) do
      {:error, :already_exists}
    else
      :ok
    end
  end

  @doc """
  Write a JSON map to a file atomically (temp file + rename).
  Creates parent directories if needed.
  """
  @spec atomic_write_json(String.t(), map()) :: {:ok, String.t()} | {:error, term()}
  def atomic_write_json(path, data) do
    dir = Path.dirname(path)

    with :ok <- File.mkdir_p(dir),
         json = Jason.encode!(data, pretty: true),
         tmp_path = path <> ".tmp",
         :ok <- File.write(tmp_path, json),
         :ok <- File.rename(tmp_path, path) do
      {:ok, path}
    else
      {:error, reason} ->
        # Clean up temp file if it exists
        File.rm(path <> ".tmp")
        {:error, reason}
    end
  end
end
