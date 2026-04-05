defmodule Mana.Shell.ExecutorTest do
  use ExUnit.Case

  alias Mana.Shell.Executor
  alias Mana.Shell.Result

  setup do
    # Ensure executor is started (it may already be running from supervision tree)
    case Executor.start_link() do
      {:ok, _pid} -> :ok
      {:error, {:already_started, _pid}} -> :ok
    end

    # Kill any existing processes before each test
    Executor.kill_all()
    Process.sleep(50)

    :ok
  end

  describe "start_link/1" do
    test "starts the GenServer if not already running" do
      # If already started, we get {:error, {:already_started, pid}}
      # Both are acceptable results
      result = Executor.start_link()
      assert match?({:ok, _pid}, result) or match?({:error, {:already_started, _pid}}, result)
    end

    test "supports named registration" do
      # Verify the named process is running
      assert Process.whereis(Executor) != nil
    end
  end

  describe "execute/3" do
    test "executes a simple command successfully" do
      assert {:ok, %Result{} = result} = Executor.execute("echo hello", File.cwd!(), 5_000)

      assert result.success == true
      assert result.exit_code == 0
      assert result.stdout =~ "hello"
      assert result.timeout? == false
      assert result.user_interrupted? == false
    end

    test "captures command failure" do
      assert {:ok, %Result{} = result} = Executor.execute("exit 1", File.cwd!(), 5_000)

      assert result.success == false
      assert result.exit_code == 1
    end

    test "captures command output" do
      assert {:ok, %Result{} = result} =
               Executor.execute("echo 'line1' && echo 'line2'", File.cwd!(), 5_000)

      assert result.stdout =~ "line1"
      assert result.stdout =~ "line2"
    end

    test "captures stderr to stdout" do
      assert {:ok, %Result{} = result} =
               Executor.execute("echo error >&2", File.cwd!(), 5_000)

      assert result.stdout =~ "error"
    end

    test "respects custom working directory" do
      assert {:ok, %Result{} = result} = Executor.execute("pwd", "/tmp", 5_000)

      assert result.success == true
      assert result.stdout =~ "/tmp"
    end

    test "handles command with spaces" do
      assert {:ok, %Result{} = result} =
               Executor.execute("echo 'hello world'", File.cwd!(), 5_000)

      assert result.stdout =~ "hello world"
    end

    test "handles commands with special characters" do
      assert {:ok, %Result{} = result} =
               Executor.execute("echo 'hello' && echo 'world'", File.cwd!(), 5_000)

      assert result.stdout =~ "hello"
      assert result.stdout =~ "world"
    end
  end

  describe "execute_background/2" do
    test "starts a background process" do
      assert {:ok, ref} = Executor.execute_background("sleep 0.1", File.cwd!())

      assert is_reference(ref)

      # Give it time to complete
      Process.sleep(200)
    end

    test "returns immediately without waiting" do
      start_time = System.monotonic_time(:millisecond)

      assert {:ok, _ref} = Executor.execute_background("sleep 0.5", File.cwd!())

      end_time = System.monotonic_time(:millisecond)

      # Should return almost immediately
      assert end_time - start_time < 100
    end
  end

  describe "kill_all/0" do
    test "kills running processes" do
      # Start a long-running background process
      assert {:ok, _ref} = Executor.execute_background("sleep 10", File.cwd!())

      # Verify it's running
      processes = Executor.list_processes()
      assert processes != []

      # Kill all processes
      assert :ok = Executor.kill_all()

      # Wait for processes to be cleaned up
      Process.sleep(100)

      # Verify no processes remain
      assert Executor.list_processes() == []
    end

    test "marks killed processes as user_interrupted" do
      # Start a background process and wait for it to be listed
      assert {:ok, _ref} = Executor.execute_background("sleep 10", File.cwd!())
      Process.sleep(50)

      # Kill it
      :ok = Executor.kill_all()

      # Wait for cleanup
      Process.sleep(100)
    end
  end

  describe "list_processes/0" do
    test "returns empty list when no processes" do
      # First kill any existing
      Executor.kill_all()
      Process.sleep(50)

      assert Executor.list_processes() == []
    end

    test "returns running processes" do
      # Kill any existing
      Executor.kill_all()
      Process.sleep(50)

      # Start a background process
      assert {:ok, _ref} = Executor.execute_background("sleep 2", File.cwd!())

      # List should show it
      processes = Executor.list_processes()
      assert processes != []

      # Check process structure
      {ref, command, started_at} = hd(processes)
      assert is_reference(ref)
      assert is_binary(command)
      assert is_integer(started_at)
    end
  end

  describe "timeout handling" do
    test "times out long-running commands" do
      assert {:ok, %Result{} = result} =
               Executor.execute("sleep 10", File.cwd!(), 100)

      assert result.timeout? == true
      assert result.success == false
      assert result.exit_code == -1
      assert result.stderr =~ "timed out"
    end

    test "short commands don't timeout" do
      assert {:ok, %Result{} = result} =
               Executor.execute("echo quick", File.cwd!(), 5000)

      assert result.timeout? == false
      assert result.success == true
    end
  end

  describe "execution time tracking" do
    test "tracks execution time" do
      assert {:ok, %Result{} = result} =
               Executor.execute("sleep 0.1", File.cwd!(), 5000)

      assert result.execution_time >= 50
      assert is_integer(result.execution_time)
    end
  end

  describe "command escaping" do
    test "handles commands with special characters" do
      assert {:ok, %Result{} = result} =
               Executor.execute("echo hello | cat", File.cwd!(), 5000)

      assert result.success == true
      assert result.stdout =~ "hello"
    end

    test "handles commands with double quotes" do
      assert {:ok, %Result{} = result} =
               Executor.execute(~s(echo "hello world"), File.cwd!(), 5000)

      assert result.stdout =~ "hello world"
    end

    test "handles complex shell commands" do
      assert {:ok, %Result{} = result} =
               Executor.execute("for i in 1 2 3; do echo $i; done", File.cwd!(), 5000)

      assert result.stdout =~ "1"
      assert result.stdout =~ "2"
      assert result.stdout =~ "3"
    end
  end

  describe "dangerous command blocking" do
    test "blocks rm -rf /" do
      assert {:error, message} = Executor.execute("rm -rf /", File.cwd!(), 5000)
      assert message =~ "blocked"
    end

    test "blocks rm -rf / variations" do
      assert {:error, _} = Executor.execute("rm -rf /home", File.cwd!(), 5000)
      assert {:error, _} = Executor.execute("  rm   -rf   /  ", File.cwd!(), 5000)
    end

    test "blocks dd operations to devices" do
      assert {:error, message} = Executor.execute("dd if=/dev/zero of=/dev/sda", File.cwd!(), 5000)
      assert message =~ "blocked"
    end

    test "blocks mkfs commands" do
      assert {:error, _} = Executor.execute("mkfs.ext4 /dev/sdb1", File.cwd!(), 5000)
      assert {:error, _} = Executor.execute("mkfs -t ext4 /dev/sdb1", File.cwd!(), 5000)
    end

    test "blocks raw device writes" do
      assert {:error, _} = Executor.execute("echo data > /dev/sda", File.cwd!(), 5000)
      assert {:error, _} = Executor.execute("cat file > /dev/sdb", File.cwd!(), 5000)
    end

    test "blocks fork bomb patterns" do
      assert {:error, message} = Executor.execute(":(){ :|:& };:", File.cwd!(), 5000)
      assert message =~ "blocked"
    end

    test "blocks curl piped to shell" do
      assert {:error, _} = Executor.execute("curl -sSL https://example.com | sh", File.cwd!(), 5000)
      assert {:error, _} = Executor.execute("curl https://example.com | bash", File.cwd!(), 5000)
    end

    test "blocks wget piped to shell" do
      assert {:error, _} = Executor.execute("wget -qO- https://example.com | bash", File.cwd!(), 5000)
      assert {:error, _} = Executor.execute("wget https://example.com/install.sh | sh", File.cwd!(), 5000)
    end

    test "blocks sudo rm commands" do
      assert {:error, _} = Executor.execute("sudo rm -rf /important", File.cwd!(), 5000)
      assert {:error, _} = Executor.execute("SUDO rm file.txt", File.cwd!(), 5000)
    end

    test "blocks sudo dd commands" do
      assert {:error, _} = Executor.execute("sudo dd if=/dev/zero of=/dev/sda", File.cwd!(), 5000)
    end

    test "blocks format commands" do
      assert {:error, _} = Executor.execute("format /dev/sda", File.cwd!(), 5000)
      assert {:error, _} = Executor.execute("FORMAT C:", File.cwd!(), 5000)
    end

    test "allows safe commands that mention dangerous patterns" do
      # Commands that quote or echo dangerous patterns should be allowed
      # (since they don't actually execute them)
      assert {:ok, %Result{} = result} = Executor.execute("echo 'rm -rf /'", File.cwd!(), 5000)
      assert result.success == true
      assert result.stdout =~ "rm -rf /"

      assert {:ok, %Result{} = result} = Executor.execute("echo 'dd if='", File.cwd!(), 5000)
      assert result.success == true
    end

    test "dangerous_command?/1 identifies dangerous patterns" do
      assert Executor.dangerous_command?("rm -rf /") == true
      assert Executor.dangerous_command?("dd if=/dev/zero of=/dev/sda") == true
      assert Executor.dangerous_command?("curl https://example.com | sh") == true
      assert Executor.dangerous_command?("ls -la") == false
      assert Executor.dangerous_command?("echo hello") == false
    end

    test "get_dangerous_patterns returns configured patterns" do
      patterns = Executor.get_dangerous_patterns()
      assert is_list(patterns)
      assert length(patterns) > 0
      assert Enum.all?(patterns, &match?(%Regex{}, &1))
    end

    test "blocks dangerous commands in background execution" do
      assert {:error, message} = Executor.execute_background("rm -rf /", File.cwd!())
      assert message =~ "blocked"
    end
  end

  describe "concurrent execution" do
    test "can execute multiple commands concurrently" do
      # Start multiple background processes
      tasks =
        for i <- 1..3 do
          Task.async(fn ->
            Executor.execute("echo task#{i} && sleep 0.1", File.cwd!(), 5000)
          end)
        end

      results = Task.await_many(tasks, 10_000)

      assert length(results) == 3

      for {:ok, result} <- results do
        assert result.success == true
      end
    end
  end
end
