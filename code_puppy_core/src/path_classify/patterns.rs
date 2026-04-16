//! Pattern definitions for path classification.
//!
//! This module contains all the glob patterns used for ignore detection.
//! Ported from Python: `code_puppy/tools/common.py` DIR_IGNORE_PATTERNS and FILE_IGNORE_PATTERNS

/// Pre-compiled patterns for directory-only matching.
/// NOTE: Keep in sync with Python `DIR_IGNORE_PATTERNS` in `code_puppy/tools/common.py`
pub const DIR_PATTERNS: &[&str] = &[
    // Version control
    "**/.git/**",
    "**/.git",
    ".git/**",
    ".git",
    "**/.svn/**",
    "**/.hg/**",
    "**/.bzr/**",
    // Cross-language common patterns
    "**/target/**",
    "**/target",
    "**/build/**",
    "**/build",
    "**/dist/**",
    "**/dist",
    "**/bin/**",
    "**/vendor/**",
    "**/deps/**",
    "**/coverage/**",
    "**/doc/**",
    "**/_build/**",
    "**/.gradle/**",
    "**/project/target/**",
    "**/project/project/**",
    // Node.js / JavaScript / TypeScript
    "**/node_modules/**",
    "**/node_modules",
    "node_modules/**",
    "node_modules",
    "**/.npm/**",
    "**/.yarn/**",
    "**/.pnpm-store/**",
    "**/.nyc_output/**",
    "**/.next/**",
    "**/.nuxt/**",
    "**/out/**",
    "**/.cache/**",
    "**/.parcel-cache/**",
    "**/.vite/**",
    "**/storybook-static/**",
    "**/*.tsbuildinfo/**",
    // Python
    "**/__pycache__/**",
    "**/__pycache__",
    "__pycache__/**",
    "__pycache__",
    "**/.pytest_cache/**",
    "**/.mypy_cache/**",
    "**/.coverage",  // Python coverage data file
    "**/htmlcov/**",
    "**/.tox/**",
    "**/.nox/**",
    "**/site-packages/**",
    "**/.venv/**",
    "**/.venv",
    "**/venv/**",
    "**/venv",
    "**/env/**",
    "**/ENV/**",
    "**/.env",
    "**/pip-wheel-metadata/**",
    "**/*.egg-info/**",
    "**/wheels/**",
    "**/pytest-reports/**",
    // Java (Maven, Gradle, SBT)
    "**/.classpath",
    "**/.project",
    "**/.settings/**",
    // Go
    "**/*.exe~",
    "**/*.test",
    "**/*.out",
    "**/go.work",
    "**/go.work.sum",
    // Ruby
    "**/.bundle/**",
    "**/.rvm/**",
    "**/.rbenv/**",
    "**/.yardoc/**",
    "**/rdoc/**",
    "**/.sass-cache/**",
    "**/.jekyll-cache/**",
    "**/_site/**",
    // PHP
    "**/.phpunit.result.cache",
    "**/storage/logs/**",
    "**/storage/framework/cache/**",
    "**/storage/framework/sessions/**",
    "**/storage/framework/testing/**",
    "**/storage/framework/views/**",
    "**/bootstrap/cache/**",
    // .NET / C#
    "**/obj/**",
    "**/packages/**",
    "**/.vs/**",
    "**/TestResults/**",
    "**/BenchmarkDotNet.Artifacts/**",
    // C/C++
    "**/CMakeFiles/**",
    "**/cmake_install.cmake",
    "**/.deps/**",
    "**/.libs/**",
    "**/autom4te.cache/**",
    // Perl
    "**/blib/**",
    "**/*.tmp",
    "**/*.bak",
    "**/*.old",
    "**/Makefile.old",
    "**/MANIFEST.bak",
    "**/.prove",
    // Scala
    "**/.bloop/**",
    "**/.metals/**",
    "**/.ammonite/**",
    // Elixir
    "**/.fetch",
    "**/.elixir_ls/**",
    // Swift
    "**/.build/**",
    "**/Packages/**",
    "**/*.xcodeproj/**",
    "**/*.xcworkspace/**",
    "**/DerivedData/**",
    "**/xcuserdata/**",
    "**/*.dSYM/**",
    // Dart/Flutter
    "**/.dart_tool/**",
    // Haskell
    "**/dist-newstyle/**",
    "**/.stack-work/**",
    // Erlang
    "**/ebin/**",
    "**/rel/**",
    // Common cache and temp directories
    "**/cache/**",
    "**/tmp/**",
    "**/temp/**",
    "**/.tmp/**",
    "**/.temp/**",
    "**/logs/**",
    // IDE and editor files
    "**/.idea/**",
    "**/.idea",
    "**/.vscode/**",
    "**/.vscode",
    "**/.emacs.d/auto-save-list/**",
    "**/.vim/**",
    // OS-specific files
    "**/.DS_Store",
    ".DS_Store",
    "**/Thumbs.db",
    "**/Desktop.ini",
    "**/.directory",
    // Backup files
    "**/*.backup",
    "**/*.save",
    // Note: "**/.*" is commented out in Python as "too aggressive"
];

