defmodule Mana.OAuth.TokenStoreTest do
  @moduledoc """
  Tests for Mana.OAuth.TokenStore module.
  """

  use ExUnit.Case, async: false

  alias Mana.OAuth.TokenStore

  setup do
    # Use a temporary directory for tests
    temp_dir = Path.join(System.tmp_dir!(), "mana_test_tokens_#{:erlang.unique_integer([:positive])}")

    # Override the default tokens directory for testing
    original_tokens_dir = Application.get_env(:mana, :tokens_dir)
    Application.put_env(:mana, :tokens_dir, temp_dir)

    # Create the directory
    File.mkdir_p!(temp_dir)

    # Clean up any existing tokens from other tests
    File.rm_rf!(temp_dir)
    File.mkdir_p!(temp_dir)

    on_exit(fn ->
      # Cleanup
      File.rm_rf!(temp_dir)

      if original_tokens_dir do
        Application.put_env(:mana, :tokens_dir, original_tokens_dir)
      else
        Application.delete_env(:mana, :tokens_dir)
      end
    end)

    {:ok, temp_dir: temp_dir}
  end

  describe "save/2 and load/1" do
    test "saves and loads tokens for a provider", %{temp_dir: temp_dir} do
      provider = "test_provider"
      tokens = %{"access_token" => "secret123", "expires_in" => 3600}

      # Save tokens
      assert :ok = TokenStore.save(provider, tokens)

      # Verify file was created
      expected_path = Path.join(temp_dir, "#{provider}.json")
      assert File.exists?(expected_path)

      # Load tokens
      assert {:ok, loaded} = TokenStore.load(provider)
      assert loaded["access_token"] == "secret123"
      assert loaded["expires_in"] == 3600
    end

    test "returns error for non-existent provider", %{temp_dir: _} do
      assert {:error, :not_found} = TokenStore.load("nonexistent_provider")
    end

    test "overwrites existing tokens", %{temp_dir: _} do
      provider = "test_overwrite"

      TokenStore.save(provider, %{"access_token" => "old_token"})
      TokenStore.save(provider, %{"access_token" => "new_token"})

      assert {:ok, loaded} = TokenStore.load(provider)
      assert loaded["access_token"] == "new_token"
    end

    test "handles JSON parsing errors gracefully", %{temp_dir: temp_dir} do
      provider = "corrupted"
      path = Path.join(temp_dir, "#{provider}.json")

      # Write invalid JSON
      File.write!(path, "not valid json{")

      assert {:error, :not_found} = TokenStore.load(provider)
    end
  end

  describe "expired?/1" do
    test "returns true for expired token" do
      # Time in the past
      expired_time = System.os_time(:second) - 100
      tokens = %{"expires_at" => expired_time}

      assert TokenStore.expired?(tokens) == true
    end

    test "returns true for just expired token" do
      # Current time exactly at expires_at
      current_time = System.os_time(:second)
      tokens = %{"expires_at" => current_time}

      assert TokenStore.expired?(tokens) == true
    end

    test "returns false for valid token" do
      # Time in the future
      future_time = System.os_time(:second) + 3600
      tokens = %{"expires_at" => future_time}

      assert TokenStore.expired?(tokens) == false
    end

    test "returns false for token without expiration" do
      tokens = %{"access_token" => "no_expiration"}

      assert TokenStore.expired?(tokens) == false
    end

    test "handles atom keys" do
      expired_time = System.os_time(:second) - 100
      tokens = %{expires_at: expired_time}

      assert TokenStore.expired?(tokens) == true
    end
  end

  describe "refresh_if_needed/2" do
    test "returns existing tokens when not expired", %{temp_dir: _} do
      provider = "fresh_provider"
      future_time = System.os_time(:second) + 3600
      tokens = %{"access_token" => "fresh", "expires_at" => future_time}

      TokenStore.save(provider, tokens)

      refresh_fn = fn _ ->
        {:ok, %{"access_token" => "refreshed"}}
      end

      assert {:ok, loaded} = TokenStore.refresh_if_needed(provider, refresh_fn)
      assert loaded["access_token"] == "fresh"
    end

    test "refreshes and saves when expired", %{temp_dir: _} do
      provider = "expired_provider"
      past_time = System.os_time(:second) - 100
      old_tokens = %{"access_token" => "expired", "expires_at" => past_time}

      TokenStore.save(provider, old_tokens)

      refresh_fn = fn current_tokens ->
        assert current_tokens["access_token"] == "expired"
        {:ok, %{"access_token" => "refreshed", "expires_at" => System.os_time(:second) + 3600}}
      end

      assert {:ok, new_tokens} = TokenStore.refresh_if_needed(provider, refresh_fn)
      assert new_tokens["access_token"] == "refreshed"

      # Verify saved
      assert {:ok, saved} = TokenStore.load(provider)
      assert saved["access_token"] == "refreshed"
    end

    test "returns error when refresh fails", %{temp_dir: _} do
      provider = "refresh_fail"
      past_time = System.os_time(:second) - 100
      tokens = %{"access_token" => "expired", "expires_at" => past_time}

      TokenStore.save(provider, tokens)

      refresh_fn = fn _ ->
        {:error, "refresh failed"}
      end

      assert {:error, "refresh failed"} = TokenStore.refresh_if_needed(provider, refresh_fn)
    end

    test "returns error when provider has no tokens" do
      refresh_fn = fn _ -> {:ok, %{}} end

      assert {:error, :not_found} =
               TokenStore.refresh_if_needed("nonexistent_provider", refresh_fn)
    end

    test "handles refresh without refresh_token in original tokens", %{temp_dir: _} do
      provider = "no_refresh_token"
      past_time = System.os_time(:second) - 100
      tokens = %{"access_token" => "expired", "expires_at" => past_time}

      TokenStore.save(provider, tokens)

      refresh_fn = fn current_tokens ->
        # Some providers may not have refresh tokens
        assert is_map(current_tokens)
        {:ok, %{"access_token" => "brand_new"}}
      end

      assert {:ok, new_tokens} = TokenStore.refresh_if_needed(provider, refresh_fn)
      assert new_tokens["access_token"] == "brand_new"
    end
  end

  describe "delete/1" do
    test "deletes saved tokens", %{temp_dir: _} do
      provider = "to_delete"
      TokenStore.save(provider, %{"access_token" => "delete_me"})

      assert :ok = TokenStore.delete(provider)
      assert {:error, :not_found} = TokenStore.load(provider)
    end

    test "returns ok when deleting non-existent provider" do
      assert :ok = TokenStore.delete("never_existed")
    end

    test "is idempotent", %{temp_dir: _} do
      provider = "idempotent_delete"
      TokenStore.save(provider, %{"access_token" => "token"})

      assert :ok = TokenStore.delete(provider)
      assert :ok = TokenStore.delete(provider)
      assert {:error, :not_found} = TokenStore.load(provider)
    end
  end

  describe "list_providers/0" do
    test "returns empty list when no tokens stored", %{temp_dir: _} do
      assert TokenStore.list_providers() == []
    end

    test "returns list of providers with tokens", %{temp_dir: _} do
      TokenStore.save("provider_a", %{"access_token" => "a"})
      TokenStore.save("provider_b", %{"access_token" => "b"})
      TokenStore.save("provider_c", %{"access_token" => "c"})

      providers = TokenStore.list_providers()
      assert length(providers) == 3
      assert "provider_a" in providers
      assert "provider_b" in providers
      assert "provider_c" in providers
    end

    test "ignores non-json files in tokens directory", %{temp_dir: temp_dir} do
      TokenStore.save("valid", %{"access_token" => "token"})

      # Create a non-JSON file
      File.write!(Path.join(temp_dir, "readme.txt"), "This is not a token file")

      providers = TokenStore.list_providers()
      assert providers == ["valid"]
    end

    test "ignores subdirectories", %{temp_dir: temp_dir} do
      TokenStore.save("valid", %{"access_token" => "token"})

      # Create a subdirectory
      File.mkdir_p!(Path.join(temp_dir, "subdir"))

      providers = TokenStore.list_providers()
      assert providers == ["valid"]
    end
  end

  describe "tokens_path/0" do
    test "returns expanded path" do
      path = TokenStore.tokens_path()
      assert is_binary(path)
      refute String.contains?(path, "~")
    end
  end
end
