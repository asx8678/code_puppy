use rustler::{Encoder, Env, NifResult, Term};

// Use the core crate directly - no PyO3 dependencies!
use turbo_parse_core::{
    extract_diagnostics, extract_symbols as _extract_symbols,
    extract_symbols_from_file as _extract_symbols_from_file, get_folds as _get_folds,
    get_folds_from_file as _get_folds_from_file, get_highlights as _get_highlights,
    get_highlights_from_file as _get_highlights_from_file, get_language as _get_language,
    get_language_info as _get_language_info, is_language_supported as _is_language_supported,
    list_supported_languages as _list_supported_languages,
    normalize_language as _normalize_language, parse_file as _parse_file,
    parse_source as _parse_source, version as _version, Diagnostic, FoldRange, FoldResult,
    HighlightCapture, HighlightResult, LanguageInfo, ParseError, ParseResult, Severity, Symbol,
    SymbolOutline, SyntaxDiagnostics,
};

// =============================================================================
// Atoms
// =============================================================================

mod atoms {
    rustler::atoms! {
        ok,
        error,
        // Severity
        error_severity = "error",
        warning = "warning",
        // Fold types
        function,
        class,
        conditional,
        loop_fold = "loop",
        block,
        import,
        generic,
        // Special
        nil,
        unsupported_language,
    }
}

// =============================================================================
// Encoder helpers - convert Rust types directly to Erlang terms
// =============================================================================

fn encode_ok<'a, T: Encoder>(env: Env<'a>, value: T) -> Term<'a> {
    (atoms::ok(), value).encode(env)
}

fn encode_error<'a>(env: Env<'a>, reason: impl Encoder) -> Term<'a> {
    (atoms::error(), reason).encode(env)
}

/// Encode a Severity enum as an Elixir atom.
fn encode_severity<'a>(env: Env<'a>, severity: &Severity) -> Term<'a> {
    match severity {
        Severity::Error => atoms::error_severity().encode(env),
        Severity::Warning => atoms::warning().encode(env),
    }
}

/// Encode a FoldType enum as an Elixir atom.
fn encode_fold_type<'a>(env: Env<'a>, fold_type: &turbo_parse_core::FoldType) -> Term<'a> {
    use turbo_parse_core::FoldType;
    let atom = match fold_type {
        FoldType::Function => atoms::function(),
        FoldType::Class => atoms::class(),
        FoldType::Conditional => atoms::conditional(),
        FoldType::Loop => atoms::loop_fold(),
        FoldType::Block => atoms::block(),
        FoldType::Import => atoms::import(),
        FoldType::Generic => atoms::generic(),
    };
    atom.encode(env)
}

/// Encode a Symbol as an Elixir map with string keys.
fn encode_symbol<'a>(env: Env<'a>, sym: &Symbol) -> Term<'a> {
    let mut map = Term::map_new(env);
    map = map
        .map_put("name".encode(env), sym.name.encode(env))
        .unwrap();
    map = map
        .map_put("kind".encode(env), sym.kind.encode(env))
        .unwrap();
    map = map
        .map_put("start_line".encode(env), sym.start_line.encode(env))
        .unwrap();
    map = map
        .map_put("start_column".encode(env), sym.start_column.encode(env))
        .unwrap();
    map = map
        .map_put("end_line".encode(env), sym.end_line.encode(env))
        .unwrap();
    map = map
        .map_put("end_column".encode(env), sym.end_column.encode(env))
        .unwrap();
    if let Some(ref parent) = sym.parent {
        map = map
            .map_put("parent".encode(env), parent.encode(env))
            .unwrap();
    }
    if let Some(ref docstring) = sym.docstring {
        map = map
            .map_put("docstring".encode(env), docstring.encode(env))
            .unwrap();
    }
    map
}

/// Encode a SymbolOutline as an Elixir map with string keys.
fn encode_symbol_outline<'a>(env: Env<'a>, outline: &SymbolOutline) -> Term<'a> {
    let symbols: Vec<Term> = outline
        .symbols
        .iter()
        .map(|s| encode_symbol(env, s))
        .collect();
    let errors: Vec<Term> = outline.errors.iter().map(|e| e.encode(env)).collect();

    let mut map = Term::map_new(env);
    map = map
        .map_put("language".encode(env), outline.language.encode(env))
        .unwrap();
    map = map
        .map_put("symbols".encode(env), symbols.encode(env))
        .unwrap();
    map = map
        .map_put(
            "extraction_time_ms".encode(env),
            outline.extraction_time_ms.encode(env),
        )
        .unwrap();
    map = map
        .map_put("success".encode(env), outline.success.encode(env))
        .unwrap();
    map = map
        .map_put("errors".encode(env), errors.encode(env))
        .unwrap();
    map
}

