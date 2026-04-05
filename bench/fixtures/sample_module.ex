defmodule Mana.Fixtures.SampleModule do
  @moduledoc """
  A sample module for RepoCompass indexing benchmarks.
  This module demonstrates various Elixir constructs.
  """

  use GenServer

  # Public API

  @doc "Start the server"
  def start_link(opts) do
    GenServer.start_link(__MODULE__, opts, name: __MODULE__)
  end

  @doc "Get the current state"
  def get_state(pid) do
    GenServer.call(pid, :get_state)
  end

  @doc "Update with new data"
  def update(pid, data) do
    GenServer.cast(pid, {:update, data})
  end

  @doc "Process a list of items"
  def process_items(items) when is_list(items) do
    Enum.map(items, &process_item/1)
  end

  @doc "Process a single item"
  def process_item(item) do
    item
    |> transform()
    |> validate()
    |> finalize()
  end

  # GenServer Callbacks

  @impl true
  def init(opts) do
    {:ok, %{data: opts[:data] || %{}, counter: 0}}
  end

  @impl true
  def handle_call(:get_state, _from, state) do
    {:reply, state, state}
  end

  @impl true
  def handle_call({:compute, input}, _from, state) do
    result = do_compute(input, state)
    {:reply, result, %{state | counter: state.counter + 1}}
  end

  @impl true
  def handle_cast({:update, data}, state) do
    {:noreply, %{state | data: data}}
  end

  @impl true
  def handle_info(:tick, state) do
    {:noreply, %{state | counter: state.counter + 1}}
  end

  # Private Functions

  defp transform(item) do
    %{item | processed: true}
  end

  defp validate(item) do
    if item.valid, do: item, else: {:error, :invalid}
  end

  defp finalize({:error, _} = err), do: err
  defp finalize(item), do: %{item | finalized: true}

  defp do_compute(input, state) do
    input * state.counter
  end
end
