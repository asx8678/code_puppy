defmodule CodePuppyControl.Messaging.Commands do
  @moduledoc """
  UI→Agent command schema and serialization.

  Defines command structs that flow FROM the UI TO the Agent, mirroring the
  Python `code_puppy.messaging.commands` models. Commands control agent
  execution (cancel, interrupt) and carry user responses to agent prompts
  (input, confirmation, selection).

      ┌─────────┐   Commands    ┌─────────┐
      │   UI    │ ────────────> │  Agent  │
      │ (User)  │               │         │
      │         │ <──────────── │         │
      └─────────┘   Messages    └─────────┘

  ## Wire Format

  All commands are serialized as JSON-safe string-keyed maps with a
  `"command_type"` discriminator for polymorphic deserialization:

      %{
        "command_type" => "cancel_agent",
        "id" => "a1b2c3d4...",
        "timestamp" => 1717000000000,
        "reason" => "user requested"
      }

  ## Command Types

  | command_type           | Struct                    | Description                        |
  |------------------------|---------------------------|------------------------------------|
  | `"cancel_agent"`       | `CancelAgentCommand`      | Soft-cancel running agent          |
  | `"interrupt_shell"`    | `InterruptShellCommand`   | SIGINT a running shell command     |
  | `"user_input_response"`| `UserInputResponse`      | Respond to a user input prompt     |
  | `"confirmation_response"`| `ConfirmationResponse` | Respond to a confirmation prompt    |
  | `"selection_response"` | `SelectionResponse`       | Respond to a selection prompt      |

  ## Validation

  - `from_wire/1` rejects unknown `command_type` values with `{:error, :unknown_command_type}`.
  - Extra/unknown fields are rejected with `{:error, :extra_fields_not_allowed}`.
  - `SelectionResponse.selected_index` must be a non-negative integer.
  - Malformed payloads (non-maps, missing required keys, wrong types) return
    `{:error, reason}` — never raises.

  ## ID & Timestamp Defaults

  When `id` or `timestamp` are absent in a wire map, defaults are generated:
  - `id`: 32-char lowercase hex from `:crypto.strong_rand_bytes(16)`.
  - `timestamp`: Integer Unix milliseconds from `System.system_time(:millisecond)`.
  """

  # ---------------------------------------------------------------------------
  # Struct Definitions
  # ---------------------------------------------------------------------------

  defstruct [:command_type, :id, :timestamp]

  @type command_type ::
          :cancel_agent
          | :interrupt_shell
          | :user_input_response
          | :confirmation_response
          | :selection_response

  @type t ::
          CancelAgentCommand.t()
          | InterruptShellCommand.t()
          | UserInputResponse.t()
          | ConfirmationResponse.t()
          | SelectionResponse.t()

  # -- CancelAgentCommand ----------------------------------------------------

  defmodule CancelAgentCommand do
    @moduledoc "Signals the agent to stop current execution gracefully."

    @enforce_keys [:command_type, :id, :timestamp]
    defstruct [:command_type, :id, :timestamp, :reason]

    @type t :: %__MODULE__{
            command_type: :cancel_agent,
            id: String.t(),
            timestamp: integer(),
            reason: String.t() | nil
          }
  end

  # -- InterruptShellCommand -------------------------------------------------

  defmodule InterruptShellCommand do
    @moduledoc "Signals to interrupt a currently running shell command."

    @enforce_keys [:command_type, :id, :timestamp]
    defstruct [:command_type, :id, :timestamp, :command_id]

    @type t :: %__MODULE__{
            command_type: :interrupt_shell,
            id: String.t(),
            timestamp: integer(),
            command_id: String.t() | nil
          }
  end

  # -- UserInputResponse -----------------------------------------------------

  defmodule UserInputResponse do
    @moduledoc "Response to a UserInputRequest from the agent."

    @enforce_keys [:command_type, :id, :timestamp, :prompt_id, :value]
    defstruct [:command_type, :id, :timestamp, :prompt_id, :value]

    @type t :: %__MODULE__{
            command_type: :user_input_response,
            id: String.t(),
            timestamp: integer(),
            prompt_id: String.t(),
            value: String.t()
          }
  end

  # -- ConfirmationResponse --------------------------------------------------

  defmodule ConfirmationResponse do
    @moduledoc "Response to a ConfirmationRequest from the agent."

    @enforce_keys [:command_type, :id, :timestamp, :prompt_id, :confirmed]
    defstruct [:command_type, :id, :timestamp, :prompt_id, :confirmed, :feedback]

    @type t :: %__MODULE__{
            command_type: :confirmation_response,
            id: String.t(),
            timestamp: integer(),
            prompt_id: String.t(),
            confirmed: boolean(),
            feedback: String.t() | nil
          }
  end

  # -- SelectionResponse -----------------------------------------------------

  defmodule SelectionResponse do
    @moduledoc "Response to a SelectionRequest from the agent."

    @enforce_keys [:command_type, :id, :timestamp, :prompt_id, :selected_index, :selected_value]
    defstruct [:command_type, :id, :timestamp, :prompt_id, :selected_index, :selected_value]

    @type t :: %__MODULE__{
            command_type: :selection_response,
            id: String.t(),
            timestamp: integer(),
            prompt_id: String.t(),
            selected_index: non_neg_integer(),
            selected_value: String.t()
          }
  end

  # ---------------------------------------------------------------------------
  # Command Type Mapping
  # ---------------------------------------------------------------------------

  @command_type_to_module %{
    "cancel_agent" => CancelAgentCommand,
    "interrupt_shell" => InterruptShellCommand,
    "user_input_response" => UserInputResponse,
    "confirmation_response" => ConfirmationResponse,
    "selection_response" => SelectionResponse
  }

  # Build reverse mapping at compile time using full module names
  # so that pattern match in to_wire/1 (%module{} = cmd) resolves correctly.
  @module_to_command_type @command_type_to_module
                          |> Enum.map(fn {type_str, mod} -> {mod, type_str} end)
                          |> Map.new()

  # Build allowed-fields map with full module keys at compile time.
  @allowed_fields (
                    fields_by_type = %{
                      "cancel_agent" => ~w(command_type id timestamp reason),
                      "interrupt_shell" => ~w(command_type id timestamp command_id),
                      "user_input_response" => ~w(command_type id timestamp prompt_id value),
                      "confirmation_response" =>
                        ~w(command_type id timestamp prompt_id confirmed feedback),
                      "selection_response" =>
                        ~w(command_type id timestamp prompt_id selected_index selected_value)
                    }

                    for {type_str, fields} <- fields_by_type,
                        into: %{} do
                      {@command_type_to_module[type_str], MapSet.new(fields)}
                    end
                  )

  # ---------------------------------------------------------------------------
  # Constructors
  # ---------------------------------------------------------------------------

  @doc """
  Builds a `CancelAgentCommand`.

  Omitting `id` or `timestamp` triggers auto-generation.
  """
  @spec cancel_agent(keyword()) :: CancelAgentCommand.t()
  def cancel_agent(opts \\ []) do
    {id, ts} = fill_defaults(opts)
    reason = Keyword.get(opts, :reason)

    %CancelAgentCommand{
      command_type: :cancel_agent,
      id: id,
      timestamp: ts,
      reason: reason
    }
  end

  @doc """
  Builds an `InterruptShellCommand`.
  """
  @spec interrupt_shell(keyword()) :: InterruptShellCommand.t()
  def interrupt_shell(opts \\ []) do
    {id, ts} = fill_defaults(opts)
    command_id = Keyword.get(opts, :command_id)

    %InterruptShellCommand{
      command_type: :interrupt_shell,
      id: id,
      timestamp: ts,
      command_id: command_id
    }
  end

  @doc """
  Builds a `UserInputResponse`.

  `prompt_id` and `value` are required.
  """
  @spec user_input_response(String.t(), String.t(), keyword()) :: UserInputResponse.t()
  def user_input_response(prompt_id, value, opts \\ []) do
    {id, ts} = fill_defaults(opts)

    %UserInputResponse{
      command_type: :user_input_response,
      id: id,
      timestamp: ts,
      prompt_id: prompt_id,
      value: value
    }
  end

  @doc """
  Builds a `ConfirmationResponse`.

  `prompt_id` and `confirmed` are required.
  """
  @spec confirmation_response(String.t(), boolean(), keyword()) :: ConfirmationResponse.t()
  def confirmation_response(prompt_id, confirmed, opts \\ []) do
    {id, ts} = fill_defaults(opts)
    feedback = Keyword.get(opts, :feedback)

    %ConfirmationResponse{
      command_type: :confirmation_response,
      id: id,
      timestamp: ts,
      prompt_id: prompt_id,
      confirmed: confirmed,
      feedback: feedback
    }
  end

  @doc """
  Builds a `SelectionResponse`.

  `prompt_id`, `selected_index` (≥ 0), and `selected_value` are required.
  Returns `{:ok, %SelectionResponse{}}` on success or
  `{:error, {:invalid_selected_index, value}}` if `selected_index` is
  negative or non-integer.
  """
  @spec selection_response(String.t(), term(), String.t(), keyword()) ::
          {:ok, SelectionResponse.t()} | {:error, {:invalid_selected_index, term()}}
  def selection_response(prompt_id, selected_index, selected_value, opts \\ []) do
    case validate_selected_index(selected_index) do
      :ok ->
        {id, ts} = fill_defaults(opts)

        {:ok,
         %SelectionResponse{
           command_type: :selection_response,
           id: id,
           timestamp: ts,
           prompt_id: prompt_id,
           selected_index: selected_index,
           selected_value: selected_value
         }}

      {:error, _} = err ->
        err
    end
  end

  @doc """
  Bang variant of `selection_response/4`.

  Returns the struct directly on success; raises `ArgumentError` on invalid
  `selected_index`.
  """
  @spec selection_response!(String.t(), non_neg_integer(), String.t(), keyword()) ::
          SelectionResponse.t()
  def selection_response!(prompt_id, selected_index, selected_value, opts \\ []) do
    case selection_response(prompt_id, selected_index, selected_value, opts) do
      {:ok, cmd} ->
        cmd

      {:error, {:invalid_selected_index, val}} ->
        raise ArgumentError, "selected_index must be a non-negative integer, got: #{inspect(val)}"
    end
  end

  # ---------------------------------------------------------------------------
  # Serialization: to_wire / from_wire
  # ---------------------------------------------------------------------------

  @doc """
  Converts a command struct to a JSON-safe string-keyed map (wire format).

  The `command_type` atom is converted to its string discriminator.
  `nil` optional fields are omitted from the wire map for compactness.
  """
  @spec to_wire(t()) :: map()
  def to_wire(%module{} = cmd) do
    type_str = @module_to_command_type[module]

    cmd
    |> Map.from_struct()
    |> Enum.filter(fn {_k, v} -> v != nil end)
    |> Enum.map(fn
      {:command_type, _atom} -> {"command_type", type_str}
      {k, v} -> {Atom.to_string(k), v}
    end)
    |> Map.new()
  end

  @doc """
  Parses a string-keyed wire map into a typed command struct.

  Returns `{:ok, command}` on success or `{:error, reason}` on failure.
  Never raises — all validation errors are returned as tagged tuples.

  ## Error Reasons

  | reason                       | meaning                                       |
  |------------------------------|-----------------------------------------------|
  | `:not_a_map`                 | Input is not a map                            |
  | `:unknown_command_type`      | `command_type` value is not recognized         |
  | `:missing_command_type`      | `command_type` key absent                      |
  | `:extra_fields_not_allowed`  | Unknown fields present (forbid extra)         |
  | `:invalid_selected_index`    | `selected_index` is negative or non-integer    |
  | `{:invalid_field_type, key}`  | A field has the wrong primitive type           |
  | `{:missing_required_field, key}` | A required field is absent                |
  """
  @spec from_wire(map()) :: {:ok, t()} | {:error, term()}
  def from_wire(wire) when is_map(wire) do
    with {:ok, type_str} <- fetch_command_type(wire),
         {:ok, module} <- resolve_module(type_str),
         :ok <- check_extra_fields(wire, module),
         {:ok, cmd} <- build_struct(wire, module) do
      {:ok, cmd}
    end
  end

  def from_wire(_), do: {:error, :not_a_map}

  # ---------------------------------------------------------------------------
  # Private Helpers
  # ---------------------------------------------------------------------------

  defp fill_defaults(opts) do
    id = Keyword.get(opts, :id) || generate_id()
    ts = Keyword.get(opts, :timestamp) || System.system_time(:millisecond)
    {id, ts}
  end

  defp generate_id do
    :crypto.strong_rand_bytes(16) |> Base.encode16(case: :lower)
  end

  defp fetch_command_type(wire) do
    case Map.fetch(wire, "command_type") do
      {:ok, type} when is_binary(type) -> {:ok, type}
      {:ok, _} -> {:error, :missing_command_type}
      :error -> {:error, :missing_command_type}
    end
  end

  defp resolve_module(type_str) do
    case Map.fetch(@command_type_to_module, type_str) do
      {:ok, module} -> {:ok, module}
      :error -> {:error, :unknown_command_type}
    end
  end

  defp check_extra_fields(wire, module) do
    allowed = @allowed_fields[module]
    extra = Map.keys(wire) |> MapSet.new() |> MapSet.difference(allowed)

    if MapSet.size(extra) == 0 do
      :ok
    else
      {:error, :extra_fields_not_allowed}
    end
  end

  defp build_struct(wire, module) do
    with {:ok, id} <- resolve_id(wire),
         {:ok, ts} <- resolve_timestamp(wire),
         {:ok, extra} <- extract_extra_fields(wire, module),
         {:ok, struct} <- construct_module(module, id, ts, extra),
         :ok <- validate_struct_fields(struct) do
      {:ok, struct}
    end
  end

  defp resolve_id(wire) do
    case Map.fetch(wire, "id") do
      {:ok, id} when is_binary(id) -> {:ok, id}
      {:ok, _} -> {:error, {:invalid_field_type, "id"}}
      :error -> {:ok, generate_id()}
    end
  end

  defp resolve_timestamp(wire) do
    case Map.fetch(wire, "timestamp") do
      {:ok, ts} when is_integer(ts) and ts >= 0 -> {:ok, ts}
      {:ok, _} -> {:error, {:invalid_field_type, "timestamp"}}
      :error -> {:ok, System.system_time(:millisecond)}
    end
  end

  # Extracts fields specific to each command module (excluding base fields).
  defp extract_extra_fields(wire, CancelAgentCommand) do
    case Map.fetch(wire, "reason") do
      {:ok, r} when is_binary(r) or is_nil(r) -> {:ok, %{reason: r}}
      {:ok, _} -> {:error, {:invalid_field_type, "reason"}}
      :error -> {:ok, %{reason: nil}}
    end
  end

  defp extract_extra_fields(wire, InterruptShellCommand) do
    case Map.fetch(wire, "command_id") do
      {:ok, c} when is_binary(c) or is_nil(c) -> {:ok, %{command_id: c}}
      {:ok, _} -> {:error, {:invalid_field_type, "command_id"}}
      :error -> {:ok, %{command_id: nil}}
    end
  end

  defp extract_extra_fields(wire, UserInputResponse) do
    with {:ok, pid} <- require_string(wire, "prompt_id"),
         {:ok, val} <- require_string(wire, "value") do
      {:ok, %{prompt_id: pid, value: val}}
    end
  end

  defp extract_extra_fields(wire, ConfirmationResponse) do
    with {:ok, pid} <- require_string(wire, "prompt_id"),
         {:ok, confirmed} <- require_bool(wire, "confirmed"),
         {:ok, feedback} <- optional_string(wire, "feedback") do
      {:ok, %{prompt_id: pid, confirmed: confirmed, feedback: feedback}}
    end
  end

  defp extract_extra_fields(wire, SelectionResponse) do
    with {:ok, pid} <- require_string(wire, "prompt_id"),
         {:ok, idx} <- require_non_neg_int(wire, "selected_index"),
         {:ok, val} <- require_string(wire, "selected_value") do
      {:ok, %{prompt_id: pid, selected_index: idx, selected_value: val}}
    end
  end

  defp construct_module(CancelAgentCommand, id, ts, %{reason: reason}) do
    {:ok,
     %CancelAgentCommand{
       command_type: :cancel_agent,
       id: id,
       timestamp: ts,
       reason: reason
     }}
  end

  defp construct_module(InterruptShellCommand, id, ts, %{command_id: command_id}) do
    {:ok,
     %InterruptShellCommand{
       command_type: :interrupt_shell,
       id: id,
       timestamp: ts,
       command_id: command_id
     }}
  end

  defp construct_module(UserInputResponse, id, ts, %{prompt_id: pid, value: val}) do
    {:ok,
     %UserInputResponse{
       command_type: :user_input_response,
       id: id,
       timestamp: ts,
       prompt_id: pid,
       value: val
     }}
  end

  defp construct_module(ConfirmationResponse, id, ts, extra) do
    {:ok,
     %ConfirmationResponse{
       command_type: :confirmation_response,
       id: id,
       timestamp: ts,
       prompt_id: extra.prompt_id,
       confirmed: extra.confirmed,
       feedback: extra.feedback
     }}
  end

  defp construct_module(SelectionResponse, id, ts, extra) do
    {:ok,
     %SelectionResponse{
       command_type: :selection_response,
       id: id,
       timestamp: ts,
       prompt_id: extra.prompt_id,
       selected_index: extra.selected_index,
       selected_value: extra.selected_value
     }}
  end

  # Final validation pass on the constructed struct.
  defp validate_struct_fields(%SelectionResponse{selected_index: idx}) do
    if is_integer(idx) and idx >= 0, do: :ok, else: {:error, :invalid_selected_index}
  end

  defp validate_struct_fields(_), do: :ok

  # -- Field type helpers ----------------------------------------------------

  defp require_string(wire, key) do
    case Map.fetch(wire, key) do
      {:ok, v} when is_binary(v) -> {:ok, v}
      {:ok, _} -> {:error, {:invalid_field_type, key}}
      :error -> {:error, {:missing_required_field, key}}
    end
  end

  defp require_bool(wire, key) do
    case Map.fetch(wire, key) do
      {:ok, v} when is_boolean(v) -> {:ok, v}
      {:ok, _} -> {:error, {:invalid_field_type, key}}
      :error -> {:error, {:missing_required_field, key}}
    end
  end

  defp require_non_neg_int(wire, key) do
    case Map.fetch(wire, key) do
      {:ok, v} when is_integer(v) and v >= 0 -> {:ok, v}
      {:ok, v} when is_integer(v) -> {:error, :invalid_selected_index}
      {:ok, _} -> {:error, :invalid_selected_index}
      :error -> {:error, {:missing_required_field, key}}
    end
  end

  defp validate_selected_index(idx) when is_integer(idx) and idx >= 0, do: :ok

  defp validate_selected_index(idx), do: {:error, {:invalid_selected_index, idx}}

  # Validates an optional string-or-nil field.
  # Returns `{:ok, value}` when present-and-valid or absent; errors on bad type.
  defp optional_string(wire, key) do
    case Map.fetch(wire, key) do
      {:ok, v} when is_binary(v) or is_nil(v) -> {:ok, v}
      {:ok, _} -> {:error, {:invalid_field_type, key}}
      :error -> {:ok, nil}
    end
  end
end
