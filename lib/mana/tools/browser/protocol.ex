defmodule Mana.Tools.Browser.Protocol do
  @moduledoc """
  JSON-RPC style command encoder/decoder for Playwright commands.

  Provides a simple protocol for communicating with a Node.js Playwright
  bridge process over an Erlang Port (stdin/stdout).

  ## Wire Format

  Commands are encoded as single-line JSON objects sent via port stdin:

      {"id":1,"command":"navigate","params":{"url":"https://example.com"}}

  Responses are single-line JSON objects read from port stdout:

      {"id":1,"success":true,"result":{"url":"https://example.com","title":"Example"}}
      {"id":1,"success":false,"error":"Navigation timeout"}

  ## Framing

  Each message is terminated with a newline (`\\n`). The port is opened
  with `:binary` and `:line` modes so we receive line-delimited data.

  ## Usage

      # Encode a command to send to the Node.js process
      iex> Mana.Tools.Browser.Protocol.encode_command("navigate", %{"url" => "https://example.com"}, id: 1)
      {:ok, ~s({"id":1,"command":"navigate","params":{"url":"https://example.com"}})}

      # Decode a response from the Node.js process
      iex> json = ~s({"id":1,"success":true,"result":{"url":"https://example.com"}})
      iex> Mana.Tools.Browser.Protocol.decode_response(json)
      {:ok, %{"id" => 1, "success" => true, "result" => %{"url" => "https://example.com"}}}
  """

  require Logger

  # ---------------------------------------------------------------------------
  # Types
  # ---------------------------------------------------------------------------

  @type command_name :: String.t()
  @type params :: map()
  @type command_id :: pos_integer()
  @type encoded_command :: String.t()

  @type encode_opts :: [
          {:id, command_id()}
        ]

  @type response :: map()

  # ---------------------------------------------------------------------------
  # Encoding
  # ---------------------------------------------------------------------------

  @doc """
  Encodes a Playwright command into a JSON string suitable for sending
  to the Node.js bridge process via port stdin.

  ## Parameters

    - `command_name` — The Playwright command (e.g. "navigate", "click", "screenshot")
    - `params` — A map of command parameters
    - `opts` — Options, including `:id` for the request correlation ID

  ## Returns

    - `{:ok, json_string}` — Successfully encoded command
    - `{:error, reason}` — Encoding failed

  ## Examples

      iex> Mana.Tools.Browser.Protocol.encode_command("click", %{"selector" => "#btn"}, id: 42)
      {:ok, ~s({"id":42,"command":"click","params":{"selector":"#btn"}})}
  """
  @spec encode_command(command_name(), params(), encode_opts()) ::
          {:ok, encoded_command()} | {:error, term()}
  def encode_command(command_name, params, opts \\ []) do
    id = Keyword.get(opts, :id, 1)

    payload = %{
      "id" => id,
      "command" => command_name,
      "params" => params
    }

    case Jason.encode(payload) do
      {:ok, json} ->
        {:ok, json <> "\n"}

      {:error, reason} ->
        Logger.error("[#{__MODULE__}] Failed to encode command #{command_name}: #{inspect(reason)}")
        {:error, {:encode_failed, reason}}
    end
  end

  @doc """
  Encodes a command and returns the binary directly (raises on error).

  Useful when the command encoding is known to succeed (e.g. static params).

  ## Examples

      iex> Mana.Tools.Browser.Protocol.encode_command!("navigate", %{"url" => "https://example.com"}, id: 1)
      ~s({"id":1,"command":"navigate","params":{"url":"https://example.com"}}) <> "\\n"
  """
  @spec encode_command!(command_name(), params(), encode_opts()) :: encoded_command()
  def encode_command!(command_name, params, opts \\ []) do
    case encode_command(command_name, params, opts) do
      {:ok, json} -> json
      {:error, reason} -> raise "Failed to encode command: #{inspect(reason)}"
    end
  end

  # ---------------------------------------------------------------------------
  # Decoding
  # ---------------------------------------------------------------------------

  @doc """
  Decodes a JSON response string received from the Node.js bridge process.

  ## Parameters

    - `json` — A JSON string (with or without trailing newline)

  ## Returns

    - `{:ok, response_map}` — Successfully decoded response
    - `{:error, reason}` — Decoding failed

  ## Examples

      iex> Mana.Tools.Browser.Protocol.decode_response(~s({"id":1,"success":true,"result":{"url":"https://example.com"}}))
      {:ok, %{"id" => 1, "success" => true, "result" => %{"url" => "https://example.com"}}}

      iex> Mana.Tools.Browser.Protocol.decode_response(~s({"id":2,"success":false,"error":"timeout"}))
      {:ok, %{"id" => 2, "success" => false, "error" => "timeout"}}
  """
  @spec decode_response(binary()) :: {:ok, response()} | {:error, term()}
  def decode_response(json) when is_binary(json) do
    json
    |> String.trim()
    |> Jason.decode()
  rescue
    e ->
      Logger.error("[#{__MODULE__}] Failed to decode response: #{inspect(e)}")
      {:error, {:decode_failed, e}}
  end

  @doc """
  Decodes a response and extracts the result or raises.

  Returns the `"result"` map on success, raises on failure.
  """
  @spec decode_response!(binary()) :: map()
  def decode_response!(json) do
    case decode_response(json) do
      {:ok, %{"success" => true, "result" => result}} ->
        result

      {:ok, %{"success" => false, "error" => error}} ->
        raise "Browser command failed: #{error}"

      {:ok, %{"success" => true}} ->
        %{}

      {:error, reason} ->
        raise "Failed to decode response: #{inspect(reason)}"
    end
  end

  # ---------------------------------------------------------------------------
  # Response Classification
  # ---------------------------------------------------------------------------

  @doc """
  Classifies a decoded response as success or failure.

  ## Returns

    - `{:ok, result}` — The command succeeded
    - `{:error, reason}` — The command failed

  ## Examples

      iex> Mana.Tools.Browser.Protocol.classify(%{"success" => true, "result" => %{"url" => "https://example.com"}})
      {:ok, %{"url" => "https://example.com"}}

      iex> Mana.Tools.Browser.Protocol.classify(%{"success" => false, "error" => "not initialized"})
      {:error, "not initialized"}
  """
  @spec classify(response()) :: {:ok, map()} | {:error, String.t()}
  def classify(%{"success" => true, "result" => result}) when is_map(result), do: {:ok, result}
  def classify(%{"success" => true}), do: {:ok, %{}}
  def classify(%{"success" => false, "error" => error}), do: {:error, error}
  def classify(other), do: {:error, "unexpected response: #{inspect(other)}"}

  # ---------------------------------------------------------------------------
  # Command Construction Helpers
  # ---------------------------------------------------------------------------

  @doc """
  Builds a browser initialization command.

  ## Parameters

    - `opts` — Options for browser initialization

  ## Options

    - `:headless` — Run browser in headless mode (default: `true`)
    - `:browser_type` — Browser engine: "chromium", "firefox", "webkit" (default: "chromium")
    - `:homepage` — Initial page to load (default: "https://www.google.com")
  """
  @spec init_command(keyword()) :: params()
  def init_command(opts \\ []) do
    %{
      "headless" => Keyword.get(opts, :headless, true),
      "browser_type" => Keyword.get(opts, :browser_type, "chromium"),
      "homepage" => Keyword.get(opts, :homepage, "https://www.google.com")
    }
  end

  @doc """
  Builds a navigate command.
  """
  @spec navigate_command(String.t(), keyword()) :: params()
  def navigate_command(url, opts \\ []) do
    %{
      "url" => url,
      "wait_until" => Keyword.get(opts, :wait_until, "domcontentloaded"),
      "timeout" => Keyword.get(opts, :timeout, 30_000)
    }
  end

  @doc """
  Builds a click command.
  """
  @spec click_command(String.t(), keyword()) :: params()
  def click_command(selector, opts \\ []) do
    %{
      "selector" => selector,
      "timeout" => Keyword.get(opts, :timeout, 10_000),
      "force" => Keyword.get(opts, :force, false),
      "button" => Keyword.get(opts, :button, "left")
    }
  end

  @doc """
  Builds a type/fill command.
  """
  @spec type_command(String.t(), String.t(), keyword()) :: params()
  def type_command(selector, text, opts \\ []) do
    %{
      "selector" => selector,
      "text" => text,
      "clear_first" => Keyword.get(opts, :clear_first, true),
      "timeout" => Keyword.get(opts, :timeout, 10_000)
    }
  end

  @doc """
  Builds a screenshot command.
  """
  @spec screenshot_command(keyword()) :: params()
  def screenshot_command(opts \\ []) do
    %{
      "full_page" => Keyword.get(opts, :full_page, false),
      "selector" => Keyword.get(opts, :selector)
    }
    |> Enum.reject(fn {_k, v} -> is_nil(v) end)
    |> Map.new()
  end

  @doc """
  Builds a find/text search command.
  """
  @spec find_text_command(String.t(), keyword()) :: params()
  def find_text_command(text, opts \\ []) do
    %{
      "text" => text,
      "exact" => Keyword.get(opts, :exact, false),
      "timeout" => Keyword.get(opts, :timeout, 10_000)
    }
  end

  @doc """
  Builds a scroll command.
  """
  @spec scroll_command(keyword()) :: params()
  def scroll_command(opts \\ []) do
    %{
      "direction" => Keyword.get(opts, :direction, "down"),
      "amount" => Keyword.get(opts, :amount, 3),
      "selector" => Keyword.get(opts, :selector)
    }
    |> Enum.reject(fn {_k, v} -> is_nil(v) end)
    |> Map.new()
  end
end
