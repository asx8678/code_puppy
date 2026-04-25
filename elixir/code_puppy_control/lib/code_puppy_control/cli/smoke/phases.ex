defmodule CodePuppyControl.CLI.Smoke.Phases do
  @moduledoc """
  Phase implementations for `CodePuppyControl.CLI.Smoke`.

  Split out of `Smoke` to keep individual modules under the 600-line
  cap.  The phases here are dispatched by `Smoke.run_phases/2` and are
  not meant to be called directly by application code — call
  `Smoke.run/1` (or `Smoke.run_phases/2` from a Mix task).

  Refs: code_puppy-baa
  """

  alias CodePuppyControl.CLI
  alias CodePuppyControl.CLI.Parser
  alias CodePuppyControl.CLI.Smoke.MockLLM
  alias CodePuppyControl.Config.Paths
  alias CodePuppyControl.REPL.OneShot
  alias CodePuppyControl.Tools.AgentCatalogue

  @type phase_result :: %{
          phase: atom(),
          status: :pass | :fail | :skip,
          detail: String.t(),
          metrics: map()
        }

  # ── Phase: parser ─────────────────────────────────────────────────────

  @doc false
  @spec parser() :: phase_result()
  def parser do
    cases = [
      {["--help"], :help_tag, fn -> match?({:help, _}, Parser.parse(["--help"])) end},
      {["--version"], :version_tag, fn -> match?({:version, _}, Parser.parse(["--version"])) end},
      {["-p", "hello"], :ok_tag,
       fn ->
         match?({:ok, %{prompt: "hello"}}, Parser.parse(["-p", "hello"]))
       end},
      {["--bogus"], :error_tag,
       fn ->
         match?({:error, _msg}, Parser.parse(["--bogus"]))
       end},
      {[:help_text, :body], :help_text_invariants,
       fn ->
         text = CLI.help_text()

         text =~ "Usage: pup [OPTIONS] [PROMPT]" and
           text =~ "code-puppy " and
           text =~ "--prompt"
       end}
    ]

    failures =
      Enum.reduce(cases, [], fn {label, tag, predicate}, acc ->
        if safe_predicate(predicate) do
          acc
        else
          [{label, tag} | acc]
        end
      end)

    if failures == [] do
      %{
        phase: :parser,
        status: :pass,
        detail: "argv parsing + help text invariants ok",
        metrics: %{cases: length(cases)}
      }
    else
      %{
        phase: :parser,
        status: :fail,
        detail: "parser case(s) failed: #{inspect(Enum.reverse(failures))}",
        metrics: %{cases: length(cases), failed: length(failures)}
      }
    end
  end

  # ── Phase: run_mode ────────────────────────────────────────────────────

  @doc false
  @spec run_mode() :: phase_result()
  def run_mode do
    expectations = [
      {%{prompt: "hello"}, :one_shot},
      {%{prompt: "hello", interactive: true}, :interactive_with_prompt},
      {%{continue: true}, :continue_session},
      {%{}, :interactive_default},
      {%{prompt: nil}, :interactive_default},
      {%{prompt: ""}, :interactive_default},
      {%{prompt: "hi", continue: true}, :one_shot}
    ]

    failures =
      Enum.reduce(expectations, [], fn {input, expected}, acc ->
        actual =
          try do
            CLI.resolve_run_mode(input)
          rescue
            err -> {:raised, err}
          end

        if actual == expected, do: acc, else: [{input, expected, actual} | acc]
      end)

    if failures == [] do
      %{
        phase: :run_mode,
        status: :pass,
        detail: "run-mode resolver routes all known inputs",
        metrics: %{cases: length(expectations)}
      }
    else
      %{
        phase: :run_mode,
        status: :fail,
        detail: "run-mode mismatches: #{inspect(Enum.reverse(failures))}",
        metrics: %{cases: length(expectations), failed: length(failures)}
      }
    end
  end

  # ── Phase: sandbox ────────────────────────────────────────────────────

  @doc false
  @spec sandbox(map()) :: phase_result()
  def sandbox(sandbox) do
    home_resolved = Paths.home_dir()
    legacy = Paths.legacy_home_dir()
    real_default = Path.expand("~/.code_puppy_ex")

    checks = [
      {home_resolved == sandbox.dir, "Paths.home_dir/0 resolves to sandbox"},
      {Paths.in_legacy_home?(legacy) == true, "legacy home detected as legacy"},
      {Paths.in_legacy_home?(sandbox.dir) == false, "sandbox not under legacy home"},
      {home_resolved != real_default,
       "Paths.home_dir/0 must NOT equal real ~/.code_puppy_ex during smoke"},
      {sandbox.dir |> File.dir?(), "sandbox dir exists on disk"}
    ]

    failures = for {ok?, label} <- checks, not ok?, do: label

    if failures == [] do
      %{
        phase: :sandbox,
        status: :pass,
        detail: "sandbox isolated; PUP_EX_HOME=#{home_resolved}",
        metrics: %{checks: length(checks)}
      }
    else
      %{
        phase: :sandbox,
        status: :fail,
        detail: "sandbox checks failed: #{inspect(failures)}",
        metrics: %{checks: length(checks), failed: length(failures)}
      }
    end
  end

  # ── Phase: one_shot ───────────────────────────────────────────────────

  @doc false
  @spec one_shot(map()) :: phase_result()
  def one_shot(_sandbox) do
    if not application_started?() do
      %{
        phase: :one_shot,
        status: :skip,
        detail:
          "code_puppy_control application not started — invoke from `mix pup_ex.smoke`" <>
            " or call Application.ensure_all_started/1 first",
        metrics: %{}
      }
    else
      do_one_shot()
    end
  end

  defp do_one_shot do
    prev_llm = Application.get_env(:code_puppy_control, :repl_llm_module)
    Application.put_env(:code_puppy_control, :repl_llm_module, MockLLM)
    MockLLM.reset()

    safe_discover_agents()

    session_id = "smoke-" <> random_hex(4)
    prompt = "smoke probe — no network"

    {captured, run_outcome} =
      capture_group_leader(fn ->
        OneShot.run(%{prompt: prompt, session_id: session_id})
      end)

    {return_value, raised} =
      case run_outcome do
        {:ok, value} -> {value, nil}
        {:raised, err} -> {:__raised__, err}
        {:caught, kind_reason} -> {:__caught__, kind_reason}
      end

    # Drain async session saves before we tear down env vars.
    Process.sleep(150)

    try do
      build_one_shot_result(raised, return_value, captured, session_id, prompt)
    after
      restore_repl_llm(prev_llm)
    end
  end

  defp build_one_shot_result(raised, return_value, captured, session_id, prompt) do
    cond do
      match?(%{__struct__: _}, raised) ->
        %{
          phase: :one_shot,
          status: :fail,
          detail:
            "OneShot.run/1 raised #{inspect(raised.__struct__)}: " <>
              Exception.message(raised),
          metrics: %{invocation_count: MockLLM.invocation_count()}
        }

      is_tuple(raised) ->
        %{
          phase: :one_shot,
          status: :fail,
          detail: "OneShot.run/1 caught: #{inspect(raised)}",
          metrics: %{invocation_count: MockLLM.invocation_count()}
        }

      return_value != :ok ->
        %{
          phase: :one_shot,
          status: :fail,
          detail: "OneShot.run/1 returned #{inspect(return_value)} (expected :ok)",
          metrics: %{invocation_count: MockLLM.invocation_count()}
        }

      MockLLM.invocation_count() != 1 ->
        %{
          phase: :one_shot,
          status: :fail,
          detail: "MockLLM was invoked #{MockLLM.invocation_count()} times (expected exactly 1)",
          metrics: %{invocation_count: MockLLM.invocation_count()}
        }

      not (captured =~ MockLLM.canned_reply()) ->
        %{
          phase: :one_shot,
          status: :fail,
          detail:
            "captured stdout did not contain mock reply " <>
              "(expected #{inspect(MockLLM.canned_reply())})",
          metrics: %{
            invocation_count: MockLLM.invocation_count(),
            captured_bytes: byte_size(captured)
          }
        }

      true ->
        %{
          phase: :one_shot,
          status: :pass,
          detail: "OneShot.run/1 dispatched to MockLLM and rendered canned reply",
          metrics: %{
            invocation_count: MockLLM.invocation_count(),
            session_id: session_id,
            prompt_bytes: byte_size(prompt),
            captured_bytes: byte_size(captured)
          }
        }
    end
  end

  defp restore_repl_llm(nil) do
    Application.delete_env(:code_puppy_control, :repl_llm_module)
  end

  defp restore_repl_llm(prev) do
    Application.put_env(:code_puppy_control, :repl_llm_module, prev)
  end

  # ── Phase: escript (opt-in) ───────────────────────────────────────────

  @doc false
  @spec escript() :: phase_result()
  def escript do
    candidates = [
      Path.join(File.cwd!(), "pup"),
      Path.expand("../../../pup", __DIR__),
      Path.expand("../../../../pup", __DIR__)
    ]

    case Enum.find(candidates, &File.regular?/1) do
      nil ->
        %{
          phase: :escript,
          status: :skip,
          detail:
            "no `pup` escript found — build with `MIX_ENV=prod mix escript.build` " <>
              "to exercise this phase",
          metrics: %{candidates: candidates}
        }

      path ->
        probe_packaged_cli(:escript, path)
    end
  end

  # ── Phase: burrito (opt-in) ───────────────────────────────────────────

  # Burrito drops binaries under `burrito_out/<release_name>_<target>` after
  # `MIX_ENV=prod mix release`.  Building Burrito artifacts requires Zig and
  # is expensive; this phase is opt-in and skips deterministically when no
  # artifact is present, so CI without a Zig toolchain stays green.
  #
  # Refs: code_puppy-d7m
  @doc false
  @spec burrito() :: phase_result()
  def burrito do
    case find_burrito_artifact() do
      {:ok, path} ->
        probe_packaged_cli(:burrito, path)

      {:skip, reason, metrics} ->
        %{
          phase: :burrito,
          status: :skip,
          detail: reason,
          metrics: metrics
        }
    end
  end

  # Locate a Burrito-built binary that is **runnable on the smoke host**.
  # Returns:
  #
  #   * `{:ok, path}`           — verified host-compatible regular file
  #   * `{:skip, reason, m}`    — no compatible artifact; phase should skip
  #
  # IMPORTANT (regression code_puppy-d7m): we MUST NOT fall back to an
  # arbitrary `burrito_out/code_puppy_control_*` regular file.  Probing a
  # cross-compiled sibling that cannot exec on this host produces a
  # confusing `:fail` (or a hang on Linux trying to exec a Mach-O) when
  # the correct outcome is `:skip` with a build hint.  Only artifacts in
  # `host_compatible_targets/0` are probed.
  defp find_burrito_artifact do
    burrito_dir = Path.join(File.cwd!(), "burrito_out")
    probe_burrito_dir(burrito_dir, host_compatible_targets())
  end

  # Public-but-undocumented entry point so the regression test can drive
  # the artifact-selection logic with a synthetic `burrito_out/` and a
  # fixed candidate list, without changing the working directory or
  # assuming anything about the test runner's host.
  #
  # Refs: code_puppy-d7m
  @doc false
  @spec probe_burrito_dir(String.t(), [String.t()]) ::
          {:ok, String.t()} | {:skip, String.t(), map()}
  def probe_burrito_dir(burrito_dir, candidate_targets)
      when is_binary(burrito_dir) and is_list(candidate_targets) do
    cond do
      not File.dir?(burrito_dir) ->
        {:skip,
         "no `burrito_out/` directory — build host-only with " <>
           "`scripts/build-burrito.sh --host-only` (requires Zig)", %{burrito_dir: burrito_dir}}

      candidate_targets == [] ->
        {:skip,
         "could not detect a host-compatible Burrito target for #{host_id()} — " <>
           "phase requires one of the targets configured in mix.exs; " <>
           "build host-only with `scripts/build-burrito.sh --host-only`",
         %{burrito_dir: burrito_dir, candidates: candidate_targets}}

      true ->
        case probe_candidates(burrito_dir, candidate_targets) do
          {:ok, path} ->
            {:ok, path}

          :none ->
            {:skip,
             "no host-compatible `code_puppy_control_*` artifact in #{burrito_dir} " <>
               "(looked for: #{Enum.join(candidate_targets, ", ")}) — " <>
               "build host-only with `scripts/build-burrito.sh --host-only`",
             %{burrito_dir: burrito_dir, candidates: candidate_targets}}
        end
    end
  end

  # Walk `candidate_targets` in priority order; return the first path that
  # exists as a regular file under `burrito_dir`.
  defp probe_candidates(_burrito_dir, []), do: :none

  defp probe_candidates(burrito_dir, [target | rest]) do
    case probe_target(burrito_dir, target) do
      {:ok, _path} = ok -> ok
      :none -> probe_candidates(burrito_dir, rest)
    end
  end

  # Probe the on-disk filename(s) Burrito actually produces for `target`
  # under `burrito_dir`.  Returns the first matching regular file or
  # `:none`.
  #
  # Refs: code_puppy-d7m
  defp probe_target(burrito_dir, target) do
    target
    |> candidate_filenames()
    |> Enum.find_value(:none, fn name ->
      path = Path.join(burrito_dir, name)
      if File.regular?(path), do: {:ok, path}, else: nil
    end)
  end

  # Burrito names the produced binary `<release>_<target>` on Unix and
  # appends a `.exe` suffix for Windows targets — see
  # `docs/burrito-release.md` ("Output Layout") and `mix.exs`.  We probe
  # the `.exe` variant for `windows_*` targets so a host-Windows smoke
  # run can actually find the artifact instead of silently skipping.
  #
  # We deliberately do NOT add a bare-name fallback for Windows targets:
  # the strict host-compat contract (regression code_puppy-d7m) requires
  # us to match only what Burrito actually emits, never an unrelated
  # planted file with a colliding name.
  #
  # Refs: code_puppy-d7m
  @doc false
  @spec candidate_filenames(String.t()) :: [String.t()]
  def candidate_filenames(target) when is_binary(target) do
    base = "code_puppy_control_#{target}"

    if String.starts_with?(target, "windows_") do
      [base <> ".exe"]
    else
      [base]
    end
  end

  # Map the running BEAM host to an ordered list of Burrito target names
  # (as configured in `mix.exs`) that are **runnable on this host**.
  # First entry is the preferred match; later entries are acceptable
  # fallbacks.  An empty list means we do not recognise the host and the
  # phase MUST skip rather than guess.
  #
  # Linux musl handling: a glibc Linux host can typically execute a
  # statically-linked musl Burrito binary, so we list the musl artifact
  # as a secondary candidate after the matching glibc artifact.  A pure
  # musl host (e.g. Alpine) cannot run glibc binaries, so we list ONLY
  # the musl artifact for that case.
  #
  # Refs: code_puppy-d7m
  @doc false
  @spec host_compatible_targets() :: [String.t()]
  def host_compatible_targets do
    {os_family, _os_name} = :os.type()
    arch = :erlang.system_info(:system_architecture) |> List.to_string()
    musl? = String.contains?(arch, "-musl")

    case {os_family, arch, musl?} do
      {:win32, _, _} -> ["windows_x86_64"]
      {:unix, "aarch64-apple" <> _, _} -> ["macos_arm64"]
      {:unix, "arm64-apple" <> _, _} -> ["macos_arm64"]
      {:unix, "x86_64-apple" <> _, _} -> ["macos_x86_64"]
      {:unix, "aarch64" <> _, true} -> ["linux_musl_arm64"]
      {:unix, "x86_64" <> _, true} -> ["linux_musl_x86_64"]
      {:unix, "aarch64" <> _, false} -> ["linux_arm64", "linux_musl_arm64"]
      {:unix, "x86_64" <> _, false} -> ["linux_x86_64", "linux_musl_x86_64"]
      _ -> []
    end
  end

  # Short, log-friendly identifier for the current host, used only in
  # skip reasons so operators know why detection failed.
  defp host_id do
    {os_family, _} = :os.type()
    arch = :erlang.system_info(:system_architecture) |> List.to_string()
    "#{os_family}/#{arch}"
  end

  # ── Shared probe helper ───────────────────────────────────────────────

  # Run the canonical no-network smoke probes against a packaged CLI
  # binary (escript or Burrito).  Both probes are deterministic and
  # touch zero network/auth state:
  #
  #   1. `--version`  must exit 0 and contain the marker `code-puppy`.
  #   2. `--help`     must exit 0 and contain the markers
  #                   `Usage: pup [OPTIONS] [PROMPT]` and `--prompt`.
  #
  # Always invokes the binary with the active `PUP_EX_HOME` (so any
  # accidental config touch lands in the smoke sandbox, NEVER
  # `~/.code_puppy_ex/`) and `PUP_SMOKE_PROBE=1` so callees can
  # detect-and-shortcircuit if they ever need to.
  defp probe_packaged_cli(phase, path) do
    env = packaged_cli_env()

    with {:version, {ver_out, 0}} <-
           {:version, System.cmd(path, ["--version"], stderr_to_stdout: true, env: env)},
         true <- ver_out =~ "code-puppy" || {:fail, :version_marker_missing, ver_out},
         {:help, {help_out, 0}} <-
           {:help, System.cmd(path, ["--help"], stderr_to_stdout: true, env: env)},
         true <-
           help_out =~ "Usage: pup [OPTIONS] [PROMPT]" ||
             {:fail, :help_usage_missing, help_out},
         true <- help_out =~ "--prompt" || {:fail, :help_prompt_flag_missing, help_out} do
      %{
        phase: phase,
        status: :pass,
        detail: "#{phase} --version and --help exited 0 with stable markers",
        metrics: %{
          path: path,
          version_bytes: byte_size(ver_out),
          help_bytes: byte_size(help_out)
        }
      }
    else
      {:version, {output, exit_status}} ->
        %{
          phase: phase,
          status: :fail,
          detail:
            "#{phase} --version exited #{exit_status}: " <>
              inspect(String.slice(output, 0, 120)),
          metrics: %{path: path, exit_status: exit_status, probe: "--version"}
        }

      {:help, {output, exit_status}} ->
        %{
          phase: phase,
          status: :fail,
          detail:
            "#{phase} --help exited #{exit_status}: " <>
              inspect(String.slice(output, 0, 120)),
          metrics: %{path: path, exit_status: exit_status, probe: "--help"}
        }

      {:fail, reason, output} ->
        %{
          phase: phase,
          status: :fail,
          detail:
            "#{phase} probe missing marker (#{reason}); first 120 bytes: " <>
              inspect(String.slice(output, 0, 120)),
          metrics: %{path: path, reason: reason}
        }
    end
  rescue
    err ->
      %{
        phase: phase,
        status: :fail,
        detail: "#{phase} probe raised #{inspect(err.__struct__)}: #{Exception.message(err)}",
        metrics: %{path: path}
      }
  end

  defp packaged_cli_env do
    [
      {"PUP_EX_HOME", System.get_env("PUP_EX_HOME") || ""},
      {"PUP_SMOKE_PROBE", "1"}
    ]
  end

  # ── Helpers ───────────────────────────────────────────────────────────

  defp random_hex(bytes) do
    :crypto.strong_rand_bytes(bytes) |> Base.encode16(case: :lower)
  end

  defp safe_predicate(fun) do
    try do
      fun.() == true
    rescue
      _ -> false
    catch
      _, _ -> false
    end
  end

  defp application_started? do
    Enum.any?(Application.started_applications(), fn {app, _, _} ->
      app == :code_puppy_control
    end)
  end

  defp safe_discover_agents do
    try do
      AgentCatalogue.discover_agent_modules()
    catch
      _, _ -> :ok
    end
  end

  # Captures everything written to the calling process's group leader
  # while `fun` runs.  Returns `{captured_string, outcome}` where
  # `outcome` is one of:
  #
  #   * `{:ok, value}`            — `fun` returned `value`
  #   * `{:raised, exception}`    — `fun` raised an exception
  #   * `{:caught, {kind, why}}`  — `fun` threw or exited
  #
  # Uses `StringIO` + `Process.group_leader/2` so the lib does NOT pull
  # in `ExUnit.CaptureIO` at runtime (ExUnit is a test-only application
  # in production / Burrito builds).
  defp capture_group_leader(fun) do
    {:ok, sio} = StringIO.open("")
    prev_leader = Process.group_leader()
    Process.group_leader(self(), sio)

    outcome =
      try do
        {:ok, fun.()}
      rescue
        err -> {:raised, err}
      catch
        kind, why -> {:caught, {kind, why}}
      after
        Process.group_leader(self(), prev_leader)
      end

    {:ok, {_input, output}} = StringIO.close(sio)
    {output, outcome}
  end
end
