//! Tests for path classification.

use crate::path_classify::{PathClassifier, SensitivePathData};

fn get_classifier() -> PathClassifier {
    PathClassifier::new().expect("Failed to create classifier")
}

fn get_sensitive_data() -> SensitivePathData {
    SensitivePathData::new().expect("Failed to create sensitive data")
}

// ===== Ignore pattern tests =====

#[test]
fn test_ignore_git_directory() {
    let c = get_classifier();
    assert!(c.should_ignore(".git"));
    assert!(c.should_ignore(".git/config"));
    assert!(c.should_ignore("./.git"));
    assert!(c.should_ignore("./.git/HEAD"));
    assert!(c.should_ignore("project/.git"));
    assert!(c.should_ignore("project/.git/hooks/pre-commit"));
}

#[test]
fn test_ignore_node_modules() {
    let c = get_classifier();
    assert!(c.should_ignore("node_modules"));
    assert!(c.should_ignore("node_modules/lodash"));
    assert!(c.should_ignore("node_modules/lodash/index.js"));
    assert!(c.should_ignore("./node_modules"));
    assert!(c.should_ignore("project/node_modules"));
}

#[test]
fn test_ignore_pycache() {
    let c = get_classifier();
    assert!(c.should_ignore("__pycache__"));
    assert!(c.should_ignore("__pycache__/foo.cpython-311.pyc"));
    assert!(c.should_ignore("./__pycache__"));
    assert!(c.should_ignore("project/__pycache__"));
}

#[test]
fn test_ignore_compiled_python() {
    let c = get_classifier();
    assert!(c.should_ignore("foo.pyc"));
    assert!(c.should_ignore("foo.pyo"));
    assert!(c.should_ignore("./foo.pyc"));
    assert!(c.should_ignore("project/foo.pyc"));
}

#[test]
fn test_ignore_binary_files() {
    let c = get_classifier();
    assert!(c.should_ignore("image.png"));
    assert!(c.should_ignore("doc.pdf"));
    assert!(c.should_ignore("archive.zip"));
    assert!(c.should_ignore("video.mp4"));
    assert!(c.should_ignore("font.ttf"));
}

#[test]
fn test_not_ignore_regular_files() {
    let c = get_classifier();
    assert!(!c.should_ignore("main.py"));
    assert!(!c.should_ignore("src/main.rs"));
    assert!(!c.should_ignore("README.md"));
    assert!(!c.should_ignore("./src/lib.rs"));
}

#[test]
fn test_ignore_npm_logs() {
    let c = get_classifier();
    assert!(c.should_ignore("npm-debug.log"));
    assert!(c.should_ignore("npm-debug.log.123456789"));
}

#[test]
fn test_ignore_hidden_files() {
    let c = get_classifier();
    // bd-28: "**/.*" pattern added for parity with Python (was commented out there)
    // This catches generic dotfiles/dotdirs
    assert!(c.should_ignore(".hidden_file"));
    assert!(c.should_ignore("./.hidden_file"));
    assert!(c.should_ignore("project/.hidden_file"));

    // Common hidden files still work
    assert!(c.should_ignore(".DS_Store"));
    assert!(c.should_ignore("./.DS_Store"));
    assert!(c.should_ignore("project/.DS_Store"));
}

#[test]
fn test_ignore_hidden_directories() {
    let c = get_classifier();
    // bd-28: Hidden directories should be ignored via "**/.*" pattern
    assert!(c.should_ignore(".hidden_dir"));
    assert!(c.should_ignore("./.hidden_dir"));
    assert!(c.should_ignore("project/.hidden_dir"));
    assert!(c.should_ignore("path/to/.hidden_dir/file"));
    assert!(c.should_ignore("path/to/.hidden_dir/nested/path/file"));
}

#[test]
fn test_ignore_swap_files() {
    let c = get_classifier();
    assert!(c.should_ignore(".file.swp"));
    assert!(c.should_ignore(".file.swo"));
    assert!(c.should_ignore("file~"));
}

#[test]
fn test_ignore_coverage_file() {
    let c = get_classifier();
    // .coverage file pattern added for parity with Python
    assert!(c.should_ignore(".coverage"));
    assert!(c.should_ignore("./.coverage"));
    assert!(c.should_ignore("project/.coverage"));
}

#[test]
fn test_ignore_lein_files() {
    let c = get_classifier();
    // .lein-* pattern using double asterisk (like Python "**/.lein-**")
    assert!(c.should_ignore(".lein-repl-history"));
    assert!(c.should_ignore(".lein-failures"));
    assert!(c.should_ignore("project/.lein-deps-sum"));
}

#[test]
fn test_ignore_gradle_app_setting() {
    let c = get_classifier();
    // gradle-app.setting pattern added for parity with Python
    assert!(c.should_ignore("gradle-app.setting"));
    assert!(c.should_ignore("./gradle-app.setting"));
    assert!(c.should_ignore("project/gradle-app.setting"));
}

// ===== Sensitive path tests =====

