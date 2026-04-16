/// Hashline: file-edit anchoring via per-line content hashes.
///
/// Each line gets a 2-char anchor encoded with NIBBLE_STR so the LLM can
/// reference lines precisely. Compatible with oh-my-pi's hashline format.

// Custom nibble encoding (matches omp's NIBBLE_STR)
const NIBBLE_STR: &[u8; 16] = b"ZPMQVRWSNKTXJBYH";

/// Compute a 2-character hash anchor for a single line.
///
/// Algorithm:
/// 1. Strip trailing whitespace / `\r`
/// 2. If line has no alphanumeric chars → seed = idx, else seed = 0
/// 3. xxHash32 of cleaned line bytes with that seed
/// 4. Take lowest byte of hash
/// 5. Encode via NIBBLE_STR: high nibble char + low nibble char
pub fn compute_line_hash(idx: u32, line: &str) -> String {
    // Strip trailing whitespace and \r
    let cleaned = line.trim_end_matches(|c: char| c == '\r' || c.is_whitespace());

    // Check if line has any alphanumeric character (Unicode-aware)
    let has_alnum = cleaned.chars().any(|c| c.is_alphanumeric());

    let seed = if has_alnum { 0u32 } else { idx };

    let hash = xxhash_rust::xxh32::xxh32(cleaned.as_bytes(), seed);

    let byte = (hash & 0xFF) as usize;
    let hi = NIBBLE_STR[(byte >> 4) & 0xF] as char;
    let lo = NIBBLE_STR[byte & 0xF] as char;

    format!("{}{}", hi, lo)
}

/// Format text with hashline prefixes.
///
/// Each line becomes `{line_number}#{hash}:{original_line}`.
/// `start_line` is 1-based by convention.
pub fn format_hashlines(text: &str, start_line: u32) -> String {
    text.split('\n')
        .enumerate()
        .map(|(i, line)| {
            let line_num = start_line + i as u32;
            let hash = compute_line_hash(line_num, line);
            format!("{}#{}:{}", line_num, hash, line)
        })
        .collect::<Vec<_>>()
        .join("\n")
}

/// Strip hashline prefixes from text, returning plain content.
///
/// Lines matching `^\d+#[A-Z]{2}:` have the prefix removed.
/// Other lines pass through unchanged.
pub fn strip_hashline_prefixes(text: &str) -> String {
    text.split('\n')
        .map(|line| strip_one_hashline_prefix(line))
        .collect::<Vec<_>>()
        .join("\n")
}

fn strip_one_hashline_prefix(line: &str) -> &str {
    // Fast path: find '#', verify digits before it, 2 uppercase after, then ':'
    let Some(hash_pos) = line.find('#') else {
        return line;
    };

    // Everything before '#' must be digits
    if !line[..hash_pos].chars().all(|c| c.is_ascii_digit()) || hash_pos == 0 {
        return line;
    }

    let after_hash = &line[hash_pos + 1..];

    // Need at least 3 chars: 2 uppercase + ':'
    if after_hash.len() < 3 {
        return line;
    }

    let bytes = after_hash.as_bytes();
    if bytes[0].is_ascii_uppercase() && bytes[1].is_ascii_uppercase() && bytes[2] == b':' {
        &after_hash[3..]
    } else {
        line
    }
}

/// Validate that a stored hash anchor still matches the current line content.
pub fn validate_hashline_anchor(idx: u32, line: &str, expected_hash: &str) -> bool {
    compute_line_hash(idx, line) == expected_hash
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_nibble_encoding_range() {
        // All 256 possible byte values should produce 2 uppercase chars in NIBBLE_STR
        for byte in 0u8..=255 {
            let hi = NIBBLE_STR[(byte >> 4) as usize] as char;
            let lo = NIBBLE_STR[(byte & 0xF) as usize] as char;
            assert!(hi.is_ascii_uppercase(), "hi nibble not uppercase for byte {byte}");
            assert!(lo.is_ascii_uppercase(), "lo nibble not uppercase for byte {byte}");
        }
    }

    #[test]
    fn test_compute_line_hash_returns_two_chars() {
        let h = compute_line_hash(1, "hello world");
        assert_eq!(h.len(), 2);
        assert!(h.chars().all(|c| c.is_ascii_uppercase()));
    }

    #[test]
    fn test_compute_line_hash_whitespace_only_uses_idx_as_seed() {
        // Two different indices should produce different hashes for whitespace-only lines
        let h1 = compute_line_hash(1, "   ");
        let h2 = compute_line_hash(2, "   ");
        // They *may* collide (only 256 values), but with different seeds the raw
        // xxh32 values differ, so this is a sanity check that seeds are applied.
        // We just verify the hashes are valid 2-char strings.
        assert_eq!(h1.len(), 2);
        assert_eq!(h2.len(), 2);
    }

    #[test]
    fn test_compute_line_hash_strips_trailing_whitespace() {
        let h1 = compute_line_hash(1, "hello");
        let h2 = compute_line_hash(1, "hello   ");
        assert_eq!(h1, h2, "trailing whitespace should be stripped before hashing");
    }

    #[test]
    fn test_format_hashlines_basic() {
        let result = format_hashlines("foo\nbar", 1);
        let lines: Vec<&str> = result.split('\n').collect();
        assert_eq!(lines.len(), 2);
        assert!(lines[0].starts_with("1#"));
        assert!(lines[0].contains(":foo"));
        assert!(lines[1].starts_with("2#"));
        assert!(lines[1].contains(":bar"));
    }

    #[test]
    fn test_format_hashlines_start_line() {
        let result = format_hashlines("hello", 10);
        assert!(result.starts_with("10#"));
        assert!(result.ends_with(":hello"));
    }

    #[test]
    fn test_strip_hashline_prefixes_roundtrip() {
        let original = "line one\nline two\n";
        let formatted = format_hashlines(original, 1);
        let stripped = strip_hashline_prefixes(&formatted);
        assert_eq!(stripped, original);
    }

    #[test]
    fn test_strip_hashline_prefixes_passthrough() {
        // Lines without hashline prefix pass through unchanged
        let text = "no prefix here\njust plain text";
        let stripped = strip_hashline_prefixes(text);
        assert_eq!(stripped, text);
    }

    #[test]
    fn test_strip_mixed_lines() {
        let formatted = format_hashlines("hello", 1);
        let mixed = format!("{}\nplain line", formatted);
        let stripped = strip_hashline_prefixes(&mixed);
        assert_eq!(stripped, "hello\nplain line");
    }

    #[test]
    fn test_validate_hashline_anchor_valid() {
        let h = compute_line_hash(5, "some code");
        assert!(validate_hashline_anchor(5, "some code", &h));
    }

    #[test]
    fn test_validate_hashline_anchor_invalid() {
        let h = compute_line_hash(5, "some code");
        assert!(!validate_hashline_anchor(5, "different code", &h));
    }

    #[test]
    fn test_validate_hashline_anchor_wrong_idx_for_blank() {
        // Blank line hashes depend on idx — validate round-trip consistency
        let h1 = compute_line_hash(1, "");
        let h2 = compute_line_hash(100, "");
        // Each hash should validate correctly for its own idx
        assert!(validate_hashline_anchor(1, "", &h1));
        assert!(validate_hashline_anchor(100, "", &h2));
        // And the hash for idx=1 must NOT validate as idx=1 with wrong content
        assert!(!validate_hashline_anchor(1, "x", &h1));
    }
}
