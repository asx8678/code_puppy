defmodule Mana.RunContext do
  @moduledoc """
  Struct and helpers for execution context.

  RunContext tracks the execution state for agents and operations.
  It is stored in the process dictionary (Elixir's equivalent to Python's contextvars).

  ## Usage

      # Create a new context
      ctx = Mana.RunContext.new(agent_name: "my_agent", model_name: "gpt-4")

      # Store in process dictionary
      Mana.RunContext.put(ctx)

      # Retrieve from process dictionary
      ctx = Mana.RunContext.current()

      # Create a child context
      child_ctx = Mana.RunContext.child(ctx, agent_name: "child_agent")

  ## Fields

  - `id`: Unique identifier for this context
  - `parent_id`: ID of the parent context (nil for root contexts)
  - `agent_name`: Name of the executing agent
  - `model_name`: Name of the model being used
  - `session_id`: Session identifier (optional)
  - `started_at`: When the context was created (DateTime)
  - `metadata`: Additional context data (map)
  """

  @process_dict_key :mana_run_context

  defstruct [
    :id,
    :parent_id,
    :agent_name,
    :model_name,
    :session_id,
    :started_at,
    :metadata
  ]

  @type t :: %__MODULE__{
          id: String.t(),
          parent_id: String.t() | nil,
          agent_name: String.t(),
          model_name: String.t(),
          session_id: String.t() | nil,
          started_at: DateTime.t(),
          metadata: map()
        }

  @doc """
  Creates a new RunContext with the given options.

  ## Options

  - `:id` - Custom ID (default: auto-generated UUID)
  - `:parent_id` - Parent context ID (default: nil)
  - `:agent_name` - Agent name (required)
  - `:model_name` - Model name (required)
  - `:session_id` - Session ID (optional)
  - `:metadata` - Additional metadata map (default: %{})

  ## Examples

      iex> ctx = Mana.RunContext.new(agent_name: "agent1", model_name: "gpt-4")
      %Mana.RunContext{...}
  """
  @spec new(keyword()) :: t()
  def new(opts \\ []) do
    id = Keyword.get(opts, :id, generate_id())
    parent_id = Keyword.get(opts, :parent_id, nil)
    agent_name = Keyword.fetch!(opts, :agent_name)
    model_name = Keyword.fetch!(opts, :model_name)
    session_id = Keyword.get(opts, :session_id, nil)
    metadata = Keyword.get(opts, :metadata, %{})

    %__MODULE__{
      id: id,
      parent_id: parent_id,
      agent_name: agent_name,
      model_name: model_name,
      session_id: session_id,
      started_at: DateTime.utc_now(),
      metadata: metadata
    }
  end

  @doc """
  Returns the current context from the process dictionary.

  Returns `nil` if no context is set.

  ## Examples

      iex> Mana.RunContext.current()
      %Mana.RunContext{agent_name: "agent1", ...}
  """
  @spec current() :: t() | nil
  def current do
    Process.get(@process_dict_key)
  end

  @doc """
  Stores the context in the process dictionary.

  Returns the context for chaining.

  ## Examples

      iex> ctx = Mana.RunContext.new(agent_name: "agent1", model_name: "gpt-4")
      iex> Mana.RunContext.put(ctx)
      %Mana.RunContext{...}
  """
  @spec put(t()) :: t()
  def put(%__MODULE__{} = context) do
    Process.put(@process_dict_key, context)
    context
  end

  @doc """
  Clears the context from the process dictionary.

  Returns the previous context or nil.

  ## Examples

      iex> Mana.RunContext.clear()
      %Mana.RunContext{...} | nil
  """
  @spec clear() :: t() | nil
  def clear do
    Process.delete(@process_dict_key)
  end

  @doc """
  Creates a child context from a parent context.

  The child inherits all fields from the parent, with optional overrides.
  The parent ID is automatically set to the parent's ID.

  ## Examples

      iex> parent = Mana.RunContext.new(agent_name: "parent", model_name: "gpt-4")
      iex> child = Mana.RunContext.child(parent, agent_name: "child")
      %Mana.RunContext{parent_id: parent.id, agent_name: "child", ...}
  """
  @spec child(t(), keyword()) :: t()
  def child(%__MODULE__{} = parent, overrides \\ []) do
    new_id = generate_id()

    # Build opts from parent with overrides
    opts = [
      id: new_id,
      parent_id: parent.id,
      agent_name: Keyword.get(overrides, :agent_name, parent.agent_name),
      model_name: Keyword.get(overrides, :model_name, parent.model_name),
      session_id: Keyword.get(overrides, :session_id, parent.session_id),
      metadata: Map.merge(parent.metadata, Keyword.get(overrides, :metadata, %{}))
    ]

    new(opts)
  end

  @doc """
  Calculates the elapsed time in milliseconds since the context was created.

  ## Examples

      iex> ctx = Mana.RunContext.new(agent_name: "agent1", model_name: "gpt-4")
      iex> :timer.sleep(10)
      iex> Mana.RunContext.elapsed_ms(ctx) >= 10
      true
  """
  @spec elapsed_ms(t()) :: non_neg_integer()
  def elapsed_ms(%__MODULE__{} = context) do
    now = DateTime.utc_now()
    DateTime.diff(now, context.started_at, :millisecond)
  end

  @doc """
  Returns true if the context has a parent (i.e., is not a root context).

  ## Examples

      iex> root = Mana.RunContext.new(agent_name: "root", model_name: "gpt-4")
      iex> Mana.RunContext.has_parent?(root)
      false
      iex> child = Mana.RunContext.child(root)
      iex> Mana.RunContext.has_parent?(child)
      true
  """
  @spec has_parent?(t()) :: boolean()
  def has_parent?(%__MODULE__{} = context) do
    context.parent_id != nil
  end

  @doc """
  Converts the context to a map representation.

  Useful for serialization or logging.

  ## Examples

      iex> ctx = Mana.RunContext.new(agent_name: "agent1", model_name: "gpt-4")
      iex> Mana.RunContext.to_map(ctx)
      %{id: "...", agent_name: "agent1", ...}
  """
  @spec to_map(t()) :: map()
  def to_map(%__MODULE__{} = context) do
    %{
      id: context.id,
      parent_id: context.parent_id,
      agent_name: context.agent_name,
      model_name: context.model_name,
      session_id: context.session_id,
      started_at: DateTime.to_iso8601(context.started_at),
      metadata: context.metadata
    }
  end

  @doc """
  Creates a context from a map representation.

  ## Examples

      iex> map = %{id: "abc", agent_name: "agent1", model_name: "gpt-4", started_at: "2024-01-01T00:00:00Z"}
      iex> Mana.RunContext.from_map(map)
      %Mana.RunContext{...}
  """
  @spec from_map(map()) :: t()
  def from_map(map) when is_map(map) do
    started_at =
      case map["started_at"] || map[:started_at] do
        %DateTime{} = dt ->
          dt

        iso_string when is_binary(iso_string) ->
          case DateTime.from_iso8601(iso_string) do
            {:ok, dt, _} -> dt
            _ -> DateTime.utc_now()
          end

        _ ->
          DateTime.utc_now()
      end

    metadata = map["metadata"] || map[:metadata] || %{}

    %__MODULE__{
      id: map["id"] || map[:id] || generate_id(),
      parent_id: map["parent_id"] || map[:parent_id],
      agent_name: map["agent_name"] || map[:agent_name] || "unknown",
      model_name: map["model_name"] || map[:model_name] || "unknown",
      session_id: map["session_id"] || map[:session_id],
      started_at: started_at,
      metadata: metadata
    }
  end

  # Private Functions

  defp generate_id do
    :crypto.strong_rand_bytes(16)
    |> Base.encode16(case: :lower)
  end
end
