---
name: shell-safety
description: Safe shell command execution practices to prevent injection attacks and accidents
version: 1.0.0
author: Mana Team
tags: shell, security, safety, command-line, best-practices
---

# Shell Safety Skill

Expert guidance for executing shell commands safely and securely.

## When to Use

Activate this skill when:
- Running shell commands programmatically
- Processing user input for command execution
- Automating system administration tasks
- Writing scripts that execute other commands
- Reviewing code that uses shell execution

## The Golden Rule

**Never pass unsanitized user input to shell commands.**

Shell injection is one of the most common and dangerous vulnerabilities. Treat all external input as potentially malicious.

## Safe Command Execution

### 1. Prefer List Over String

```python
# DANGEROUS - shell injection possible
import os
filename = user_input  # "; rm -rf / #"
os.system(f"cat {filename}")

# SAFE - no shell interpretation
import subprocess
filename = user_input
subprocess.run(["cat", filename])  # Literally looks for file named "; rm -rf / #"
```

### 2. Use subprocess with shell=False (default)

```python
import subprocess

# Safe - no shell involved
result = subprocess.run(
    ["git", "clone", repo_url],
    capture_output=True,
    text=True,
    check=True
)
```

### 3. If You Must Use Shell=True

Only use when necessary (pipes, redirection, globbing), and always escape:

```python
import shlex
import subprocess

# Escape user input
safe_path = shlex.quote(user_provided_path)
result = subprocess.run(
    f"find {safe_path} -name '*.py' | head -n 10",
    shell=True,
    capture_output=True,
    text=True
)
```

## Input Sanitization

### Validate Before Executing

```python
import re
import shlex

def safe_filename(filename: str) -> bool:
    """Check if filename is safe to use."""
    # Block path traversal
    if ".." in filename:
        return False
    # Block absolute paths if not expected
    if filename.startswith("/"):
        return False
    # Block shell metacharacters
    dangerous = set(';|&`$(){}[]<>!\\"\'\n')
    if any(c in dangerous for c in filename):
        return False
    return True

def execute_command_safe(command: list[str]) -> None:
    """Execute command with validation."""
    if not command:
        raise ValueError("Empty command")
    
    # Ensure command exists
    import shutil
    if not shutil.which(command[0]):
        raise ValueError(f"Command not found: {command[0]}")
    
    subprocess.run(command, check=True)
```

### Whitelist Approach

```python
ALLOWED_COMMANDS = {"git", "ls", "cat", "grep", "find", "pytest"}

def run_allowed_command(cmd_name: str, args: list[str]):
    if cmd_name not in ALLOWED_COMMANDS:
        raise ValueError(f"Command '{cmd_name}' not in allowlist")
    
    subprocess.run([cmd_name] + args, check=True)
```

## Dangerous Patterns to Avoid

### ❌ String Interpolation

```python
# NEVER do this
os.system(f"rm -rf {user_input}")
subprocess.call(f"git clone {url}", shell=True)
```

### ❌ eval/exec

```python
# EXTREMELY DANGEROUS
eval(user_input)
exec(user_code)
```

### ❌ Unsafe Deserialization

```python
# Pickle can execute arbitrary code
pickle.loads(user_data)
yaml.load(user_yaml)  # Use yaml.safe_load instead
```

### ❌ SQL String Building

```python
# SQL injection
cursor.execute(f"SELECT * FROM users WHERE id = {user_id}")

# Safe
 cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
```

## Secure Alternatives

| Dangerous | Safer Alternative |
|-----------|-------------------|
| `os.system()` | `subprocess.run()` with list |
| `shell=True` | `shell=False` (default) |
| String formatting | List of arguments |
| `eval()` | `ast.literal_eval()` for literals |
| `pickle` | `json` or messagepack |
| `yaml.load()` | `yaml.safe_load()` |

## Command Whitelist Pattern

```python
from dataclasses import dataclass
from typing import Callable
import subprocess

@dataclass
class SafeCommand:
    name: str
    allowed_args: list[str]
    validator: Callable[[list[str]], bool]

class CommandRunner:
    def __init__(self):
        self._allowed: dict[str, SafeCommand] = {}
    
    def register(self, cmd: SafeCommand):
        self._allowed[cmd.name] = cmd
    
    def run(self, command: list[str]) -> subprocess.CompletedProcess:
        if not command:
            raise ValueError("Empty command")
        
        cmd_name = command[0]
        if cmd_name not in self._allowed:
            raise ValueError(f"Command not allowed: {cmd_name}")
        
        safe_cmd = self._allowed[cmd_name]
        args = command[1:]
        
        if not safe_cmd.validator(args):
            raise ValueError(f"Invalid arguments for {cmd_name}")
        
        return subprocess.run(command, capture_output=True, text=True, check=True)

# Usage
runner = CommandRunner()
runner.register(SafeCommand(
    name="git",
    allowed_args=["clone", "pull", "status"],
    validator=lambda args: args[0] in ["clone", "pull", "status"] if args else False
))
```

## Audit Checklist

Before executing any shell command:
- [ ] Is user input properly escaped/quoted?
- [ ] Is `shell=True` necessary? If so, why?
- [ ] Are all inputs validated against a whitelist?
- [ ] Is the command in a known allowlist?
- [ ] Are errors handled without leaking sensitive info?
- [ ] Is the working directory explicitly set if needed?
