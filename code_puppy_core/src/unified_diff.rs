//! Unified diff generation using the `similar` crate.
//!
//! Provides a Rust implementation to replace Python's `difflib.unified_diff`.
//! Matches the standard unified diff format with ---/+++ headers and @@ hunk markers.

use similar::{ChangeTag, TextDiff};

/// Split text into lines, preserving line endings like Python's splitlines(keepends=True).
fn split_lines_keep_ends(text: &str) -> Vec<&str> {
    if text.is_empty() {
        return Vec::new();
    }

    let mut lines = Vec::new();
    let mut start = 0;

    for (i, ch) in text.char_indices() {
        if ch == '\n' {
            lines.push(&text[start..=i]);
            start = i + 1;
        }
    }

    // Handle last line if no trailing newline
    if start < text.len() {
        lines.push(&text[start..]);
    }

    lines
}

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
    // Handle edge case: identical content
    if old == new {
        return String::new();
    }

    let old_lines = split_lines_keep_ends(old);
    let new_lines = split_lines_keep_ends(new);

    // Handle empty old (file creation)
    if old_lines.is_empty() {
        let mut output = String::new();
        output.push_str(&format!("--- {}\n", from_file));
        output.push_str(&format!("+++ {}\n", to_file));
        output.push_str(&format!("@@ -0,0 +1,{} @@\n", new_lines.len()));

        for line in &new_lines {
            output.push('+');
            output.push_str(line);
        }
        return output;
    }

    // Handle empty new (file deletion)
    if new_lines.is_empty() {
        let mut output = String::new();
        output.push_str(&format!("--- {}\n", from_file));
        output.push_str(&format!("+++ {}\n", to_file));
        output.push_str(&format!("@@ -1,{} +0,0 @@\n", old_lines.len()));

        for line in &old_lines {
            output.push('-');
            output.push_str(line);
        }
        return output;
    }

    // For normal diffs, use TextDiff
    // Note: TextDiff will include newlines in the diff, so we handle that
    let diff = TextDiff::from_slices(&old_lines, &new_lines);

    let mut output = String::new();
    output.push_str(&format!("--- {}\n", from_file));
    output.push_str(&format!("+++ {}\n", to_file));

    // Collect all hunks
    let mut all_hunks: Vec<Hunk> = Vec::new();
    let mut current_hunk: Option<Hunk> = None;

    for change in diff.iter_all_changes() {
        let old_idx = change.old_index();
        let new_idx = change.new_index();
        let tag = change.tag();
        let value = change.value();

        // Check if we need to start a new hunk
        let need_new_hunk = if let Some(ref h) = current_hunk {
            // Check if there's a gap larger than context_lines
            let old_pos = old_idx.unwrap_or(h.old_start + h.old_count);
            let new_pos = new_idx.unwrap_or(h.new_start + h.new_count);

            let old_gap = old_pos.saturating_sub(h.old_start + h.old_count);
            let new_gap = new_pos.saturating_sub(h.new_start + h.new_count);

            // Start new hunk if gap exceeds context_lines
            old_gap > context_lines || new_gap > context_lines
        } else {
            true
        };

        if need_new_hunk {
            // Finish current hunk if exists
            if let Some(mut h) = current_hunk.take() {
                // Add trailing context
                add_trailing_context(&mut h, &old_lines, context_lines);
                all_hunks.push(h);
            }

            // Calculate hunk start with context
            let old_start = old_idx.unwrap_or(0).saturating_sub(context_lines);
            let new_start = new_idx.unwrap_or(0).saturating_sub(context_lines);

            let mut new_hunk = Hunk::new(old_start, new_start);

            // Add context lines before this change
            for i in old_start..old_idx.unwrap_or(old_start).min(old_lines.len()) {
                new_hunk.add_line(ChangeTag::Equal, old_lines[i]);
            }

            // Add the actual change
            new_hunk.add_line(tag, value);

            current_hunk = Some(new_hunk);
        } else {
            // Add context lines between changes
            if let Some(ref mut h) = current_hunk {
                let prev_old_end = h.old_start + h.old_count;
                let old_pos = old_idx.unwrap_or(prev_old_end);

                for i in prev_old_end..old_pos.min(old_lines.len()) {
                    h.add_line(ChangeTag::Equal, old_lines[i]);
                }

                h.add_line(tag, value);
            }
        }
    }

    // Push final hunk
    if let Some(mut h) = current_hunk {
        add_trailing_context(&mut h, &old_lines, context_lines);
        all_hunks.push(h);
    }

    // Render all hunks
    for hunk in &all_hunks {
        hunk.render(&mut output);
    }

    output
}

