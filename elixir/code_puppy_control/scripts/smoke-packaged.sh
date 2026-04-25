#!/usr/bin/env bash
# scripts/smoke-packaged.sh — packaged-CLI smoke wrapper
#
# Builds the shipped CLI artifact(s) and runs the no-network dogfood
# smoke runner against them.  Designed to be deterministic and
# CI-friendly: never touches `~/.code_puppy_ex/`, never makes network
# calls, never asks for API keys.
#
# Layers (each layer is opt-in past the default escript layer):
#
#   1. (default)         escript-only smoke
#                        -> `mix escript.build` + `mix pup_ex.smoke --escript`
#
#   2. --with-burrito    add a host-only Burrito build + Burrito smoke
#                        -> `scripts/build-burrito.sh --host-only` +
#                          `mix pup_ex.smoke --escript --burrito`
#                        Requires Zig on PATH; without Zig, prints a
#                        clear skip notice and exits 0 (this is the
#                        documented opt-in behaviour for code_puppy-d7m).
#
#   3. --strict          do NOT skip on missing toolchain;
#                        exit non-zero if Zig is requested but missing.
#                        Useful for CI images that should always have
#                        Zig pre-installed.
#
# Usage:
#   scripts/smoke-packaged.sh                       # escript-only smoke
#   scripts/smoke-packaged.sh --json                # JSON report
#   scripts/smoke-packaged.sh --with-burrito        # add Burrito layer
#   scripts/smoke-packaged.sh --with-burrito --strict
#   scripts/smoke-packaged.sh --skip-build          # reuse an already-built ./pup
#
# Exit codes:
#   0  every selected layer passed (or was deliberately skipped)
#   1  at least one layer failed
#   2  bad arguments
#
# Refs: code_puppy-d7m

set -euo pipefail

# ── Color helpers ──────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

info()  { echo -e "${BLUE}[smoke-packaged]${NC} $*"; }
ok()    { echo -e "${GREEN}[smoke-packaged]${NC} $*"; }
warn()  { echo -e "${YELLOW}[smoke-packaged]${NC} $*"; }
error() { echo -e "${RED}[smoke-packaged]${NC} $*" >&2; }

# ── Parse arguments ───────────────────────────────────────────────────────
WITH_BURRITO=false
STRICT=false
SKIP_BUILD=false
JSON_FLAG=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --with-burrito) WITH_BURRITO=true; shift ;;
    --strict)        STRICT=true; shift ;;
    --skip-build)    SKIP_BUILD=true; shift ;;
    --json)          JSON_FLAG="--json"; shift ;;
    --help|-h)
      sed -n '1,50p' "$0"
      exit 0
      ;;
    *)
      error "Unknown option: $1"
      exit 2
      ;;
  esac
done

# ── Locate the Elixir project ─────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

if [[ ! -f "${PROJECT_ROOT}/mix.exs" ]]; then
  error "could not find mix.exs at ${PROJECT_ROOT}"
  exit 2
fi

cd "${PROJECT_ROOT}"
info "project root: ${PROJECT_ROOT}"

# ── Prerequisite checks ───────────────────────────────────────────────────
if ! command -v mix >/dev/null 2>&1; then
  error "Elixir/Mix not found on PATH. Install Elixir first."
  exit 1
fi

# ── Layer 1: escript build + smoke ───────────────────────────────────────
ESCRIPT_PATH="${PROJECT_ROOT}/pup"

if [[ "${SKIP_BUILD}" != "true" ]]; then
  info "building escript (mix escript.build)..."
  mix escript.build >/tmp/pup_escript_build.log 2>&1 || {
    error "mix escript.build failed; see /tmp/pup_escript_build.log"
    tail -40 /tmp/pup_escript_build.log >&2 || true
    exit 1
  }
  ok "escript built: ${ESCRIPT_PATH}"
else
  if [[ ! -x "${ESCRIPT_PATH}" ]]; then
    error "--skip-build requested but ${ESCRIPT_PATH} does not exist"
    exit 1
  fi
  info "reusing existing escript: ${ESCRIPT_PATH}"
fi

# ── Layer 2 (optional): Burrito host-only build ──────────────────────────
BURRITO_FLAG=""

if [[ "${WITH_BURRITO}" == "true" ]]; then
  if command -v zig >/dev/null 2>&1; then
    info "Zig detected ($(zig version 2>/dev/null || echo "unknown")); building host-only Burrito..."

    if [[ ! -x "${SCRIPT_DIR}/build-burrito.sh" ]]; then
      error "scripts/build-burrito.sh missing or not executable"
      exit 1
    fi

    "${SCRIPT_DIR}/build-burrito.sh" --host-only >/tmp/pup_burrito_build.log 2>&1 || {
      error "Burrito host-only build failed; see /tmp/pup_burrito_build.log"
      tail -40 /tmp/pup_burrito_build.log >&2 || true
      exit 1
    }
    ok "Burrito host-only build complete"
    BURRITO_FLAG="--burrito"
  else
    if [[ "${STRICT}" == "true" ]]; then
      error "--with-burrito --strict requested but Zig is not on PATH"
      error "Install Zig (brew install zig / apt install zig / choco install zig)"
      exit 1
    else
      warn "Zig not on PATH -- skipping Burrito layer (use --strict to fail)"
      warn "Install Zig and re-run with --with-burrito to exercise this layer"
    fi
  fi
fi

# ── Run the smoke ─────────────────────────────────────────────────────────
info "running mix pup_ex.smoke --escript ${BURRITO_FLAG} ${JSON_FLAG}"
SMOKE_ARGS=("pup_ex.smoke" "--escript")
if [[ -n "${BURRITO_FLAG}" ]]; then
  SMOKE_ARGS+=("${BURRITO_FLAG}")
fi
if [[ -n "${JSON_FLAG}" ]]; then
  SMOKE_ARGS+=("${JSON_FLAG}")
fi

set +e
mix "${SMOKE_ARGS[@]}"
SMOKE_EXIT=$?
set -e

if [[ ${SMOKE_EXIT} -eq 0 ]]; then
  ok "packaged-CLI smoke PASS"
else
  error "packaged-CLI smoke FAIL (exit ${SMOKE_EXIT})"
fi

exit ${SMOKE_EXIT}
