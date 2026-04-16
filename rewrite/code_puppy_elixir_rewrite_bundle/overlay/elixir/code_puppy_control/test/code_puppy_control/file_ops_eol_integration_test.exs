defmodule CodePuppyControl.FileOpsEOLIntegrationTest do
  use ExUnit.Case, async: true

  alias CodePuppyControl.FileOps

  @bom <<0xEF, 0xBB, 0xBF>>

  setup do
    dir =
      Path.join(
        System.tmp_dir!(),
        "file_ops_eol_test_#{:erlang.unique_integer([:positive])}"
      )

    File.rm_rf!(dir)
    File.mkdir_p!(dir)

    on_exit(fn ->
      File.rm_rf!(dir)
    end)

    %{test_dir: dir}
  end

  test "read_file normalizes CRLF and strips a leading BOM", %{test_dir: dir} do
    path = Path.join(dir, "windows.txt")
    File.write!(path, @bom <> "line1\r\nline2")

    assert {:ok, result} = FileOps.read_file(path)
    assert result.content == "line1\nline2"
    assert result.error == nil
    refute String.starts_with?(result.content, @bom)
  end

  test "line slicing happens after normalization", %{test_dir: dir} do
    path = Path.join(dir, "range.txt")
    File.write!(path, "row1\r\nrow2\r\nrow3")

    assert {:ok, result} = FileOps.read_file(path, start_line: 2, num_lines: 2)
    assert result.content == "row2\nrow3"
    assert result.truncated == true
  end
end