/// Encode a ParseError as an Elixir map with string keys.
fn encode_parse_error<'a>(env: Env<'a>, err: &ParseError) -> Term<'a> {
    let mut map = Term::map_new(env);
    map = map
        .map_put("message".encode(env), err.message.encode(env))
        .unwrap();
    map = map
        .map_put("line".encode(env), err.line.encode(env))
        .unwrap();
    map = map
        .map_put("column".encode(env), err.column.encode(env))
        .unwrap();
    map = map
        .map_put("offset".encode(env), err.offset.encode(env))
        .unwrap();
    map
}

/// Encode a Diagnostic as an Elixir map with string keys.
fn encode_diagnostic<'a>(env: Env<'a>, diag: &Diagnostic) -> Term<'a> {
    let mut map = Term::map_new(env);
    map = map
        .map_put("message".encode(env), diag.message.encode(env))
        .unwrap();
    map = map
        .map_put("severity".encode(env), encode_severity(env, &diag.severity))
        .unwrap();
    map = map
        .map_put("line".encode(env), diag.line.encode(env))
        .unwrap();
    map = map
        .map_put("column".encode(env), diag.column.encode(env))
        .unwrap();
    map = map
        .map_put("offset".encode(env), diag.offset.encode(env))
        .unwrap();
    map = map
        .map_put("length".encode(env), diag.length.encode(env))
        .unwrap();
    map = map
        .map_put("node_kind".encode(env), diag.node_kind.encode(env))
        .unwrap();
    map
}

/// Encode SyntaxDiagnostics as an Elixir map with string keys.
fn encode_syntax_diagnostics<'a>(env: Env<'a>, diags: &SyntaxDiagnostics) -> Term<'a> {
    let diagnostics: Vec<Term> = diags
        .diagnostics
        .iter()
        .map(|d| encode_diagnostic(env, d))
        .collect();
    let mut map = Term::map_new(env);
    map = map
        .map_put("diagnostics".encode(env), diagnostics.encode(env))
        .unwrap();
    map = map
        .map_put("error_count".encode(env), diags.error_count().encode(env))
        .unwrap();
    map = map
        .map_put(
            "warning_count".encode(env),
            diags.warning_count().encode(env),
        )
        .unwrap();
    map
}

/// Encode a serde_json::Value recursively as an Erlang term.
fn encode_json_value<'a>(env: Env<'a>, value: &serde_json::Value) -> Term<'a> {
    match value {
        serde_json::Value::Null => atoms::nil().encode(env),
        serde_json::Value::Bool(b) => b.encode(env),
        serde_json::Value::Number(n) => {
            if let Some(i) = n.as_i64() {
                i.encode(env)
            } else if let Some(f) = n.as_f64() {
                f.encode(env)
            } else {
                atoms::nil().encode(env)
            }
        }
        serde_json::Value::String(s) => s.encode(env),
        serde_json::Value::Array(arr) => {
            let terms: Vec<Term> = arr.iter().map(|v| encode_json_value(env, v)).collect();
            terms.encode(env)
        }
        serde_json::Value::Object(obj) => {
            let mut map = Term::map_new(env);
            for (key, val) in obj {
                map = map
                    .map_put(key.encode(env), encode_json_value(env, val))
                    .unwrap();
            }
            map
        }
    }
}

/// Encode a ParseResult as an Elixir map with string keys.
fn encode_parse_result<'a>(env: Env<'a>, result: &ParseResult) -> Term<'a> {
    let errors: Vec<Term> = result
        .errors
        .iter()
        .map(|e| encode_parse_error(env, e))
        .collect();
    let tree_term = match &result.tree {
        Some(tree) => encode_json_value(env, tree),
        None => atoms::nil().encode(env),
    };

    let mut map = Term::map_new(env);
    map = map
        .map_put("language".encode(env), result.language.encode(env))
        .unwrap();
    map = map.map_put("tree".encode(env), tree_term).unwrap();
    map = map
        .map_put(
            "parse_time_ms".encode(env),
            result.parse_time_ms.encode(env),
        )
        .unwrap();
    map = map
        .map_put("success".encode(env), result.success.encode(env))
        .unwrap();
    map = map
        .map_put("errors".encode(env), errors.encode(env))
        .unwrap();
    map = map
        .map_put(
            "diagnostics".encode(env),
            encode_syntax_diagnostics(env, &result.diagnostics),
        )
        .unwrap();
    map
}

