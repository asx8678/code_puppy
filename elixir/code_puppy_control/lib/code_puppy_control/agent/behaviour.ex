defmodule CodePuppyControl.Agent.Behaviour do
  @moduledoc """
  Behaviour that all Code Puppy agents must implement.

  This defines the contract for agent modules — the "what" of an agent.
  The "how" (the run loop, tool dispatch, streaming) lives in `Agent.Loop`.

  ## Example

      defmodule MyApp.Agents.ElixirDev do
        @behaviour CodePuppyControl.Agent.Behaviour

        @impl true
        def name, do: :elixir_dev

        @impl true
        def system_prompt(_context) do
          "You are an expert Elixir developer..."
        end

        @impl true
        def allowed_tools, do: [:file_read, :file_write, :shell]

        @impl true
        def model_preference, do: "claude-sonnet-4-20250514"

        @impl true
        def on_tool_result(_tool_name, _result, state), do: {:cont, state}
      end
  """

  @typedoc """
  Context map passed to callbacks. Contains runtime information about
  the current run, including session, messages, and caller-supplied opts.
  """
  @type context :: %{
          optional(:session_id) => String.t(),
          optional(:run_id) => String.t(),
          optional(:messages) => [map()],
          optional(:metadata) => map(),
          optional(atom()) => term()
        }

  @typedoc """
  Mutable state carried through a run. Agents can extend this via
  `on_tool_result/3` to track domain-specific state across turns.
  """
  @type agent_state :: %{
          optional(:turn_number) => non_neg_integer(),
          optional(:tool_results) => [map()],
          optional(atom()) => term()
        }

  @doc """
  Returns the unique atom name for this agent.

  Used for registration, logging, and telemetry.
  """
  @callback name() :: atom()

  @doc """
  Returns the system prompt for this agent, given the current context.

  The context includes session_id, run_id, and any caller-supplied metadata.
  The returned string becomes the system message in the LLM conversation.
  """
  @callback system_prompt(context()) :: String.t()

  @doc """
  Returns the list of tool names this agent is allowed to call.

  Tool dispatch in the loop will reject calls to tools not in this list.
  """
  @callback allowed_tools() :: [atom()]

  @doc """
  Returns the preferred model for this agent.

  Can be a model name string (e.g. `"claude-sonnet-4-20250514"`) or
  a `{:pack, :role}` tuple for model pack resolution.
  """
  @callback model_preference() :: String.t() | {:pack, atom()}

  @doc """
  Returns an optional Ecto schema module for validating text responses.

  When defined and returning a module, the agent loop will pass text-only
  responses (no tool calls) through `ResponseValidator.validate/2`. This
  enables typed, validated structured output from LLMs.

  Return `nil` to skip validation (default).

  ## Example

      @impl true
      def response_schema, do: MyAgent.PlanResponse

  See `CodePuppyControl.Agent.ResponseValidator` for schema requirements.
  """
  @callback response_schema() :: module() | nil

  @optional_callbacks [response_schema: 0]

  @doc """
  Called after a tool execution completes.

  The agent can inspect the result and either:
  - `{:cont, state}` — continue the run loop
  - `{:halt, reason}` — stop the run early (e.g. user interrupt, fatal error)

  The `state` map is agent-owned mutable state that persists across turns.
  Default implementation: always continue.
  """
  @callback on_tool_result(tool_name :: atom(), result :: term(), agent_state()) ::
              {:cont, agent_state()} | {:halt, term()}

  @doc false
  defmacro __using__(_opts) do
    quote do
      @behaviour CodePuppyControl.Agent.Behaviour

      @impl true
      def on_tool_result(_tool_name, _result, state), do: {:cont, state}

      @impl true
      def response_schema, do: nil

      defoverridable on_tool_result: 3, response_schema: 0
    end
  end
end
