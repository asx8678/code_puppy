/// Hashline NIF: Elixir-native line anchoring via per-line content hashes.
///
/// Each line gets a 2-char anchor encoded with NIBBLE_STR so the LLM can
/// reference lines precisely. Compatible with oh-my-pi's hashline format
/// and the Python/Rust reference implementations.

// Custom nibble encoding (matches omp's NIBBLE_STR)
const NIBBLE_STR: &[u8; 16] = b"ZPMQVRWSNKTXJBYH";

// ---------------------------------------------------------------------------
// Core implementation (pure Rust, no NIF concerns)
// ---------------------------------------------------------------------------

/// Core hash computation logic (non-NIF, callable from other Rust code).
fn compute_hash_core(idx: u32, line: &str) -> String {
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

// ---------------------------------------------------------------------------
// NIF wrappers
// ---------------------------------------------------------------------------

/// Compute a 2-character hash anchor for a single line.
///
/// Algorithm:
/// 1. Strip trailing whitespace / `\r`
/// 2. If line has no alphanumeric chars => seed = idx, else seed = 0
/// 3. xxHash32 of cleaned line bytes with that seed
/// 4. Take lowest byte of hash
/// 5. Encode via NIBBLE_STR: high nibble char + low nibble char
#[rustler::nif]
fn compute_line_hash(idx: u32, line: String) -> String {
    compute_hash_core(idx, &line)
}

/// Format text with hashline prefixes.
///
/// Each line becomes `{line_number}#{hash}:{original_line}`.
/// `start_line` is 1-based by convention.
#[rustler::nif]
fn format_hashlines(text: String, start_line: u32) -> String {
    text.split('\n')
        .enumerate()
        .map(|(i, line)| {
            let line_num = start_line + i as u32;
            let hash = compute_hash_core(line_num, line);
            format!("{}#{}:{}", line_num, hash, line)
        })
        .collect::<Vec<_>>()
        .join("\n")
}

/// Strip hashline prefixes from text, returning plain content.
///
/// Lines matching `^\d+#[A-Z]{2}:` have the prefix removed.
/// Other lines pass through unchanged.
#[rustler::nif]
fn strip_hashline_prefixes(text: String) -> String {
    text.split('\n')
        .map(|line| strip_one_hashline_prefix(line))
        .collect::<Vec<_>>()
        .join("\n")
}

/// Validate that a stored hash anchor still matches the current line content.
#[rustler::nif]
fn validate_hashline_anchor(idx: u32, line: String, expected_hash: String) -> bool {
    compute_hash_core(idx, &line) == expected_hash
}

rustler::init!("Elixir.CodePuppyControl.HashlineNif");