/// Encode a FoldRange as an Elixir map with string keys.
fn encode_fold_range<'a>(env: Env<'a>, fold: &FoldRange) -> Term<'a> {
    let mut map = Term::map_new(env);
    map = map
        .map_put("start_line".encode(env), fold.start_line.encode(env))
        .unwrap();
    map = map
        .map_put("end_line".encode(env), fold.end_line.encode(env))
        .unwrap();
    map = map
        .map_put(
            "fold_type".encode(env),
            encode_fold_type(env, &fold.fold_type),
        )
        .unwrap();
    if let Some(ref node_kind) = fold.node_kind {
        map = map
            .map_put("node_kind".encode(env), node_kind.encode(env))
            .unwrap();
    }
    map
}

/// Encode a FoldResult as an Elixir map with string keys.
fn encode_fold_result<'a>(env: Env<'a>, result: &FoldResult) -> Term<'a> {
    let folds: Vec<Term> = result
        .folds
        .iter()
        .map(|f| encode_fold_range(env, f))
        .collect();
    let errors: Vec<Term> = result.errors.iter().map(|e| e.encode(env)).collect();

    let mut map = Term::map_new(env);
    map = map
        .map_put("language".encode(env), result.language.encode(env))
        .unwrap();
    map = map.map_put("folds".encode(env), folds.encode(env)).unwrap();
    map = map
        .map_put(
            "extraction_time_ms".encode(env),
            result.extraction_time_ms.encode(env),
        )
        .unwrap();
    map = map
        .map_put("success".encode(env), result.success.encode(env))
        .unwrap();
    map = map
        .map_put("errors".encode(env), errors.encode(env))
        .unwrap();
    map
}

/// Encode a HighlightCapture as an Elixir map with string keys.
fn encode_highlight_capture<'a>(env: Env<'a>, cap: &HighlightCapture) -> Term<'a> {
    let mut map = Term::map_new(env);
    map = map
        .map_put("start_byte".encode(env), cap.start_byte.encode(env))
        .unwrap();
    map = map
        .map_put("end_byte".encode(env), cap.end_byte.encode(env))
        .unwrap();
    map = map
        .map_put("capture_name".encode(env), cap.capture_name.encode(env))
        .unwrap();
    map
}

/// Encode a HighlightResult as an Elixir map with string keys.
fn encode_highlight_result<'a>(env: Env<'a>, result: &HighlightResult) -> Term<'a> {
    let captures: Vec<Term> = result
        .captures
        .iter()
        .map(|c| encode_highlight_capture(env, c))
        .collect();
    let errors: Vec<Term> = result.errors.iter().map(|e| e.encode(env)).collect();

    let mut map = Term::map_new(env);
    map = map
        .map_put("language".encode(env), result.language.encode(env))
        .unwrap();
    map = map
        .map_put("captures".encode(env), captures.encode(env))
        .unwrap();
    map = map
        .map_put(
            "extraction_time_ms".encode(env),
            result.extraction_time_ms.encode(env),
        )
        .unwrap();
    map = map
        .map_put("success".encode(env), result.success.encode(env))
        .unwrap();
    map = map
        .map_put("errors".encode(env), errors.encode(env))
        .unwrap();
    map
}

/// Encode a LanguageInfo as an Elixir map with string keys.
fn encode_language_info<'a>(env: Env<'a>, info: &LanguageInfo) -> Term<'a> {
    let mut map = Term::map_new(env);
    map = map
        .map_put("name".encode(env), info.name.encode(env))
        .unwrap();
    map = map
        .map_put(
            "highlights_available".encode(env),
            info.highlights_available.encode(env),
        )
        .unwrap();
    map = map
        .map_put(
            "folds_available".encode(env),
            info.folds_available.encode(env),
        )
        .unwrap();
    map = map
        .map_put(
            "indents_available".encode(env),
            info.indents_available.encode(env),
        )
        .unwrap();
    map
}

// =============================================================================
// NIF Functions
// =============================================================================

/// Get the turbo_parse version string.
#[rustler::nif]
fn version() -> &'static str {
    _version()
}

/// Normalize a language name (aliases to canonical name).
#[rustler::nif]
fn normalize_language(language: String) -> String {
    _normalize_language(&language)
}

