//! Content preparation: text detection, EOL normalization, and BOM stripping.
//!
//! Multi-pass implementation using SIMD-accelerated scanning (memchr)
//! for maximum throughput.

use pyo3::prelude::*;

// UTF-8 BOM bytes: EF BB BF
const BOM: &[u8] = b"\xef\xbb\xbf";

/// Result of preparing content: text detection, BOM/CRLF handling.
#[pyclass(frozen)]
#[derive(Debug, PartialEq)]
pub struct PreparedContent {
    /// The processed content as a String (BOM stripped, CRLF normalized if text)
    #[pyo3(get)]
    pub content: String,
    /// True if the content appears to be text (no NUL bytes, sufficient printable ratio)
    #[pyo3(get)]
    pub is_text: bool,
    /// True if a UTF-8 BOM was present and stripped
    #[pyo3(get)]
    pub had_bom: bool,
    /// True if CRLF sequences were detected (and normalized if is_text)
    #[pyo3(get)]
    pub had_crlf: bool,
}

/// Detect if byte slice appears to be text.
///
/// Criteria:
/// 1. No NUL bytes (\x00) anywhere — strongest binary signal
/// 2. At least 90% of bytes are ≥0x20 or common whitespace (\t, \n, \r)
///
/// Empty content is considered text.
pub fn looks_textish(raw: &[u8]) -> bool {
    if raw.is_empty() {
        return true;
    }

    // Check for NUL bytes
    if memchr::memchr(0, raw).is_some() {
        return false;
    }

    // Count printable bytes
    let total = raw.len();
    let printable = raw
        .iter()
        .filter(|&&b| b >= 0x20 || b == b'\t' || b == b'\n' || b == b'\r')
        .count();

    let ratio = printable as f64 / total as f64;
    ratio >= 0.90
}

/// Normalize CRLF to LF in a string.
///
/// First converts CRLF (\r\n) to LF (\n), then converts any remaining orphan CRs.
/// This is only called when content is known to be text.
pub fn normalize_eol(text: &str) -> String {
    if !text.contains('\r') {
        return text.to_string();
    }

    // CRLF -> LF first, then orphan CR -> LF
    let result = text.replace("\r\n", "\n");
    result.replace('\r', "\n")
}

/// Strip UTF-8 BOM from beginning of string if present.
///
/// Returns (content_without_bom, had_bom).
pub fn strip_bom(text: &str) -> (String, bool) {
    if text.starts_with('\u{FEFF}') {
        // U+FEFF is 3 bytes in UTF-8 (EF BB BF), so we use char_indices
        // to correctly skip the first char
        let mut chars = text.chars();
        chars.next(); // Skip the BOM
        (chars.as_str().to_string(), true)
    } else {
        (text.to_string(), false)
    }
}

/// Strip UTF-8 BOM from beginning of byte slice if present.
///
/// Returns (content_without_bom, had_bom).
fn strip_bom_bytes(raw: &[u8]) -> (&[u8], bool) {
    if raw.starts_with(BOM) {
        (&raw[BOM.len()..], true)
    } else {
        (raw, false)
    }
}

/// Prepare content: single-pass detection and normalization.
///
/// This is the main entry point. It scans the raw bytes once to:
/// 1. Detect and strip BOM
/// 2. Detect NUL bytes (binary check)
/// 3. Detect CRLF sequences
/// 4. If text: normalize CRLF to LF
///
/// Returns a PreparedContent struct with all detection results.
pub fn prepare_content(raw: &[u8]) -> PreparedContent {
    // Handle empty input
    if raw.is_empty() {
        return PreparedContent {
            content: String::new(),
            is_text: true,
            had_bom: false,
            had_crlf: false,
        };
    }

    // Strip BOM first (if present)
    let (content_bytes, had_bom) = strip_bom_bytes(raw);

    // Check for NUL bytes (binary detection)
    let has_nul = memchr::memchr(0, content_bytes).is_some();

    // Check for CRLF sequences
    let has_crlf = memchr::memmem::find(content_bytes, b"\r\n").is_some();

    // If NUL found, it's binary - return as-is (but still decode for the string)
    if has_nul {
        // For binary, we still need to return a String. Use lossy UTF-8 conversion.
        // Use content_bytes (BOM already stripped) to maintain invariant: had_bom == true means BOM is NOT in content
        let content = String::from_utf8_lossy(content_bytes).into_owned();
        return PreparedContent {
            content,
            is_text: false,
            had_bom,
            had_crlf: has_crlf,
        };
    }

    // It's text - check printable ratio for extra safety
    let is_text = looks_textish(content_bytes);

    if !is_text {
        // Binary-like but no NUL - still treat as binary
        // Use content_bytes (BOM already stripped) to maintain invariant: had_bom == true means BOM is NOT in content
        let content = String::from_utf8_lossy(content_bytes).into_owned();
        return PreparedContent {
            content,
            is_text: false,
            had_bom,
            had_crlf: has_crlf,
        };
    }

    // It's confirmed text - decode and normalize
    let text = String::from_utf8_lossy(content_bytes);

    // Normalize line endings: CRLF -> LF, then orphan CR -> LF
    // Do this unconditionally since orphan CRs should also be normalized
    let content = normalize_eol(&text);

    PreparedContent {
        content,
        is_text: true,
        had_bom,
        had_crlf: has_crlf,
    }
}

