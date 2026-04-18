import sys
import re

def add_import(lines):
    for i, line in enumerate(lines):
        if line.strip() == 'import pexpect':
            lines.insert(i+1, 'import pytest\n')
            return lines
    return lines

def add_decorators(lines):
    new_lines = []
    i = 0
    while i < len(lines):
        line = lines[i]
        new_lines.append(line)
        if line.startswith('def test_'):
            # insert decorators before this line (but we already added it)
            # we need to insert before the previous line (the blank line before function)
            # Let's insert two decorators before the function definition.
            # Ensure we have proper indentation (none).
            new_lines.insert(-1, '@pytest.mark.serial\n')
            new_lines.insert(-1, '@pytest.mark.xdist_group(name="pty-spawn")\n')
        i += 1
    return new_lines

with open('tests/integration/test_smoke.py', 'r') as f:
    lines = f.readlines()

lines = add_import(lines)
lines = add_decorators(lines)

with open('tests/integration/test_smoke.py', 'w') as f:
    f.writelines(lines)
print('Modified test_smoke.py')