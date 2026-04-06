defmodule Mana.OAuth.RefreshManagerTest do
  use ExUnit.Case, async: false

  alias Mana.OAuth.{RefreshManager, TokenStore}

  @provider "crash_test"

  setup_all do
    temp_dir = Path.join(System.tmp_dir!(), "mana_refresh_manager_test_#{System.unique_integer([:positive])}")
    original_tokens_dir = Application.get_env(:mana, :tokens_dir)

    Application.put_env(:mana, :tokens_dir, temp_dir)
    File.mkdir_p!(temp_dir)

    on_exit(fn ->
      File.rm_rf!(temp_dir)

      if original_tokens_dir do
        Application.put_env(:mana, :tokens_dir, original_tokens_dir)
      else
        Application.delete_env(:mana, :tokens_dir)
      end
    end)

    :ok
  end

  setup do
    case Process.whereis(RefreshManager) do
      nil -> {:ok, _} = RefreshManager.start_link([])
      _pid -> :ok
    end

    TokenStore.delete(@provider)
    RefreshManager.reset_provider(@provider)

    on_exit(fn ->
      TokenStore.delete(@provider)
      RefreshManager.reset_provider(@provider)
    end)

    :ok
  end

  test "raising refresh_fn does not wedge the manager — caller gets error tuple" do
    expired_tokens = %{
      "access_token" => "old_token",
      "refresh_token" => "refresh_token",
      "expires_at" => 1
    }

    :ok = TokenStore.save(@provider, expired_tokens)

    raising_fn = fn _tokens -> raise "simulated provider crash" end

    result = RefreshManager.refresh_if_needed(@provider, raising_fn)

    assert {:error, {:refresh_crashed, _kind, _reason}} = result
  end

  test "after a crash, a subsequent successful refresh works" do
    expired_tokens = %{
      "access_token" => "old_token",
      "refresh_token" => "refresh_token",
      "expires_at" => 1
    }

    :ok = TokenStore.save(@provider, expired_tokens)

    raising_fn = fn _tokens -> raise "first call crashes" end
    {:error, _} = RefreshManager.refresh_if_needed(@provider, raising_fn)

    good_fn = fn _tokens ->
      {:ok, %{"access_token" => "good_token", "expires_at" => 9_999_999_999}}
    end

    assert {:ok, %{"access_token" => "good_token"}} =
             RefreshManager.refresh_if_needed(@provider, good_fn)
  end
end
