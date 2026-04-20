defmodule CodePuppyControl.Tools.UniversalConstructor.CreateAction do
  @moduledoc """
  Handles the create action for Universal Constructor tools.

  This module extracts the complex tool creation logic from the main
  UniversalConstructor module to improve maintainability and reduce file size.
  """

  require Logger

  alias CodePuppyControl.Config.Isolation
  alias CodePuppyControl.Config.Paths
  alias CodePuppyControl.Tools.UniversalConstructor.Models
  alias CodePuppyControl.Tools.UniversalConstructor.Registry
  alias CodePuppyControl.Tools.UniversalConstructor.Validator

  @doc """
  Handles the create action for creating a new UC tool.

  ## Parameters
    * `tool_name` - Optional name hint for the tool
    * `elixir_code` - The Elixir source code for the tool
    * `description` - Optional description for the tool

  ## Returns
    A map with action, success, error, and create_result keys.
  """
  @spec execute(String.t() | nil, String.t() | nil, String.t() | nil) :: map()
  def execute(tool_name, elixir_code, description) do
    with {:ok, _} <- validate_input(elixir_code),
         {:ok, validation} <- validate_syntax(elixir_code),
         {:ok, func_result} <- validate_has_functions(validation),
         {:ok, {final_name, final_namespace}} <-
           determine_tool_name_and_namespace(elixir_code, tool_name, func_result),
         {:ok, _} <- validate_has_name(final_name),
         {:ok, file_path, file_dir} <- build_file_path(final_namespace, final_name),
         {:ok, final_code, _warnings} <-
           prepare_final_code(elixir_code, final_name, final_namespace, description, func_result) do
      write_tool_file(file_dir, file_path, final_code, final_name, final_namespace)
    else
      {:error, reason} -> build_output("create", false, reason)
    end
  end

  # ============================================================================
  # Input Validation
  # ============================================================================

  defp validate_input(nil), do: {:error, "elixir_code is required for create action"}
  defp validate_input(""), do: {:error, "elixir_code is required for create action"}
  defp validate_input(code) when is_binary(code), do: {:ok, code}

  defp validate_syntax(elixir_code) do
    validation = Validator.validate_syntax(elixir_code)

    if validation.valid do
      {:ok, validation}
    else
      {:error, "Syntax error in code: #{Enum.join(validation.errors, "; ")}"}
    end
  end

  defp validate_has_functions(validation) do
    if validation.functions == [] do
      {:error, "No functions found in code - tool must have at least one function"}
    else
      {:ok, validation}
    end
  end

  # ============================================================================
  # Tool Name & Namespace Resolution
  # ============================================================================

  defp determine_tool_name_and_namespace(elixir_code, tool_name, func_result) do
    existing_meta = Validator.extract_uc_tool_meta(elixir_code)

    case existing_meta do
      {:ok, meta} when is_map(meta) ->
        # Use name from existing meta
        name = meta[:name] || tool_name || "unnamed"
        namespace = meta[:namespace] || ""
        {:ok, {name, namespace}}

      _ ->
        # Parse namespace from tool_name if provided (e.g., "api.weather")
        parse_tool_name(tool_name, func_result)
    end
  end

  defp parse_tool_name(nil, func_result) do
    # Use first function name as tool name
    func = hd(func_result.functions)
    {:ok, {to_string(func.name), ""}}
  end

  defp parse_tool_name(tool_name, _func_result) do
    parts = String.split(tool_name, ".")

    if length(parts) > 1 do
      {:ok, {List.last(parts), Enum.join(Enum.drop(parts, -1), ".")}}
    else
      {:ok, {tool_name, ""}}
    end
  end

  defp validate_has_name(final_name) when final_name == "" or is_nil(final_name) do
    {:error, "Could not determine tool name - provide tool_name or include @uc_tool in code"}
  end

  defp validate_has_name(final_name), do: {:ok, final_name}

  # ============================================================================
  # File Path Construction
  # ============================================================================

  defp build_file_path(final_namespace, final_name) do
    tools_dir = Paths.universal_constructor_dir()

    file_dir =
      if final_namespace != "" do
        Path.join(tools_dir, String.replace(final_namespace, ".", "/"))
      else
        tools_dir
      end

    file_path = Path.join(file_dir, "#{final_name}.ex")

    {:ok, file_path, file_dir}
  end

  # ============================================================================
  # Code Preparation
  # ============================================================================

  defp prepare_final_code(elixir_code, final_name, final_namespace, description, _func_result) do
    safety = Validator.check_safety(elixir_code)

    validation_warnings =
      if not safety.safe, do: ["Potentially dangerous patterns detected"], else: []

    # Handle existing meta vs generating new meta
    case Validator.extract_uc_tool_meta(elixir_code) do
      {:ok, meta} when is_map(meta) ->
        meta_errors = Validator.validate_tool_meta(meta)

        if meta_errors != [] do
          {:error, "Invalid TOOL_META: #{Enum.join(meta_errors, "; ")}"}
        else
          {:ok, elixir_code, validation_warnings}
        end

      _ ->
        # Generate @uc_tool and prepend
        final_description = description || "Tool: #{final_name}"
        now = DateTime.utc_now() |> DateTime.to_iso8601()

        meta_map =
          inspect(
            %{
              name: final_name,
              namespace: final_namespace,
              description: final_description,
              enabled: true,
              version: "1.0.0",
              author: "user",
              created_at: now
            },
            pretty: true
          )

        meta_str = "@uc_tool #{meta_map}\n\n"
        {:ok, meta_str <> elixir_code, ["@uc_tool was auto-generated" | validation_warnings]}
    end
  end

  # ============================================================================
  # File Writing & Registry Update
  # ============================================================================

  defp write_tool_file(file_dir, file_path, final_code, final_name, final_namespace) do
    try do
      Isolation.safe_mkdir_p!(file_dir)
      Isolation.safe_write!(file_path, final_code)

      # Read back for preview
      preview = Validator.generate_preview(final_code)

      # Reload registry
      _count = Registry.reload()

      full_name = Models.full_name(final_namespace, final_name)

      create_output =
        Models.uc_create_output(
          success: true,
          tool_name: full_name,
          source_path: file_path,
          preview: preview,
          validation_warnings: []
        )

      build_output("create", true, nil, create_result: create_output)
    rescue
      e in File.Error ->
        build_output("create", false, "Failed to write tool file: #{Exception.message(e)}")
    end
  end

  # ============================================================================
  # Output Building
  # ============================================================================

  defp build_output(action, success, error, extra \\ []) do
    base = %{
      action: to_string(action),
      success: success,
      error: error,
      list_result: nil,
      call_result: nil,
      create_result: nil,
      update_result: nil,
      info_result: nil
    }

    Enum.reduce(extra, base, fn {key, value}, acc ->
      Map.put(acc, key, value)
    end)
  end
end
