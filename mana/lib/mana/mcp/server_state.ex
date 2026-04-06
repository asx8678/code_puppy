defmodule Mana.MCP.ServerState do
  @moduledoc """
  MCP server state machine definitions and transition helpers.

  This module defines the possible states of an MCP server and provides
  predicates for state validation and transition checking.

  ## States

  - `:stopped` - Server is not running (default initial state)
  - `:starting` - Server is initializing but not yet ready
  - `:running` - Server is active and handling requests
  - `:stopping` - Server is shutting down
  - `:error` - Server encountered an error and cannot operate
  - `:quarantined` - Server is temporarily disabled (circuit breaker)

  ## Transitions

  State transitions follow this pattern:

      stopped -> starting -> running -> stopping -> stopped
         ^        |          |          |            |
         |        v          v          v            |
         +------ error <----+-----------+            |
         ^                                            |
         +----------- quarantined --------------------+

  A quarantined server can recover to `:stopped` or `:running` depending
  on whether it's enabled when the quarantine expires.
  """

  @typedoc "MCP server state atom"
  @type t :: :stopped | :starting | :running | :stopping | :error | :quarantined

  @all_states [:stopped, :starting, :running, :stopping, :error, :quarantined]

  @doc """
  Returns all valid server states.

  ## Examples

      iex> Mana.MCP.ServerState.all()
      [:stopped, :starting, :running, :stopping, :error, :quarantined]
  """
  @spec all() :: [t()]
  def all, do: @all_states

  @doc """
  Checks if a state is valid.

  ## Examples

      iex> Mana.MCP.ServerState.valid?(:running)
      true

      iex> Mana.MCP.ServerState.valid?(:invalid)
      false
  """
  @spec valid?(atom()) :: boolean()
  def valid?(state) when is_atom(state), do: state in @all_states
  def valid?(_), do: false

  @doc """
  Returns valid transitions from a given state.

  ## Examples

      iex> Mana.MCP.ServerState.transitions_from(:stopped)
      [:starting, :error]

      iex> Mana.MCP.ServerState.transitions_from(:running)
      [:stopping, :error, :quarantined]
  """
  @spec transitions_from(t()) :: [t()]
  def transitions_from(:stopped), do: [:starting, :error]
  def transitions_from(:starting), do: [:running, :error, :stopped]
  def transitions_from(:running), do: [:stopping, :error, :quarantined]
  def transitions_from(:stopping), do: [:stopped, :error]
  def transitions_from(:error), do: [:stopped]
  def transitions_from(:quarantined), do: [:stopped, :running]

  @doc """
  Checks if a transition from one state to another is valid.

  ## Examples

      iex> Mana.MCP.ServerState.can_transition?(:stopped, :starting)
      true

      iex> Mana.MCP.ServerState.can_transition?(:stopped, :running)
      false
  """
  @spec can_transition?(t(), t()) :: boolean()
  def can_transition?(from, to) do
    valid?(from) and valid?(to) and to in transitions_from(from)
  end

  @doc """
  Returns a human-readable description of a state.

  ## Examples

      iex> Mana.MCP.ServerState.description(:running)
      "Server is active and handling requests"
  """
  @spec description(t()) :: String.t()
  def description(:stopped), do: "Server is not running"
  def description(:starting), do: "Server is initializing"
  def description(:running), do: "Server is active and handling requests"
  def description(:stopping), do: "Server is shutting down"
  def description(:error), do: "Server encountered an error"
  def description(:quarantined), do: "Server is temporarily disabled"

  @doc """
  Checks if a state represents an active/running server.

  Returns true for `:running` only.

  ## Examples

      iex> Mana.MCP.ServerState.active?(:running)
      true

      iex> Mana.MCP.ServerState.active?(:starting)
      false
  """
  @spec active?(t()) :: boolean()
  def active?(:running), do: true
  def active?(_), do: false

  @doc """
  Checks if a state represents a terminal or non-recoverable state.

  A terminal state is one that requires external intervention to exit.

  ## Examples

      iex> Mana.MCP.ServerState.terminal?(:error)
      true

      iex> Mana.MCP.ServerState.terminal?(:quarantined)
      false
  """
  @spec terminal?(t()) :: boolean()
  def terminal?(:error), do: true
  def terminal?(_), do: false

  @doc """
  Checks if a state is considered healthy (can accept requests).

  A healthy server is either running or in a transitional state
  that will lead to running.

  ## Examples

      iex> Mana.MCP.ServerState.healthy?(:running)
      true

      iex> Mana.MCP.ServerState.healthy?(:error)
      false
  """
  @spec healthy?(t()) :: boolean()
  def healthy?(state) when state in [:running, :starting], do: true
  def healthy?(_), do: false
end
