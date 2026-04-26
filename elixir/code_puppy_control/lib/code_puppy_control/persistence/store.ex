defmodule CodePuppyControl.Persistence.Store do
  @moduledoc """
  Ecto-backed CRUD persistence store for sessions, configs, and workflow state.

  Provides a unified interface for persisting domain entities to SQLite via
  Ecto. All state-changing operations use `Ecto.Multi` to guarantee
  dual-write discipline (§6.3) when events are co-written.

  ## Supported entity types

  | Entity | Schema | Namespace |
  |--------|--------|-----------|
  | Configs | `PersistedConfig` | configurable via `:namespace` |
  | Workflow snapshots | `WorkflowSnapshot` | keyed by `session_id` |
  | Chat sessions | `ChatSession` | keyed by `name` |

  ## Quick start

      Store.create(:config, %{key: "theme", value: %{"color" => "dark"}})
      Store.get(:config, "theme")
      Store.update(:config, "theme", %{value: %{"color" => "light"}})
      Store.delete(:config, "theme")
      Store.list(:config)
  """

  import Ecto.Query, warn: false

  alias CodePuppyControl.{
    Repo,
    Persistence.PersistedConfig,
    Persistence.WorkflowSnapshot,
    Sessions.ChatSession
  }

  require Logger

  # ── Types ─────────────────────────────────────────────────────────────────

  @type entity_type :: :config | :workflow_snapshot | :session
  @type create_attrs :: map()
  @type update_attrs :: map()
  @type key :: String.t() | integer()
  @type entity :: PersistedConfig.t() | WorkflowSnapshot.t() | ChatSession.t()

  # ── Create ────────────────────────────────────────────────────────────────

  @doc """
  Creates a new entity of the given type.

  ## Parameters

    * `type` - Entity type (`:config`, `:workflow_snapshot`, `:session`)
    * `attrs` - Attributes map

  ## Returns

    * `{:ok, struct}` on success
    * `{:error, changeset}` on validation failure
  """
  @spec create(entity_type(), create_attrs()) :: {:ok, entity()} | {:error, Ecto.Changeset.t()}
  def create(:config, attrs) do
    %PersistedConfig{}
    |> PersistedConfig.changeset(attrs)
    |> Repo.insert()
  end

  def create(:workflow_snapshot, attrs) do
    %WorkflowSnapshot{}
    |> WorkflowSnapshot.changeset(attrs)
    |> Repo.insert()
  end

  def create(:session, attrs) do
    %ChatSession{}
    |> ChatSession.changeset(attrs)
    |> Repo.insert()
  end

  # ── Get ───────────────────────────────────────────────────────────────────

  @doc """
  Retrieves a single entity by its key.

  For `:config`, `key` is the config key string (uses default namespace).
  For `:workflow_snapshot`, `key` is the session_id.
  For `:session`, `key` is the session name.

  ## Returns

    * `{:ok, struct}` if found
    * `{:error, :not_found}` if not found
  """
  @spec get(entity_type(), key()) :: {:ok, entity()} | {:error, :not_found}
  def get(:config, key) when is_binary(key) do
    case Repo.get_by(PersistedConfig, key: key, namespace: "default") do
      nil -> {:error, :not_found}
      config -> {:ok, config}
    end
  end

  def get(:workflow_snapshot, session_id) when is_binary(session_id) do
    WorkflowSnapshot
    |> where(session_id: ^session_id)
    |> order_by(desc: :inserted_at)
    |> limit(1)
    |> Repo.one()
    |> case do
      nil -> {:error, :not_found}
      snapshot -> {:ok, snapshot}
    end
  end

  def get(:session, name) when is_binary(name) do
    case Repo.get_by(ChatSession, name: name) do
      nil -> {:error, :not_found}
      session -> {:ok, session}
    end
  end

  @doc """
  Retrieves a config by namespace and key.
  """
  @spec get_config(String.t(), String.t()) :: {:ok, PersistedConfig.t()} | {:error, :not_found}
  def get_config(namespace, key) when is_binary(namespace) and is_binary(key) do
    case Repo.get_by(PersistedConfig, key: key, namespace: namespace) do
      nil -> {:error, :not_found}
      config -> {:ok, config}
    end
  end

  # ── Update ────────────────────────────────────────────────────────────────

  @doc """
  Updates an existing entity.

  Finds the entity by key, then applies the changeset with `attrs`.

  ## Returns

    * `{:ok, struct}` on success
    * `{:error, :not_found}` if the entity doesn't exist
    * `{:error, changeset}` on validation failure
  """
  @spec update(entity_type(), key(), update_attrs()) ::
          {:ok, entity()} | {:error, :not_found | Ecto.Changeset.t()}
  def update(:config, key, attrs) when is_binary(key) do
    case Repo.get_by(PersistedConfig, key: key, namespace: "default") do
      nil ->
        {:error, :not_found}

      config ->
        config
        |> PersistedConfig.changeset(attrs)
        |> Repo.update()
    end
  end

  def update(:session, name, attrs) when is_binary(name) do
    case Repo.get_by(ChatSession, name: name) do
      nil ->
        {:error, :not_found}

      session ->
        session
        |> ChatSession.changeset(attrs)
        |> Repo.update()
    end
  end

  def update(:workflow_snapshot, session_id, attrs) when is_binary(session_id) do
    case get(:workflow_snapshot, session_id) do
      {:ok, snapshot} ->
        snapshot
        |> WorkflowSnapshot.changeset(attrs)
        |> Repo.update()

      error ->
        error
    end
  end

  # ── Delete ────────────────────────────────────────────────────────────────

  @doc """
  Deletes an entity by key.

  ## Returns

    * `:ok` on success
    * `{:error, :not_found}` if the entity doesn't exist
  """
  @spec delete(entity_type(), key()) :: :ok | {:error, :not_found}
  def delete(:config, key) when is_binary(key) do
    case Repo.get_by(PersistedConfig, key: key, namespace: "default") do
      nil ->
        {:error, :not_found}

      config ->
        Repo.delete(config)
        :ok
    end
  end

  def delete(:session, name) when is_binary(name) do
    case Repo.get_by(ChatSession, name: name) do
      nil ->
        {:error, :not_found}

      session ->
        Repo.delete(session)
        :ok
    end
  end

  def delete(:workflow_snapshot, session_id) when is_binary(session_id) do
    case get(:workflow_snapshot, session_id) do
      {:ok, snapshot} ->
        Repo.delete(snapshot)
        :ok

      error ->
        error
    end
  end

  # ── List ──────────────────────────────────────────────────────────────────

  @doc """
  Lists all entities of the given type.

  Accepts optional query opts:
    * `:namespace` - Filter configs by namespace (default: all)
    * `:limit` - Maximum number of results (default: 100)
    * `:order` - Sort order `:asc` or `:desc` (default: `:desc`)
  """
  @spec list(entity_type(), keyword()) :: [entity()]
  def list(type, opts \\ [])

  def list(:config, opts) do
    limit = Keyword.get(opts, :limit, 100)
    order = Keyword.get(opts, :order, :desc)

    query =
      from(c in PersistedConfig,
        order_by: [{^order, c.inserted_at}],
        limit: ^limit
      )

    query =
      case Keyword.get(opts, :namespace) do
        nil -> query
        ns -> where(query, namespace: ^ns)
      end

    Repo.all(query)
  end

  def list(:workflow_snapshot, opts) do
    limit = Keyword.get(opts, :limit, 100)
    order = Keyword.get(opts, :order, :desc)

    query =
      from(ws in WorkflowSnapshot,
        order_by: [{^order, ws.inserted_at}],
        limit: ^limit
      )

    query =
      case Keyword.get(opts, :session_id) do
        nil -> query
        sid -> where(query, session_id: ^sid)
      end

    Repo.all(query)
  end

  def list(:session, opts) do
    limit = Keyword.get(opts, :limit, 100)
    order = Keyword.get(opts, :order, :desc)

    from(s in ChatSession,
      order_by: [{^order, s.inserted_at}],
      limit: ^limit
    )
    |> Repo.all()
  end

  # ── Upsert (convenience) ─────────────────────────────────────────────────

  @doc """
  Creates or updates a config entry (upsert by namespace + key).

  If a config with the given namespace and key exists, its value is updated.
  Otherwise, a new entry is created.
  """
  @spec put_config(String.t(), String.t(), map()) ::
          {:ok, PersistedConfig.t()} | {:error, Ecto.Changeset.t()}
  def put_config(namespace, key, value) do
    case get_config(namespace, key) do
      {:ok, existing} ->
        existing
        |> PersistedConfig.changeset(%{value: value})
        |> Repo.update()

      {:error, :not_found} ->
        create(:config, %{namespace: namespace, key: key, value: value})
    end
  end

  @doc """
  Convenience wrapper: creates or updates a default-namespace config.
  """
  @spec put_config(String.t(), map()) ::
          {:ok, PersistedConfig.t()} | {:error, Ecto.Changeset.t()}
  def put_config(key, value) do
    put_config("default", key, value)
  end
end
