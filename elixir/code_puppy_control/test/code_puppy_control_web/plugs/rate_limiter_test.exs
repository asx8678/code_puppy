defmodule CodePuppyControlWeb.Plugs.RateLimiterTest do
  use ExUnit.Case, async: true

  import Phoenix.ConnTest

  alias CodePuppyControlWeb.Plugs.RateLimiter

  setup do
    RateLimiter.create_table()
    RateLimiter.reset()

    on_exit(fn ->
      RateLimiter.reset()
    end)

    :ok
  end

  describe "check_rate/1" do
    test "allows requests when no failures recorded" do
      conn = loopback_conn()
      assert {:ok, 0} = RateLimiter.check_rate(conn)
    end

    test "allows requests below failure threshold" do
      conn = loopback_conn()

      for _ <- 1..4 do
        RateLimiter.record_failure(conn)
      end

      assert {:ok, 4} = RateLimiter.check_rate(conn)
    end

    test "blocks requests when failure threshold exceeded" do
      conn = loopback_conn()

      for _ <- 1..5 do
        RateLimiter.record_failure(conn)
      end

      assert {:error, :rate_limited, retry_after} = RateLimiter.check_rate(conn)
      assert is_integer(retry_after)
      assert retry_after >= 1
    end

    test "tracks failures per IP independently" do
      conn_a = conn_for_ip({10, 0, 0, 1})
      conn_b = conn_for_ip({10, 0, 0, 2})

      # Exhaust failures for IP A
      for _ <- 1..5 do
        RateLimiter.record_failure(conn_a)
      end

      # IP B should still be allowed
      assert {:ok, 0} = RateLimiter.check_rate(conn_b)

      # IP A should be rate limited
      assert {:error, :rate_limited, _} = RateLimiter.check_rate(conn_a)
    end
  end

  describe "record_failure/1" do
    test "records failure for the correct IP" do
      conn = conn_for_ip("192.168.1.1")
      RateLimiter.record_failure(conn)

      assert {:ok, 1} = RateLimiter.check_rate(conn)
    end
  end

  describe "reset/0" do
    test "clears all rate limit data" do
      conn = loopback_conn()

      for _ <- 1..5 do
        RateLimiter.record_failure(conn)
      end

      RateLimiter.reset()
      assert {:ok, 0} = RateLimiter.check_rate(conn)
    end
  end

  describe "plug call/2" do
    test "passes through when not rate limited" do
      conn = loopback_conn()
      _result = RateLimiter.call(conn, [])
      refute conn.halted
    end

    test "returns 429 when rate limited" do
      conn = loopback_conn()

      for _ <- 1..5 do
        RateLimiter.record_failure(conn)
      end

      result = RateLimiter.call(conn, [])
      assert result.status == 429
      assert result.halted
    end
  end

  # ---------------------------------------------------------------------------
  # Helpers
  # ---------------------------------------------------------------------------

  defp loopback_conn do
    conn_for_ip({127, 0, 0, 1})
  end

  defp conn_for_ip(ip) when is_tuple(ip) do
    %{build_conn() | remote_ip: ip}
  end

  defp conn_for_ip(ip) when is_binary(ip) do
    # Parse string IP to tuple for remote_ip
    case :inet_parse.address(String.to_charlist(ip)) do
      {:ok, addr} -> %{build_conn() | remote_ip: addr}
      {:error, _} -> %{build_conn() | remote_ip: {0, 0, 0, 0}}
    end
  end
end
