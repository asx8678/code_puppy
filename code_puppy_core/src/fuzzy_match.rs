/// Fuzzy window matching: sliding-window Jaro-Winkler similarity search.
///
/// Finds the best matching window of lines from a haystack against a needle,
/// using Jaro-Winkler similarity scoring with aggressive pre-filtering for
/// zero-allocation performance.

const JW_THRESHOLD: f64 = 0.6;
const LENGTH_THRESHOLD_RATIO: f64 = 0.5;

/// Result of a fuzzy match operation.
#[derive(Debug, Clone, Copy)]
pub struct MatchResult {
    /// Start line index (0-based, inclusive)
    pub start: usize,
    /// End line index (0-based, exclusive), or None if no match found
    pub end: Option<usize>,
    /// Similarity score (0.0 to 1.0)
    pub score: f64,
}

impl MatchResult {
    /// Returns true if a valid match was found.
    pub fn is_found(&self) -> bool {
        self.end.is_some()
    }
}

/// Find the best matching window in haystack lines for the given needle.
///
/// Uses sliding window with Jaro-Winkler similarity, with prefix-sum pre-filters
/// for O(1) length estimation and aggressive early rejection.
///
/// # Arguments
/// * `haystack_lines` - File content split into lines (without trailing newlines)
/// * `needle` - Target string to find (may contain newlines)
///
/// # Returns
/// * `MatchResult` with best match span and score, or (0, None, 0.0) if no match
pub fn fuzzy_match_window_impl(haystack_lines: &[&str], needle: &str) -> MatchResult {
    if haystack_lines.is_empty() || needle.is_empty() {
        return MatchResult {
            start: 0,
            end: None,
            score: 0.0,
        };
    }

    // Parse needle: strip trailing newlines and split into lines
    let needle_stripped = needle.trim_end_matches('\n');
    let needle_lines: Vec<&str> = needle_stripped.split('\n').collect();

    if needle_lines.is_empty() {
        return MatchResult {
            start: 0,
            end: None,
            score: 0.0,
        };
    }

    let win_size = needle_lines.len();

    // If window is larger than haystack, we can't match
    if win_size > haystack_lines.len() {
        return MatchResult {
            start: 0,
            end: None,
            score: 0.0,
        };
    }

    let needle_len = needle_stripped.len();
    let needle_joined = needle_stripped; // Already joined with \n

    // Pre-extract first line for cheap pre-filtering
    let needle_first_line = needle_lines[0];
    let needle_first_len = needle_first_line.len();
    let needle_first_char = needle_first_line.chars().next();

    // PREFIX-SUM: Build cumulative char counts for O(1) window length estimation
    let haystack_len = haystack_lines.len();
    let mut prefix_sum = vec![0usize; haystack_len + 1];
    for (i, line) in haystack_lines.iter().enumerate() {
        prefix_sum[i + 1] = prefix_sum[i] + line.len();
    }

    let max_start = haystack_len - win_size + 1;
    let mut best_score: f64 = 0.0;
    let mut best_start: usize = 0;
    let mut best_end: Option<usize> = None;

    // Reusable buffer for window joining (to avoid repeated allocations)
    // Pre-allocate with estimated capacity (needle length as heuristic)
    let mut window_buffer = String::with_capacity(needle_len.max(256));

    for i in 0..max_start {
        let window_end = i + win_size;
        let first_line = haystack_lines[i];

        // Pre-filter 1: First-line length check (cheap rejection)
        if needle_first_len > 0 {
            let first_line_len = first_line.len();
            let len_diff = if first_line_len > needle_first_len {
                first_line_len - needle_first_len
            } else {
                needle_first_len - first_line_len
            };
            if len_diff as f64 > needle_first_len as f64 * LENGTH_THRESHOLD_RATIO {
                continue;
            }
        }

        // Pre-filter 2: First character check (ultra-cheap rejection)
        if let Some(nc) = needle_first_char {
            if let Some(fc) = first_line.chars().next() {
                if nc != fc {
                    continue;
                }
            }
        }

        // O(1) window length estimation using prefix sum
        // Window chars = sum of line chars + newlines between lines
        let window_chars = prefix_sum[window_end] - prefix_sum[i] + (win_size.saturating_sub(1));

        // Early skip: if estimated length differs by >50%, skip expensive join
        let len_diff = if window_chars > needle_len {
            window_chars - needle_len
        } else {
            needle_len - window_chars
        };
        let max_len = needle_len.max(window_chars);
        if max_len > 0 && (len_diff as f64) > (max_len as f64) * LENGTH_THRESHOLD_RATIO {
            continue;
        }

        // Build window string (expensive, but only for promising candidates)
        window_buffer.clear();
        for (j, line) in haystack_lines[i..window_end].iter().enumerate() {
            if j > 0 {
                window_buffer.push('\n');
            }
            window_buffer.push_str(line);
        }

        // Compute Jaro-Winkler similarity
        let score = jaro_winkler_similarity(&window_buffer, needle_joined);

        if score > best_score {
            best_score = score;
            best_start = i;
            best_end = Some(window_end);

            // Early exit if we found an exact match
            if score >= 1.0 {
                break;
            }
        }
    }

    // Check threshold
    if best_score < JW_THRESHOLD {
        MatchResult {
            start: 0,
            end: None,
            score: best_score,
        }
    } else {
        MatchResult {
            start: best_start,
            end: best_end,
            score: best_score,
        }
    }
}

