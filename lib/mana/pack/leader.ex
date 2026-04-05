defmodule Mana.Pack.Leader do
  @moduledoc """
  Pack Leader 🐺 - Workflow orchestrator for parallel multi-agent development.

  A GenServer that orchestrates the pack workflow with a state machine:
  :idle → :planning → :executing → :reviewing → :merging → :done

  Coordinates: Bloodhound (issues), Terrier (worktrees), Husky (execution),
  Shepherd (code review), Watchdog (QA), Retriever (merging).

  ## Usage

      {:ok, pid} = Mana.Pack.Leader.start_link(base_branch: "main")
      :ok = Mana.Pack.Leader.run_workflow(pid, max_parallel: 4)
      {:ok, status} = Mana.Pack.Leader.get_status(pid)
  """

  use GenServer

  require Logger

  alias Mana.Pack.Agents.{Bloodhound, Husky, Retriever, Shepherd, Terrier, Watchdog}

  @default_max_parallel 4
  @default_base_branch "main"
  @default_timeout 300_000

  @typedoc "Workflow state"
  @type state :: :idle | :planning | :executing | :reviewing | :merging | :done

  @typedoc "Issue reference (e.g., 'bd-42')"
  @type issue_id :: String.t()

  @typedoc "Task tracking information"
  @type task_info :: %{
          issue_id: issue_id(),
          worktree: String.t(),
          branch: String.t(),
          status: :pending | :completed | :failed | :approved | :rejected,
          shepherd_verdict: :approve | :changes_requested | nil,
          watchdog_verdict: :approve | :changes_requested | nil,
          error: term() | nil,
          completed_at: DateTime.t() | nil
        }

  # Client API

  @doc "Starts the Pack Leader GenServer."
  @spec start_link(keyword()) :: GenServer.on_start()
  def start_link(opts \\ []) do
    name = Keyword.get(opts, :name)
    server_opts = if name, do: [name: name], else: []
    GenServer.start_link(__MODULE__, opts, server_opts)
  end

  @doc "Starts a workflow asynchronously, transitioning through all states."
  @spec run_workflow(GenServer.server(), keyword()) :: :ok
  def run_workflow(server, opts \\ []), do: GenServer.cast(server, {:run_workflow, opts})

  @doc "Gets the current workflow status."
  @spec get_status(GenServer.server()) :: {:ok, map()}
  def get_status(server), do: GenServer.call(server, :get_status)

  @doc "Stops the leader gracefully."
  @spec stop(GenServer.server()) :: :ok
  def stop(server), do: GenServer.stop(server, :normal)

  # Server Callbacks

  @impl true
  def init(opts) do
    {:ok, task_sup} = Task.Supervisor.start_link()

    state = %{
      state: :idle,
      base_branch: Keyword.get(opts, :base_branch, @default_base_branch),
      tasks: %{},
      ready_issues: [],
      completed_count: 0,
      failed_count: 0,
      errors: [],
      started_at: nil,
      completed_at: nil,
      opts: opts,
      task_sup: task_sup
    }

    Logger.info("Pack Leader initialized with base branch: #{state.base_branch}")
    {:ok, state}
  end

  @impl true
  def handle_cast({:run_workflow, opts}, %{state: :idle} = state) do
    Logger.info("Pack Leader: Starting workflow")
    new_state = %{state | state: :planning, started_at: DateTime.utc_now(), opts: Keyword.merge(state.opts, opts)}
    send(self(), :do_planning)
    {:noreply, new_state}
  end

  def handle_cast({:run_workflow, _}, state) do
    Logger.warning("Pack Leader: Workflow already in progress (state: #{state.state})")
    {:noreply, state}
  end

  @impl true
  def handle_call(:get_status, _from, state) do
    status = %{
      state: state.state,
      base_branch: state.base_branch,
      tasks: state.tasks,
      ready_issues: state.ready_issues,
      progress: {state.completed_count, map_size(state.tasks)},
      failed_count: state.failed_count,
      errors: state.errors,
      started_at: state.started_at,
      completed_at: state.completed_at,
      elapsed_ms: elapsed_ms(state)
    }

    {:reply, {:ok, status}, state}
  end

  @impl true
  def handle_info(:do_planning, state) do
    Logger.info("Pack Leader: Planning phase - querying bd ready")

    case query_ready_issues() do
      {:ok, []} ->
        Logger.info("Pack Leader: No ready issues found, workflow complete")
        {:noreply, transition_to_done(state)}

      {:ok, issue_ids} ->
        Logger.info("Pack Leader: Found #{length(issue_ids)} ready issues")

        tasks =
          Map.new(issue_ids, fn id ->
            {id,
             %{
               issue_id: id,
               worktree: Terrier.worktree_path_for_issue(id),
               branch: Terrier.branch_name_for_issue(id, "task"),
               status: :pending,
               shepherd_verdict: nil,
               watchdog_verdict: nil,
               error: nil,
               completed_at: nil
             }}
          end)

        send(self(), :do_execution)
        {:noreply, %{state | tasks: tasks, ready_issues: issue_ids, state: :executing}}

      {:error, reason} ->
        Logger.error("Pack Leader: Planning failed - #{inspect(reason)}")
        {:noreply, transition_to_done(%{state | errors: [reason | state.errors]})}
    end
  end

  def handle_info(:do_execution, state) do
    Logger.info("Pack Leader: Execution phase - dispatching agents")
    max_parallel = Keyword.get(state.opts, :max_parallel, @default_max_parallel)
    base = state.base_branch

    specs = build_execution_specs(state.ready_issues, state.tasks, base)

    results = run_parallel(specs, max_parallel, state.task_sup)

    {tasks, failed} =
      Enum.reduce(results, {state.tasks, 0}, fn
        {id, {:ok, _}, {:ok, _}}, {t, f} ->
          {put_in(t[id].status, :completed) |> put_in([id, :completed_at], DateTime.utc_now()), f}

        {id, t_res, h_res}, {t, f} ->
          err =
            case {t_res, h_res} do
              {{:error, e}, _} -> e
              {_, {:error, e}} -> e
              _ -> :unknown_error
            end

          {put_in(t[id].status, :failed)
           |> put_in([id, :error], err)
           |> put_in([id, :completed_at], DateTime.utc_now()), f + 1}

        _, {t, f} ->
          {t, f}
      end)

    completed = Enum.count(tasks, fn {_, v} -> v.status == :completed end)
    Logger.info("Pack Leader: Execution complete - #{completed} completed, #{failed} failed")

    send(self(), :do_review)

    {:noreply,
     %{state | tasks: tasks, completed_count: completed, failed_count: state.failed_count + failed, state: :reviewing}}
  end

  def handle_info(:do_review, state) do
    Logger.info("Pack Leader: Review phase - running critics")
    to_review = Enum.filter(state.tasks, fn {_, t} -> t.status == :completed end)

    if Enum.empty?(to_review) do
      {:noreply, %{state | state: :merging}, {:continue, :do_merge}}
    else
      max_parallel = Keyword.get(state.opts, :max_parallel, @default_max_parallel)
      specs = build_review_specs(to_review)

      results = run_parallel(specs, max_parallel, state.task_sup)

      tasks =
        Enum.reduce(results, state.tasks, fn result, t ->
          process_review_result(result, t)
        end)

      approved = Enum.count(tasks, fn {_, t} -> t.status == :approved end)
      rejected = Enum.count(tasks, fn {_, t} -> t.status == :rejected end)
      Logger.info("Pack Leader: Review complete - #{approved} approved, #{rejected} rejected")

      {:noreply, %{state | tasks: tasks, state: :merging}, {:continue, :do_merge}}
    end
  end

  @impl true
  def handle_continue(:do_merge, state) do
    Logger.info("Pack Leader: Merge phase - merging approved branches")
    approved = Enum.filter(state.tasks, fn {_, t} -> t.status == :approved end)

    if Enum.empty?(approved) do
      {:noreply, transition_to_done(state)}
    else
      base = state.base_branch

      results =
        Enum.map(approved, fn {id, task} ->
          {id,
           Retriever.execute(
             %{
               id: "retriever-#{id}",
               issue_id: id,
               worktree: task.worktree,
               description: "Merge #{task.branch}",
               metadata: %{action: "full_merge", branch: task.branch, base: base, strategy: "no_ff", cleanup: true}
             },
             []
           )}
        end)

      {tasks, closed} =
        Enum.reduce(results, {state.tasks, 0}, fn result, acc ->
          process_merge_result(result, acc, state.base_branch)
        end)

      Logger.info("Pack Leader: Merged #{closed} branches")
      {:noreply, transition_to_done(%{state | tasks: tasks})}
    end
  end

  # Helper functions

  defp build_execution_specs(ready_issues, tasks, base) do
    Enum.map(ready_issues, fn id ->
      task = tasks[id]

      fn ->
        t_result =
          Terrier.execute(
            %{
              id: "terrier-#{id}",
              issue_id: id,
              worktree: task.worktree,
              description: "Create worktree",
              metadata: %{action: "create", branch: task.branch, base: base}
            },
            []
          )

        h_result =
          Husky.execute(
            %{
              id: "husky-#{id}",
              issue_id: id,
              worktree: task.worktree,
              description: "Execute task",
              metadata: %{command_type: "mix_test", env: %{}}
            },
            []
          )

        {id, t_result, h_result}
      end
    end)
  end

  defp build_review_specs(to_review) do
    Enum.map(to_review, fn {id, task} ->
      fn ->
        s_result =
          Shepherd.execute(
            %{
              id: "shepherd-#{id}",
              issue_id: id,
              worktree: task.worktree,
              description: "Review code",
              metadata: %{checks: ["compile", "format", "test"], auto_fix: false}
            },
            []
          )

        w_result =
          Watchdog.execute(
            %{
              id: "watchdog-#{id}",
              issue_id: id,
              worktree: task.worktree,
              description: "QA review",
              metadata: %{min_coverage: 80, check_edge_cases: true}
            },
            []
          )

        {id, s_result, w_result}
      end
    end)
  end

  defp run_parallel(specs, max_parallel, task_sup) do
    Task.Supervisor.async_stream_nolink(task_sup, specs, fn f -> f.() end,
      max_concurrency: max_parallel,
      on_timeout: :kill_task,
      timeout: @default_timeout
    )
    |> Enum.map(fn
      {:ok, r} -> r
      {:exit, reason} -> {:error, reason}
    end)
  end

  defp query_ready_issues() do
    case Bloodhound.execute(
           %{
             id: "planning-query",
             issue_id: nil,
             worktree: nil,
             description: "Query ready",
             metadata: %{command: "ready", args: ["--json"]}
           },
           []
         ) do
      {:ok, result} -> parse_ready_output(result[:stdout])
      {:error, reason} -> {:error, reason}
    end
  end

  defp parse_ready_output(nil), do: {:ok, []}
  defp parse_ready_output(""), do: {:ok, []}

  defp parse_ready_output(output) do
    case Jason.decode(output) do
      {:ok, list} when is_list(list) ->
        {:ok, Enum.reject(Enum.map(list, &(&1["id"] || &1[:id])), &is_nil/1)}

      {:error, _} ->
        {:ok,
         output |> String.split("\n") |> Enum.map(&String.trim/1) |> Enum.filter(&String.starts_with?(&1, "bd-"))}

      _ ->
        {:ok, []}
    end
  rescue
    e ->
      Logger.error("Pack Leader: Failed to parse ready output: #{inspect(e)}")
      {:ok, []}
  end

  defp process_review_result({id, {:ok, s}, {:ok, w}}, tasks) do
    sv = s[:verdict]
    wv = w[:verdict]
    status = if sv == :approve && wv == :approve, do: :approved, else: :rejected
    put_in(tasks[id].status, status)
    |> put_in([id, :shepherd_verdict], sv)
    |> put_in([id, :watchdog_verdict], wv)
  end

  defp process_review_result(_, tasks), do: tasks

  defp process_merge_result({id, {:ok, %{status: :completed}}}, {tasks, closed}, _base_branch) do
    close_res =
      Bloodhound.execute(
        %{
          id: "close-#{id}",
          issue_id: id,
          worktree: nil,
          description: "Close issue",
          metadata: %{command: "close", issue_id: id}
        },
        []
      )

    new_closed = if match?({:ok, _}, close_res), do: closed + 1, else: closed
    {put_in(tasks[id].status, :merged), new_closed}
  end

  defp process_merge_result({id, {:ok, r}}, {tasks, closed}, _base_branch) do
    {put_in(tasks[id].status, :failed)
     |> put_in([id, :error], r[:message] || :merge_failed), closed}
  end

  defp process_merge_result({id, {:error, reason}}, {tasks, closed}, _base_branch) do
    {put_in(tasks[id].status, :failed)
     |> put_in([id, :error], reason), closed}
  end

  defp transition_to_done(state) do
    %{state | state: :done, completed_at: DateTime.utc_now(), ready_issues: []}
  end

  defp elapsed_ms(%{started_at: nil}), do: nil
  defp elapsed_ms(%{started_at: s, completed_at: nil}), do: DateTime.diff(DateTime.utc_now(), s, :millisecond)
  defp elapsed_ms(%{started_at: s, completed_at: c}), do: DateTime.diff(c, s, :millisecond)
end
