defmodule Mana.Models.Provider do
  @moduledoc """
  Behaviour definition for model providers.

  This module defines the contract that all model providers must implement,
  including completion and streaming capabilities.
  """

  @doc """
  Returns the unique provider identifier string.
  """
  @callback provider_id() :: String.t()

  @doc """
  Validates the provider configuration.

  Returns `:ok` if valid, or `{:error, reason}` if invalid.
  """
  @callback validate_config(config :: map()) :: :ok | {:error, String.t()}

  @doc """
  Performs a completion request.

  Returns `{:ok, response}` on success, or `{:error, reason}` on failure.
  The response should contain `:content`, `:usage`, and `:model` keys.
  """
  @callback complete(messages :: [map()], model :: String.t(), opts :: keyword()) ::
              {:ok, map()} | {:error, term()}

  @doc """
  Performs a streaming completion request.

  Returns an `Enumerable.t()` that yields stream events.
  Events can be:
  - `{:part_start, type}`
  - `{:part_delta, type, content}`
  - `{:part_end, type}`
  """
  @callback stream(messages :: [map()], model :: String.t(), opts :: keyword()) :: Enumerable.t()
end
