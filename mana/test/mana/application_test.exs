defmodule Mana.ApplicationTest do
  @moduledoc """
  Tests for the Mana.Application module.
  """

  use ExUnit.Case, async: false

  describe "config_change/3" do
    test "returns :ok when called with empty lists" do
      assert :ok = Mana.Application.config_change([], [], [])
    end

    test "returns :ok when called with configuration changes" do
      changed = [mana: [some_key: "new_value"]]
      removed = [mana: [:old_key]]
      assert :ok = Mana.Application.config_change(changed, [], removed)
    end

    test "delegates to Mana.Web.Endpoint with changed configuration" do
      # Save original config to restore after test
      original = Application.get_env(:mana, Mana.Web.Endpoint)

      changed = [{Mana.Web.Endpoint, Keyword.put(original || [], :test_marker, :s14s_test)}]

      # The call should not raise and should return :ok
      assert :ok = Mana.Application.config_change(changed, [], [])

      # Cleanup — restore original config
      if original do
        Application.put_env(:mana, Mana.Web.Endpoint, original)
      end
    end
  end
end
