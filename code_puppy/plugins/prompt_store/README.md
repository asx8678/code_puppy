# Prompt Store Plugin

User-editable prompt templates for code_puppy agents. Customize system prompts without writing Python code.

## Overview

The Prompt Store plugin provides a JSON-backed store for custom prompt templates, allowing you to:
- Create and edit custom system prompts for any agent
- Switch between different prompts per agent
- Duplicate and modify existing templates
- Keep custom prompts safely separate from built-in defaults

This **complements** (not replaces) the existing callback-based prompt injection used by other plugins like `agent_skills`.

## Storage Location

Templates are stored in `~/.code_puppy/prompt_store.json`

You can customize this via the `PUPPY_PROMPT_STORE` environment variable.

## Commands

All commands are accessed via `/prompts`:

| Command | Description |
|---------|-------------|
| `/prompts list [agent]` | List all templates (optionally filter by agent name) |
| `/prompts show <id>` | Show full content of a specific template |
| `/prompts create <agent> <name>` | Create a new template (opens `$EDITOR`) |
| `/prompts edit <id>` | Edit an existing user template |
| `/prompts duplicate <id> <new-name>` | Create an editable copy of any template |
| `/prompts delete <id>` | Delete a user template |
| `/prompts activate <agent> <id>` | Set a template as active for an agent |
| `/prompts reset <agent>` | Revert to the default system prompt |
| `/prompts help` | Show this help |

## Example Workflow

```bash
# Create a custom prompt for code-puppy
/prompts create code-puppy "Concise Mode"
# [your editor opens - write a shorter system prompt, save, exit]

# Activate it
/prompts activate code-puppy code-puppy.custom-1

# Use the agent - it now uses your custom prompt
# To revert to default:
/prompts reset code-puppy
```

## Safety Notes

- **Built-in defaults are always preserved** - They cannot be deleted or modified
- **User templates are fully editable** - Create, update, delete as needed
- **Atomic writes** - Store updates are atomic (temp file + rename)
- **Malformed store recovery** - If the JSON gets corrupted, it's backed up and reset

## Integration

The plugin hooks into the `load_prompt` callback (early-stage prompt assembly). When an agent runs:

1. If you've activated a custom prompt for that agent → it's loaded via `load_prompt`
2. Otherwise → no contribution from prompt_store (agent's default is used)
3. Other plugins (like `agent_skills`, `repo_compass`) hook into `get_model_system_prompt` 
   to enhance the system prompt with their content

This architecture ensures:
- **prompt_store** provides the **base template** (via `load_prompt`)
- **agent_skills** adds available skills information
- **repo_compass** adds project context
- All contributions coexist in the final prompt

The Prompt Store returns `None` when there's no active custom template, letting other handlers process normally.

## Environment Variables

- `PUPPY_PROMPT_STORE`: Override the default store path
- `EDITOR` or `VISUAL`: Specify your preferred editor for `/prompts create` and `/prompts edit`
  - Supports editors with arguments (e.g., `EDITOR="code --wait"`, `VISUAL="subl -n -w"`)

## Editor Comments

When creating or editing templates in your editor, lines starting with `# // ` are treated as editor comments and stripped from the final content. This preserves:
- Markdown headers (e.g., `# Heading`, `## Subheader`)
- Regular code comments (e.g., `# TODO: fix this`)
- All other lines starting with `#`

Example:
```
# // This line is stripped (editor comment)
# This line is preserved (regular comment)
# Heading
This is my prompt content.
```
