# Security Audit Report - Phase 2.1 (Batch A)

**Project:** code_puppy  
**Audit Date:** 2026-04-07  
**Audited Files:**
- `claude_cache_client.py`
- `chatgpt_codex_client.py`
- `session_storage.py`
- `adaptive_rate_limiter.py`
- `plugins/` directory
- `command_line/` (shell execution paths)
- `.env.example` and credential handling

---

## [SEV-MEDIUM] JWT Parsing Without Signature Verification
**File:** `claude_cache_client.py:47-75`
**Issue:** The `_get_jwt_iat()` function decodes JWT tokens to extract the `iat` claim but does not verify the signature. While this is used only for age calculation (not authentication), the JWT parsing uses manual base64url decoding without proper JWT library validation. This could lead to accepting malformed tokens or tokens with algorithm confusion attacks if the parsing logic is modified in the future.

**Fix:** Consider using a proper JWT library like `PyJWT` with signature verification disabled explicitly for this use case (e.g., `jwt.decode(token, options={"verify_signature": False})`), or add explicit algorithm validation and comment explaining why signature verification is intentionally skipped.

---

## [SEV-LOW] Hardcoded OAuth Client IDs in Configuration
**File:** 
- `plugins/claude_code_oauth/config.py:13`
- `plugins/chatgpt_oauth/config.py:15`

**Issue:** OAuth client IDs are hardcoded in source code:
- Claude Code: `"9d1c250a-e61b-44d9-88ed-5944d1962f5e"`
- ChatGPT: `"app_EMoamEEZ73f0CkXaXp7hrann"`

While client IDs are generally considered public information in OAuth2, they identify the application to the OAuth provider and could be used for reconnaissance or rate limiting attacks. They should ideally be configurable.

**Fix:** Move client IDs to environment variables or configuration files that can be overridden by users without modifying source code.

---

## [SEV-CRITICAL] Arbitrary Code Execution via User Plugins
**File:** `plugins/__init__.py:52-104`
**Issue:** The user plugin loader executes arbitrary Python code via `spec.loader.exec_module(module)` (line 99). While there are security checks (lines 75-96) that require `enable_user_plugins=true` and optionally an allowlist, the warning messages indicate this executes with "full system privileges". A malicious plugin could:
- Steal stored OAuth tokens from `~/.code_puppy/`
- Modify the codebase
- Install persistent malware
- Exfiltrate environment variables containing API keys

**Fix:** 
1. Implement sandboxed plugin execution using `subprocess` isolation or restricted Python environments (e.g., `RestrictedPython`, `sandboxed`)
2. Add plugin signature verification before execution
3. Consider using WASM-based plugins for untrusted user code
4. Add prominent documentation warnings about the security implications

---

## [SEV-HIGH] Shell Command Injection via shell=True
**File:** 
- `tools/command_runner.py:227-230`
- `command_line/shell_passthrough.py:151-155`

**Issue:** Both files use `subprocess.Popen(..., shell=True)` with user-controlled input. The `command_runner.py` validates commands (lines 75-96), but the defense-in-depth comment admits upstream validation is the primary security mechanism. The `shell_passthrough.py` has minimal validation (`_validate_passthrough_command` only checks for dangerous patterns like `rm -rf /` and `curl ... | sh`), which can be easily bypassed.

**Code:**
```python
# command_runner.py
return subprocess.Popen(
    command,
    shell=True,  # noqa: S602 — validated above, required for pipes/redirects
    cwd=cwd,
    **kwargs
)

# shell_passthrough.py
result = subprocess.run(
    command,
    shell=True,  # Direct shell execution with minimal validation
    ...
)
```

**Fix:** 
1. For shell_passthrough, implement stricter input validation or use a shell lexer/parser to validate safe command structures
2. Consider requiring user confirmation for destructive operations
3. Document the security model clearly: shell_passthrough bypasses the safety pipeline

---

## [SEV-MEDIUM] Token/Credential Storage Without Encryption
**File:** 
- `plugins/claude_code_oauth/utils.py:86-88`
- `plugins/claude_code_oauth/utils.py:359-365`
- `plugins/claude_code_oauth/config.py:47-49`

**Issue:** OAuth tokens and API keys are stored in plain JSON files (`claude_code_oauth.json`, `chatgpt_oauth.json`) with file permissions set to `0o600`. While this provides basic filesystem-level protection, the tokens are not encrypted at rest. If an attacker gains access to the user's home directory (e.g., via backup files, sync services, or other compromised applications), they can read these tokens.

**Fix:** 
1. Encrypt tokens at rest using the OS keyring (e.g., `keyring` library for cross-platform support, macOS Keychain, Windows DPAPI, Linux Secret Service)
2. Add a migration path for existing unencrypted tokens
3. Consider using memory-safe storage that clears tokens from memory when not in use

