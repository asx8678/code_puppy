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

  @doc """
  Returns the human-readable display name for this agent.

  Used in the TUI agent selector and log messages.
  Default: title-cased version of `name/0` atom.
  """

  @callback response_schema() :: module() | nil

  @callback display_name() :: String.t()

  @doc """
  Returns a brief description of what this agent does.

  Shown in `/agents` output and the agent selector.
  Default: empty string.
  """

  @callback response_schema() :: module() | nil

  @callback description() :: String.t()

  @doc """
  Returns an optional custom user prompt prefix.

  When defined, this text is prepended to the user's message.
  Return `nil` to use the user's message as-is (default).
  """
  @callback user_prompt() :: String.t() | nil

  @doc """
  Returns optional tool configuration overrides.

  When defined, returns a map of tool-specific configuration
  (e.g. timeouts, permission modes). Return `nil` for defaults.
  """
  @callback tools_config() :: map() | nil

  @doc """
  Called before the agent run starts.

  Receives the run context. Return `{:ok, context}` to proceed
  (possibly with modified context) or `{:error, reason}` to abort.

  Plugins can use this to inject runtime dependencies or veto runs.
  Default: always proceed.
  """
  @callback on_before_run(context()) :: {:ok, context()} | {:error, term()}

  @doc """
  Called after the agent run completes (success or failure).

  Receives the final context and result summary. Return value is ignored.
  Useful for cleanup, logging, and side effects.
  Default: no-op.
  """
  @callback on_after_run(context(), result :: map()) :: :ok

  @callback response_schema() :: module() | nil

  @optional_callbacks [
    response_schema: 0,
    display_name: 0,
    description: 0,
    user_prompt: 0,
    tools_config: 0,
    on_before_run: 1,
    on_after_run: 2
  ]

  @doc """
  Called after a tool execution completes.

  The agent can inspect the result and either:
  - `{:cont, state}` — continue the run loop
  - `{:halt, reason}` — stop the run early (e.g. user interrupt, fatal error)

  The `state` map is agent-owned mutable state that persists across turns.
  Default implementation: always continue.
  """

  @callback response_schema() :: module() | nil

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

      @impl true
      def display_name do
        name()
        |> Atom.to_string()
        |> String.replace("_", " ")
        |> String.split(" ")
        |> Enum.map(&String.capitalize/1)
        |> Enum.join(" ")
      end

      @impl true
      def description, do: ""

      @impl true
      def user_prompt, do: nil

      @impl true
      def tools_config, do: nil

      @impl true
      def on_before_run(context), do: {:ok, context}

      @impl true
      def on_after_run(_context, _result), do: :ok

      defoverridable on_tool_result: 3,
                     response_schema: 0,
                     display_name: 0,
                     description: 0,
                     user_prompt: 0,
                     tools_config: 0,
                     on_before_run: 1,
                     on_after_run: 2
    end
  end
end
