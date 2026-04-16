defmodule CodePuppyControl.FileOps.Security do
  @moduledoc """
  Security module for file operations.

  Handles sensitive path detection and path validation to prevent
  access to SSH keys, cloud credentials, and other system secrets.
  """

  @sensitive_dir_prefixes MapSet.new([
                            Path.join(System.user_home!(), ".ssh"),
                            Path.join(System.user_home!(), ".aws"),
                            Path.join(System.user_home!(), ".gnupg"),
                            Path.join(System.user_home!(), ".gcp"),
                            Path.join(System.user_home!(), ".config/gcloud"),
                            Path.join(System.user_home!(), ".azure"),
                            Path.join(System.user_home!(), ".kube"),
                            Path.join(System.user_home!(), ".docker"),
                            "/etc",
                            "/private/etc",
                            "/dev",
                            "/root",
                            "/proc",
                            "/var/log"
                          ])

  @sensitive_exact_files MapSet.new([
                           Path.join(System.user_home!(), ".netrc"),
                           Path.join(System.user_home!(), ".pgpass"),
                           Path.join(System.user_home!(), ".my.cnf"),
                           Path.join(System.user_home!(), ".env"),
                           Path.join(System.user_home!(), ".bash_history"),
                           Path.join(System.user_home!(), ".npmrc"),
                           Path.join(System.user_home!(), ".pypirc"),
                           Path.join(System.user_home!(), ".gitconfig"),
                           "/etc/shadow",
                           "/etc/sudoers",
                           "/etc/passwd",
                           "/etc/master.passwd",
                           "/private/etc/shadow",
                           "/private/etc/sudoers",
                           "/private/etc/passwd",
                           "/private/etc/master.passwd"
                         ])

  @sensitive_filenames MapSet.new([".env"])

  @allowed_env_patterns MapSet.new([".env.example", ".env.sample", ".env.template"])

  @sensitive_extensions MapSet.new([
                          ".pem",
                          ".key",
                          ".p12",
                          ".pfx",
                          ".keystore"
                        ])

  @spec sensitive_path?(String.t()) :: boolean()
  def sensitive_path?(file_path) when is_binary(file_path) do
    if file_path == "" do
      false
    else
      expanded = Path.expand(file_path)

      # Check directory prefixes
      sensitive_dir_prefix =
        Enum.any?(@sensitive_dir_prefixes, fn prefix ->
          String.starts_with?(expanded, prefix <> "/") or expanded == prefix
        end)

      # Check exact-match files
      sensitive_exact = MapSet.member?(@sensitive_exact_files, expanded)

      # Check sensitive filenames
      basename = Path.basename(expanded)
      basename_lower = String.downcase(basename)

      sensitive_filename =
        cond do
          # Exact match for .env file (not .env.example, etc.)
          basename == ".env" ->
            true

          # .env.* files are sensitive except allowed patterns
          String.starts_with?(basename_lower, ".env.") ->
            not MapSet.member?(@allowed_env_patterns, basename_lower)

          # Other filenames in the sensitive list
          MapSet.member?(@sensitive_filenames, basename) ->
            true

          true ->
            false
        end

      # Check for private key files by extension
      ext = Path.extname(expanded) |> String.downcase()
      sensitive_ext = MapSet.member?(@sensitive_extensions, ext)

      sensitive_dir_prefix or sensitive_exact or sensitive_filename or sensitive_ext
    end
  end

  def sensitive_path?(_), do: false

  @spec validate_path(String.t(), atom()) :: {:ok, String.t()} | {:error, String.t()}
  def validate_path(file_path, operation) when is_binary(file_path) do
    cond do
      file_path == "" ->
        {:error, "File path cannot be empty"}

      String.contains?(file_path, "\0") ->
        {:error, "File path contains null byte"}

      sensitive_path?(file_path) ->
        {:error,
         "Access to sensitive path blocked (#{operation}): SSH keys, cloud credentials, and system secrets are never accessible."}

      true ->
        {:ok, Path.expand(file_path)}
    end
  end

  def validate_path(_, _), do: {:error, "Invalid file path"}
end