---

## [SEV-MEDIUM] HMAC Key File Creation Race Condition (TOCTOU)
**File:** `session_storage.py:143-156`
**Issue:** The `_get_or_create_hmac_key()` function attempts atomic file creation with `open("xb")`, but there's a time-of-check to time-of-use (TOCTOU) race condition:
1. File existence check via `FileExistsError` exception handling
2. File permission setting (`chmod 0o600`) happens AFTER writing the key

Between these steps, another process could potentially read the file with default permissions.

**Fix:** 
1. Use `os.open()` with `O_CREAT | O_EXCL` and `O_CLOEXEC` flags to ensure atomic creation
2. Set permissions atomically during creation using `os.open()` mode flags where possible
3. On Unix, use `os.fchmod()` on the file descriptor before writing

---

## [SEV-LOW] Potential Credential Leakage in Logs
**File:** 
- `claude_cache_client.py:259-264`
- `claude_cache_client.py:317-320`

**Issue:** The proactive token refresh mechanism logs at INFO level when tokens are refreshed, including messages like "JWT token is %.1f seconds old". While this doesn't directly log the token, debug logging at line 320 (`logger.debug("Error during proactive token refresh check: %s", exc)`) could potentially include token data if exceptions contain request details.

**Fix:** 
1. Audit all logging statements to ensure tokens are never logged, even in exception messages
2. Implement a log sanitization filter that redacts patterns matching `Bearer [a-zA-Z0-9_-]+`
3. Document security considerations for debug logging

---

## [SEV-LOW] Unsafe JWT Decoding (No Algorithm Validation)
**File:** `claude_cache_client.py:101-143`
**Issue:** The `_get_jwt_age_seconds()` function manually decodes JWT tokens without using a proper JWT library. This bypasses built-in security checks like algorithm validation. While the code currently doesn't verify signatures, future modifications could inadvertently introduce vulnerabilities if the parsing logic is changed.

**Fix:** Use a proper JWT library (e.g., `PyJWT`) for all JWT operations, even when signature verification is intentionally disabled. Add explicit options: `jwt.decode(token, options={"verify_signature": False, "verify_exp": False, "verify_iat": False})`

---

## [SEV-HIGH] Missing Input Validation on JWT Claims
**File:** `claude_cache_client.py:115-143`
**Issue:** When decoding the JWT for age calculation, the code extracts `iat` and `exp` claims without validating:
1. The `exp` claim could be in the past (expired) but still used for calculations
2. The `iat` claim could be in the future (clock skew issues)
3. No validation that these are numeric values before arithmetic operations

**Fix:** Add validation that `iat` and `exp` are positive numbers within reasonable bounds before using them in calculations.

---

## [SEV-MEDIUM] Session Storage HMAC Uses Per-Install Key (Not Per-Session)
**File:** `session_storage.py:135-175`
**Issue:** The HMAC key is generated once per installation (stored in `~/.code_puppy/.session_hmac_key`). This means:
1. All sessions across all time use the same key
2. Session files from different dates can have their HMACs recomputed by any party with access to this key
3. If the key is compromised, all historical session integrity is void

**Fix:** Consider using per-session keys derived from a master key, or at minimum document the security model clearly. The current implementation provides tamper detection but not cryptographic security against determined attackers with filesystem access.

---

## [SEV-LOW] Command Injection via Clipboard Operations
**File:** `command_line/clipboard.py:98-115, 137-152, 229-242`
**Issue:** The clipboard module executes shell commands (`xclip`, `wl-copy`, `pbcopy`, etc.) via `subprocess.run()` with user-controlled input indirectly through clipboard content. While the clipboard content is typically controlled by the user, a malicious application could manipulate the clipboard before code_puppy reads it.

**Code:**
```python
subprocess.run(
    ["xclip", "-selection", "clipboard", "-o"],
    ...
)
```

**Fix:** While lower risk than direct shell execution, validate that subprocess arguments are properly quoted and consider using Python libraries (e.g., `pyperclip`, `clipboard`) instead of direct subprocess calls.

---

## [SEV-LOW] Insecure File Permissions in Data Directories
**File:** 
- `plugins/claude_code_oauth/config.py:47-49`
- `config.py:157-166`

**Issue:** Data directories are created with `0o700` permissions, which is correct, but the permission setting uses `mkdir(..., mode=0o700, exist_ok=True)`. The `exist_ok=True` means if the directory already exists with different permissions, they won't be corrected.

**Fix:** After `mkdir()`, explicitly check and enforce permissions with `chmod()` to ensure correct permissions even if the directory was previously created with different permissions.

---