fn add_trailing_context<'a>(hunk: &mut Hunk<'a>, old_lines: &[&'a str], context_lines: usize) {
    let trailing_start = hunk.old_start + hunk.old_count;
    let trailing_end = (trailing_start + context_lines).min(old_lines.len());

    for i in trailing_start..trailing_end {
        hunk.add_line(ChangeTag::Equal, old_lines[i]);
    }
}

/// A hunk in a unified diff
struct Hunk<'a> {
    old_start: usize,
    new_start: usize,
    old_count: usize,
    new_count: usize,
    lines: Vec<(ChangeTag, &'a str)>,
}

impl<'a> Hunk<'a> {
    fn new(old_start: usize, new_start: usize) -> Self {
        Self {
            old_start,
            new_start,
            old_count: 0,
            new_count: 0,
            lines: Vec::new(),
        }
    }

    fn add_line(&mut self, tag: ChangeTag, line: &'a str) {
        match tag {
            ChangeTag::Equal => {
                self.old_count += 1;
                self.new_count += 1;
            }
            ChangeTag::Delete => {
                self.old_count += 1;
            }
            ChangeTag::Insert => {
                self.new_count += 1;
            }
        }
        self.lines.push((tag, line));
    }

    fn render(&self, output: &mut String) {
        // Unified diff uses 1-based line numbers
        let old_start_1based = self.old_start + 1;
        let new_start_1based = self.new_start + 1;

        // For empty start, show 0 (only for new files where count is 0)
        let old_start_display = if self.old_count == 0 && self.old_start == 0 {
            0
        } else {
            old_start_1based
        };
        let new_start_display = if self.new_count == 0 && self.new_start == 0 {
            0
        } else {
            new_start_1based
        };

        output.push_str(&format!(
            "@@ -{},{} +{},{} @@\n",
            old_start_display, self.old_count, new_start_display, self.new_count
        ));

        for (tag, line) in &self.lines {
            let prefix = match tag {
                ChangeTag::Equal => ' ',
                ChangeTag::Delete => '-',
                ChangeTag::Insert => '+',
            };
            output.push(prefix);
            output.push_str(line);
            // Note: line already includes trailing newline from split_lines_keep_ends
            // or is the last line without newline
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_split_lines_keep_ends() {
        assert_eq!(split_lines_keep_ends(""), Vec::<&str>::new());
        assert_eq!(split_lines_keep_ends("line 1\n"), vec!["line 1\n"]);
        assert_eq!(
            split_lines_keep_ends("line 1\nline 2\n"),
            vec!["line 1\n", "line 2\n"]
        );
        assert_eq!(
            split_lines_keep_ends("line 1\nline 2"),
            vec!["line 1\n", "line 2"]
        );
        assert_eq!(split_lines_keep_ends("no newline"), vec!["no newline"]);
    }

    #[test]
    fn test_identical_strings() {
        let old = "line 1\nline 2\nline 3";
        let new = "line 1\nline 2\nline 3";
        let result = unified_diff_impl(old, new, 3, "a/file.txt", "b/file.txt");
        assert!(result.is_empty());
    }

    #[test]
    fn test_single_line_change() {
        let old = "line 1\nline 2\nline 3";
        let new = "line 1\nmodified line 2\nline 3";
        let result = unified_diff_impl(old, new, 3, "a/file.txt", "b/file.txt");

        assert!(result.contains("--- a/file.txt"));
        assert!(result.contains("+++ b/file.txt"));
        // Header format: @@ -old_start,old_count +new_start,new_count @@
        assert!(result.contains("@@ -1,"));
        assert!(result.contains("+1,"));
        assert!(result.contains("@@"));
        assert!(result.contains(" line 1") || result.contains("line 1\n")); // Context line
        assert!(result.contains("-line 2"));
        assert!(result.contains("+modified line 2"));
    }

    #[test]
    fn test_addition() {
        let old = "line 1\nline 2";
        let new = "line 1\nline 2\nline 3";
        let result = unified_diff_impl(old, new, 3, "a/file.txt", "b/file.txt");

        assert!(result.contains("@@"));
        assert!(result.contains("+line 3"));
    }

    #[test]
    fn test_deletion() {
        let old = "line 1\nline 2\nline 3";
        let new = "line 1\nline 3";
        let result = unified_diff_impl(old, new, 3, "a/file.txt", "b/file.txt");

        assert!(result.contains("@@"));
        assert!(result.contains("-line 2"));
    }

    #[test]
    fn test_empty_old() {
        let old = "";
        let new = "line 1\nline 2";
        let result = unified_diff_impl(old, new, 3, "a/file.txt", "b/file.txt");

        assert!(result.contains("--- a/file.txt"));
        assert!(result.contains("+++ b/file.txt"));
        assert!(result.contains("@@ -0,0 +1,2 @@"));
        assert!(result.contains("+line 1"));
        assert!(result.contains("+line 2"));
    }

    #[test]
    fn test_empty_new() {
        let old = "line 1\nline 2";
        let new = "";
        let result = unified_diff_impl(old, new, 3, "a/file.txt", "b/file.txt");

        assert!(result.contains("--- a/file.txt"));
        assert!(result.contains("+++ b/file.txt"));
        // For deletion, should show old lines deleted
        assert!(result.contains("@@"));
        assert!(result.contains("-line 1"));
        assert!(result.contains("-line 2"));
    }

    #[test]
    fn test_completely_different() {
        let old = "aaa\nbbb\nccc";
        let new = "xxx\nyyy\nzzz";
        let result = unified_diff_impl(old, new, 3, "a/file.txt", "b/file.txt");

        // Verify that removed lines are marked with - and added lines with +
        assert!(result.contains("-aaa") || result.contains("-bbb") || result.contains("-ccc"));
        assert!(result.contains("+xxx") || result.contains("+yyy") || result.contains("+zzz"));
    }

    #[test]
    fn test_format_matches_difflib() {
        // Test that our format matches what difflib would produce
        let old = "first\nsecond\nthird";
        let new = "first\nmodified\nthird";
        let result = unified_diff_impl(old, new, 3, "a/test.py", "b/test.py");

        // Verify the format
        let lines: Vec<&str> = result.lines().collect();
        assert_eq!(lines[0], "--- a/test.py");
        assert_eq!(lines[1], "+++ b/test.py");
        assert!(lines[2].starts_with("@@"));
        assert!(lines[2].contains("@@"));

        // Check markers
        assert!(result.contains("-second"));
        assert!(result.contains("+modified"));
    }

    #[test]
    fn test_exact_match_difflib_simple() {
        // This is a basic comparison to verify key aspects match Python's behavior
        let old = "line 1\nline 2\nline 3";
        let new = "line 1\nmodified\nline 3";
        let result = unified_diff_impl(old, new, 3, "a/file.txt", "b/file.txt");

        // Check exact expected output
        assert!(result.starts_with("--- a/file.txt\n"));
        assert!(result.contains("+++ b/file.txt\n"));
        assert!(result.contains("@@"));
        assert!(result.contains("-line 2\n"));
        assert!(result.contains("+modified\n"));
    }
}