/// File extension patterns (binary/non-text files).
/// NOTE: Keep in sync with Python `FILE_IGNORE_PATTERNS` in `code_puppy/tools/common.py`
pub const FILE_PATTERNS: &[&str] = &[
    // Compiled/binary artifacts
    "**/*.class",
    "**/*.jar",
    "**/*.dll",
    "**/*.exe",
    "**/*.so",
    "**/*.dylib",
    "**/*.pdb",
    "**/*.o",
    "**/*.beam",
    "**/*.obj",
    "**/*.a",
    "**/*.lib",
    // Python compiled
    "**/*.pyc",
    "**/*.pyo",
    "**/*.pyd",
    // Java
    "**/*.war",
    "**/*.ear",
    "**/*.nar",
    "**/hs_err_pid*",
    // Rust
    "**/Cargo.lock",
    // Ruby
    "**/*.gem",
    "**/Gemfile.lock",
    // PHP
    "**/composer.lock",
    // .NET
    "**/*.cache",
    "**/*.user",
    "**/*.suo",
    // C/C++
    "**/CMakeCache.txt",
    "**/Makefile",
    "**/compile_commands.json",
    // Perl
    "**/Build",
    "**/Build.bat",
    "**/META.yml",
    "**/META.json",
    "**/MYMETA.*",
    // Scala
    // Clojure
    "**/.lein-**",  // Double asterisk to match lein-* files like Python
    "**/.nrepl-port",
    "**/pom.xml.asc",
    // Dart/Flutter
    "**/.packages",
    "**/pubspec.lock",
    "**/*.g.dart",
    "**/*.freezed.dart",
    "**/*.gr.dart",
    // Haskell
    "**/*.hi",
    "**/*.prof",
    "**/*.aux",
    "**/*.hp",
    "**/*.eventlog",
    "**/*.tix",
    // Erlang
    "**/*.boot",
    "**/*.plt",
    // Kotlin
    "**/*.kotlin_module",
    // Elixir
    "**/erl_crash.dump",
    "**/*.ez",
    // Swift
    // Log files
    "**/*.log",
    "**/*.log.*",
    "**/npm-debug.log*",
    "**/yarn-debug.log*",
    "**/yarn-error.log*",
    "**/pnpm-debug.log*",
    // IDE swap files
    "**/*.swp",
    "**/*.swo",
    "**/*~",
    "**/.#*",
    "**/#*#",
    "**/.netrwhist",
    "**/Session.vim",
    "**/.sublime-project",
    "**/.sublime-workspace",
    // Artifacts
    "**/*.orig",
    "**/*.rej",
    "**/*.patch",
    "**/*.diff",
    "**/.*.orig",
    "**/.*.rej",
    // Binary image formats
    "**/*.png",
    "**/*.jpg",
    "**/*.jpeg",
    "**/*.gif",
    "**/*.bmp",
    "**/*.tiff",
    "**/*.tif",
    "**/*.webp",
    "**/*.ico",
    "**/*.svg",
    // Binary document formats
    "**/*.pdf",
    "**/*.doc",
    "**/*.docx",
    "**/*.xls",
    "**/*.xlsx",
    "**/*.ppt",
    "**/*.pptx",
    // Archive formats
    "**/*.zip",
    "**/*.tar",
    "**/*.gz",
    "**/*.bz2",
    "**/*.xz",
    "**/*.rar",
    "**/*.7z",
    // Media files
    "**/*.mp3",
    "**/*.mp4",
    "**/*.avi",
    "**/*.mov",
    "**/*.wmv",
    "**/*.flv",
    "**/*.wav",
    "**/*.ogg",
    // Font files
    "**/*.ttf",
    "**/*.otf",
    "**/*.woff",
    "**/*.woff2",
    "**/*.eot",
    // Other binary formats
    "**/*.bin",
    "**/*.dat",
    "**/*.db",
    "**/*.sqlite",
    "**/*.sqlite3",
    // OS files
    "**/*.lnk",
    // Gradle
    "**/gradle-app.setting",
];
