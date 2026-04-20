defmodule CodePuppyControl.LLM.RoundRobinConcurrencyTest do
  @moduledoc """
  Concurrency safety tests for RoundRobinModel, ported from Python
  tests/test_round_robin_thread_safety.py (bd-212).

  The Elixir RoundRobinModel is a GenServer backed by an ETS table with
  read/write concurrency enabled. These tests verify that `advance_and_get/0`
  distributes evenly under high concurrent access — i.e., no calls are
  swallowed or double-counted due to race conditions.

  Python → Elixir translation notes:
  - asyncio.gather → Task.async_stream / Task.yield_many
  - collections.Counter → Enum.frequencies/1
  - RoundRobinModel instance → named GenServer (configure/1 + advance_and_get/0)
  """

  use ExUnit.Case, async: false
  use ExUnitProperties

  alias CodePuppyControl.RoundRobinModel

  # Number of concurrent worker tasks
  @num_workers 10
  # Calls each worker makes
  @calls_per_worker 300

  setup do
    CodePuppyControl.TestSupport.Reset.ensure_gen_server_started(RoundRobinModel)
    :ok
  end

  # ── Helper ────────────────────────────────────────────────────────────────

  defp run_concurrent_workers(num_workers, calls_per_worker) do
    # Each task calls advance_and_get/0 repeatedly, collecting results locally.
    # Task.async_stream with max_concurrency ensures true parallelism.
    tasks =
      for _i <- 1..num_workers do
        Task.async(fn ->
          for _j <- 1..calls_per_worker do
            RoundRobinModel.advance_and_get()
          end
        end)
      end

    # Collect all results — timeout generous for CI
    task_results = Task.yield_many(tasks, 30_000)

    # Flatten: each task returned {:ok, list_of_models} or nil on timeout
    all_results =
      task_results
      |> Enum.flat_map(fn
        {_task, {:ok, models}} -> models
        {_task, nil} -> flunk("A worker task timed out")
        {_task, {:exit, reason}} -> flunk("A worker task crashed: #{inspect(reason)}")
      end)

    all_results
  end

  # ── Tests ─────────────────────────────────────────────────────────────────

  describe "concurrent access with rotate_every=1" do
    test "advance_and_get distributes evenly under high concurrency" do
      models = ["model0", "model1", "model2"]
      :ok = RoundRobinModel.configure(models: models, rotate_every: 1)

      all_results = run_concurrent_workers(@num_workers, @calls_per_worker)
      total = @num_workers * @calls_per_worker

      assert length(all_results) == total,
             "Expected #{total} results, got #{length(all_results)} — some calls were lost or duplicated"

      frequencies = Enum.frequencies(all_results)
      expected_per_model = total |> div(length(models))

      for model <- models do
        count = Map.get(frequencies, model, 0)
        assert count == expected_per_model,
               "#{model} got #{count} requests, expected #{expected_per_model}. " <>
                 "Distribution: #{inspect(frequencies)}"
      end
    end
  end

  describe "concurrent access with rotate_every > 1" do
    test "advance_and_get distributes evenly with rotate_every=3" do
      models = ["model0", "model1"]
      :ok = RoundRobinModel.configure(models: models, rotate_every: 3)

      # 6 workers × 300 calls = 1800 total
      # 1800 / 2 models = 900 each; 1800 divisible by rotate_every*num_models (6) ✓
      num_workers = 6
      calls_per_worker = 300

      all_results = run_concurrent_workers(num_workers, calls_per_worker)
      total = num_workers * calls_per_worker

      assert length(all_results) == total,
             "Expected #{total} results, got #{length(all_results)} — some calls were lost or duplicated"

      frequencies = Enum.frequencies(all_results)
      expected_per_model = total |> div(length(models))

      for model <- models do
        count = Map.get(frequencies, model, 0)
        assert count == expected_per_model,
               "#{model} got #{count} requests, expected #{expected_per_model}. " <>
                 "Distribution: #{inspect(frequencies)}"
      end
    end
  end

  describe "distribution invariant (property-based)" do
    property "total call count always equals num_workers × calls_per_worker" do
      # StreamData generators
      import StreamData

      check all(
              num_models <- integer(2..5),
              rotate_every <- integer(1..4),
              num_workers <- integer(2..6),
              calls_per_worker <- integer(50..100),
              # Ensure total is divisible by num_models for clean distribution
              # (rotate_every * num_models) must divide (num_workers * calls_per_worker)
              max_runs: 20
            ) do
        models = for i <- 1..num_models, do: "m#{i}"
        total = num_workers * calls_per_worker

        # Distribution is only perfectly even when total is divisible by
        # rotate_every * num_models (a full rotation cycle). With rotate_every=3
        # and 5 models, a cycle is 15 calls. If total isn't a multiple of 15,
        # some models will get one extra rotate_every-block.
        cycle = rotate_every * num_models

        unless rem(total, cycle) != 0 do
          :ok = RoundRobinModel.configure(models: models, rotate_every: rotate_every)

          all_results = run_concurrent_workers(num_workers, calls_per_worker)

          # The hard invariant: every call produced a result
          assert length(all_results) == total,
                 "Lost or duplicated calls: expected #{total}, got #{length(all_results)}"

          # Every result is a valid model name
          for result <- all_results do
            assert result in models,
                   "Got unexpected model name: #{inspect(result)}"
          end

          frequencies = Enum.frequencies(all_results)
          expected_per_model = total |> div(num_models)

          for model <- models do
            count = Map.get(frequencies, model, 0)
            assert count == expected_per_model,
                   "#{model} got #{count}, expected #{expected_per_model}. " <>
                     "Distribution: #{inspect(frequencies)}"
          end
        end
      end
    end
  end
end
