import Config

if config_env() == :prod do
  secret_key_base =
    System.get_env("SECRET_KEY_BASE") ||
      raise """
      environment variable SECRET_KEY_BASE is missing.
      You can generate one by calling: mix phx.gen.secret
      """

  config :code_puppy_control, CodePuppyControlWeb.Endpoint,
    secret_key_base: secret_key_base

  database_path =
    System.get_env("DATABASE_PATH") ||
      raise """
      environment variable DATABASE_PATH is missing.
      """

  config :code_puppy_control, CodePuppyControl.Repo,
    database: database_path

  config :code_puppy_control, :python_worker_script,
    System.get_env("PYTHON_WORKER_SCRIPT") ||
      raise """
      environment variable PYTHON_WORKER_SCRIPT is missing.
      This should point to the Python worker entry point.
      """
end
