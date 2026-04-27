defmodule CodePuppyControl.Tools.FileModifications.PermissionsTest do
  @moduledoc "Tests for Permissions — user rejection and policy denial responses."

  use ExUnit.Case, async: true

  alias CodePuppyControl.Tools.FileModifications.Permissions

  describe "create_rejection_response/2" do
    test "creates rejection response without user feedback" do
      result = Permissions.create_rejection_response("/tmp/test.txt")

      assert result.success == false
      assert result.path == "/tmp/test.txt"
      assert result.message =~ "USER REJECTED"
      assert result.message =~ "do not retry"
      assert result.changed == false
      assert result.user_rejection == true
      assert result.rejection_type == "explicit_user_denial"
      assert result.user_feedback == nil
    end

    test "creates rejection response with user feedback" do
      result = Permissions.create_rejection_response("/tmp/test.txt", "I don't want this file changed")

      assert result.success == false
      assert result.message =~ "User feedback: I don't want this file changed"
      assert result.user_feedback == "I don't want this file changed"
    end

    test "handles empty user feedback" do
      result = Permissions.create_rejection_response("/tmp/test.txt", "")

      # Empty feedback should be treated as nil
      assert result.message =~ "do not retry"
    end
  end

  describe "create_denial_response/2" do
    test "creates policy denial response" do
      result = Permissions.create_denial_response("/tmp/test.txt", "Path is sensitive")

      assert result.success == false
      assert result.message =~ "Operation denied"
      assert result.message =~ "Path is sensitive"
      assert result.user_rejection == false
      assert result.rejection_type == "policy_denial"
    end
  end

  describe "create_security_response/2" do
    test "creates security block response" do
      result = Permissions.create_security_response("/tmp/test.txt", "SSH key access blocked")

      assert result.success == false
      assert result.message =~ "Security"
      assert result.message =~ "SSH key access blocked"
      assert result.user_rejection == false
      assert result.rejection_type == "security_block"
    end
  end

  describe "check_permission/2" do
    test "allows non-sensitive paths" do
      assert :ok = Permissions.check_permission("/tmp/safe_file.txt", "create")
    end

    test "denies sensitive SSH key paths" do
      assert {:deny, _reason} =
               Permissions.check_permission(
                 Path.join(System.user_home!(), ".ssh/id_rsa"),
                 "read"
               )
    end

    test "denies empty paths" do
      assert {:deny, _reason} = Permissions.check_permission("", "create")
    end
  end

  describe "with_permission/3" do
    test "executes function when permission is granted" do
      result =
        Permissions.with_permission("/tmp/safe_file.txt", "create", fn ->
          {:ok, %{success: true, message: "done"}}
        end)

      assert result == {:ok, %{success: true, message: "done"}}
    end

    test "returns security response when permission is denied" do
      result =
        Permissions.with_permission(
          Path.join(System.user_home!(), ".ssh/id_rsa"),
          "read",
          fn -> {:ok, %{success: true}} end
        )

      assert match?({:error, %{rejection_type: "security_block"}}, result)
    end
  end
end