#[test]
fn test_sensitive_ssh_directory() {
    let sd = get_sensitive_data();
    // Test that ~username/.ssh paths are detected as sensitive
    // (other users' SSH directories should always be sensitive)
    assert!(sd.is_sensitive("~other/.ssh/id_rsa"));
    assert!(sd.is_sensitive("~alice/.ssh"));
    assert!(sd.is_sensitive("~root/.ssh"));
    assert!(sd.is_sensitive("~root/.ssh/authorized_keys"));
}

#[test]
fn test_sensitive_etc_paths() {
    let sd = get_sensitive_data();
    assert!(sd.is_sensitive("/etc/shadow"));
    assert!(sd.is_sensitive("/etc/passwd"));
    assert!(sd.is_sensitive("/etc/sudoers"));
}

#[test]
fn test_sensitive_private_etc() {
    let sd = get_sensitive_data();
    assert!(sd.is_sensitive("/private/etc/shadow"));
    assert!(sd.is_sensitive("/private/etc/passwd"));
    assert!(sd.is_sensitive("/private/etc/sudoers"));
    assert!(sd.is_sensitive("/private/etc"));
}

#[test]
fn test_sensitive_dev() {
    let sd = get_sensitive_data();
    assert!(sd.is_sensitive("/dev/sda1"));
    assert!(sd.is_sensitive("/dev/null"));
    assert!(sd.is_sensitive("/dev"));
}

#[test]
fn test_sensitive_proc_not_detected() {
    let sd = get_sensitive_data();
    // /proc paths should NOT be detected as sensitive in file operations
    // (Python is_sensitive_path does NOT have /proc check)
    assert!(!sd.is_sensitive("/proc/1/cmdline"));
    assert!(!sd.is_sensitive("/proc"));
}

#[test]
fn test_sensitive_var_log_not_detected() {
    let sd = get_sensitive_data();
    // /var/log paths should NOT be detected as sensitive in file operations
    // (Python is_sensitive_path does NOT have /var/log check)
    assert!(!sd.is_sensitive("/var/log/syslog"));
    assert!(!sd.is_sensitive("/var/log/auth.log"));
}

#[test]
fn test_sensitive_root_not_detected() {
    let sd = get_sensitive_data();
    // /root paths should NOT be detected as sensitive in file operations
    // (Python is_sensitive_path does NOT check /root as a prefix)
    // ~root paths ARE detected via ~username handling
    assert!(!sd.is_sensitive("/root"));
    assert!(!sd.is_sensitive("/root/.bashrc"));
    assert!(sd.is_sensitive("~root/.ssh/id_rsa"));
}

#[test]
fn test_sensitive_env_files() {
    let sd = get_sensitive_data();
    // Regular .env is sensitive
    assert!(sd.is_sensitive(".env"));
    assert!(sd.is_sensitive("project/.env"));
    assert!(sd.is_sensitive("/path/to/.env"));

    // Allowed variants are NOT sensitive
    assert!(!sd.is_sensitive(".env.example"));
    assert!(!sd.is_sensitive(".env.sample"));
    assert!(!sd.is_sensitive(".env.template"));
    assert!(!sd.is_sensitive("project/.env.example"));
}

#[test]
fn test_sensitive_extensions() {
    let sd = get_sensitive_data();
    assert!(sd.is_sensitive("id_rsa.pem"));
    assert!(sd.is_sensitive("server.key"));
    assert!(sd.is_sensitive("cert.p12"));
    assert!(sd.is_sensitive("keystore.pfx"));
    assert!(sd.is_sensitive("android.keystore"));
}

#[test]
fn test_not_sensitive_regular_files() {
    let sd = get_sensitive_data();
    assert!(!sd.is_sensitive("main.py"));
    assert!(!sd.is_sensitive("README.md"));
    assert!(!sd.is_sensitive("src/lib.rs"));
}

#[test]
fn test_empty_path() {
    let sd = get_sensitive_data();
    assert!(!sd.is_sensitive(""));
}

// ===== Classifier combined tests =====

#[test]
fn test_classify_path() {
    let c = get_classifier();

    // Regular file: not ignored, not sensitive
    assert_eq!(c.classify_path("main.py"), (false, false));

    // node_modules: IS ignored, not sensitive
    assert_eq!(c.classify_path("node_modules"), (true, false));
}

#[test]
fn test_dir_only_vs_all() {
    let c = get_classifier();

    // Directory patterns should match both
    assert!(c.should_ignore("node_modules"));
    assert!(c.should_ignore_dir("node_modules"));

    // File patterns should match only all_globset
    assert!(c.should_ignore("image.png"));
    assert!(!c.should_ignore_dir("image.png"));

    // Regular files shouldn't match either
    assert!(!c.should_ignore("main.py"));
    assert!(!c.should_ignore_dir("main.py"));
}

#[test]
fn test_hidden_check_edge_cases() {
    let c = get_classifier();
    // Parent directory is NOT treated as hidden
    assert!(!c.should_ignore(".."));
    assert!(!c.should_ignore("foo/.."));
    
    // Double-dot prefix names ARE hidden (parity with Python **/.* pattern)
    assert!(c.should_ignore("..hidden"));
    assert!(c.should_ignore("...hidden"));
    assert!(c.should_ignore("project/..hidden"));
    assert!(c.should_ignore("project/...hidden"));
}
