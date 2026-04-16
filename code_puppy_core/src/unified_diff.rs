//! Unified diff generation using the `similar` crate.
//!
//! Provides a Rust implementation to replace Python's `difflib.unified_diff`.
//! Matches the standard unified diff format with ---/+++ headers and @@ hunk markers.

use similar::TextDiff;

/// Generate a unified diff between two texts.
///
/// # Arguments
/// * `old` - Original text content
/// * `new` - New text content
/// * `context_lines` - Number of context lines to include around each change
/// * `from_file` - Label for the original file (shown in --- header)
/// * `to_file` - Label for the new file (shown in +++ header)
///
/// # Returns
/// A string containing the unified diff output.
pub fn unified_diff_impl(
    old: &str,
    new: &str,
    context_lines: usize,
    from_file: &str,
    to_file: &str,
) -> String {
    if old == new {
        return String::new();
    }
    let diff = TextDiff::from_lines(old, new);
    diff.unified_diff()
        .context_radius(context_lines)
        .header(from_file, to_file)
        .missing_newline_hint(false)
        .to_string()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_identical_strings() {
        let old = "line 1\nline 2\nline 3";
        let new = "line 1\nline 2\nline 3";
        let result = unified_diff_impl(old, new, 3, "a/file.txt", "b/file.txt");
        assert_eq!(result, "");
    }

    #[test]
    fn test_single_line_change_exact() {
        let old = "line 1\nline 2\nline 3\n";
        let new = "line 1\nmodified line 2\nline 3\n";
        let result = unified_diff_impl(old, new, 3, "a/file.txt", "b/file.txt");

        // Note: similar's UnifiedDiff uses space prefix for context lines (standard format)
        let expected = concat!(
            "--- a/file.txt\n",
            "+++ b/file.txt\n",
            "@@ -1,3 +1,3 @@\n",
            " line 1\n",
            "-line 2\n",
            "+modified line 2\n",
            " line 3\n"
        );
        assert_eq!(result, expected);
    }

    #[test]
    fn test_addition_exact() {
        let old = "line 1\nline 2\n";
        let new = "line 1\nline 2\nline 3\n";
        let result = unified_diff_impl(old, new, 3, "a/file.txt", "b/file.txt");

        // Note: similar's UnifiedDiff uses space prefix for context lines (standard format)
        let expected = concat!(
            "--- a/file.txt\n",
            "+++ b/file.txt\n",
            "@@ -1,2 +1,3 @@\n",
            " line 1\n",
            " line 2\n",
            "+line 3\n"
        );
        assert_eq!(result, expected);
    }

    #[test]
    fn test_deletion_exact() {
        let old = "line 1\nline 2\nline 3\n";
        let new = "line 1\nline 3\n";
        let result = unified_diff_impl(old, new, 3, "a/file.txt", "b/file.txt");

        // Note: similar's UnifiedDiff uses space prefix for context lines (standard format)
        let expected = concat!(
            "--- a/file.txt\n",
            "+++ b/file.txt\n",
            "@@ -1,3 +1,2 @@\n",
            " line 1\n",
            "-line 2\n",
            " line 3\n"
        );
        assert_eq!(result, expected);
    }

    #[test]
    fn test_empty_old_exact() {
        let old = "";
        let new = "line 1\nline 2\n";
        let result = unified_diff_impl(old, new, 3, "a/file.txt", "b/file.txt");

        let expected = concat!(
            "--- a/file.txt\n",
            "+++ b/file.txt\n",
            "@@ -0,0 +1,2 @@\n",
            "+line 1\n",
            "+line 2\n"
        );
        assert_eq!(result, expected);
    }

    #[test]
    fn test_empty_new_exact() {
        let old = "line 1\nline 2\n";
        let new = "";
        let result = unified_diff_impl(old, new, 3, "a/file.txt", "b/file.txt");

        let expected = concat!(
            "--- a/file.txt\n",
            "+++ b/file.txt\n",
            "@@ -1,2 +0,0 @@\n",
            "-line 1\n",
            "-line 2\n"
        );
        assert_eq!(result, expected);
    }

    #[test]
    fn test_completely_different_exact() {
        let old = "aaa\nbbb\nccc\n";
        let new = "xxx\nyyy\nzzz\n";
        let result = unified_diff_impl(old, new, 3, "a/file.txt", "b/file.txt");

        // When everything changes, there are no context lines (no space prefix on any line)
        let expected = concat!(
            "--- a/file.txt\n",
            "+++ b/file.txt\n",
            "@@ -1,3 +1,3 @@\n",
            "-aaa\n",
            "-bbb\n",
            "-ccc\n",
            "+xxx\n",
            "+yyy\n",
            "+zzz\n"
        );
        assert_eq!(result, expected);
    }

    /// Multi-hunk test: changes separated by > 2*context lines MUST produce separate hunks.
    /// With context=3, changes at line 3 and line 17 have a gap of 14 lines,
    /// which is > 6 (2*context), so they should be in separate hunks.
    #[test]
    fn test_multi_hunk_produces_separate_hunks() {
        // Lines 1-20, we'll change line 3 and line 17
        let old = "line 1\nline 2\nline 3\nline 4\nline 5\n\
                   line 6\nline 7\nline 8\nline 9\nline 10\n\
                   line 11\nline 12\nline 13\nline 14\nline 15\n\
                   line 16\nline 17\nline 18\nline 19\nline 20\n";
        let new = "line 1\nline 2\nMODIFIED 3\nline 4\nline 5\n\
                   line 6\nline 7\nline 8\nline 9\nline 10\n\
                   line 11\nline 12\nline 13\nline 14\nline 15\n\
                   line 16\nMODIFIED 17\nline 18\nline 19\nline 20\n";

        let result = unified_diff_impl(old, new, 3, "a/file.txt", "b/file.txt");

        // Count hunk headers - should be exactly 2
        let hunk_count = result.matches("@@ -").count();
        assert_eq!(
            hunk_count, 2,
            "Expected 2 separate hunks, but got {}. Output:\n{}",
            hunk_count, result
        );

        // Verify first hunk contains the first change
        assert!(result.contains("-line 3\n"), "First hunk should show removal of line 3");
        assert!(
            result.contains("+MODIFIED 3\n"),
            "First hunk should show addition of MODIFIED 3"
        );

        // Verify second hunk contains the second change
        assert!(result.contains("-line 17\n"), "Second hunk should show removal of line 17");
        assert!(
            result.contains("+MODIFIED 17\n"),
            "Second hunk should show addition of MODIFIED 17"
        );
    }

    /// Parity test: verify output matches expected unified diff format exactly
    /// This matches Python's difflib.unified_diff output
    #[test]
    fn test_parity_with_difflib() {
        // Standard unified diff format test case
        let old = "first\nsecond\nthird\n";
        let new = "first\nmodified\nthird\n";
        let result = unified_diff_impl(old, new, 3, "a/test.py", "b/test.py");

        // Note: similar's UnifiedDiff uses space prefix for context lines (standard format)
        // The " first" and " third" lines have 1 leading space (context line prefix)
        let expected = concat!(
            "--- a/test.py\n",
            "+++ b/test.py\n",
            "@@ -1,3 +1,3 @@\n",
            " first\n",
            "-second\n",
            "+modified\n",
            " third\n"
        );

        assert_eq!(
            result, expected,
            "Output should match standard unified diff format exactly"
        );
    }

    /// Test that context lines parameter is respected
    #[test]
    fn test_context_lines_parameter() {
        let old = "a\nb\nc\nd\ne\n";
        let new = "a\nB\nc\nd\ne\n";

        // With context=1, only 1 line of context around change
        let result = unified_diff_impl(old, new, 1, "old", "new");

        // Should have @@ -2,1 +2,1 @@ (only 1 context line before and after)
        // and only show lines b/B with 1 context line on each side
        assert!(result.contains("@@"));
        assert!(result.contains("-b\n"));
        assert!(result.contains("+B\n"));
    }
}
