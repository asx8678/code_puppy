defmodule CodePuppyControl.Tool.Runner do
  @moduledoc """
  Dispatches tool invocations with permission checks, schema validation,
  telemetry, and timeout handling.

  The runner is the single entry point for executing tools from the agent
  loop. It handles the full lifecycle:

  1. Resolve the tool module (registry → legacy fallback)
  2. Check permissions
  3. Validate arguments against the tool's schema
  4. Invoke the tool with timeout protection
  5. Emit telemetry events

  ## Usage

      # From the agent loop:
      result = Runner.invoke(:command_runner, %{"command" => "ls"}, %{run_id: "run-1"})

      # Returns:
      {:ok, %{success: true, stdout: "...", ...}}
      # or
      {:error, "permission denied: ..."}
      # or
      {:error, "validation failed: ..."}

  ## Telemetry

  Emits the following events:

  - `[:tool, :invoke, :start]` — before invocation, with `%{tool_name, args}`
  - `[:tool, :invoke, :stop]` — after invocation, with `%{tool_name, result, duration_ms}`

  ## Timeout

  Default timeout is 60 seconds. Override per-invocation via context `:timeout` key.
  """

  require Logger

  alias CodePuppyControl.Tool.Registry
  alias CodePuppyControl.Tool.Schema

  @default_timeout_ms 60_000

  # ── Public API ───────────────────────────────────────────────────────────

  @doc """
  Invokes a tool by name with the given arguments and context.

  ## Arguments

  - `tool_name` — Atom name of the tool (e.g., `:command_runner`)
  - `args` — Map of arguments (already decoded from JSON string) or raw
    JSON string to decode
  - `context` — Map with runtime metadata. Supported keys:
    - `:run_id` — Agent run identifier (for telemetry/logging)
    - `:agent_module` — The agent module requesting the tool
    - `:timeout` — Override timeout in milliseconds

  ## Returns

  - `{:ok, result}` — Tool executed successfully
  - `{:error, reason}` — Tool failed (permission denied, validation error,
    timeout, or tool error)

  ## Examples

      iex> Runner.invoke(:command_runner, %{"command" => "echo hello"}, %{run_id: "run-1"})
      {:ok, %{success: true, stdout: "hello\\n", ...}}

      iex> Runner.invoke(:nonexistent_tool, %{}, %{})
      {:error, "Tool not found: nonexistent_tool"}
  """
  @spec invoke(atom(), map() | String.t(), map()) :: {:ok, term()} | {:error, term()}
  def invoke(tool_name, args, context \\ %{}) when is_atom(tool_name) do
    # Decode args if they're a JSON string from the LLM
    args = decode_args(args)

    with {:ok, module} <- resolve_tool(tool_name) do
      do_invoke(module, tool_name, args, context)
    end
  end

  # ── Resolution ───────────────────────────────────────────────────────────

  @doc """
  Resolves a tool name to its implementing module.

  Checks the registry first, then falls back to legacy module resolution
  (converting atom name like `:echo_tool` to module `Tool.EchoTool`).
  """
  @spec resolve_tool(atom()) :: {:ok, module()} | {:error, String.t()}
  def resolve_tool(tool_name) when is_atom(tool_name) do
    case Registry.lookup(tool_name) do
      {:ok, module} ->
        {:ok, module}

      :error ->
        # Legacy fallback: resolve from atom name to module
        case legacy_resolve(tool_name) do
          {:ok, module} -> {:ok, module}
          :error -> {:error, "Tool not found: #{tool_name}"}
        end
    end
  end

  defp legacy_resolve(tool_name) when is_atom(tool_name) do
    module_name =
      tool_name
      |> Atom.to_string()
      |> String.split("_")
      |> Enum.map(&String.capitalize/1)
      |> Enum.join()

    # Try Tool.* namespace first (matches existing convention)
    module = Module.concat([Tool, module_name])

    if Code.ensure_loaded?(module) and function_exported?(module, :execute, 1) do
      {:ok, module}
    else
      :error
    end
  end

  # ── Dispatch ─────────────────────────────────────────────────────────────

  defp do_invoke(module, tool_name, args, context) do
    timeout = Map.get(context, :timeout, @default_timeout_ms)

    # Emit start telemetry
    start_time = System.monotonic_time(:millisecond)

    :telemetry.execute(
      [:tool, :invoke, :start],
      %{system_time: System.system_time()},
      %{tool_name: tool_name, args: args}
    )

    # Run the tool with timeout protection
    result = run_with_timeout(module, tool_name, args, context, timeout)

    # Emit stop telemetry
    duration_ms = System.monotonic_time(:millisecond) - start_time

    :telemetry.execute(
      [:tool, :invoke, :stop],
      %{duration: duration_ms},
      %{tool_name: tool_name, result: result}
    )

    result
  end

  defp run_with_timeout(module, tool_name, args, context, timeout) do
    task =
      Task.async(fn ->
        # 1. Permission check
        with :ok <- check_permission(module, args, context) do
          # 2. Schema validation (only for modules with the Tool behaviour)
          with :ok <- validate_args(module, args) do
            # 3. Invoke the tool
            invoke_tool(module, tool_name, args, context)
          end
        end
      end)

    case Task.yield(task, timeout) || Task.shutdown(task, :brutal_kill) do
      {:ok, result} ->
        result

      nil ->
        Logger.warning("Tool #{tool_name} timed out after #{timeout}ms")
        {:error, "Tool #{tool_name} timed out after #{timeout}ms"}

      {:exit, reason} ->
        Logger.warning("Tool #{tool_name} crashed: #{inspect(reason)}")
        {:error, "Tool #{tool_name} crashed: #{inspect(reason)}"}
    end
  end

  # ── Permission Check ─────────────────────────────────────────────────────

  defp check_permission(module, args, context) do
    if function_exported?(module, :permission_check, 2) do
      try do
        case module.permission_check(args, context) do
          :ok -> :ok
          {:deny, reason} -> {:error, "permission denied: #{reason}"}
        end
      rescue
        e -> {:error, "permission check failed: #{Exception.message(e)}"}
      end
    else
      # No permission_check defined — allow by default
      :ok
    end
  end

  # ── Argument Validation ──────────────────────────────────────────────────

  defp validate_args(module, args) do
    if function_exported?(module, :parameters, 0) do
      schema = module.parameters()

      case Schema.validate(schema, args) do
        {:ok, _validated} -> :ok
        {:error, violations} -> {:error, "validation failed: #{Enum.join(violations, "; ")}"}
      end
    else
      # No schema defined — skip validation
      :ok
    end
  end

  # ── Tool Invocation ──────────────────────────────────────────────────────

  defp invoke_tool(module, tool_name, args, context) do
    try do
      if function_exported?(module, :invoke, 2) do
        module.invoke(args, context)
      else
        # Legacy fallback: call execute/1
        module.execute(args)
      end
    rescue
      e ->
        Logger.warning("Tool #{tool_name} raised: #{Exception.message(e)}")
        {:error, "Tool #{tool_name} error: #{Exception.message(e)}"}
    catch
      kind, reason ->
        Logger.warning("Tool #{tool_name} threw #{kind}: #{inspect(reason)}")
        {:error, "Tool #{tool_name} #{kind}: #{inspect(reason)}"}
    end
  end

  # ── Argument Decoding ────────────────────────────────────────────────────

  @doc """
  Decodes tool arguments from the format the LLM provides.

  LLM providers typically send tool arguments as a JSON string. This
  function handles both string and map inputs gracefully.
  """
  @spec decode_args(String.t() | map() | nil) :: map()
  def decode_args(args)

  def decode_args(args) when is_binary(args) do
    case Jason.decode(args) do
      {:ok, map} when is_map(map) -> map
      {:ok, other} -> %{"_raw" => other}
      {:error, _} -> %{"_raw" => args}
    end
  end

  def decode_args(args) when is_map(args), do: args
  def decode_args(nil), do: %{}
  def decode_args(_other), do: %{}

  # ── Context Builder ──────────────────────────────────────────────────────

  @doc """
  Builds a standard tool invocation context map.

  Useful for constructing context from agent loop state.

  ## Examples

      iex> Runner.build_context(run_id: "run-1", agent_module: MyApp.Agents.ElixirDev)
      %{run_id: "run-1", agent_module: MyApp.Agents.ElixirDev}
  """
  @spec build_context(keyword()) :: map()
  def build_context(opts \\ []) do
    opts
    |> Enum.into(%{})
    |> Map.put_new(:timestamp, System.system_time(:millisecond))
  end
end
