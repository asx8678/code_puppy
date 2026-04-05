defmodule Mana.Plugins.PackParallelism do
  @moduledoc "Injects parallel agent constraints into system prompts"
  @behaviour Mana.Plugin.Behaviour

  @default_max_parallel 2

  @impl true
  def name, do: "pack_parallelism"

  @impl true
  def init(config) do
    state = %{
      config: config,
      max_parallel: Map.get(config, :max_parallel, @default_max_parallel)
    }

    {:ok, state}
  end

  @impl true
  def hooks do
    [
      {:load_prompt, &__MODULE__.inject_parallelism_constraint/0},
      {:custom_command, &__MODULE__.handle_pack_parallel/2}
    ]
  end

  @doc """
  Injects the MAX_PARALLEL_AGENTS constraint into the system prompt.
  """
  def inject_parallelism_constraint do
    max = get_max_parallel()
    "\n## Pack Parallelism\nMAX_PARALLEL_AGENTS = #{max}\n"
  end

  @doc """
  Handles the /pack-parallel custom command.
  """
  def handle_pack_parallel("pack-parallel", [n]) when is_binary(n) do
    case Integer.parse(n) do
      {num, _} when num > 0 ->
        save_max_parallel(num)
        "Pack parallelism set to #{num}"

      _ ->
        "Invalid number. Usage: /pack-parallel N"
    end
  end

  def handle_pack_parallel("pack-parallel", _) do
    "Usage: /pack-parallel N (current: #{get_max_parallel()})"
  end

  def handle_pack_parallel(_, _), do: nil

  @doc """
  Gets the current max parallel agents setting from config.
  """
  def get_max_parallel do
    case Mana.Config.get(:pack_parallelism) do
      nil -> @default_max_parallel
      value when is_integer(value) and value > 0 -> value
      _ -> @default_max_parallel
    end
  end

  @doc """
  Saves the max parallel agents setting to config.
  """
  def save_max_parallel(n) when is_integer(n) and n > 0 do
    Mana.Config.put(:pack_parallelism, n)
  end

  @impl true
  def terminate do
    :ok
  end
end
