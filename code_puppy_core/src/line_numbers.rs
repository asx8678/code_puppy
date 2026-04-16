/// Line number formatting with continuation markers for long lines.
///
/// Ports Python's format_content_with_line_numbers() from file_display.py.
/// Provides cat -n style line numbering with continuation markers for
/// lines exceeding the maximum length.

const DEFAULT_MAX_LINE_LENGTH: usize = 5000;
const DEFAULT_LINE_NUMBER_WIDTH: usize = 6;

/// Format content with line numbers (cat -n style).
///
/// For lines exceeding max_line_length, splits into chunks with
/// continuation markers (e.g., "5.1", "5.2", "5.3").
///
/// Args:
///   content: The content to format (lines separated by \n)
///   start_line: Starting line number (1-based)
///   max_line_length: Maximum length before splitting into chunks
///   line_number_width: Width for line number column
///
/// Returns:
///   Formatted content with line numbers and continuation markers
///
/// Example:
///   format_line_numbers("hello\nworld", 1) -> "     1\thello\n     2\tworld"
pub fn format_line_numbers(
    content: &str,
    start_line: usize,
    max_line_length: usize,
    line_number_width: usize,
) -> String {
    // Pre-allocate: estimate output size as ~1.1x input + line number overhead
    let estimated_lines = content.bytes().filter(|&b| b == b'\n').count() + 1;
    let estimated_capacity = content.len() + estimated_lines * (line_number_width + 1);
    let mut result = String::with_capacity(estimated_capacity);

    // Use split('\n') to match Python's behavior (keeps \r from CRLF endings)
    let mut line_idx = 0_usize;
    let lines: Vec<&str> = content.split('\n').collect();

    for line in lines {
        let line_num = start_line + line_idx;
        let line_len = line.len();

        if line_len <= max_line_length {
            // Normal line: just format with line number
            if line_idx > 0 {
                result.push('\n');
            }
            result.push_str(&format_line(line_num, line, line_number_width));
        } else {
            // Long line: split into chunks with continuation markers
            let num_chunks = (line_len + max_line_length - 1) / max_line_length;

            for chunk_idx in 0..num_chunks {
                let start = chunk_idx * max_line_length;
                let end = ((start + max_line_length).min(line_len)).max(start);
                let chunk = &line[start..end];

                if line_idx > 0 || chunk_idx > 0 {
                    result.push('\n');
                }

                if chunk_idx == 0 {
                    // First chunk: regular line number format
                    result.push_str(&format_line(line_num, chunk, line_number_width));
                } else {
                    // Continuation chunk: use marker like "5.1", "5.2" (no space!)
                    let marker = format!("{}.{}", line_num, chunk_idx);
                    // Right-align the marker in the line number width
                    let padding = line_number_width.saturating_sub(marker.len());
                    for _ in 0..padding {
                        result.push(' ');
                    }
                    result.push_str(&marker);
                    result.push('\t');
                    result.push_str(chunk);
                }
            }
        }

        line_idx += 1;
    }

    result
}

/// Format a single line with line number (cat -n style).
fn format_line(line_num: usize, line: &str, width: usize) -> String {
    format!("{:width$}\t{}", line_num, line, width = width)
}

