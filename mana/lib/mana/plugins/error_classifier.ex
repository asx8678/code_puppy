defmodule Mana.Plugins.ErrorClassifier do
  @moduledoc """
  Plugin that classifies agent and tool errors by category.

  Hooks into `agent_exception` and `agent_run_end` events, classifying
  errors into categories for better debugging and monitoring:

  - `:rate_limit` — HTTP 429 / rate-limit responses
  - `:auth` — Authentication / authorization failures
  - `:timeout` — Request timeouts
  - `:model_error` — Model API errors (5xx, invalid response)
  - `:tool_error` — Tool execution failures
  - `:unknown` — Unclassified errors

  ## Hooks Registered

  - `:agent_exception` — Classify errors on agent exception
  - `:agent_run_end` — Classify errors at end of agent run

  ## Example

      # In config
      config :mana, Mana.Plugin.Manager,
        plugins: [:discover, Mana.Plugins.ErrorClassifier]
  """

  @behaviour Mana.Plugin.Behaviour

  require Logger

  @type error_category ::
          :rate_limit | :auth | :timeout | :model_error | :tool_error | :unknown

  @type classification :: %{
          category: error_category(),
          message: String.t(),
          severity: atom(),
          retryable: boolean()
        }

  # ── Patterns for string-based classification ──────────────────────────────

  @rate_limit_patterns [
    ~r/rate.?limit/i,
    ~r/too many requests/i,
    ~r/429/,
    ~r/throttl/i,
    ~r/quota.*exceeded/i,
    ~r/RESOURCE_EXHAUSTED/
  ]

  @auth_patterns [
    ~r/unauthorized/i,
    ~r/forbidden/i,
    ~r/invalid.?api.?key/i,
    ~r/authentication/i,
    ~r/401/,
    ~r/403/,
    ~r/permission denied/i
  ]

  @timeout_patterns [
    ~r/timeout/i,
    ~r/timed? ?out/i,
    ~r/deadline exceeded/i,
    ~r/connection refused/i
  ]

  @model_error_patterns [
    ~r/model.*not found/i,
    ~r/invalid.?model/i,
    ~r/server error/i,
    ~r/internal server error/i,
    ~r/500/,
    ~r/502/,
    ~r/503/,
    ~r/context.?length/i,
    ~r/max.?tokens/i,
    ~r/content.?filter/i
  ]

  @tool_error_patterns [
    ~r/tool.*error/i,
    ~r/tool.*failed/i,
    ~r/execution.*error/i,
    ~r/function.*call.*fail/i
  ]

  # ── Plugin Behaviour ──────────────────────────────────────────────────────

  @impl true
  def name, do: "error_classifier"

  @impl true
  def init(config) do
    level = Map.get(config, :log_level, :info)
    Logger.put_module_level(__MODULE__, level)
    Logger.info("ErrorClassifier plugin initialized")
    {:ok, %{config: config}}
  end

  @impl true
  def hooks do
    [
      {:agent_exception, &__MODULE__.on_agent_exception/3},
      {:agent_run_end, &__MODULE__.on_agent_run_end/7}
    ]
  end

  @impl true
  def terminate do
    Logger.info("ErrorClassifier plugin shutting down")
    :ok
  end

  # ── Hook Handlers ─────────────────────────────────────────────────────────

  @doc """
  Classifies an agent exception and logs it by category.

  Called via the `:agent_exception` hook with `(exception, args, kwargs)`.
  """
  @spec on_agent_exception(Exception.t(), term(), term()) :: :ok
  def on_agent_exception(exception, _args, _kwargs) do
    classification = classify(exception)

    Logger.warning(
      "[ErrorClassifier] Agent exception classified as #{classification.category}: " <>
        classification.message <>
        " (severity: #{classification.severity}, retryable: #{classification.retryable})"
    )

    :ok
  rescue
    e ->
      Logger.error("[ErrorClassifier] Failed to classify exception: #{inspect(e)}")
      :ok
  end

  @doc """
  Classifies errors at the end of agent runs.

  Called via the `:agent_run_end` hook.
  """
  @spec on_agent_run_end(String.t(), String.t(), String.t() | nil, boolean(), term(), term(), term()) ::
          :ok
  def on_agent_run_end(_agent_name, _model_name, _session_id, true, _error, _response, _meta),
    do: :ok

  def on_agent_run_end(agent_name, model_name, session_id, false, error, _response, _meta) do
    if error != nil do
      classification = classify(error)
      session = session_id || "no-session"

      Logger.warning(
        "[ErrorClassifier] Agent run failed: #{agent_name} (model: #{model_name}, session: #{session}) " <>
          "-> #{classification.category}: #{classification.message}"
      )
    end

    :ok
  rescue
    e ->
      Logger.error("[ErrorClassifier] Failed in agent_run_end handler: #{inspect(e)}")
      :ok
  end

  # ── Public Classification API ─────────────────────────────────────────────

  @doc """
  Classify an error into a category.

  Accepts exceptions, error tuples, or strings. Returns a classification
  map with `:category`, `:message`, `:severity`, and `:retryable`.

  ## Examples

      iex> Mana.Plugins.ErrorClassifier.classify(%RuntimeError{message: "timeout exceeded"})
      %{category: :timeout, message: "timeout exceeded", severity: :warning, retryable: true}

      iex> Mana.Plugins.ErrorClassifier.classify({:error, :rate_limit})
      %{category: :rate_limit, message: "Rate limit error: rate_limit", severity: :warning, retryable: true}
  """
  @spec classify(Exception.t() | term()) :: classification()
  def classify(error) when is_binary(error) do
    classify_string(error)
  end

  def classify({:error, reason}) do
    classify_error_tuple(reason)
  end

  def classify(%{__struct__: _struct_name} = exception) do
    # First try the existing Mana.ErrorClassifier for detailed info
    detailed = Mana.ErrorClassifier.classify(exception)

    # Map the detailed severity to our category
    category = category_from_string(Exception.message(exception))
    severity = detailed.severity
    retryable = detailed.retryable

    %{category: category, message: detailed.message, severity: severity, retryable: retryable}
  rescue
    e ->
      message = safe_message(e)
      classify_string(message)
  end

  def classify(error) when is_atom(error) do
    case error do
      :timeout -> %{category: :timeout, message: "Operation timed out", severity: :warning, retryable: true}
      :rate_limit -> %{category: :rate_limit, message: "Rate limit exceeded", severity: :warning, retryable: true}
      :unauthorized -> %{category: :auth, message: "Unauthorized", severity: :error, retryable: false}
      :forbidden -> %{category: :auth, message: "Forbidden", severity: :error, retryable: false}
      other -> %{category: :unknown, message: "Error: #{other}", severity: :error, retryable: false}
    end
  end

  def classify(error) do
    message = safe_message(error)
    classify_string(message)
  end

  # ── Private Helpers ───────────────────────────────────────────────────────

  defp classify_string(string) when is_binary(string) do
    cond do
      matches_any?(string, @rate_limit_patterns) ->
        %{category: :rate_limit, message: truncate(string, 200), severity: :warning, retryable: true}

      matches_any?(string, @auth_patterns) ->
        %{category: :auth, message: truncate(string, 200), severity: :error, retryable: false}

      matches_any?(string, @timeout_patterns) ->
        %{category: :timeout, message: truncate(string, 200), severity: :warning, retryable: true}

      matches_any?(string, @model_error_patterns) ->
        %{category: :model_error, message: truncate(string, 200), severity: :error, retryable: true}

      matches_any?(string, @tool_error_patterns) ->
        %{category: :tool_error, message: truncate(string, 200), severity: :error, retryable: false}

      true ->
        %{category: :unknown, message: truncate(string, 200), severity: :error, retryable: false}
    end
  end

  defp classify_string(other), do: classify(safe_message(other))

  defp classify_error_tuple(reason) when is_binary(reason) do
    %{category: category_from_string(reason), message: reason, severity: :error, retryable: false}
  end

  defp classify_error_tuple(reason) when is_atom(reason) do
    classify(reason)
  end

  defp classify_error_tuple(reason) do
    message = inspect(reason, limit: 200)

    %{
      category: category_from_string(message),
      message: "Rate limit error: #{message}",
      severity: :error,
      retryable: false
    }
  end

  defp category_from_string(string) do
    cond do
      matches_any?(string, @rate_limit_patterns) -> :rate_limit
      matches_any?(string, @auth_patterns) -> :auth
      matches_any?(string, @timeout_patterns) -> :timeout
      matches_any?(string, @model_error_patterns) -> :model_error
      matches_any?(string, @tool_error_patterns) -> :tool_error
      true -> :unknown
    end
  end

  defp matches_any?(string, patterns) do
    Enum.any?(patterns, &Regex.match?(&1, string))
  end

  defp safe_message(error) when is_binary(error), do: error
  defp safe_message(%{message: msg}) when is_binary(msg), do: msg
  defp safe_message(other), do: inspect(other, limit: 200)

  defp truncate(string, max_len) when is_binary(string) do
    if byte_size(string) > max_len do
      String.slice(string, 0, max_len) <> "..."
    else
      string
    end
  end

  defp truncate(other, max_len), do: truncate(safe_message(other), max_len)
end
