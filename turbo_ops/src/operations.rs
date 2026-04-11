//! Core file operations for turbo_ops.
//!
//! Implements the three main operations:
//! - list_files: Directory traversal with filtering
//! - grep: Pattern matching across files
//! - read_files: File content reading with token estimation

use crate::models::{estimate_tokens, FileInfo, FileReadResult, GrepMatch};
use regex::Regex;
use serde_json::json;
use std::fs;
use std::path::Path;
use walkdir::WalkDir;

/// Build a FileInfo from a path and its metadata
fn metadata_to_file_info(path: &Path, metadata: &std::fs::Metadata) -> FileInfo {
    let modified = metadata
        .modified()
        .ok()
        .and_then(|t| t.duration_since(std::time::UNIX_EPOCH).ok())
        .and_then(|d| chrono::DateTime::from_timestamp(d.as_secs() as i64, 0))
        .map(|dt| dt.to_rfc3339());
    FileInfo {
        path: path.to_string_lossy().to_string(),
        name: path
            .file_name()
            .unwrap_or_default()
            .to_string_lossy()
            .to_string(),
        is_dir: metadata.is_dir(),
        size: metadata.len(),
        modified,
    }
}

/// Execute list_files operation
pub fn execute_list_files(args: &serde_json::Value) -> Result<serde_json::Value, String> {
    let directory = args
        .get("directory")
        .and_then(|v| v.as_str())
        .unwrap_or(".");
    let recursive = args
        .get("recursive")
        .and_then(|v| v.as_bool())
        .unwrap_or(true);

    let path = Path::new(directory);
    if !path.exists() {
        return Err(format!("Directory does not exist: {}", directory));
    }
    if !path.is_dir() {
        return Err(format!("Path is not a directory: {}", directory));
    }

    let mut files = Vec::new();

    if recursive {
        for entry in WalkDir::new(path)
            .follow_links(false)
            .into_iter()
            .filter_map(|e| e.ok())
        {
            let metadata = match entry.metadata() {
                Ok(m) => m,
                Err(_) => continue,
            };

            files.push(metadata_to_file_info(entry.path(), &metadata));
        }
    } else {
        // Non-recursive: just list immediate children
        let entries = match fs::read_dir(path) {
            Ok(entries) => entries,
            Err(e) => return Err(format!("Failed to read directory: {}", e)),
        };

        for entry in entries.filter_map(|e| e.ok()) {
            let metadata = match entry.metadata() {
                Ok(m) => m,
                Err(_) => continue,
            };

            files.push(metadata_to_file_info(&entry.path(), &metadata));
        }
    }

    // Sort: directories first, then by name
    files.sort_by(|a, b| {
        match (a.is_dir, b.is_dir) {
            (true, false) => std::cmp::Ordering::Less,
            (false, true) => std::cmp::Ordering::Greater,
            _ => a.name.cmp(&b.name),
        }
    });

    Ok(json!({
        "files": files,
        "total_count": files.len(),
        "directory": directory,
        "recursive": recursive,
    }))
}

