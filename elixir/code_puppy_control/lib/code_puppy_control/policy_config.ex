defmodule CodePuppyControl.PolicyConfig do
  @moduledoc """
  Policy configuration loader for the PolicyEngine.

  Loads policy rules from standard locations:
    - `~/.code_puppy/policy.json`  (user-level, lower priority)
    - `.code_puppy/policy.json`    (project-level, higher priority)

  ## Usage

      alias CodePuppyControl.{PolicyConfig, PolicyEngine}

      # Load rules into the engine
      PolicyConfig.load_policy_rules(PolicyEngine.get_engine())

  ## Rules JSON Format

      {
        "rules": [
          {"tool_name": "read_file",       "decision": "allow",    "priority": 10},
          {"tool_name": "delete_file",     "decision": "deny",     "priority": 20},
          {"tool_name": "run_shell_command","command_pattern": "^git\\b", "decision": "allow", "priority": 15}
        ]
      }

  ## Priority System

  Rules are sorted by priority (highest first). When multiple rules match,
  the highest priority rule wins. Project-level rules are typically loaded
  after user-level rules, allowing them to override with higher priority.

  ## Standard Search Paths

  - **User policy**: `~/.code_puppy/policy.json`
  - **Project policy**: `.code_puppy/policy.json` (current working directory)

  """

  require Logger

  alias CodePuppyControl.PolicyEngine

  # Standard search paths (user then project; project rules win because
  # they are loaded last and can have higher priority values).
  @user_policy_path [System.user_home!(), ".code_puppy", "policy.json"]
  @project_policy_path [File.cwd!(), ".code_puppy", "policy.json"]

  @typedoc "Policy engine process or module reference"
  @type engine :: pid() | atom()

  @typedoc "Optional path override"
  @type path_override :: String.t() | nil

  @doc """
  Loads policy rules from user and project config files into a PolicyEngine.

  ## Arguments

  - `engine` - The PolicyEngine process to populate with rules
  - `opts` - Keyword options:
    - `:user_policy` - Override the user-level policy file path
    - `:project_policy` - Override the project-level policy file path

  ## Returns

  Total number of rules loaded across all files.

  ## Examples

      # Load with default paths
      PolicyConfig.load_policy_rules(engine)

      # Load with custom paths
      PolicyConfig.load_policy_rules(engine,
        user_policy: "/custom/path/policy.json",
        project_policy: "/project/custom/policy.json"
      )

  """
  @spec load_policy_rules(engine(), keyword()) :: non_neg_integer()
  def load_policy_rules(engine, opts \\ []) when is_pid(engine) or is_atom(engine) do
    user_path = Keyword.get(opts, :user_policy, Path.join(@user_policy_path))
    project_path = Keyword.get(opts, :project_policy, Path.join(@project_policy_path))

    total = 0
    total = total + PolicyEngine.load_rules_from_file(user_path, "user")
    total = total + PolicyEngine.load_rules_from_file(project_path, "project")

    Logger.info("Loaded #{total} total policy rules")
    total
  end

  @doc """
  Returns the default user policy file path.

  ## Examples

      iex> PolicyConfig.user_policy_path()
      "/home/username/.code_puppy/policy.json"

  """
  @spec user_policy_path() :: String.t()
  def user_policy_path do
    Path.join(@user_policy_path)
  end

  @doc """
  Returns the default project policy file path.

  ## Examples

      iex> PolicyConfig.project_policy_path()
      "/current/working/dir/.code_puppy/policy.json"

  """
  @spec project_policy_path() :: String.t()
  def project_policy_path do
    Path.join(@project_policy_path)
  end

  @doc """
  Checks if a policy file exists at the given path.

  ## Examples

      iex> PolicyConfig.policy_file_exists?("/path/to/policy.json")
      true

      iex> PolicyConfig.policy_file_exists?(PolicyConfig.user_policy_path())
      false

  """
  @spec policy_file_exists?(String.t()) :: boolean()
  def policy_file_exists?(path) do
    File.exists?(path)
  end

  @doc """
  Creates a sample policy file at the specified path.

  Returns `:ok` if created successfully, or `{:error, reason}` if the
  file already exists or cannot be written.

  ## Examples

      PolicyConfig.create_sample_policy(PolicyConfig.user_policy_path())
      # => :ok

  """
  @spec create_sample_policy(String.t()) :: :ok | {:error, atom() | String.t()}
  def create_sample_policy(path) do
    if File.exists?(path) do
      {:error, "File already exists"}
    else
      dir = Path.dirname(path)

      with :ok <- File.mkdir_p(dir) do
        sample = %{
          "rules" => [
            %{
              "tool_name" => "read_file",
              "decision" => "allow",
              "priority" => 10,
              "source" => "sample"
            },
            %{
              "tool_name" => "delete_file",
              "decision" => "ask_user",
              "priority" => 20,
              "source" => "sample"
            },
            %{
              "tool_name" => "run_shell_command",
              "command_pattern" => "^git\\s+",
              "decision" => "allow",
              "priority" => 15,
              "source" => "sample"
            }
          ]
        }

        case File.write(path, Jason.encode!(sample, pretty: true)) do
          :ok -> :ok
          error -> error
        end
      end
    end
  end

  @doc """
  Returns a map with policy configuration status for debugging.

  Shows which policy files are present and their load status.

  ## Examples

      iex> PolicyConfig.status()
      %{
        user_policy: %{path: "...", exists: true, loaded: 5},
        project_policy: %{path: "...", exists: false, loaded: 0}
      }

  """
  @spec status() :: map()
  def status do
    user_path = user_policy_path()
    project_path = project_policy_path()

    %{
      user_policy: %{
        path: user_path,
        exists: File.exists?(user_path),
        can_read: File.exists?(user_path) and File.regular?(user_path)
      },
      project_policy: %{
        path: project_path,
        exists: File.exists?(project_path),
        can_read: File.exists?(project_path) and File.regular?(project_path)
      },
      engine_running: PolicyEngine.running?()
    }
  end
end
