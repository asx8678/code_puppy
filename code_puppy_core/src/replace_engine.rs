//! Replace engine: combines exact/fuzzy matching with unified diff generation.
//!
//! Implements a robust replacement engine that:
//! 1. Tries exact match first (fast path)
//! 2. Falls back to fuzzy Jaro-Winkler matching if exact fails
//! 3. Slices lines for fuzzy matches, string replace for exact
//! 4. Generates unified diff of changes

use crate::fuzzy_match::fuzzy_match_window_impl;
use crate::unified_diff::unified_diff_impl;

/// Threshold for fuzzy matching (stricter than the 0.6 in fuzzy_match.rs)
const FUZZY_THRESHOLD: f64 = 0.95;

/// Result of a replace operation.
#[derive(Debug, Clone)]
pub struct ReplaceResult {
    /// The modified content after all replacements
    pub modified: String,
    /// Unified diff between original and modified
    pub diff: String,
    /// Whether all replacements succeeded
    pub success: bool,
    /// Error message if fuzzy match failed (JW < 0.95)
    pub error: Option<String>,
    /// The JW score if fuzzy match was attempted
    pub jw_score: Option<f64>,
}

/// Apply a list of replacements to content, with exact and fuzzy matching.
///
/// For each (old_str, new_str) pair:
/// 1. Try exact match first - if found, replace first occurrence only
/// 2. If exact fails, use fuzzy window matching (JW threshold: 0.95)
/// 3. If fuzzy fails (score < 0.95), return error result
///
/// After all replacements, generates a unified diff.
///
/// # Arguments
/// * `content` - Original content string
/// * `replacements` - Vector of (old_str, new_str) pairs to apply
///
/// # Returns
/// * `ReplaceResult` with modified content, diff, and success/error info
pub fn replace_in_content(content: &str, replacements: &[(String, String)]) -> ReplaceResult {
    // Handle empty inputs early
    if replacements.is_empty() {
        return ReplaceResult {
            modified: content.to_string(),
            diff: String::new(),
            success: true,
            error: None,
            jw_score: None,
        };
    }

    let original = content.to_string();
    let mut modified = content.to_string();
    let mut modified_lines: Option<Vec<String>> = None;
    let mut last_jw_score: Option<f64> = None;

    for (old_str, new_str) in replacements {
        // Skip empty old_str - nothing to match
        if old_str.is_empty() {
            continue;
        }

        // Fast path: exact match - replace first occurrence only
        if modified.contains(old_str) {
            modified = modified.replacen(old_str, new_str, 1);
            // Invalidate cached lines since content changed
            modified_lines = None;
            continue;
        }

        // Lazy initialization of cached lines for fuzzy matching
        if modified_lines.is_none() {
            modified_lines = Some(modified.split('\n').map(String::from).collect());
        }

        let lines = modified_lines.as_ref().unwrap();
        let lines_refs: Vec<&str> = lines.iter().map(|s| s.as_str()).collect();

        // Fuzzy match: find best window in the current content
        let match_result = fuzzy_match_window_impl(&lines_refs, old_str);

        last_jw_score = Some(match_result.score);

        // Check if match meets the stricter threshold
        if match_result.score < FUZZY_THRESHOLD || match_result.end.is_none() {
            return ReplaceResult {
                modified: original.clone(),
                diff: String::new(),
                success: false,
                error: Some(format!(
                    "No suitable match in content (JW {:.3} < {:.2})",
                    match_result.score, FUZZY_THRESHOLD
                )),
                jw_score: Some(match_result.score),
            };
        }

        let start = match_result.start;
        let end = match_result.end.unwrap();

        // Parse new_str into lines for splicing
        let new_lines: Vec<String> = new_str.trim_end_matches('\n').split('\n').map(String::from).collect();

        // Splice replacement into lines: replace [start, end) with new_lines
        let lines_mut = modified_lines.as_mut().unwrap();
        lines_mut.splice(start..end, new_lines);

        // Rebuild the string immediately so subsequent exact matches work
        modified = lines_mut.join("\n");
        if original.ends_with('\n') && !modified.ends_with('\n') {
            modified.push('\n');
        }
    }

    // Rebuild modified string from cached lines if needed (fuzzy path)
    if modified.is_empty() && modified_lines.is_some() {
        let lines = modified_lines.unwrap();
        modified = lines.join("\n");
        // Preserve trailing newline if original had one
        if original.ends_with('\n') && !modified.ends_with('\n') {
            modified.push('\n');
        }
    }

    // Generate unified diff
    let diff = if modified == original {
        String::new()
    } else {
        unified_diff_impl(&original, &modified, 3, "original", "modified")
    };

    ReplaceResult {
        modified,
        diff,
        success: true,
        error: None,
        jw_score: last_jw_score,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_exact_match_single() {
        let content = "hello world\nfoo bar\n";
        let replacements = vec![("world".to_string(), "universe".to_string())];
        let result = replace_in_content(content, &replacements);

        assert!(result.success);
        assert_eq!(result.modified, "hello universe\nfoo bar\n");
        assert!(!result.diff.is_empty());
        assert!(result.error.is_none());
        assert!(result.jw_score.is_none()); // Exact match, no fuzzy
    }

    #[test]
    fn test_exact_match_multiple() {
        let content = "hello world\nfoo bar\nbaz qux\n";
        let replacements = vec![
            ("world".to_string(), "universe".to_string()),
            ("foo".to_string(), "FOO".to_string()),
        ];
        let result = replace_in_content(content, &replacements);

        assert!(result.success);
        assert_eq!(result.modified, "hello universe\nFOO bar\nbaz qux\n");
        assert!(!result.diff.is_empty());
    }

    #[test]
    fn test_exact_match_only_first_occurrence() {
        let content = "foo foo foo\n";
        let replacements = vec![("foo".to_string(), "bar".to_string())];
        let result = replace_in_content(content, &replacements);

        assert!(result.success);
        // replacen with n=1 only replaces first occurrence
        assert_eq!(result.modified, "bar foo foo\n");
    }

    #[test]
    fn test_fuzzy_match_close_but_not_exact() {
        // "def baz():" is close to "def bar():" (typo)
        let content = "def foo():\n    pass\ndef bar():\n    return 1\n";
        let replacements = vec![("def baz():".to_string(), "def qux():".to_string())];
        let result = replace_in_content(content, &replacements);

        assert!(result.success);
        assert!(result.jw_score.unwrap() >= FUZZY_THRESHOLD);
        assert!(result.modified.contains("def qux():"));
        assert!(!result.modified.contains("def bar():"));
    }

    #[test]
    fn test_fuzzy_match_fails_below_threshold() {
        let content = "completely different text\nthat has no similarity\n";
        let replacements = vec![("xyz123-nomatch".to_string(), "replacement".to_string())];
        let result = replace_in_content(content, &replacements);

        assert!(!result.success);
        assert!(result.error.is_some());
        assert!(result.error.as_ref().unwrap().contains("JW"));
        assert!(result.error.as_ref().unwrap().contains("0.95"));
        // Content should be unchanged
        assert_eq!(result.modified, content);
        assert!(result.diff.is_empty());
    }

    #[test]
    fn test_empty_replacements() {
        let content = "hello world\n";
        let replacements: Vec<(String, String)> = vec![];
        let result = replace_in_content(content, &replacements);

        assert!(result.success);
        assert_eq!(result.modified, content);
        assert!(result.diff.is_empty());
    }

    #[test]
    fn test_empty_content() {
        let content = "";
        let replacements = vec![("foo".to_string(), "bar".to_string())];
        let result = replace_in_content(content, &replacements);

        assert!(!result.success); // Can't find "foo" in empty content
        assert!(result.error.is_some());
    }

    #[test]
    fn test_trailing_newline_preserved() {
        let content = "line1\nline2\n"; // Has trailing newline
        let replacements = vec![("line1".to_string(), "LINE1".to_string())];
        let result = replace_in_content(content, &replacements);

        assert!(result.success);
        assert!(result.modified.ends_with('\n'), "Trailing newline should be preserved");
        assert_eq!(result.modified, "LINE1\nline2\n");
    }

    #[test]
    fn test_no_trailing_newline_added_if_not_present() {
        let content = "line1\nline2"; // No trailing newline
        let replacements = vec![("line1".to_string(), "LINE1".to_string())];
        let result = replace_in_content(content, &replacements);

        assert!(result.success);
        assert!(!result.modified.ends_with('\n'), "Should not add trailing newline");
        assert_eq!(result.modified, "LINE1\nline2");
    }

    #[test]
    fn test_empty_old_str_skipped() {
        let content = "hello world\n";
        let replacements = vec![
            ("".to_string(), "ignored".to_string()), // Empty old_str should be skipped
            ("world".to_string(), "universe".to_string()),
        ];
        let result = replace_in_content(content, &replacements);

        assert!(result.success);
        assert_eq!(result.modified, "hello universe\n");
    }

    #[test]
    fn test_fuzzy_multiline_replacement() {
        let content = "def func():\n    x = 1\n    return x\n";
        // Exact match - content has the exact multiline needle
        let replacements = vec![(
            "    x = 1\n    return x".to_string(),
            "    y = 2\n    return y".to_string(),
        )];
        let result = replace_in_content(content, &replacements);

        assert!(result.success);
        // Exact match means no JW score (fast path taken)
        assert!(result.jw_score.is_none());
        assert!(result.modified.contains("y = 2"));
    }

    #[test]
    fn test_mixed_exact_and_fuzzy() {
        let content = "hello world\ndef bar():\n    pass\n";
        let replacements = vec![
            ("world".to_string(), "universe".to_string()), // Exact
            ("def baz():".to_string(), "def qux():".to_string()), // Fuzzy (typo)
        ];
        let result = replace_in_content(content, &replacements);

        assert!(result.success);
        assert!(result.modified.contains("hello universe"));
        assert!(result.modified.contains("def qux():"));
        assert!(!result.modified.contains("def bar():"));
    }

    #[test]
    fn test_fuzzy_then_exact() {
        // Test that after a fuzzy match succeeds, we rebuild the string
        // so that subsequent operations work on the new content
        let content = "hello world\ndef baz():\n    pass\n";
        let replacements = vec![
            ("def bar():".to_string(), "def qux():".to_string()), // Fuzzy match "def baz():"
            ("world".to_string(), "universe".to_string()),        // Exact match on original first line
        ];
        let result = replace_in_content(content, &replacements);

        assert!(result.success);
        // Both replacements should have been applied
        assert!(result.modified.contains("hello universe"));
        assert!(result.modified.contains("def qux():"));
        assert!(!result.modified.contains("def baz():"));
    }

    #[test]
    fn test_diff_format() {
        let content = "line1\nline2\nline3\n";
        let replacements = vec![("line2".to_string(), "MODIFIED".to_string())];
        let result = replace_in_content(content, &replacements);

        assert!(result.success);
        assert!(result.diff.contains("--- original"));
        assert!(result.diff.contains("+++ modified"));
        assert!(result.diff.contains("-line2"));
        assert!(result.diff.contains("+MODIFIED"));
        assert!(result.diff.contains("@@"));
    }

    #[test]
    fn test_no_changes_when_replacement_same() {
        let content = "hello world\n";
        let replacements = vec![("world".to_string(), "world".to_string())];
        let result = replace_in_content(content, &replacements);

        assert!(result.success);
        assert_eq!(result.modified, content);
        assert!(result.diff.is_empty()); // No diff when content unchanged
    }

    #[test]
    fn test_fuzzy_single_line() {
        // "def bar():" vs "def baz():" is similar but not exact
        let content = "def foo():\n    pass\ndef bar():\n    return 1\n";
        let replacements = vec![("def baz():".to_string(), "def qux():".to_string())];
        let result = replace_in_content(content, &replacements);

        assert!(result.success);
        assert!(result.jw_score.unwrap() >= FUZZY_THRESHOLD);
        assert!(result.modified.contains("def qux():"));
        assert!(!result.modified.contains("def bar():"));
    }
}
