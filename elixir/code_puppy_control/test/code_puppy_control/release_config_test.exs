# async: false — this suite mutates the __BURRITO env var and calls
# default_secret_key_base/0 which writes to disk under :user_data basedir.
# Those are global side effects incompatible with async test execution.
defmodule CodePuppyControl.ReleaseConfigTest do
  use ExUnit.Case, async: false

  describe "releases config" do
    test "releases/0 is configured in mix.exs" do
      releases = Mix.Project.config()[:releases]
      assert is_list(releases)
      assert Keyword.has_key?(releases, :code_puppy_control)
    end

    test ":assemble step is present" do
      opts = Mix.Project.config()[:releases][:code_puppy_control]
      assert :assemble in opts[:steps]
    end

    test "burrito wrap step is the actual Burrito.wrap/1 function" do
      opts = Mix.Project.config()[:releases][:code_puppy_control]
      steps = opts[:steps]
      wrap_fn = Enum.find(steps, &is_function/1)
      assert wrap_fn, "no function step found (expected &Burrito.wrap/1)"
      info = :erlang.fun_info(wrap_fn)
      assert info[:module] == Burrito
      assert info[:name] == :wrap
      assert info[:arity] == 1
    end

    test "includes all five target platforms" do
      opts = Mix.Project.config()[:releases][:code_puppy_control]
      targets = opts[:burrito][:targets]

      expected = [
        :macos_arm64,
        :macos_x86_64,
        :linux_x86_64,
        :linux_arm64,
        :windows_x86_64
      ]

      for t <- expected do
        assert Keyword.has_key?(targets, t), "missing target: #{t}"
      end
    end

    test "targets have correct OS + CPU tuples" do
      opts = Mix.Project.config()[:releases][:code_puppy_control]
      targets = opts[:burrito][:targets]

      assert targets[:macos_arm64][:os] == :darwin
      assert targets[:macos_arm64][:cpu] == :aarch64
      assert targets[:windows_x86_64][:os] == :windows
      assert targets[:linux_arm64][:cpu] == :aarch64
    end

    test "include_erts is true (self-contained)" do
      opts = Mix.Project.config()[:releases][:code_puppy_control]
      assert opts[:include_erts] == true
    end
  end

  describe "Burrito defaults (ADR-003 isolation)" do
    alias CodePuppyControl.Config

    test "default_database_path/0 writes under :user_data basedir, NOT ~/.code_puppy" do
      path = Config.default_database_path()

      refute String.contains?(path, "/.code_puppy/"),
             "default_database_path must not leak into Python legacy home ~/.code_puppy/"

      expected_root = :filename.basedir(:user_data, "code_puppy") |> to_string()
      assert String.starts_with?(path, expected_root)
      assert String.ends_with?(path, "data.sqlite")
    end

    test "default_secret_key_base/0 returns a key of at least 64 bytes" do
      key = Config.default_secret_key_base()
      assert is_binary(key)
      assert byte_size(key) >= 64
    end

    test "default_secret_key_base/0 is stable across calls (persisted)" do
      k1 = Config.default_secret_key_base()
      k2 = Config.default_secret_key_base()
      assert k1 == k2, "secret key base must persist; got fresh key on second call"
    end

    test "burrito_binary?/0 returns false when __BURRITO env var is absent" do
      original = System.get_env("__BURRITO")
      System.delete_env("__BURRITO")

      try do
        refute Config.burrito_binary?()
      after
        if original, do: System.put_env("__BURRITO", original)
      end
    end

    test "burrito_binary?/0 returns true when __BURRITO env var is set" do
      original = System.get_env("__BURRITO")
      System.put_env("__BURRITO", "1")

      try do
        assert Config.burrito_binary?()
      after
        if original, do: System.put_env("__BURRITO", original), else: System.delete_env("__BURRITO")
      end
    end
  end

  describe "Burrito CLI dispatch" do
    test "application.ex has burrito mode detection" do
      # Source-level check: Application must reference __BURRITO so CLI
      # dispatch works when running as a Burrito binary. This is fragile
      # but appropriate — we can't easily test Application.start/2 without
      # actually starting the supervision tree.
      source = File.read!("lib/code_puppy_control/application.ex")
      assert source =~ "__BURRITO",
             "Application must detect __BURRITO env var to dispatch CLI from Burrito binary"
    end

    test "application.ex reads argv via :init.get_plain_arguments (not Burrito runtime)" do
      source = File.read!("lib/code_puppy_control/application.ex")
      assert source =~ ":init.get_plain_arguments",
             "Application must read Burrito argv via :init.get_plain_arguments/0, " <>
               "not Burrito.Util.Args (runtime: false dep)"
    end
  end
end
