# Burrito Single-Binary Releases

[Burrito](https://github.com/burrito-elixir/burrito) is an Elixir packaging tool that produces self-contained, single-binary executables for macOS, Linux, and Windows. It bundles the BEAM VM, your compiled application, and the Erlang runtime into a self-extracting archive wrapped by a small Zig binary.

This means end users don't need Erlang, Elixir, or any other runtime installed — they just download and run the binary.

## Prerequisites

### Zig Compiler

Burrito uses [Zig](https://ziglang.org/) to compile the native wrapper binary. You need Zig ≥ 0.11 on your PATH.

| Platform | Install Command | Notes |
|----------|----------------|-------|
| macOS | `brew install zig` | Homebrew tracks latest stable |
| Ubuntu/Debian | `apt install zig` | Verify version ≥ 0.11; some distros ship older versions |
| Arch Linux | `pacman -S zig` | Usually up to date |
| Windows | `choco install zig` | Or download from [ziglang.org](https://ziglang.org/download/) |

### Additional Tools

| Platform | Tool | Purpose |
|----------|------|---------|
| All | XZ (`xz`) | Payload compression |
| Windows targets | 7-Zip (`7z`) | Windows payload handling |

## Building

Use the provided helper script:

```bash
# Build all targets (macOS arm64, macOS x86_64, Linux x86_64, Linux arm64, Windows x86_64)
scripts/build-burrito.sh

# Build only for the current host platform
scripts/build-burrito.sh --host-only

# Build a specific target
scripts/build-burrito.sh --target macos_arm64
scripts/build-burrito.sh --target linux_x86_64
scripts/build-burrito.sh --target windows_x86_64
```

Or manually:

```bash
MIX_ENV=prod mix deps.get --only prod
MIX_ENV=prod mix release code_puppy_control --overwrite

# Build a single target:
BURRITO_TARGET=macos_arm64 MIX_ENV=prod mix release code_puppy_control --overwrite
```

## Output Layout

Built binaries appear under `burrito_out/`:

```
burrito_out/
├── code_puppy_control_macos_arm64
├── code_puppy_control_macos_x86_64
├── code_puppy_control_linux_x86_64
├── code_puppy_control_linux_arm64
└── code_puppy_control_windows_x86_64.exe
```

## First-Run Behavior

On first launch, the Burrito binary extracts its payload (BEAM code + ERTS) to the system user cache directory (`:filename.basedir(:user_cache, "burrito")`):

| Platform | Extraction Path |
|----------|----------------|
| macOS | `~/Library/Caches/burrito/` |
| Linux | `~/.cache/burrito/` |
| Windows | `%LOCALAPPDATA%\burrito\` |

First-run extraction takes ~2-5 seconds. Subsequent launches of the same version are fast (the cached payload is reused).

## Running

```bash
# macOS / Linux
./code_puppy_control_macos_arm64 "explain this code"
./code_puppy_control_linux_x86_64 --help

# Windows
.\code_puppy_control_windows_x86_64.exe --help
```

The binary accepts the same CLI arguments as the escript `pup` command.

### Configuration Defaults

When running as a Burrito binary, `PUP_DATABASE_PATH` and `PUP_SECRET_KEY_BASE` are not required — sensible defaults are auto-generated:

- **Database**: `data.sqlite` under the system user-data directory
  - macOS: `~/Library/Application Support/code_puppy/data.sqlite`
  - Linux: `~/.local/share/code_puppy/data.sqlite`
  - Windows: `%LOCALAPPDATA%\code_puppy\data.sqlite`
- **Secret key base**: Auto-generated via `:crypto.strong_rand_bytes/1` and persisted to `secret_key_base` in the same directory

These paths are intentionally **outside** `~/.code_puppy/` (Python pup's home) to respect ADR-003 config isolation.

## CI/CD Release Automation

Tag-push builds and GitHub Release publishing are automated via `.github/workflows/burrito-release.yml` (bd-236).

### How it works

| Aspect | Detail |
|--------|--------|
| **Trigger** | Git tag push matching `v*` (e.g. `v1.0.0`) or manual `workflow_dispatch` |
| **Matrix** | 3 platforms: `macos-latest` (arm64), `ubuntu-latest` (x86_64), `windows-latest` (x86_64) |
| **Artifacts** | 3 native binaries + `SHA256SUMS.txt` attached to a GitHub Release |
| **Run history** | `https://github.com/<owner>/<repo>/actions/workflows/burrito-release.yml` |

On a tag push, each platform builds a Burrito binary, uploads it as a workflow artifact, then a `release` job downloads all three, computes SHA-256 checksums, and creates a GitHub Release with all files attached.

`workflow_dispatch` runs build artifacts but **do not** publish a release (the `release` job only runs on tag refs).

### Codesigning

The CI-produced binaries are **unsigned**. Codesigning is tracked separately:

- **Windows Authenticode** → bd-240
- **macOS codesigning/notarization** → bd-241

### Missing targets

| Target | Status |
|--------|--------|
| `linux_arm64` | Tracked in bd-239 area |
| `macos_x86_64` | Not yet tracked (follow-up needed) |
| `linux_musl` (Alpine) | Tracked in bd-239 |

## Known Issues

### macOS Gatekeeper

macOS Gatekeeper blocks unsigned binaries. Workaround until codesigning is implemented:

```bash
xattr -c ./code_puppy_control_macos_arm64
```

> **Future work:** Apple Developer ID codesigning and notarization (tracked as a follow-up).

### Windows SmartScreen

Windows SmartScreen may flag unsigned executables with an "unrecognized app" warning. Users can click "More info" → "Run anyway".

> **Future work:** Authenticode signing with a code-signing certificate.

### Linux (musl/Alpine)

The default Linux target links against glibc. Users on Alpine Linux or other musl-based distributions will need a separate musl target. This is not yet configured in the release matrix.

> **Future work:** Add `linux_musl_x86_64` target with a custom ERTS build.

## Troubleshooting

### "Zig compiler not found"

Install Zig (see [Prerequisites](#prerequisites)) and ensure it's on your PATH:

```bash
zig version  # should print e.g. 0.13.0
```

### Build fails with linker errors

Common causes:
- **Missing C compiler**: Burrito cross-compiles NIFs which requires a C toolchain. On macOS, install Xcode Command Line Tools (`xcode-select --install`). On Linux, install `build-essential`.
- **Zig version mismatch**: Burrito 1.3 requires Zig 0.13+. Check with `zig version`.

### "NIF compilation failed"

If NIF-bearing dependencies (e.g., `xxhash`, `erlexec`, `exqlite`) fail to compile for a cross-compilation target:
1. Ensure Zig is installed and accessible
2. Try building with `--host-only` first to verify the native build works
3. Cross-compilation of NIFs depends on Zig's cross-compilation support for the target platform

### Binary exits immediately with no output

This usually means the BEAM application failed to start. Check:
1. The binary was built with `MIX_ENV=prod`
2. Required configuration is available (env vars or Burrito auto-defaults)
3. Run with `__BURRITO_DEBUG=1` environment variable for verbose output

## Relationship to Mix Release Overlays

The `rel/overlays/bin/code-puppy` and `rel/overlays/bin/gac` shell wrappers are used **only** by `mix release` output (the traditional Mix release workflow). They require Elixir/Erlang installed on the target machine.

Burrito binaries are self-contained and do **not** use these overlays. Both workflows coexist:

| Workflow | Command | Output | Requires Erlang on target |
|----------|---------|--------|---------------------------|
| Mix release | `mix release` | `_build/prod/rel/` | Yes |
| Burrito | `scripts/build-burrito.sh` | `burrito_out/` | No |
