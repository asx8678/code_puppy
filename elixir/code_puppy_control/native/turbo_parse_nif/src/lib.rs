use rustler::{Encoder, Env, NifResult, Term};
use serde::Serialize;

// Use the core crate directly - no PyO3 dependencies!
use turbo_parse_core::{
    extract_symbols as _extract_symbols,
    extract_symbols_from_file as _extract_symbols_from_file,
    parse_source as _parse_source,
    parse_file as _parse_file,
    is_language_supported as _is_language_supported,
    list_supported_languages as _list_supported_languages,
    get_language as _get_language,
    extract_diagnostics,
    get_folds as _get_folds,
    get_folds_from_file as _get_folds_from_file,
    get_highlights as _get_highlights,
    get_highlights_from_file as _get_highlights_from_file,
};

/// Convert a serializable Rust value to an Elixir term via JSON.
fn to_elixir_term<'a>(env: Env<'a>, value: &impl Serialize) -> NifResult<Term<'a>> {
    let json = serde_json::to_string(value)
        .map_err(|e| rustler::Error::Term(Box::new(format!("JSON serialization error: {}", e))))?;

    // Parse JSON string to Elixir term using rustler_json-like approach
    // For simplicity, we encode as a binary and let Elixir decode it
    Ok(json.encode(env))
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
    to_elixir_term(env, &outline)
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
    to_elixir_term(env, &outline)
}

/// Parse source code and return AST info.
#[rustler::nif]
fn parse_source<'a>(env: Env<'a>, source: String, language: String) -> NifResult<Term<'a>> {
    let result = _parse_source(&source, &language);
    to_elixir_term(env, &result)
}

/// Parse a file.
#[rustler::nif]
fn parse_file<'a>(
    env: Env<'a>,
    path: String,
    language: Option<String>,
) -> NifResult<Term<'a>> {
    let lang_ref = language.as_deref();
    let result = _parse_file(&path, lang_ref);
    to_elixir_term(env, &result)
}

/// Extract syntax diagnostics (errors).
#[rustler::nif]
fn extract_syntax_diagnostics<'a>(
    env: Env<'a>,
    source: String,
    language: String,
) -> NifResult<Term<'a>> {
    // Get the tree-sitter language
    let ts_language = match _get_language(&language) {
        Ok(lang) => lang,
        Err(_) => {
            let error_result = serde_json::json!({
                "diagnostics": [],
                "error_count": 0,
                "warning_count": 0,
                "error": format!("Unsupported language: '{}'", language),
            });
            return to_elixir_term(env, &error_result);
        }
    };

    let diagnostics = extract_diagnostics(&source, &ts_language);

    let result = serde_json::json!({
        "diagnostics": diagnostics.diagnostics,
        "error_count": diagnostics.error_count(),
        "warning_count": diagnostics.warning_count(),
    });

    to_elixir_term(env, &result)
}

/// Get fold ranges.
#[rustler::nif]
fn get_folds<'a>(env: Env<'a>, source: String, language: String) -> NifResult<Term<'a>> {
    let result = _get_folds(&source, &language);
    to_elixir_term(env, &result)
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
    to_elixir_term(env, &result)
}

/// Get syntax highlights.
#[rustler::nif]
fn get_highlights<'a>(env: Env<'a>, source: String, language: String) -> NifResult<Term<'a>> {
    let result = _get_highlights(&source, &language);
    to_elixir_term(env, &result)
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
    to_elixir_term(env, &result)
}

rustler::init!("Elixir.CodePuppyControl.TurboParseNif");