/// Convenience function with default parameters (for Python interop).
pub fn format_line_numbers_default(content: &str, start_line: usize) -> String {
    format_line_numbers(content, start_line, DEFAULT_MAX_LINE_LENGTH, DEFAULT_LINE_NUMBER_WIDTH)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_simple_content() {
        let result = format_line_numbers("hello\nworld", 1, 5000, 6);
        assert_eq!(result, "     1\thello\n     2\tworld");
    }

    #[test]
    fn test_single_line() {
        let result = format_line_numbers("hello", 1, 5000, 6);
        assert_eq!(result, "     1\thello");
    }

    #[test]
    fn test_start_line_offset() {
        let result = format_line_numbers("hello\nworld", 10, 5000, 6);
        assert_eq!(result, "    10\thello\n    11\tworld");
    }

    #[test]
    fn test_empty_content() {
        // Empty content produces one empty line numbered (like Python's split('\n'))
        let result = format_line_numbers("", 1, 5000, 6);
        assert_eq!(result, "     1\t");
    }

    #[test]
    fn test_empty_lines() {
        let result = format_line_numbers("\n\n", 1, 5000, 6);
        assert_eq!(result, "     1\t\n     2\t\n     3\t");
    }

    #[test]
    fn test_trailing_newline() {
        // Content ending with \n should have an empty line numbered
        let result = format_line_numbers("hello\n", 1, 5000, 6);
        assert_eq!(result, "     1\thello\n     2\t");
    }

    #[test]
    fn test_long_line_continuation() {
        // Create a line of 12000 'a' characters
        let long_line = "a".repeat(12000);
        let content = format!("{}", long_line);
        let result = format_line_numbers(&content, 1, 5000, 6);

        // Should have 3 chunks: 5000, 5000, 2000
        assert!(result.contains("     1\t"), "First chunk should have regular line number");
        assert!(result.contains("   1.1\t"), "Second chunk should have .1 continuation marker");
        assert!(result.contains("   1.2\t"), "Third chunk should have .2 continuation marker");

        // Verify the structure
        let lines: Vec<&str> = result.split('\n').collect();
        assert_eq!(lines.len(), 3, "Should have 3 chunks for 12000 chars with 5000 limit");

        // First chunk: regular format
        assert!(lines[0].starts_with("     1\t"));
        assert_eq!(lines[0].len(), 6 + 1 + 5000, "First chunk should be 5000 chars");

        // Second chunk: continuation marker .1
        assert!(lines[1].starts_with("   1.1\t"));

        // Third chunk: continuation marker .2
        assert!(lines[2].starts_with("   1.2\t"));
    }

    #[test]
    fn test_long_line_exact_boundary() {
        // Line exactly at boundary - no continuation needed
        let line = "a".repeat(5000);
        let result = format_line_numbers(&line, 1, 5000, 6);

        // Should have only 1 line, no continuation
        assert!(!result.contains(".1"), "Should not have continuation for exact boundary");
        assert_eq!(result, format!("     1\t{}", line));
    }

    #[test]
    fn test_long_line_just_over_boundary() {
        // Line just over boundary (5001 chars) -> 2 chunks
        let line = "a".repeat(5001);
        let result = format_line_numbers(&line, 1, 5000, 6);

        let lines: Vec<&str> = result.split('\n').collect();
        assert_eq!(lines.len(), 2, "5001 chars with 5000 limit should split into 2 chunks");

        // First chunk regular
        assert!(lines[0].starts_with("     1\t"));
        // Second chunk has continuation
        assert!(lines[1].starts_with("   1.1\t"));
    }

    #[test]
    fn test_multiple_long_lines() {
        let line1 = "x".repeat(7500); // Will be 2 chunks
        let line2 = "y".repeat(6000);  // Will be 2 chunks
        let content = format!("{}\n{}", line1, line2);
        let result = format_line_numbers(&content, 1, 5000, 6);

        let lines: Vec<&str> = result.split('\n').collect();
        assert_eq!(lines.len(), 4, "Two lines with continuations = 4 output lines");

        // Line 1 chunks
        assert!(lines[0].starts_with("     1\t"));
        assert!(lines[1].starts_with("   1.1\t"));

        // Line 2 chunks
        assert!(lines[2].starts_with("     2\t"));
        assert!(lines[3].starts_with("   2.1\t"));
    }

    #[test]
    fn test_continuation_marker_formatting() {
        // Test marker formatting for various line numbers
        let line = "a".repeat(10000); // 2 chunks
        let result = format_line_numbers(&line, 100, 5000, 6);

        // Line 100.1 marker (6 chars width: " 100.1")
        assert!(result.contains(" 100.1\t"), "Continuation marker should be right-aligned");
    }

    #[test]
    fn test_crlf_line_endings() {
        // Windows line endings should be handled like Python's split('\n')
        // The \r stays as part of the line content
        let result = format_line_numbers("hello\r\nworld", 1, 5000, 6);
        // The \r is part of the first line content
        assert!(result.contains("     1\thello\r"), "CR should be preserved from CRLF");
        assert!(result.contains("     2\tworld"));
    }

    #[test]
    fn test_line_with_tabs() {
        let result = format_line_numbers("hello\tworld", 1, 5000, 6);
        assert_eq!(result, "     1\thello\tworld");
    }

    #[test]
    fn test_unicode_content() {
        let result = format_line_numbers("héllo\nwörld", 1, 5000, 6);
        assert_eq!(result, "     1\théllo\n     2\twörld");
    }

    #[test]
    fn test_default_parameters() {
        // Test the convenience function with defaults
        let result = format_line_numbers_default("hello\nworld", 1);
        assert_eq!(result, "     1\thello\n     2\tworld");
    }

    #[test]
    fn test_large_start_line() {
        // Test with large line numbers that might affect alignment
        let result = format_line_numbers("hello", 1000000, 6, 6);
        // 1000000 is 7 digits, but width is 6, so it overflows
        assert!(result.starts_with("1000000\t"), "Large line numbers should not truncate");
    }

    #[test]
    fn test_continuation_with_large_line_number() {
        // Test continuation marker with line 1000
        let line = "a".repeat(7500);
        let result = format_line_numbers(&line, 1000, 5000, 6);

        // "1000.1" is 6 chars, with width 6 it fits exactly
        assert!(result.contains("1000.1\t"));
    }
}