/// Execute grep operation
pub fn execute_grep(args: &serde_json::Value) -> Result<serde_json::Value, String> {
    let search_string = args
        .get("search_string")
        .and_then(|v| v.as_str())
        .ok_or("grep requires 'search_string' argument")?;
    let directory = args
        .get("directory")
        .and_then(|v| v.as_str())
        .unwrap_or(".");

    // Check for ripgrep-style case-insensitive flag
    let case_insensitive = search_string.starts_with("(?i)");
    let pattern_str = if case_insensitive {
        &search_string[4..]
    } else {
        search_string
    };

    // Compile regex
    let regex = if case_insensitive {
        Regex::new(&format!("(?i){}", regex::escape(pattern_str)))
    } else {
        Regex::new(&regex::escape(pattern_str))
    }
    .map_err(|e| format!("Invalid regex pattern: {}", e))?;

    let path = Path::new(directory);
    if !path.exists() {
        return Err(format!("Directory does not exist: {}", directory));
    }
    if !path.is_dir() {
        return Err(format!("Path is not a directory: {}", directory));
    }

    let mut matches = Vec::new();

    for entry in WalkDir::new(path)
        .follow_links(false)
        .into_iter()
        .filter_map(|e| e.ok())
    {
        let path_ref = entry.path();

        // Skip directories and binary files
        if !path_ref.is_file() {
            continue;
        }

        // Skip known binary extensions and large files
        let ext = path_ref
            .extension()
            .and_then(|e| e.to_str())
            .unwrap_or("");
        let skip_extensions = [
            "png", "jpg", "jpeg", "gif", "bmp", "ico", "svg", "webp", // Images
            "mp3", "mp4", "avi", "mov", "webm", "wav", "ogg", // Media
            "zip", "tar", "gz", "bz2", "7z", "rar", // Archives
            "pdf", "doc", "docx", "xls", "xlsx", // Documents
            "so", "dll", "dylib", "exe", "bin", // Binaries
            "pyc", "pyo", "class", "o", "a", // Compiled
        ];
        if skip_extensions.contains(&ext.to_lowercase().as_str()) {
            continue;
        }

        // Skip large files (> 10MB)
        let metadata = match entry.metadata() {
            Ok(m) => m,
            Err(_) => continue,
        };
        if metadata.len() > 10_000_000 {
            continue;
        }

        // Read and search file
        let content = match fs::read_to_string(path_ref) {
            Ok(c) => c,
            Err(_) => continue, // Skip files we can't read (likely binary)
        };

        let file_path = path_ref.to_string_lossy().to_string();

        for (line_number, line) in content.lines().enumerate() {
            if regex.is_match(line) {
                matches.push(GrepMatch {
                    file_path: file_path.clone(),
                    line_number: line_number + 1, // 1-indexed
                    line_content: line.to_string(),
                });
            }
        }
    }

    Ok(json!({
        "matches": matches,
        "total_matches": matches.len(),
        "search_string": search_string,
        "directory": directory,
    }))
}

/// Execute read_files operation
pub fn execute_read_files(args: &serde_json::Value) -> Result<serde_json::Value, String> {
    let file_paths = args
        .get("file_paths")
        .and_then(|v| v.as_array())
        .ok_or("read_files requires 'file_paths' argument (list of strings)")?;

    let start_line = args
        .get("start_line")
        .and_then(|v| v.as_u64())
        .map(|v| v as usize);

    let num_lines = args
        .get("num_lines")
        .and_then(|v| v.as_u64())
        .map(|v| v as usize);

    let paths: Vec<String> = file_paths
        .iter()
        .filter_map(|v| v.as_str().map(|s| s.to_string()))
        .collect();

    if paths.is_empty() {
        return Err("No valid file paths provided".to_string());
    }

    let mut files_data = Vec::new();

    for file_path in paths {
        let path = Path::new(&file_path);

        if !path.exists() {
            files_data.push(FileReadResult {
                file_path: file_path.clone(),
                content: None,
                num_tokens: 0,
                error: Some(format!("File does not exist: {}", file_path)),
                success: false,
            });
            continue;
        }

        if !path.is_file() {
            files_data.push(FileReadResult {
                file_path: file_path.clone(),
                content: None,
                num_tokens: 0,
                error: Some(format!("Path is not a file: {}", file_path)),
                success: false,
            });
            continue;
        }

        // Read file content
        let content = match fs::read_to_string(path) {
            Ok(c) => c,
            Err(e) => {
                files_data.push(FileReadResult {
                    file_path: file_path.clone(),
                    content: None,
                    num_tokens: 0,
                    error: Some(format!("Failed to read file: {}", e)),
                    success: false,
                });
                continue;
            }
        };

        // Apply line range if specified
        let final_content = if let Some(start) = start_line {
            let lines: Vec<&str> = content.lines().collect();
            let start_idx = start.saturating_sub(1).min(lines.len()); // Convert to 0-indexed AND clamp
            let end_idx = if let Some(num) = num_lines {
                (start_idx + num).min(lines.len())
            } else {
                lines.len()
            };
            lines[start_idx..end_idx].join("\n")
        } else {
            content
        };

        let num_tokens = estimate_tokens(&final_content);

        files_data.push(FileReadResult {
            file_path: file_path.clone(),
            content: Some(final_content),
            num_tokens,
            error: None,
            success: true,
        });
    }

    let successful = files_data.iter().filter(|f| f.success).count();

    Ok(json!({
        "files": files_data,
        "total_files": files_data.len(),
        "successful_reads": successful,
    }))
}
