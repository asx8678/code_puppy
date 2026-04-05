defmodule Mana.TTSR.Rule do
  @moduledoc "A TTSR rule definition"

  defstruct [
    :name,
    # Compiled Regex
    :trigger,
    # Rule content to inject
    :content,
    # File path
    :source,
    # :text | :thinking | :tool | :all
    scope: :text,
    # :once | {:gap, N}
    repeat: :once,
    triggered_at_turn: nil,
    pending: false
  ]

  @type t :: %__MODULE__{
          name: String.t(),
          trigger: Regex.t(),
          content: String.t(),
          source: String.t(),
          scope: :text | :thinking | :tool | :all,
          repeat: :once | {:gap, non_neg_integer()},
          triggered_at_turn: non_neg_integer() | nil,
          pending: boolean()
        }

  @doc """
  Creates a new Rule from options.

  ## Options

  - `:trigger` (required) - String regex pattern
  - `:content` - Rule content to inject
  - `:source` - File path
  - `:scope` - One of :text, :thinking, :tool, :all (default: :text)
  - `:repeat` - :once or {:gap, n} (default: :once)

  ## Examples

      iex> Mana.TTSR.Rule.new(
      ...>   name: "my_rule",
      ...>   trigger: "error|fail",
      ...>   content: "Watch for errors",
      ...>   source: "/path/to/rule.md"
      ...> )
  """
  @spec new(keyword()) :: t()
  def new(opts) do
    trigger = Keyword.fetch!(opts, :trigger)
    compiled = Regex.compile!(trigger)
    struct!(__MODULE__, Keyword.put(opts, :trigger, compiled))
  end

  @doc """
  Returns true if the rule is eligible to fire based on its repeat policy
  and the current turn count.
  """
  @spec eligible?(t(), non_neg_integer()) :: boolean()
  def eligible?(rule, current_turn) do
    case rule.repeat do
      :once ->
        is_nil(rule.triggered_at_turn)

      {:gap, n} ->
        is_nil(rule.triggered_at_turn) or
          current_turn - rule.triggered_at_turn >= n
    end
  end
end