## [SEV-MEDIUM] Rate Limiter Circuit Breaker State Manipulation
**File:** `adaptive_rate_limiter.py:648-683`
**Issue:** The `acquire_model_slot()` function checks circuit breaker state under a lock but then waits outside the lock:
```python
async with lock:
    state = _ensure_state(key)
    if state.circuit_state == CircuitState.OPEN:
        need_wait_open = True

# ... later ...
if need_wait_open:
    async with state.condition:
        while state.circuit_state == CircuitState.OPEN:
            await asyncio.wait_for(state.condition.wait(), timeout=timeout)
```

This is a TOCTOU race condition where the state could change between the check and the wait, potentially leading to incorrect wait behavior.

**Fix:** Ensure all state checks and condition waits happen atomically under the same lock.

---

## [SEV-LOW] Environment Variable Credential Leakage Risk
**File:** `.env.example`
**Issue:** The `.env.example` file suggests storing API keys in environment variables or `.env` files. While this is a common pattern, `.env` files are frequently:
1. Accidentally committed to git repositories
2. Included in backup files
3. Exposed through process listings (`ps e` on Linux)
4. Logged by CI/CD systems

**Fix:** 
1. Add prominent warnings in `.env.example` about the risks
2. Recommend using OS-specific secret storage (keyring, Keychain, etc.) as the preferred method
3. Add `.env` to `.gitignore` explicitly

---

## [SEV-LOW] Token Refresh Race Condition
**File:** `claude_cache_client.py:317-350`
**Issue:** The proactive token refresh mechanism doesn't use any locking/synchronization. If multiple concurrent requests detect an expired token simultaneously, they could all trigger token refresh operations, leading to:
1. Rate limiting by the OAuth provider
2. Invalidation of previously issued tokens (depending on provider implementation)
3. Unnecessary network traffic

**Fix:** Implement a mutex or lock around the token refresh operation to ensure only one refresh happens at a time when the token expires.

---

## [SEV-HIGH] Path Traversal in Plugin Loading
**File:** `plugins/__init__.py:88-99`
**Issue:** The user plugin loader constructs the module path from user-controlled directory contents:
```python
callbacks_file = USER_PLUGINS_DIR / plugin_name / "register_callbacks.py"
...
spec = importlib.util.spec_from_file_location(module_name, callbacks_file)
```

While `plugin_name` comes from directory listing (not direct user input), symlinks or unusual filesystem configurations could potentially lead to loading code from outside the intended plugin directory.

**Fix:** 
1. Resolve all paths to absolute paths and verify they are within the plugin directory using `Path.resolve()` and path prefix checking
2. Reject plugin names containing `..`, `/`, or `\` characters
3. Check for symlinks and reject or follow them carefully

---

## [SEV-MEDIUM] Missing Cleanup of HMAC Key on Uninstall
**File:** `session_storage.py:143-156`
**Issue:** The HMAC key file at `~/.code_puppy/.session_hmac_key` is created during first use but there's no mechanism to securely delete it when code_puppy is uninstalled. The key persists on disk and could be recovered from disk images or backups.

**Fix:** 
1. Provide a secure uninstall/cleanup command that overwrites and deletes the key file
2. Consider using OS-provided credential storage instead of a raw file
3. Document that users should manually delete the `.code_puppy` directory on uninstall

---

## [SEV-LOW] Information Disclosure via Error Messages
**File:** `session_storage.py:321-340, 347-365, 387-405`
**Issue:** When session loading fails, the error messages include exception details that could potentially leak:
- File system paths (via `FileNotFoundError`)
- Internal data structures (via pickle/msgpack errors)

**Fix:** Sanitize error messages to ensure they don't leak sensitive path information. Log full details internally but show sanitized messages to users.

---

## Summary Statistics

| Severity | Count |
|----------|-------|
| CRITICAL | 1 |
| HIGH | 3 |
| MEDIUM | 6 |
| LOW | 8 |

**Total Findings:** 18

---

## Recommendations by Priority

### Immediate (Critical/High)
1. **Implement plugin sandboxing** - User plugins are the highest risk
2. **Strengthen shell passthrough validation** - Current bypasses are too easy
3. **Add token encryption at rest** - Protect OAuth tokens with OS keyring
4. **Fix HMAC TOCTOU race condition** - Use atomic file operations

### Short Term (Medium)
1. Move OAuth client IDs to environment variables
2. Add per-session key derivation for session HMAC
3. Fix rate limiter circuit breaker race condition
4. Implement token refresh locking
5. Add path traversal protection in plugin loader

### Long Term (Low)
1. Migrate to proper JWT library with explicit validation options
2. Implement secure uninstall procedure
3. Add credential leakage sanitization for logs
4. Improve error message sanitization
5. Add prominent documentation about security model

---

*Report generated by: agent_security_auditor*
*Worktree: /Users/adam2/projects/code_puppy-i1j1*
*Branch: feature/code_puppy-i1j1-security-audit*
