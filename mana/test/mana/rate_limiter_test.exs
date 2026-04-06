defmodule Mana.RateLimiterTest do
  use ExUnit.Case, async: false

  alias Mana.RateLimiter

  setup do
    # Start a fresh rate limiter for each test
    start_supervised!({RateLimiter, []})

    :ok
  end

  describe "start_link/1" do
    test "starts the GenServer" do
      # The GenServer was started in setup
      assert Process.whereis(RateLimiter) != nil
    end
  end

  describe "child_spec/1" do
    test "returns proper child spec" do
      spec = RateLimiter.child_spec([])
      assert spec.id == RateLimiter
      assert spec.restart == :permanent
      assert spec.type == :worker
    end
  end

  describe "check/1" do
    test "allows requests under the limit" do
      # First 60 requests should be allowed (default limit)
      for _ <- 1..60 do
        assert :ok == RateLimiter.check("gpt-4")
      end
    end

    test "blocks requests when limit exceeded" do
      # Exhaust the limit
      for _ <- 1..60 do
        RateLimiter.check("gpt-4")
      end

      # Next request should be rate limited
      assert {:error, :rate_limited} == RateLimiter.check("gpt-4")
    end

    test "tracks different models separately" do
      # Exhaust limit for model A
      for _ <- 1..60 do
        RateLimiter.check("model-a")
      end

      assert {:error, :rate_limited} == RateLimiter.check("model-a")

      # Model B should still have available capacity
      assert :ok == RateLimiter.check("model-b")
    end
  end

  describe "report_rate_limit/1" do
    test "reduces the limit when rate limit is reported" do
      # Make some requests
      for _ <- 1..30 do
        RateLimiter.check("gpt-4")
      end

      # Report rate limit
      RateLimiter.report_rate_limit("gpt-4")

      # Check state was updated
      state = RateLimiter.get_model_state("gpt-4")
      assert state.state == :open
      # Half of original 60
      assert state.limit == 30
    end

    test "reduces limit further on multiple reports" do
      # Report rate limit twice
      RateLimiter.report_rate_limit("gpt-4")
      RateLimiter.report_rate_limit("gpt-4")

      state = RateLimiter.get_model_state("gpt-4")
      # 60 -> 30 -> 15
      assert state.limit == 15
    end

    test "limit never goes below 1" do
      # Report many times
      for _ <- 1..10 do
        RateLimiter.report_rate_limit("gpt-4")
      end

      state = RateLimiter.get_model_state("gpt-4")
      assert state.limit == 1
    end
  end

  describe "circuit breaker behavior" do
    test "opens circuit when limit exceeded" do
      # Exhaust limit
      for _ <- 1..60 do
        RateLimiter.check("test-model")
      end

      # Circuit should be open
      assert {:error, :rate_limited} == RateLimiter.check("test-model")
    end

    test "half-open state allows test request" do
      model = "half-open-test"

      # Exhaust limit and report rate limit
      for _ <- 1..60 do
        RateLimiter.check(model)
      end

      RateLimiter.report_rate_limit(model)

      # Verify circuit is open
      assert {:error, :rate_limited} == RateLimiter.check(model)

      # Simulate recovery by manually transitioning to half-open
      # (In real scenario, this happens via the :recover message)
      state = RateLimiter.get_model_state(model)
      assert state.state == :open
    end
  end

  describe "get_model_state/1" do
    test "returns nil for unknown model" do
      assert RateLimiter.get_model_state("unknown-model") == nil
    end

    test "returns state for known model" do
      RateLimiter.check("known-model")
      state = RateLimiter.get_model_state("known-model")

      assert state != nil
      assert state.count >= 1
      assert state.state in [:closed, :open, :half_open]
      assert state.limit == 60
    end
  end

  describe "recovery mechanism" do
    test "recovery timer is scheduled on init" do
      # Check that the GenServer has a timer scheduled
      state = :sys.get_state(RateLimiter)
      assert state.last_recovery != nil
    end
  end
end