/// Get language metadata (name, available query types).
#[rustler::nif]
fn get_language_info<'a>(env: Env<'a>, language: String) -> NifResult<Term<'a>> {
    match _get_language_info(&language) {
        Some(info) => Ok(encode_ok(env, encode_language_info(env, &info))),
        None => Ok(encode_error(env, atoms::unsupported_language())),
    }
}

/// Check if a language is supported.
#[rustler::nif]
fn is_language_supported(language: String) -> bool {
    _is_language_supported(&language)
}

/// Get list of supported languages.
#[rustler::nif]
fn supported_languages() -> Vec<String> {
    _list_supported_languages()
}

/// Extract symbols from source code.
#[rustler::nif]
fn extract_symbols<'a>(env: Env<'a>, source: String, language: String) -> NifResult<Term<'a>> {
    let outline = _extract_symbols(&source, &language);
    Ok(encode_ok(env, encode_symbol_outline(env, &outline)))
}

/// Extract symbols from a file.
#[rustler::nif]
fn extract_symbols_from_file<'a>(
    env: Env<'a>,
    path: String,
    language: Option<String>,
) -> NifResult<Term<'a>> {
    let lang_ref = language.as_deref();
    let outline = _extract_symbols_from_file(&path, lang_ref);
    Ok(encode_ok(env, encode_symbol_outline(env, &outline)))
}

/// Parse source code and return AST info.
#[rustler::nif]
fn parse_source<'a>(env: Env<'a>, source: String, language: String) -> NifResult<Term<'a>> {
    let result = _parse_source(&source, &language);
    Ok(encode_ok(env, encode_parse_result(env, &result)))
}

/// Parse a file.
#[rustler::nif]
fn parse_file<'a>(env: Env<'a>, path: String, language: Option<String>) -> NifResult<Term<'a>> {
    let lang_ref = language.as_deref();
    let result = _parse_file(&path, lang_ref);
    Ok(encode_ok(env, encode_parse_result(env, &result)))
}

/// Extract syntax diagnostics (errors).
#[rustler::nif]
fn extract_syntax_diagnostics<'a>(
    env: Env<'a>,
    source: String,
    language: String,
) -> NifResult<Term<'a>> {
    let ts_language = match _get_language(&language) {
        Ok(lang) => lang,
        Err(_) => {
            let mut map = Term::map_new(env);
            map = map
                .map_put("diagnostics".encode(env), Vec::<Term>::new().encode(env))
                .unwrap();
            map = map
                .map_put("error_count".encode(env), 0usize.encode(env))
                .unwrap();
            map = map
                .map_put("warning_count".encode(env), 0usize.encode(env))
                .unwrap();
            map = map
                .map_put(
                    "error".encode(env),
                    format!("Unsupported language: '{}'", language).encode(env),
                )
                .unwrap();
            return Ok(encode_ok(env, map));
        }
    };

    let diagnostics = extract_diagnostics(&source, &ts_language);
    Ok(encode_ok(env, encode_syntax_diagnostics(env, &diagnostics)))
}

/// Get fold ranges.
#[rustler::nif]
fn get_folds<'a>(env: Env<'a>, source: String, language: String) -> NifResult<Term<'a>> {
    let result = _get_folds(&source, &language);
    Ok(encode_ok(env, encode_fold_result(env, &result)))
}

/// Get fold ranges from a file.
#[rustler::nif]
fn get_folds_from_file<'a>(
    env: Env<'a>,
    path: String,
    language: Option<String>,
) -> NifResult<Term<'a>> {
    let lang_ref = language.as_deref();
    let result = _get_folds_from_file(&path, lang_ref);
    Ok(encode_ok(env, encode_fold_result(env, &result)))
}

/// Get syntax highlights.
#[rustler::nif]
fn get_highlights<'a>(env: Env<'a>, source: String, language: String) -> NifResult<Term<'a>> {
    let result = _get_highlights(&source, &language);
    Ok(encode_ok(env, encode_highlight_result(env, &result)))
}

/// Get syntax highlights from a file.
#[rustler::nif]
fn get_highlights_from_file<'a>(
    env: Env<'a>,
    path: String,
    language: Option<String>,
) -> NifResult<Term<'a>> {
    let lang_ref = language.as_deref();
    let result = _get_highlights_from_file(&path, lang_ref);
    Ok(encode_ok(env, encode_highlight_result(env, &result)))
}

rustler::init!("Elixir.CodePuppyControl.TurboParseNif");
