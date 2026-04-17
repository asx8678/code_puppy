# KIRO ULTRA - Complete Documentation

> **Enterprise-grade autonomous debugging system with safety-first design**

---

## Table of Contents

1. [Overview](#overview)
2. [Installation](#installation)
3. [Agents](#agents)
4. [Safety Features](#safety-features)
5. [Secret Scanning](#secret-scanning)
6. [Sensitive File Protection](#sensitive-file-protection)
7. [Code Leak Prevention](#code-leak-prevention)
8. [Smart Log Handling](#smart-log-handling)
9. [Auto-Linting](#auto-linting)
10. [Confirmation System](#confirmation-system)
11. [Cost Management](#cost-management)
12. [Runbook Library](#runbook-library)
13. [Memory System](#memory-system)
14. [Session Management](#session-management)
15. [Commands Reference](#commands-reference)
16. [Configuration](#configuration)
17. [Troubleshooting](#troubleshooting)

---

## Overview

KIRO ULTRA is an autonomous debugging assistant that helps you:

- 🔍 **Investigate** bugs with read-only safety
- 🔧 **Fix** issues with verification
- ✅ **Verify** fixes aren't hallucinations
- 📚 **Learn** from past incidents via runbooks
- 🔒 **Stay safe** with enterprise security features

### Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           KIRO ULTRA ARCHITECTURE                       │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐                │
│  │ kiro-debug  │ →  │  kiro-fix   │ →  │kiro-verify  │                │
│  │   (Haiku)   │    │  (Sonnet)   │    │(Sonnet→Opus)│                │
│  │             │    │             │    │             │                │
│  │ Investigate │    │ Plan & Fix  │    │   Verify    │                │
│  │  READ-ONLY  │    │   CAREFUL   │    │  ESCALATE   │                │
│  └─────────────┘    └─────────────┘    └─────────────┘                │
│         │                  │                  │                        │
│         └──────────────────┴──────────────────┘                        │
│                            │                                           │
│                    ┌───────┴───────┐                                   │
│                    │  HOOK SYSTEM  │                                   │
│                    └───────┬───────┘                                   │
│                            │                                           │
│  ┌─────────────────────────┼─────────────────────────┐                │
│  │                         │                         │                │
│  ▼                         ▼                         ▼                │
│ Security              Confirmation              Memory                │
│ • secret-scanner      • confirm-gate           • bronze (all)        │
│ • sensitive-guard     • cost-guard             • silver (scored)     │
│ • code-leak-guard     • lint-gate              • gold (persistent)   │
│ • log-guard                                                          │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Installation

### Verify Installation

```bash
~/.kiro/verify-installation.sh
```

### Repair Installation

```bash
~/.kiro/install.sh
```

### Directory Structure

```
~/.kiro/
├── agents/                    # Agent configurations
│   ├── kiro-debug.json        # Main debugging agent
│   ├── kiro-fix.json          # Fix implementation agent
│   ├── kiro-verify.json       # Verification agent
│   └── root-cause.json        # Git archaeology agent
│
├── scripts/                   # Hook scripts (20+)
│   ├── security-audit.sh
│   ├── secret-scanner.sh
│   ├── sensitive-file-guard.sh
│   ├── code-leak-guard.sh
│   ├── log-guard.sh
│   ├── confirmation-gate.sh
│   ├── cost-guard.sh
│   ├── lint-gate.sh
│   └── ... (more)
│
├── runbooks/                  # Incident procedures
│   ├── incidents/
│   ├── procedures/
│   └── fixes/
│
├── memory/                    # Knowledge tiers
│   ├── bronze/                # Raw events
│   ├── silver/                # Processed findings
│   └── gold/                  # Persistent knowledge
│
├── state/                     # Session state
└── temp/                      # Temporary files
```

---

## Agents

### kiro-debug (Main Agent)

**Purpose:** Investigate bugs with read-only safety

**Model:** Claude Haiku (fast, cheap)

**Start:**
```bash
kiro-cli --agent kiro-debug
```

**Capabilities:**
| Action | Status |
|--------|--------|
| Read files | ✅ Allowed |
| Search code (grep/glob) | ✅ Allowed |
| Git log/diff/blame | ✅ Allowed |
| Write files | 🚫 Blocked |
| Git commit/push | 🚫 Blocked |

**Example Prompts:**
```
"Investigate why login fails after password reset"
"Show errors from application.log"
"Find where UserService is used"
"Check git history for auth.py"
```

---

### kiro-fix (Fix Agent)

**Purpose:** Plan and apply code fixes

**Model:** Claude Sonnet 4.6 (intelligent)

**Start:**
```bash
kiro-cli --agent kiro-fix
```

**Capabilities:**
| Action | Status |
|--------|--------|
| All read operations | ✅ Allowed |
| Write/edit files | ✅ Allowed (with tracking) |
| Run tests | ✅ Allowed |
| Git add/stash | ✅ Allowed |
| Git commit | ⚠️ Requires confirmation |
| Git push | 🚫 Blocked |

**Workflow:**
```
1. VERIFY FINDINGS    ← Confirms bug exists
2. PLAN THE FIX       ← Shows plan before coding
3. APPLY THE FIX      ← Stash first, then apply
4. VALIDATE           ← Run tests, verify fix
5. REPORT             ← Summary for human review
```

**Example Prompts:**
```
"Apply the fix for the session bug"
"Fix the null pointer exception in auth.py"
"Auto fix the lint errors"
```

---

### kiro-verify (Verification Agent)

**Purpose:** Verify fixes, check for hallucinations, escalate if needed

**Model:** Claude Sonnet 4.6 → Claude Opus 4.5 (escalation)

**Start:**
```bash
kiro-cli --agent kiro-verify
```

**Features:**
- Independent verification of findings
- Hallucination detection
- Escalation to Opus for complex issues

**Hallucination Indicators:**
```
⚠️ HALLUCINATION INDICATORS
□ File paths that don't exist
□ Function names not in codebase
□ Line numbers that don't match
□ Logic that doesn't make sense
□ Claims without evidence
```

**Escalation Triggers:**
- Multiple fix attempts failed
- Complex multi-system interactions
- Subtle race conditions
- Unclear root cause

**Example Prompts:**
```
"Verify the fix to session.py actually works"
"Check if the bug diagnosis is correct"
"Escalate to Opus - this is too complex"
```

---

### root-cause (Git Archaeology Agent)

**Purpose:** Deep git history analysis

**Model:** Claude Sonnet 4.6

**Start:**
```bash
kiro-cli --agent root-cause
```

**Capabilities:**
- git log, blame, diff, show
- Bisect planning (not execution)
- Historical analysis

**Example Prompts:**
```
"Find when the auth regression was introduced"
"Who last modified session.py and why"
"Show changes between v2.3 and v2.4"
```

---

## Safety Features

KIRO implements multiple layers of safety:

### Hook Priority Chain

```
PRE-TOOL HOOKS (can block execution):
┌─────────────────────────────────────────────────────────────┐
│  Priority 1: security-audit.sh       → Dangerous commands   │
│  Priority 2: sensitive-file-guard.sh → .env protection      │
│  Priority 3: log-guard.sh            → Smart log handling   │
│  Priority 4: code-leak-guard.sh      → Web search safety    │
│  Priority 5: confirmation-gate.sh    → Confirm dangerous    │
│  Priority 6: secret-scanner.sh       → Credential detection │
│  Priority 7: lint-gate.sh            → Pre-commit linting   │
│  Priority 8: fix-safety-gate.sh      → Category guards      │
└─────────────────────────────────────────────────────────────┘

POST-TOOL HOOKS (observe and capture):
┌─────────────────────────────────────────────────────────────┐
│  cost-guard.sh       → Track model costs                    │
│  change-tracker.sh   → Log file modifications               │
│  bronze-capture.sh   → Audit trail                          │
└─────────────────────────────────────────────────────────────┘
```

### Blocking Mechanism

KIRO uses exit codes to control tool execution:

| Exit Code | Meaning |
|-----------|---------|
| `exit 0` | ✅ Allow - tool proceeds |
| `exit 1` | ⚠️ Warning - tool still proceeds |
| `exit 2` | 🚫 Block - tool is stopped |

---

## Secret Scanning

Automatically detects leaked credentials before commits.

### Detected Secrets (30+ patterns)

| Category | Examples | Severity |
|----------|----------|----------|
| **AWS** | `AKIA...`, Secret Keys | 🔴 Critical |
| **GitHub** | `ghp_...`, `gho_...` | 🔴 Critical |
| **OpenAI** | `sk-...` | 🔴 Critical |
| **Anthropic** | `sk-ant-...` | 🔴 Critical |
| **Stripe** | `sk_live_...` | 🔴 Critical |
| **Slack** | `xox...` | 🔴 Critical |
| **Private Keys** | `-----BEGIN RSA PRIVATE KEY-----` | 🔴 Critical |
| **Database URLs** | `postgres://user:pass@...` | 🟡 High |
| **Generic** | `api_key = "..."` | 🟡 High |
| **JWT** | `eyJ...` | 🟢 Medium |

### Usage

**Automatic:** Runs before every `git commit`

**Manual scan:**
```bash
~/.kiro/scripts/secret-scan-file.sh path/to/file.py
```

### Example Output

```
🚨 SECRET SCANNING FAILED: 2 potential secret(s) found!

  [CRITICAL] AWS_ACCESS_KEY
    File: src/config.py:23
    Found: AKIAIOSFODNN...7EXAMPLE

  [HIGH] GENERIC_PASSWORD
    File: src/database.py:45
    Found: password...ecret

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

⚠️ NEVER commit secrets to version control!

To fix:
  1. Remove the secret from the file
  2. Use environment variables instead
```

### Ignoring False Positives

Create `.kiro-secrets-ignore`:
```
# Ignore test fixtures
tests/fixtures/mock_tokens.py:GENERIC_TOKEN

# Ignore documentation examples
docs/api-examples.md:*
```

---

## Sensitive File Protection

Protects sensitive files from accidental exposure.

### Protection Levels

| Level | Files | Action |
|-------|-------|--------|
| 🚫 **BLOCKED** | `id_rsa`, `*.pem`, `.aws/credentials` | Never allowed |
| ⚠️ **CONFIRM** | `.env`, `config.json`, `*.tfvars` | Requires confirmation |
| ✅ **ALLOWED** | `*.py`, `*.js`, `README.md` | No restriction |

### Always Blocked Files

```
• SSH Keys: id_rsa, id_ed25519, *.pem, *.key
• Cloud Creds: .aws/credentials, .gcloud/*, .azure/*
• Password DBs: *.kdbx, vault.json, secrets.json
• GPG Keys: secring.gpg, private-keys-v1.d
```

### Confirmation Required Files

```
• Environment: .env, .env.local, .env.production
• Configs: config.json, settings.yaml, application.properties
• Docker/K8s: docker-compose.yml, *secret*.yaml
• Terraform: *.tfvars, terraform.tfstate
• CI/CD: .github/workflows/*.yml, Jenkinsfile
```

### Safe Alternatives

| Command | What It Does |
|---------|--------------|
| `"read redacted"` | Shows file with `[REDACTED]` values |
| `"show env keys"` | Lists variable names only |
| `"show structure"` | Shows structure without secrets |

### Example

```
🔐 CONFIRMATION REQUIRED: Sensitive File Access

File: .env.production
Type: .env.*
Size: 1234 bytes, Lines: 45

⚠️ This file may contain:
  • API keys and secrets
  • Database credentials
  • Authentication tokens

To read this file:
  → Say: "confirm read"

To read with redaction (RECOMMENDED):
  → Say: "read redacted"
```

---

## Code Leak Prevention

Prevents sending proprietary code via web searches.

### What's Protected

| Category | Action |
|----------|--------|
| API Keys in queries | 🚫 Blocked |
| Passwords in queries | 🚫 Blocked |
| Internal IPs | 🚫 Blocked |
| Connection strings | 🚫 Blocked |
| Long code snippets (200+ chars) | ⚠️ Confirm |
| Short code patterns | ⚠️ Warning |

### Safe Search Examples

✅ **ALLOWED:**
```
"Python TypeError NoneType object is not iterable"
"how to handle async timeout in Python"
"axios retry interceptor example"
```

❌ **BLOCKED:**
```
"why does api_key=sk-12345 not work"
"def connect(): return redis.connect(password='secret')"
```

---

## Smart Log Handling

Prevents loading full logs, extracts only relevant information.

### The Problem

```
❌ BAD: "read application.log" (500MB = millions of tokens!)
✅ GOOD: "show errors from application.log" (errors only)
```

### Extraction Modes

| Mode | What It Extracts |
|------|------------------|
| `errors` | ERROR, FAIL, EXCEPTION, FATAL, PANIC |
| `warnings` | WARN, WARNING, DEPRECATED |
| `all-issues` | Both errors and warnings |
| `recent [N]` | Last N lines (default 50) |
| `summary` | Stats + sample errors |
| `exceptions` | Stack traces with context |
| `unique` | Deduplicated error messages |
| `pattern <P>` | Custom grep pattern |

### Commands

```bash
# Extract errors
~/.kiro/scripts/log-extract.sh /var/log/app.log errors

# Get summary
~/.kiro/scripts/log-extract.sh /var/log/app.log summary

# Search pattern
~/.kiro/scripts/log-extract.sh /var/log/app.log pattern "timeout"
```

### Voice Commands

```
"show errors from app.log"
"show last 50 lines"
"summarize the log"
"find exceptions in log"
"unique errors only"
```

---

## Auto-Linting

Automatically runs linters before commits.

### Supported Languages

| Language | Linters | Auto-Fix |
|----------|---------|----------|
| Python | ruff, flake8, pylint, mypy | ruff, black |
| JavaScript | eslint | eslint --fix, prettier |
| TypeScript | tsc, eslint | eslint --fix, prettier |
| Go | golangci-lint, go vet, gofmt | gofmt, goimports |
| Rust | clippy, rustfmt | cargo fmt |

---

## Confirmation System

Requires confirmation for dangerous or expensive operations.

### Operations Requiring Confirmation

| Operation | Trigger | Severity |
|-----------|---------|----------|
| File deletion | `rm -rf`, `rm -r` | 🔴 High |
| Git commit | `git commit` | 🟡 Medium |
| Bulk writes | 10+ files in 5 min | 🟡 Medium |
| Opus model | First Opus call | 💰 Cost |

### Example Flow

```
KIRO: I need to delete the temp files...
      shell: rm -rf ./temp/

⚠️ CONFIRMATION REQUIRED: File Deletion

Command: rm -rf ./temp/
To confirm: Say "confirm"
To cancel: Say "cancel"

⏱️ Confirmation expires in 60 seconds.

USER: confirm

✅ CONFIRMED: Executing previously approved operation.
```

---

## Cost Management

Tracks model usage and costs.

### Model Costs

| Model | Est. Cost/Call | Usage |
|-------|----------------|-------|
| Haiku | ~$0.01 | Default, most tasks |
| Sonnet | ~$0.03 | Fix implementation |
| Opus | ~$0.15 | Complex escalation |

### Cost Tracking

View session costs:
```bash
~/.kiro/scripts/show-session-cost.sh
```

---

## Runbook Library

Searchable library of incident procedures.

### Directory Structure

```
~/.kiro/runbooks/
├── incidents/          # Error resolution
├── procedures/         # Standard operating procedures
├── fixes/              # Quick fix recipes
└── templates/          # Runbook templates
```

### Commands

| Command | Script |
|---------|--------|
| Search | `~/.kiro/scripts/runbook-search.sh <query>` |
| Show | `~/.kiro/scripts/runbook-show.sh <name>` |
| Create | `~/.kiro/scripts/runbook-create.sh <title> [category]` |
| Suggest | `~/.kiro/scripts/runbook-suggest.sh <error>` |

---

## Memory System

Three-tier knowledge architecture.

### Tiers

```
┌─────────────────────────────────────────────────────────────────────────┐
│  🥉 BRONZE TIER (Raw Events)                                           │
│  Location: ~/.kiro/memory/bronze/YYYY/MM/DD/events.jsonl               │
│  Retention: 7 days (auto-cleanup)                                      │
│  Contains: Every tool execution with full context                      │
└─────────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  🥈 SILVER TIER (Processed Findings)                                   │
│  Location: ~/.kiro/memory/silver/findings/                             │
│  Retention: 30 days                                                    │
│  Contains: Error patterns, insights, test results                      │
└─────────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  🥇 GOLD TIER (Persistent Knowledge)                                   │
│  Location: ~/.kiro/memory/gold/                                        │
│  Retention: Forever (never auto-cleaned)                               │
│  Contains: Bug patterns, anti-patterns, resolution recipes             │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Session Management

### Check Status

```bash
~/.kiro/scripts/session-status.sh
```

### Cleanup

**Regular cleanup:**
```bash
~/.kiro/scripts/session-cleanup.sh
```

**Deep cleanup (interactive):**
```bash
~/.kiro/scripts/deep-cleanup.sh
```

---

## Commands Reference

### Starting Agents

```bash
kiro-cli --agent kiro-debug    # Investigate
kiro-cli --agent kiro-fix      # Fix
kiro-cli --agent kiro-verify   # Verify
kiro-cli --agent root-cause    # Git archaeology
```

### Inside KIRO Session

| Command | What It Does |
|---------|--------------|
| `/help` | Show commands |
| `/agent list` | List agents |
| `/agent use <name>` | Switch agent |
| `/model <name>` | Switch model |
| `/clear` | Clear conversation |
| `/exit` | End session |

---

## Configuration

### Agent Configuration

Location: `~/.kiro/agents/<agent>.json`

Example structure:
```json
{
  "name": "kiro-debug",
  "description": "Main debugging agent",
  "model": "claude-haiku-4-5-20241022",
  "tools": ["read", "grep", "glob", "shell", "thinking"],
  "hooks": {
    "preToolUse": [
      {"command": "~/.kiro/scripts/security-audit.sh", "timeout": 2000}
    ],
    "postToolUse": [
      {"command": "~/.kiro/scripts/bronze-capture.sh", "timeout": 1000}
    ]
  }
}
```

---

## Troubleshooting

### Verify Installation

```bash
~/.kiro/verify-installation.sh
```

### Common Issues

**Scripts not executing:**
```bash
find ~/.kiro/scripts -name "*.sh" -exec chmod +x {} \;
```

**Agent not found:**
```bash
ls ~/.kiro/agents/*.json
```

### Reset Everything

```bash
~/.kiro/scripts/deep-cleanup.sh
```

### Get Help

```bash
cat ~/.kiro/DOCUMENTATION.md
cat ~/.kiro/QUICKSTART.md
```

---

## License

MIT License - Use freely in your organization.

---

*Built with 🐕 KIRO ULTRA - Enterprise Debugging System*