/// Jaro-Winkler similarity between two strings (0.0 to 1.0).
///
/// Jaro similarity considers transpositions of characters.
/// Winkler modification boosts scores for prefix matches.
fn jaro_winkler_similarity(s1: &str, s2: &str) -> f64 {
    if s1 == s2 {
        return 1.0;
    }

    let len1 = s1.chars().count();
    let len2 = s2.chars().count();

    if len1 == 0 || len2 == 0 {
        return 0.0;
    }

    // Match distance: characters within this distance are considered matching
    let match_distance = (len1.max(len2) / 2).saturating_sub(1);

    if match_distance == 0 && len1 != len2 {
        // Strings are very short and different lengths, no matches possible
        return 0.0;
    }

    // Track which characters are matched
    let mut s1_matches = vec![false; len1];
    let mut s2_matches = vec![false; len2];

    let s1_chars: Vec<char> = s1.chars().collect();
    let s2_chars: Vec<char> = s2.chars().collect();

    let mut matches = 0usize;
    let mut transpositions = 0usize;

    // First pass: find matches
    for (i, &c1) in s1_chars.iter().enumerate() {
        let start = i.saturating_sub(match_distance);
        let end = (i + match_distance + 1).min(len2);

        for j in start..end {
            if !s2_matches[j] && c1 == s2_chars[j] {
                s1_matches[i] = true;
                s2_matches[j] = true;
                matches += 1;
                break;
            }
        }
    }

    if matches == 0 {
        return 0.0;
    }

    // Second pass: count transpositions
    let mut k = 0usize;
    for i in 0..len1 {
        if s1_matches[i] {
            // Find the next match in s2
            while k < len2 && !s2_matches[k] {
                k += 1;
            }
            if k < len2 && s1_chars[i] != s2_chars[k] {
                transpositions += 1;
            }
            k += 1;
        }
    }

    // Jaro similarity
    let matches_f = matches as f64;
    let len1_f = len1 as f64;
    let len2_f = len2 as f64;
    let transpositions_f = (transpositions / 2) as f64;

    let jaro = (matches_f / len1_f
        + matches_f / len2_f
        + (matches_f - transpositions_f) / matches_f)
        / 3.0;

    // Winkler modification: boost for common prefix (up to 4 chars)
    let mut prefix_len = 0usize;
    for i in 0..len1.min(len2).min(4) {
        if s1_chars[i] == s2_chars[i] {
            prefix_len += 1;
        } else {
            break;
        }
    }

    let winkler_boost = 0.1 * prefix_len as f64 * (1.0 - jaro);

    (jaro + winkler_boost).min(1.0)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_exact_match_returns_1_0() {
        let haystack = vec!["hello", "world", "foo", "bar"];
        let result = fuzzy_match_window_impl(&haystack, "hello\nworld");
        assert!(result.is_found());
        assert_eq!(result.start, 0);
        assert_eq!(result.end, Some(2));
        assert!((result.score - 1.0).abs() < 0.001);
    }

    #[test]
    fn test_fuzzy_match_finds_best_window() {
        let haystack = vec!["def foo():", "    pass", "def bar():", "    return 1"];
        // "def baz():" is close to "def bar():" (typo)
        let result = fuzzy_match_window_impl(&haystack, "def baz():");
        assert!(result.is_found());
        assert_eq!(result.start, 2); // Should match "def bar():"
        assert!(result.score > 0.8);
    }

    #[test]
    fn test_empty_needle_returns_no_match() {
        let haystack = vec!["hello", "world"];
        let result = fuzzy_match_window_impl(&haystack, "");
        assert!(!result.is_found());
        assert_eq!(result.score, 0.0);
    }

    #[test]
    fn test_empty_haystack_returns_no_match() {
        let haystack: Vec<&str> = vec![];
        let result = fuzzy_match_window_impl(&haystack, "hello");
        assert!(!result.is_found());
        assert_eq!(result.score, 0.0);
    }

    #[test]
    fn test_needle_larger_than_haystack() {
        let haystack = vec!["hello"];
        let result = fuzzy_match_window_impl(&haystack, "hello\nworld\nfoo");
        assert!(!result.is_found());
    }

    #[test]
    fn test_single_line_match() {
        let haystack = vec!["apple", "banana", "cherry"];
        let result = fuzzy_match_window_impl(&haystack, "banana");
        assert!(result.is_found());
        assert_eq!(result.start, 1);
        assert_eq!(result.end, Some(2));
    }

    #[test]
    fn test_trailing_newline_stripped() {
        let haystack = vec!["hello", "world"];
        let result = fuzzy_match_window_impl(&haystack, "hello\nworld\n");
        assert!(result.is_found());
        assert_eq!(result.start, 0);
    }

    #[test]
    fn test_no_match_below_threshold() {
        let haystack = vec!["completely", "different", "text", "here"];
        let result = fuzzy_match_window_impl(&haystack, "xyz123-nomatch");
        // Score should be below threshold
        assert!(!result.is_found() || result.score < JW_THRESHOLD);
    }

    #[test]
    fn test_window_size_1() {
        let haystack = vec!["a", "b", "c", "d", "e"];
        let result = fuzzy_match_window_impl(&haystack, "c");
        assert!(result.is_found());
        assert_eq!(result.start, 2);
        assert_eq!(result.end, Some(3));
    }

    #[test]
    fn test_jaro_winkler_identical_strings() {
        assert_eq!(jaro_winkler_similarity("hello", "hello"), 1.0);
        assert_eq!(jaro_winkler_similarity("", ""), 1.0);
    }

    #[test]
    fn test_jaro_winkler_empty_string() {
        assert_eq!(jaro_winkler_similarity("hello", ""), 0.0);
        assert_eq!(jaro_winkler_similarity("", "world"), 0.0);
    }

    #[test]
    fn test_jaro_winkler_typo_tolerance() {
        // Similar strings should have high similarity
        let sim = jaro_winkler_similarity("martha", "marhta");
        assert!(sim > 0.9, "typo tolerance failed: sim = {}", sim);
    }

    #[test]
    fn test_jaro_winkler_prefix_boost() {
        // "code" prefix should get boost
        let sim1 = jaro_winkler_similarity("code_puppy", "code_kitten");
        let sim2 = jaro_winkler_similarity("puppy_code", "kitten_code");
        // Prefix match should score higher
        assert!(sim1 > sim2, "prefix boost failed: {} vs {}", sim1, sim2);
    }

    #[test]
    fn test_jaro_winkler_completely_different() {
        let sim = jaro_winkler_similarity("abcdef", "ghijkl");
        assert!(sim < 0.5, "completely different strings should have low sim: {}", sim);
    }

    #[test]
    fn test_large_window_performance() {
        // This test ensures the function handles larger inputs reasonably
        let haystack: Vec<String> = (0..100).map(|i| format!("line number {} with some content", i)).collect();
        let haystack_refs: Vec<&str> = haystack.iter().map(|s| s.as_str()).collect();

        // Find a 10-line window
        let target = haystack_refs[45..55].join("\n");
        let result = fuzzy_match_window_impl(&haystack_refs, &target);

        assert!(result.is_found());
        assert_eq!(result.start, 45);
        assert_eq!(result.end, Some(55));
        assert!((result.score - 1.0).abs() < 0.001);
    }

    #[test]
    fn test_unicode_handling() {
        let haystack = vec!["こんにちは", "世界", "foo"];
        let result = fuzzy_match_window_impl(&haystack, "こんにちは\n世界");
        assert!(result.is_found());
        assert_eq!(result.start, 0);
    }

    #[test]
    fn test_edge_case_whitespace_lines() {
        let haystack = vec!["", "  ", "   ", "content"];
        let result = fuzzy_match_window_impl(&haystack, "  ");
        assert!(result.is_found());
        assert_eq!(result.start, 1);
    }
}
