defmodule Mana.Streaming.PartTracker do
  @moduledoc """
  Tracks active streaming parts and token counts.

  Replaces 6 Python sets + 2 dicts with a single Elixir struct.
  Maintains state about active parts, token counts, and tool names
  during streaming event processing.

  ## Fields

  - `:active_parts` - Map of part_id => %{type: atom, started_at: integer}
  - `:token_counts` - Map of part_id => %{input: integer, output: integer}
  - `:tool_names` - Map of part_id => tool_name
  - `:total_input_tokens` - Cumulative input token count
  - `:total_output_tokens` - Cumulative output token count
  - `:part_counter` - Counter for tracking part order

  ## Example

      tracker = Mana.Streaming.PartTracker.new()
      tracker = Mana.Streaming.PartTracker.start_part(tracker, "part_1", :text)
      tracker = Mana.Streaming.PartTracker.update_tokens(tracker, "part_1", 10, 5)
      {input, output} = Mana.Streaming.PartTracker.total_tokens(tracker)
  """

  defstruct [
    :active_parts,
    :token_counts,
    :tool_names,
    :total_input_tokens,
    :total_output_tokens,
    :part_counter
  ]

  @type t :: %__MODULE__{
          active_parts: %{String.t() => %{type: atom(), started_at: integer()}},
          token_counts: %{String.t() => %{input: non_neg_integer(), output: non_neg_integer()}},
          tool_names: %{String.t() => String.t()},
          total_input_tokens: non_neg_integer(),
          total_output_tokens: non_neg_integer(),
          part_counter: non_neg_integer()
        }

  @doc """
  Creates a new empty PartTracker.
  """
  @spec new() :: t()
  def new do
    %__MODULE__{
      active_parts: %{},
      token_counts: %{},
      tool_names: %{},
      total_input_tokens: 0,
      total_output_tokens: 0,
      part_counter: 0
    }
  end

  @doc """
  Starts tracking a new part.

  ## Parameters

  - `tracker` - The current PartTracker struct
  - `part_id` - Unique identifier for the part
  - `type` - Atom indicating the part type (e.g., `:text`, `:thinking`, `:tool`)

  ## Returns

  Updated PartTracker with the new part added to active_parts and counter incremented.
  """
  @spec start_part(t(), String.t(), atom()) :: t()
  def start_part(%__MODULE__{} = tracker, part_id, type) do
    part_info = %{
      type: type,
      started_at: System.monotonic_time(:millisecond)
    }

    %__MODULE__{
      tracker
      | active_parts: Map.put(tracker.active_parts, part_id, part_info),
        part_counter: tracker.part_counter + 1
    }
  end

  @doc """
  Ends tracking for a part.

  ## Parameters

  - `tracker` - The current PartTracker struct
  - `part_id` - Unique identifier for the part to remove

  ## Returns

  Updated PartTracker with the part removed from active_parts.
  """
  @spec end_part(t(), String.t()) :: t()
  def end_part(%__MODULE__{} = tracker, part_id) do
    %__MODULE__{
      tracker
      | active_parts: Map.delete(tracker.active_parts, part_id)
    }
  end

  @doc """
  Updates token counts for a part.

  ## Parameters

  - `tracker` - The current PartTracker struct
  - `part_id` - Unique identifier for the part
  - `input_delta` - Number of input tokens to add
  - `output_delta` - Number of output tokens to add

  ## Returns

  Updated PartTracker with incremented token counts.
  """
  @spec update_tokens(t(), String.t(), non_neg_integer(), non_neg_integer()) :: t()
  def update_tokens(%__MODULE__{} = tracker, part_id, input_delta, output_delta) do
    current_counts = Map.get(tracker.token_counts, part_id, %{input: 0, output: 0})

    new_counts = %{
      input: current_counts.input + input_delta,
      output: current_counts.output + output_delta
    }

    %__MODULE__{
      tracker
      | token_counts: Map.put(tracker.token_counts, part_id, new_counts),
        total_input_tokens: tracker.total_input_tokens + input_delta,
        total_output_tokens: tracker.total_output_tokens + output_delta
    }
  end

  @doc """
  Sets the tool name for a part.

  ## Parameters

  - `tracker` - The current PartTracker struct
  - `part_id` - Unique identifier for the part
  - `tool_name` - String name of the tool

  ## Returns

  Updated PartTracker with the tool name recorded.
  """
  @spec set_tool_name(t(), String.t(), String.t()) :: t()
  def set_tool_name(%__MODULE__{} = tracker, part_id, tool_name) do
    %__MODULE__{
      tracker
      | tool_names: Map.put(tracker.tool_names, part_id, tool_name)
    }
  end

  @doc """
  Checks if any active part has the given type.

  ## Parameters

  - `tracker` - The current PartTracker struct
  - `type` - Atom indicating the part type to check for

  ## Returns

  `true` if any active part has the given type, `false` otherwise.
  """
  @spec active_type?(t(), atom()) :: boolean()
  def active_type?(tracker, type) do
    Enum.any?(tracker.active_parts, fn {_part_id, info} ->
      info.type == type
    end)
  end

  @doc """
  Returns the map of active parts.
  """
  @spec active_parts(t()) :: %{String.t() => %{type: atom(), started_at: integer()}}
  def active_parts(tracker), do: tracker.active_parts

  @doc """
  Returns the total token counts as a tuple {input, output}.
  """
  @spec total_tokens(t()) :: {non_neg_integer(), non_neg_integer()}
  def total_tokens(tracker) do
    {tracker.total_input_tokens, tracker.total_output_tokens}
  end
end
