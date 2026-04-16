//! Line number formatting with continuation markers for long lines.
//!
//! Ports Python's format_content_with_line_numbers() from file_display.py.
//! Provides cat -n style line numbering with continuation markers for
//! lines exceeding the maximum length.
//!
//! IMPORTANT: Uses character-based chunking to match Python's behavior.
//! Python's len(line) counts characters, not bytes. For multi-byte
//! UTF-8 content, this matters - £ is 1 char in Python but 2 bytes.

/// Find the byte position of the Nth character in a string.
/// Used for character-based chunking that matches Python's len() behavior.
fn char_byte_offset(s: &str, char_idx: usize) -> usize {
    s.char_indices()
        .nth(char_idx)
        .map(|(byte_idx, _)| byte_idx)
        .unwrap_or(s.len())
}

/// Format content with line numbers (cat -n style).
///
/// For lines exceeding max_line_length (character count, not bytes),
/// splits into chunks with continuation markers (e.g., "5.1", "5.2", "5.3").
///
/// Args:
///   content: The content to format (lines separated by \n)
///   start_line: Starting line number (1-based)
///   max_line_length: Maximum character count before splitting into chunks
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
    // Using enumerate() instead of manual counter (clippy fix)
    for (line_idx, line) in content.split('\n').enumerate() {
        let line_num = start_line + line_idx;
        // CHARACTER-BASED length (not bytes) to match Python's len(line)
        let char_len = line.chars().count();

        if char_len <= max_line_length {
            // Normal line: just format with line number
            if line_idx > 0 {
                result.push('\n');
            }
            result.push_str(&format_line(line_num, line, line_number_width));
        } else {
            // Long line: split into chunks with continuation markers
            // CHARACTER-BASED chunking to match Python
            let num_chunks = char_len.div_ceil(max_line_length);

            for chunk_idx in 0..num_chunks {
                // Calculate character indices (not byte indices)
                let start_char = chunk_idx * max_line_length;
                let end_char = ((chunk_idx + 1) * max_line_length).min(char_len);

                // Convert char indices to byte positions for slicing
                let start_byte = char_byte_offset(line, start_char);
                let end_byte = char_byte_offset(line, end_char);
                let chunk = &line[start_byte..end_byte];

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
    }

    result
}

/// Format a single line with line number (cat -n style).
fn format_line(line_num: usize, line: &str, width: usize) -> String {
    format!("{:width$}\t{}", line_num, line, width = width)
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
        // Test with explicit defaults (5000 for max_line_length, 6 for width)
        let result = format_line_numbers("hello\nworld", 1, 5000, 6);
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

    #[test]
    fn test_long_line_with_multibyte_utf8() {
        // CHARACTER-BASED chunking: é counts as 1 character (like Python's len())
        // 5001 é chars = 5001 chars > 5000 limit → should trigger continuation
        let line = "é".repeat(5001);
        let result = format_line_numbers(&line, 1, 5000, 6);

        // Verify basic structure
        assert!(result.contains("     1\t"), "First chunk should have regular line number");
        assert!(result.contains("   1.1\t"), "Should have continuation marker for overflow");
    }

    #[test]
    fn test_multibyte_at_chunk_boundary() {
        // CHARACTER-BASED chunking: £ counts as 1 character
        // 3000 £ chars = 3000 chars < 5000 limit → NO continuation (unlike byte-based)
        // Even though 3000 £ = 6000 bytes in UTF-8, Python counts chars, not bytes
        let line = "£".repeat(3000);
        let result = format_line_numbers(&line, 1, 5000, 6);

        // Should NOT have continuation marker (character-based, not byte-based)
        assert!(
            !result.contains("   1.1\t"),
            "3000 £ chars (3000 < 5000 limit) should NOT have continuation - char-based chunking"
        );
        assert!(result.contains("     1\t"));

        // Verify all characters are valid UTF-8
        for ch in result.chars() {
            let _ = ch;
        }
    }

    #[test]
    fn test_multibyte_chars_chunked_by_char_count() {
        // 3000 '£' chars = 3000 chars < 5000 limit → no continuation
        // Python: len('£' * 3000) == 3000, so no chunking needed
        let line = "£".repeat(3000);
        let result = format_line_numbers(&line, 1, 5000, 6);

        // Single line, no continuation marker
        assert!(
            !result.contains(".1\t"),
            "Should not chunk by bytes (3000 chars < 5000 limit)"
        );
        assert_eq!(result.matches('\n').count(), 0, "Single line should have no newlines");
        assert!(result.starts_with("     1\t"));
        assert!(result.ends_with("£".repeat(3000).as_str()));
    }

    #[test]
    fn test_multibyte_chars_over_char_limit() {
        // 5001 '£' chars > 5000 limit → should get continuation
        let line = "£".repeat(5001);
        let result = format_line_numbers(&line, 1, 5000, 6);

        assert!(result.contains("   1.1\t"), "Should chunk at 5000 chars");

        // Verify chunks are correctly sized
        let lines: Vec<&str> = result.split('\n').collect();
        assert_eq!(lines.len(), 2, "5001 chars should split into 2 chunks");

        // First chunk: 5000 chars
        let first_chunk_content = lines[0].strip_prefix("     1\t").unwrap();
        assert_eq!(first_chunk_content.chars().count(), 5000);

        // Second chunk: 1 char
        let second_chunk_content = lines[1].strip_prefix("   1.1\t").unwrap();
        assert_eq!(second_chunk_content.chars().count(), 1);
    }

    #[test]
    fn test_mixed_multibyte_and_ascii() {
        // Mix of ASCII and multibyte: all count as 1 char each
        // 2500 é + 2501 a = 5001 chars > 5000 limit
        let line = format!("{}{}", "é".repeat(2500), "a".repeat(2501));
        let result = format_line_numbers(&line, 1, 5000, 6);

        assert!(result.contains("   1.1\t"), "Mixed content should chunk at char boundary");

        let lines: Vec<&str> = result.split('\n').collect();
        assert_eq!(lines.len(), 2);

        // First chunk ends with é chars (characters 2496-2500 are é)
        let first_chunk = lines[0].strip_prefix("     1\t").unwrap();
        assert_eq!(first_chunk.chars().count(), 5000);
        // Last char of first chunk should be 'a' (position 5000)
        assert_eq!(first_chunk.chars().last().unwrap(), 'a');
    }

    #[test]
    fn test_char_count_parity_with_python() {
        // Verify character-based length matches Python len()
        // Python: len('£' * 1000) == 1000 (chars, not bytes)
        // Rust (byte-based): '£'.repeat(1000).len() == 2000 (bytes)
        // Rust (char-based): '£'.repeat(1000).chars().count() == 1000 (chars) ✓

        let pound_line = "£".repeat(1000);
        let byte_len = pound_line.len();
        let char_len = pound_line.chars().count();

        assert_eq!(byte_len, 2000, "£ is 2 bytes in UTF-8");
        assert_eq!(char_len, 1000, "But Python/Rust char count is 1000");

        // At limit 1500, byte-based would chunk (2000 > 1500)
        // Char-based should NOT chunk (1000 < 1500)
        let result = format_line_numbers(&pound_line, 1, 1500, 6);
        assert!(
            !result.contains(".1\t"),
            "1000 chars at 1500 limit should NOT chunk"
        );
    }
}
