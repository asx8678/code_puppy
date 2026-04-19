defmodule CodePuppyControl.Credentials.CryptoTest do
  use ExUnit.Case, async: true

  alias CodePuppyControl.Credentials.Crypto

  describe "derive_key/0" do
    test "produces a 32-byte key" do
      key = Crypto.derive_key()
      assert byte_size(key) == 32
    end

    test "is deterministic on the same machine" do
      key1 = Crypto.derive_key()
      key2 = Crypto.derive_key()
      assert key1 == key2
    end
  end

  describe "derive_key/1" do
    test "produces a 32-byte key from a secret" do
      key = Crypto.derive_key("my-secret")
      assert byte_size(key) == 32
    end

    test "different secrets produce different keys" do
      key1 = Crypto.derive_key("secret-a")
      key2 = Crypto.derive_key("secret-b")
      assert key1 != key2
    end

    test "same secret produces same key" do
      key1 = Crypto.derive_key("the-same")
      key2 = Crypto.derive_key("the-same")
      assert key1 == key2
    end
  end

  describe "encrypt/2 and decrypt/2" do
    test "encrypt then decrypt round-trips successfully" do
      key = Crypto.derive_key("test-key")
      plaintext = "sk-ant-api03-1234567890abcdef"

      encrypted = Crypto.encrypt(plaintext, key)
      assert {:ok, decrypted} = Crypto.decrypt(encrypted, key)
      assert decrypted == plaintext
    end

    test "encrypted output has iv, tag, and data fields" do
      key = Crypto.derive_key("test-key")
      encrypted = Crypto.encrypt("hello", key)

      assert Map.has_key?(encrypted, :iv)
      assert Map.has_key?(encrypted, :tag)
      assert Map.has_key?(encrypted, :data)
    end

    test "encrypted fields are Base64-encoded" do
      key = Crypto.derive_key("test-key")
      encrypted = Crypto.encrypt("hello", key)

      assert {:ok, _} = Base.decode64(encrypted.iv)
      assert {:ok, _} = Base.decode64(encrypted.tag)
      assert {:ok, _} = Base.decode64(encrypted.data)
    end

    test "decryption with wrong key fails" do
      key1 = Crypto.derive_key("key-one")
      key2 = Crypto.derive_key("key-two")

      encrypted = Crypto.encrypt("secret", key1)
      assert {:error, :decryption_failed} = Crypto.decrypt(encrypted, key2)
    end

    test "decryption with tampered data fails" do
      key = Crypto.derive_key("test-key")
      encrypted = Crypto.encrypt("secret", key)

      # Tamper with the ciphertext
      tampered = %{encrypted | data: Base.encode64(<<"tampered_data">>)}
      assert {:error, :decryption_failed} = Crypto.decrypt(tampered, key)
    end

    test "decryption with tampered IV fails" do
      key = Crypto.derive_key("test-key")
      encrypted = Crypto.encrypt("secret", key)

      # Tamper with the IV
      tampered = %{encrypted | iv: Base.encode64(:crypto.strong_rand_bytes(12))}
      assert {:error, :decryption_failed} = Crypto.decrypt(tampered, key)
    end

    test "decryption with invalid base64 returns error" do
      key = Crypto.derive_key("test-key")

      invalid = %{iv: "not-base64!!!", tag: "abc", data: "def"}
      assert {:error, :invalid_base64} = Crypto.decrypt(invalid, key)
    end

    test "decryption with wrong IV length returns error" do
      key = Crypto.derive_key("test-key")

      invalid = %{
        iv: Base.encode64(<<0, 0, 0>>),
        tag: Base.encode64(<<0::128>>),
        data: Base.encode64(<<0>>)
      }

      assert {:error, :invalid_field_length} = Crypto.decrypt(invalid, key)
    end

    test "handles empty plaintext" do
      key = Crypto.derive_key("test-key")

      encrypted = Crypto.encrypt("", key)
      assert {:ok, ""} = Crypto.decrypt(encrypted, key)
    end

    test "handles large values (e.g. long API keys)" do
      key = Crypto.derive_key("test-key")
      # Simulate a 1KB token
      plaintext = String.duplicate("x", 1024)

      encrypted = Crypto.encrypt(plaintext, key)
      assert {:ok, ^plaintext} = Crypto.decrypt(encrypted, key)
    end

    test "handles unicode in values" do
      key = Crypto.derive_key("test-key")
      plaintext = "sk-日本語-🔐"

      encrypted = Crypto.encrypt(plaintext, key)
      assert {:ok, ^plaintext} = Crypto.decrypt(encrypted, key)
    end

    test "each encryption uses a unique IV" do
      key = Crypto.derive_key("test-key")

      enc1 = Crypto.encrypt("same-value", key)
      enc2 = Crypto.encrypt("same-value", key)

      # IVs should be different (random)
      assert enc1.iv != enc2.iv
      # Ciphertext should be different
      assert enc1.data != enc2.data
    end

    test "decrypt returns error for invalid input type" do
      key = Crypto.derive_key("test-key")
      assert {:error, :invalid_input} = Crypto.decrypt("not a map", key)
      assert {:error, :invalid_input} = Crypto.decrypt(nil, key)
    end
  end

  describe "encrypt_to_json/2 and decrypt_from_json/2" do
    test "round-trip with string keys" do
      key = Crypto.derive_key("test-key")
      plaintext = "sk-test-key-value"

      json_map = Crypto.encrypt_to_json(plaintext, key)
      # Keys should be strings
      assert Map.keys(json_map) |> Enum.all?(&is_binary/1)

      assert {:ok, ^plaintext} = Crypto.decrypt_from_json(json_map, key)
    end

    test "decrypt_from_json returns error for invalid input" do
      key = Crypto.derive_key("test-key")
      assert {:error, :invalid_input} = Crypto.decrypt_from_json(%{}, key)
      assert {:error, :invalid_input} = Crypto.decrypt_from_json(nil, key)
    end
  end
end