// ── Python-exposed functions ───────────────────────────────────────────────

#[pyfunction]
fn looks_textish_py(raw: &[u8]) -> bool {
    looks_textish(raw)
}

#[pyfunction]
fn normalize_eol_py(text: &str) -> String {
    normalize_eol(text)
}

#[pyfunction]
fn strip_bom_py(text: &str) -> (String, bool) {
    strip_bom(text)
}

#[pyfunction]
fn prepare_content_py(raw: &[u8]) -> PreparedContent {
    prepare_content(raw)
}

// ── Module registration ────────────────────────────────────────────────────

pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<PreparedContent>()?;
    m.add_function(wrap_pyfunction!(looks_textish_py, m)?)?;
    m.add_function(wrap_pyfunction!(normalize_eol_py, m)?)?;
    m.add_function(wrap_pyfunction!(strip_bom_py, m)?)?;
    m.add_function(wrap_pyfunction!(prepare_content_py, m)?)?;
    Ok(())
}

// ── Tests ───────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_looks_textish_empty() {
        assert!(looks_textish(b""));
    }

    #[test]
    fn test_looks_textish_pure_ascii() {
        assert!(looks_textish(b"Hello, World!"));
        assert!(looks_textish(b"Line 1\nLine 2\nLine 3"));
    }

    #[test]
    fn test_looks_textish_with_crlf() {
        assert!(looks_textish(b"Line 1\r\nLine 2\r\n"));
    }

    #[test]
    fn test_looks_textish_with_tabs() {
        assert!(looks_textish(b"Column1\tColumn2\tColumn3"));
    }

    #[test]
    fn test_looks_textish_binary_nul() {
        assert!(!looks_textish(b"Hello\x00World"));
        assert!(!looks_textish(b"\x00"));
    }

    #[test]
    fn test_looks_textish_binary_low_ratio() {
        // Content with < 90% printable chars
        let mut binary_like = vec![b'\x01'; 100];
        binary_like.extend(vec![b'a'; 5]); // Only 5% printable
        assert!(!looks_textish(&binary_like));
    }

    #[test]
    fn test_looks_textish_binary_high_control() {
        // Mix of control chars and some text
        let content = b"\x01\x02\x03\x04\x05Hello\x06\x07\x08\x09\x10";
        assert!(!looks_textish(content));
    }

    #[test]
    fn test_looks_textish_exactly_90_percent() {
        let mut input = vec![b'a'; 9];
        input.push(b'\x01');
        assert!(looks_textish(&input)); // 90% = text
    }

    #[test]
    fn test_looks_textish_just_below_90_percent() {
        let mut input = vec![b'a'; 89];
        input.extend(vec![b'\x01'; 11]);
        assert!(!looks_textish(&input)); // 89% = binary
    }

    #[test]
    fn test_normalize_eol_no_crlf() {
        let input = "Line 1\nLine 2\n";
        assert_eq!(normalize_eol(input), "Line 1\nLine 2\n");
    }

    #[test]
    fn test_normalize_eol_crlf() {
        let input = "Line 1\r\nLine 2\r\n";
        assert_eq!(normalize_eol(input), "Line 1\nLine 2\n");
    }

    #[test]
    fn test_normalize_eol_orphan_cr() {
        let input = "Line 1\rLine 2\r";
        assert_eq!(normalize_eol(input), "Line 1\nLine 2\n");
    }

    #[test]
    fn test_normalize_eol_mixed() {
        let input = "Line 1\r\nLine 2\rLine 3\n";
        assert_eq!(normalize_eol(input), "Line 1\nLine 2\nLine 3\n");
    }

    #[test]
    fn test_strip_bom_present() {
        let input = "\u{FEFF}Hello World";
        let (result, had_bom) = strip_bom(input);
        assert_eq!(result, "Hello World");
        assert!(had_bom);
    }

    #[test]
    fn test_strip_bom_absent() {
        let input = "Hello World";
        let (result, had_bom) = strip_bom(input);
        assert_eq!(result, "Hello World");
        assert!(!had_bom);
    }

    #[test]
    fn test_strip_bom_bytes() {
        let with_bom = b"\xef\xbb\xbfHello";
        let (result, had_bom) = strip_bom_bytes(with_bom);
        assert_eq!(result, b"Hello");
        assert!(had_bom);

        let without_bom = b"Hello";
        let (result, had_bom) = strip_bom_bytes(without_bom);
        assert_eq!(result, b"Hello");
        assert!(!had_bom);
    }

    #[test]
    fn test_prepare_content_empty() {
        let result = prepare_content(b"");
        assert_eq!(result.content, "");
        assert!(result.is_text);
        assert!(!result.had_bom);
        assert!(!result.had_crlf);
    }

    #[test]
    fn test_prepare_content_pure_text() {
        let result = prepare_content(b"Hello, World!");
        assert_eq!(result.content, "Hello, World!");
        assert!(result.is_text);
        assert!(!result.had_bom);
        assert!(!result.had_crlf);
    }

    #[test]
    fn test_prepare_content_with_crlf() {
        let result = prepare_content(b"Line 1\r\nLine 2\r\n");
        assert_eq!(result.content, "Line 1\nLine 2\n");
        assert!(result.is_text);
        assert!(!result.had_bom);
        assert!(result.had_crlf);
    }

    #[test]
    fn test_prepare_content_with_bom() {
        let input = b"\xef\xbb\xbfHello World";
        let result = prepare_content(input);
        assert_eq!(result.content, "Hello World");
        assert!(result.is_text);
        assert!(result.had_bom);
        assert!(!result.had_crlf);
    }

    #[test]
    fn test_prepare_content_with_bom_and_crlf() {
        let input = b"\xef\xbb\xbfLine 1\r\nLine 2";
        let result = prepare_content(input);
        assert_eq!(result.content, "Line 1\nLine 2");
        assert!(result.is_text);
        assert!(result.had_bom);
        assert!(result.had_crlf);
    }

    #[test]
    fn test_prepare_content_binary_nul() {
        // NUL byte anywhere in content marks it as binary
        let input = b"Hello\x00World";
        let result = prepare_content(input);
        assert!(!result.is_text);
        assert!(!result.had_bom);
        assert!(!result.had_crlf);
    }

    #[test]
    fn test_prepare_content_binary_low_printable() {
        // Create content that passes NUL check but fails printable ratio
        let mut input = vec![b'a'; 9]; // 9 printable
        input.extend(vec![b'\x01'; 91]); // 91 non-printable
        let result = prepare_content(&input);
        assert!(!result.is_text);
        assert!(!result.had_bom);
        assert!(!result.had_crlf);
    }

    #[test]
    fn test_prepare_content_unicode() {
        let input = "Hello 世界 🌍".as_bytes();
        let result = prepare_content(input);
        assert_eq!(result.content, "Hello 世界 🌍");
        assert!(result.is_text);
        assert!(!result.had_bom);
        assert!(!result.had_crlf);
    }

    #[test]
    fn test_prepare_content_unicode_with_crlf() {
        let input = "Line 1\r\n世界\r\n🌍".as_bytes();
        let result = prepare_content(input);
        assert_eq!(result.content, "Line 1\n世界\n🌍");
        assert!(result.is_text);
        assert!(!result.had_bom);
        assert!(result.had_crlf);
    }

    #[test]
    fn test_prepare_content_orphan_cr() {
        // Orphan CR (not part of CRLF) should be normalized too
        let input = b"Line 1\rLine 2";
        let result = prepare_content(input);
        assert_eq!(result.content, "Line 1\nLine 2");
        assert!(result.is_text);
        // had_crlf tracks CRLF sequences; orphan CRs don't set this
        assert!(!result.had_crlf);
    }

    #[test]
    fn test_prepare_content_binary_with_bom() {
        let input = b"\xef\xbb\xbfHello\x00World";
        let result = prepare_content(input);
        assert!(!result.is_text);
        assert!(result.had_bom);
        assert!(!result.content.starts_with('\u{FEFF}'));
    }
}
