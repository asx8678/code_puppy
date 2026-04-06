defmodule Mana.MCP.ServerConfigTest do
  @moduledoc """
  Tests for Mana.MCP.ServerConfig module.
  """

  use ExUnit.Case, async: true

  alias Mana.MCP.ServerConfig

  doctest Mana.MCP.ServerConfig

  describe "new/1" do
    test "creates a valid stdio config" do
      {:ok, config} =
        ServerConfig.new(
          id: "test",
          name: "Test Server",
          type: :stdio,
          command: "npx",
          args: ["-y", "server-filesystem"],
          env: %{"NODE_ENV" => "production"}
        )

      assert config.id == "test"
      assert config.name == "Test Server"
      assert config.type == :stdio
      assert config.command == "npx"
      assert config.args == ["-y", "server-filesystem"]
      assert config.env == %{"NODE_ENV" => "production"}
      assert config.enabled == true
      assert config.quarantined == false
      assert config.timeout == 60_000
      assert config.config == %{}
    end

    test "creates a valid sse config" do
      {:ok, config} =
        ServerConfig.new(
          id: "sse-test",
          name: "SSE Server",
          type: :sse,
          url: "http://localhost:3001/sse",
          headers: %{"Authorization" => "Bearer token"}
        )

      assert config.id == "sse-test"
      assert config.name == "SSE Server"
      assert config.type == :sse
      assert config.url == "http://localhost:3001/sse"
      assert config.headers == %{"Authorization" => "Bearer token"}
      assert config.command == nil
      assert config.args == nil
    end

    test "creates a valid http config" do
      {:ok, config} =
        ServerConfig.new(
          id: "http-test",
          name: "HTTP Server",
          type: :http,
          url: "http://localhost:8080/mcp"
        )

      assert config.type == :http
      assert config.url == "http://localhost:8080/mcp"
    end

    test "creates config with custom timeout" do
      {:ok, config} =
        ServerConfig.new(
          id: "test",
          name: "Test",
          type: :stdio,
          command: "cmd",
          timeout: 120_000
        )

      assert config.timeout == 120_000
    end

    test "creates config with custom read_timeout" do
      {:ok, config} =
        ServerConfig.new(
          id: "test",
          name: "Test",
          type: :stdio,
          command: "cmd",
          read_timeout: 90_000
        )

      assert config.read_timeout == 90_000
    end

    test "creates disabled config when enabled: false" do
      {:ok, config} =
        ServerConfig.new(
          id: "test",
          name: "Test",
          type: :stdio,
          command: "cmd",
          enabled: false
        )

      assert config.enabled == false
    end

    test "creates quarantined config" do
      {:ok, config} =
        ServerConfig.new(
          id: "test",
          name: "Test",
          type: :stdio,
          command: "cmd",
          quarantined: true
        )

      assert config.quarantined == true
    end

    test "creates config with arbitrary config map" do
      {:ok, config} =
        ServerConfig.new(
          id: "test",
          name: "Test",
          type: :stdio,
          command: "cmd",
          config: %{"custom_key" => "custom_value"}
        )

      assert config.config == %{"custom_key" => "custom_value"}
    end
  end

  describe "new/1 - validation errors" do
    test "returns error when id is missing" do
      {:error, reason} =
        ServerConfig.new(
          name: "Test",
          type: :stdio,
          command: "cmd"
        )

      assert reason == {:missing_required_field, :id}
    end

    test "returns error when name is missing" do
      {:error, reason} =
        ServerConfig.new(
          id: "test",
          type: :stdio,
          command: "cmd"
        )

      assert reason == {:missing_required_field, :name}
    end

    test "returns error when type is missing" do
      {:error, reason} =
        ServerConfig.new(
          id: "test",
          name: "Test",
          command: "cmd"
        )

      assert reason == {:missing_required_field, :type}
    end

    test "returns error for invalid server type" do
      {:error, reason} =
        ServerConfig.new(
          id: "test",
          name: "Test",
          type: :invalid
        )

      assert reason == :invalid_server_type
    end

    test "returns error when stdio server missing command" do
      {:error, reason} =
        ServerConfig.new(
          id: "test",
          name: "Test",
          type: :stdio
        )

      assert reason == {:missing_required_field, :command}
    end

    test "returns error when sse server missing url" do
      {:error, reason} =
        ServerConfig.new(
          id: "test",
          name: "Test",
          type: :sse
        )

      assert reason == {:missing_required_field, :url}
    end

    test "returns error when http server missing url" do
      {:error, reason} =
        ServerConfig.new(
          id: "test",
          name: "Test",
          type: :http
        )

      assert reason == {:missing_required_field, :url}
    end

    test "returns error for negative timeout" do
      {:error, reason} =
        ServerConfig.new(
          id: "test",
          name: "Test",
          type: :stdio,
          command: "cmd",
          timeout: -1
        )

      assert reason == {:invalid_timeout, -1}
    end

    test "returns error for non-integer timeout" do
      {:error, reason} =
        ServerConfig.new(
          id: "test",
          name: "Test",
          type: :stdio,
          command: "cmd",
          timeout: "60"
        )

      assert reason == {:invalid_timeout, "60"}
    end
  end

  describe "new!/1" do
    test "creates config on valid input" do
      config =
        ServerConfig.new!(
          id: "test",
          name: "Test",
          type: :stdio,
          command: "cmd"
        )

      assert %ServerConfig{id: "test"} = config
    end

    test "raises on invalid input" do
      assert_raise ArgumentError, ~r/Invalid server config/, fn ->
        ServerConfig.new!(id: "test", name: "Test", type: :invalid)
      end
    end
  end

  describe "validate/1 direct tests" do
    test "validates a well-formed config" do
      config = %ServerConfig{
        id: "test",
        name: "Test",
        type: :stdio,
        command: "cmd"
      }

      assert {:ok, ^config} = ServerConfig.validate(config)
    end

    test "returns error for missing required id field" do
      config = %ServerConfig{
        id: nil,
        name: "Test",
        type: :stdio,
        command: "cmd"
      }

      assert {:error, {:missing_required_field, :id}} = ServerConfig.validate(config)
    end

    test "returns error for missing required name field" do
      config = %ServerConfig{
        id: "test",
        name: nil,
        type: :stdio,
        command: "cmd"
      }

      assert {:error, {:missing_required_field, :name}} = ServerConfig.validate(config)
    end

    test "returns error for missing required type field" do
      config = %ServerConfig{
        id: "test",
        name: "Test",
        type: nil,
        command: "cmd"
      }

      assert {:error, {:missing_required_field, :type}} = ServerConfig.validate(config)
    end

    test "returns error for invalid server type" do
      config = %ServerConfig{
        id: "test",
        name: "Test",
        type: :invalid,
        command: "cmd"
      }

      assert {:error, :invalid_server_type} = ServerConfig.validate(config)
    end

    test "returns error when stdio server missing command (validate/1 path)" do
      # Directly create struct without going through new/1 to test validate/1 path
      config = %ServerConfig{
        id: "test",
        name: "Test",
        type: :stdio,
        command: nil
      }

      assert {:error, {:missing_required_field, :command}} = ServerConfig.validate(config)
    end

    test "returns error when sse server missing url (validate/1 path)" do
      config = %ServerConfig{
        id: "test",
        name: "Test",
        type: :sse,
        url: nil
      }

      assert {:error, {:missing_required_field, :url}} = ServerConfig.validate(config)
    end

    test "returns error when http server missing url (validate/1 path)" do
      config = %ServerConfig{
        id: "test",
        name: "Test",
        type: :http,
        url: nil
      }

      assert {:error, {:missing_required_field, :url}} = ServerConfig.validate(config)
    end

    test "returns error for negative timeout (validate/1 path)" do
      config = %ServerConfig{
        id: "test",
        name: "Test",
        type: :stdio,
        command: "cmd",
        timeout: -1
      }

      assert {:error, {:invalid_timeout, -1}} = ServerConfig.validate(config)
    end

    test "returns error for non-integer timeout (validate/1 path)" do
      config = %ServerConfig{
        id: "test",
        name: "Test",
        type: :stdio,
        command: "cmd",
        timeout: "60"
      }

      assert {:error, {:invalid_timeout, "60"}} = ServerConfig.validate(config)
    end

    test "returns error for zero or negative read_timeout (validate/1 path)" do
      config = %ServerConfig{
        id: "test",
        name: "Test",
        type: :stdio,
        command: "cmd",
        read_timeout: 0
      }

      assert {:error, {:invalid_read_timeout, 0}} = ServerConfig.validate(config)
    end

    test "returns error for invalid read_timeout type (validate/1 path)" do
      config = %ServerConfig{
        id: "test",
        name: "Test",
        type: :stdio,
        command: "cmd",
        read_timeout: "90"
      }

      assert {:error, {:invalid_read_timeout, "90"}} = ServerConfig.validate(config)
    end
  end

  describe "validate/1" do
    test "validates a well-formed config" do
      config = %ServerConfig{
        id: "test",
        name: "Test",
        type: :stdio,
        command: "cmd"
      }

      assert {:ok, ^config} = ServerConfig.validate(config)
    end
  end

  describe "available?/1" do
    test "returns true when enabled and not quarantined" do
      config = %ServerConfig{id: "t", name: "T", type: :stdio, enabled: true, quarantined: false}
      assert ServerConfig.available?(config)
    end

    test "returns false when disabled" do
      config = %ServerConfig{id: "t", name: "T", type: :stdio, enabled: false, quarantined: false}
      refute ServerConfig.available?(config)
    end

    test "returns false when quarantined" do
      config = %ServerConfig{id: "t", name: "T", type: :stdio, enabled: true, quarantined: true}
      refute ServerConfig.available?(config)
    end

    test "returns false when both disabled and quarantined" do
      config = %ServerConfig{id: "t", name: "T", type: :stdio, enabled: false, quarantined: true}
      refute ServerConfig.available?(config)
    end
  end

  describe "initial_state/1" do
    test "always returns :stopped" do
      config = %ServerConfig{id: "test", name: "Test", type: :stdio}
      assert ServerConfig.initial_state(config) == :stopped
    end
  end

  describe "required_fields_for/1" do
    test "stdio requires command" do
      assert ServerConfig.required_fields_for(:stdio) == [:command]
    end

    test "sse requires url" do
      assert ServerConfig.required_fields_for(:sse) == [:url]
    end

    test "http requires url" do
      assert ServerConfig.required_fields_for(:http) == [:url]
    end
  end
end
