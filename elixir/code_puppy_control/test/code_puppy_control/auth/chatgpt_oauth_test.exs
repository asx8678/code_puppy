defmodule CodePuppyControl.Auth.ChatGptOAuthTest do
  use ExUnit.Case, async: false
  alias CodePuppyControl.Auth.ChatGptOAuth

  describe "prepare_oauth_context/0" do
    test "generates valid PKCE context" do
      ctx = ChatGptOAuth.prepare_oauth_context()
      assert byte_size(ctx.state) == 64
      assert byte_size(ctx.code_verifier) == 128
      assert byte_size(ctx.code_challenge) > 0
      assert ctx.redirect_uri == nil
      assert ctx.expires_at > ctx.created_at
    end

    test "different calls produce different states" do
      ctx1 = ChatGptOAuth.prepare_oauth_context()
      ctx2 = ChatGptOAuth.prepare_oauth_context()
      assert ctx1.state != ctx2.state
      assert ctx1.code_verifier != ctx2.code_verifier
    end
  end

  describe "assign_redirect_uri/2" do
    test "assigns redirect URI on correct port" do
      ctx = ChatGptOAuth.prepare_oauth_context()
      result = ChatGptOAuth.assign_redirect_uri(ctx, 1455)
      assert result.redirect_uri == "http://localhost:1455/auth/callback"
    end

    test "raises on wrong port" do
      ctx = ChatGptOAuth.prepare_oauth_context()

      assert_raise RuntimeError, fn ->
        ChatGptOAuth.assign_redirect_uri(ctx, 9999)
      end
    end
  end

  describe "build_authorization_url/1" do
    test "builds valid URL with PKCE params" do
      ctx = ChatGptOAuth.prepare_oauth_context() |> ChatGptOAuth.assign_redirect_uri(1455)
      url = ChatGptOAuth.build_authorization_url(ctx)
      assert String.starts_with?(url, "https://auth.openai.com/oauth/authorize?")
      assert String.contains?(url, "code_challenge=")
      assert String.contains?(url, "code_challenge_method=S256")
      assert String.contains?(url, "response_type=code")
      assert String.contains?(url, "state=")
    end

    test "raises without redirect URI" do
      ctx = ChatGptOAuth.prepare_oauth_context()

      assert_raise RuntimeError, fn ->
        ChatGptOAuth.build_authorization_url(ctx)
      end
    end
  end

  describe "parse_jwt_claims/1" do
    test "parses valid JWT" do
      header = Base.url_encode64(Jason.encode!(%{"alg" => "RS256"}), padding: false)

      payload =
        Base.url_encode64(Jason.encode!(%{"exp" => 1_234_567_890, "sub" => "test"}),
          padding: false
        )

      sig = Base.url_encode64("signature", padding: false)
      token = header <> "." <> payload <> "." <> sig
      result = ChatGptOAuth.parse_jwt_claims(token)
      assert result["exp"] == 1_234_567_890
      assert result["sub"] == "test"
    end

    test "returns nil for invalid token" do
      assert ChatGptOAuth.parse_jwt_claims("not-a-jwt") == nil
      assert ChatGptOAuth.parse_jwt_claims("") == nil
      assert ChatGptOAuth.parse_jwt_claims(nil) == nil
    end
  end

  describe "blocked_model?/1" do
    test "blocks known stale models" do
      assert ChatGptOAuth.blocked_model?("gpt-5.2") == true
      assert ChatGptOAuth.blocked_model?("gpt-4o") == true
      assert ChatGptOAuth.blocked_model?("gpt-5.1-codex") == true
    end

    test "allows current models" do
      assert ChatGptOAuth.blocked_model?("gpt-5.4") == false
      assert ChatGptOAuth.blocked_model?("gpt-5.3-codex") == false
    end

    test "handles prefixed names" do
      assert ChatGptOAuth.blocked_model?("chatgpt-gpt-5.2") == true
      assert ChatGptOAuth.blocked_model?("chatgpt-gpt-5.4") == false
    end
  end

  describe "default_models/0" do
    test "returns non-empty list of current models" do
      models = ChatGptOAuth.default_models()
      assert "gpt-5.4" in models
      assert "gpt-5.3-codex" in models
      refute "gpt-5.2" in models
      refute "gpt-4o" in models
    end
  end

  describe "token storage" do
    setup do
      tmp_dir =
        Path.join(
          System.tmp_dir!(),
          "chatgpt_oauth_test_" <> Integer.to_string(:erlang.unique_integer())
        )

      File.mkdir_p!(tmp_dir)
      original_home = System.get_env("PUP_EX_HOME")
      System.put_env("PUP_EX_HOME", tmp_dir)

      on_exit(fn ->
        if original_home,
          do: System.put_env("PUP_EX_HOME", original_home),
          else: System.delete_env("PUP_EX_HOME")

        File.rm_rf!(tmp_dir)
      end)

      :ok
    end

    test "save and load tokens round-trip" do
      tokens = %{"access_token" => "test_token", "refresh_token" => "test_refresh"}
      :ok = ChatGptOAuth.save_tokens(tokens)
      loaded = ChatGptOAuth.load_stored_tokens()
      assert loaded["access_token"] == "test_token"
      assert loaded["refresh_token"] == "test_refresh"
    end

    test "clear_stored_tokens removes the file" do
      :ok = ChatGptOAuth.save_tokens(%{"access_token" => "to_be_cleared"})
      :ok = ChatGptOAuth.clear_stored_tokens()
      assert ChatGptOAuth.load_stored_tokens() == nil
    end

    test "load_stored_tokens returns nil when no file" do
      assert ChatGptOAuth.load_stored_tokens() == nil
    end
  end

  describe "config/0" do
    test "returns expected OAuth configuration" do
      cfg = ChatGptOAuth.config()
      assert cfg.issuer == "https://auth.openai.com"
      assert cfg.required_port == 1455
      assert cfg.prefix == "chatgpt-"
    end
  end
end
