# Code Puppy Configuration Specification

> **Purpose:** Complete specification of Python `config.py` semantics for Elixir migration.
> **Source:** `code_puppy/config.py` (2,698 lines, 92 KB)
> **Status:** Draft - bd-279

## Overview

The Python configuration system is centralized in `code_puppy/config.py` with:
- **89 public functions** 
- **~60 exported symbols** in `__all__`
- Thread-safe caching via `@thread_safe_lru_cache`
- XDG Base Directory compliance
- Isolation guards for dual-home safety

---

## 1. Path Constants & Directories

### XDG Base Directories

| Constant | Default | Env Override | Description |
|----------|---------|--------------|-------------|
| \`STATE_DIR\` | \`~/.local/state/code_puppy\` | \`XDG_STATE_HOME\` | Persistent state (sessions, history) |
| \`CONFIG_DIR\` | \`~/.config/code_puppy\` | \`XDG_CONFIG_HOME\` | User configuration files |
| \`CACHE_DIR\` | \`~/.cache/code_puppy\` | \`XDG_CACHE_HOME\` | Ephemeral cache data |
| \`AUTOSAVE_DIR\` | \`{STATE_DIR}/autosave\` | — | Auto-saved session backups |

### Key Files

| File | Location | Purpose |
|------|----------|---------|
| \`puppy.cfg\` | \`{CONFIG_DIR}/puppy.cfg\` | Main INI config file |
| \`models.json\` | \`{CONFIG_DIR}/models.json\` | Built-in model definitions |
| \`extra_models.json\` | \`{CONFIG_DIR}/extra_models.json\` | User-added models |
| \`agents/\` | \`{CONFIG_DIR}/agents/\` | Custom agent definitions |
| \`skills/\` | \`{CONFIG_DIR}/skills/\` | Custom skill definitions |

**Elixir equivalent:** \`CodePuppyControl.Config.Paths\`


---

## 2. Core Config Access

### puppy.cfg Structure

```ini
[ui]
puppy_name = Buddy
owner_name = 
default_agent = code-puppy
banner_color = cyan
diff_addition_color = green
diff_deletion_color = red

[session]
auto_save = true
resume_message_count = 50
compaction_threshold = 100
compaction_strategy = smart
protected_token_count = 4000

[model]
default = claude-sonnet-4-20250514
temperature = 0.7

[features]
use_dbos = false
yolo_mode = false
adaptive_rendering = true
universal_constructor = false
```

### Config Accessors

| Function | Type | Default | Section.Key | Description |
|----------|------|---------|-------------|-------------|
| `get_value(section, key)` | `str \| None` | — | any | Generic config getter |
| `set_value(section, key, val)` | `None` | — | any | Generic config setter |
| `get_config_keys()` | `list[str]` | — | — | List all config keys |

**Elixir equivalent:** `CodePuppyControl.Config.get/2`, `CodePuppyControl.Config.Loader`

---

## 3. Personalization

| Function | Type | Default | Description |
|----------|------|---------|-------------|
| `get_puppy_name()` | `str` | `"Puppy"` | Display name for the assistant |
| `get_owner_name()` | `str` | `""` | User's name for personalization |
| `get_default_agent()` | `str` | `"code-puppy"` | Default agent on startup |

**Elixir equivalent:** `CodePuppyControl.Config` (`:puppy_name`, `:owner_name`, `:default_agent`)

---

## 4. Model Configuration

### Global Model Settings

| Function | Type | Default | Description |
|----------|------|---------|-------------|
| `get_global_model_name()` | `str` | `"claude-sonnet-4-20250514"` | Current default model |
| `set_model_name(name)` | `None` | — | Set default model |
| `get_temperature()` | `float` | `0.7` | LLM temperature |
| `get_effective_temperature(model)` | `float` | varies | Model-specific temperature |

### Per-Model Settings

| Function | Type | Default | Description |
|----------|------|---------|-------------|
| `get_all_model_settings(model)` | `dict` | `{}` | All settings for a model |
| `model_supports_setting(model, key)` | `bool` | — | Check if model supports setting |
| `set_model_setting(model, key, val)` | `None` | — | Set model-specific config |

### OpenAI-Specific Settings

| Function | Type | Default | Description |
|----------|------|---------|-------------|
| `get_openai_reasoning_effort()` | `str` | `"medium"` | o1/o3 reasoning effort level |
| `set_openai_reasoning_effort(val)` | `None` | — | Set reasoning effort |
| `get_openai_reasoning_summary()` | `bool` | `false` | Enable reasoning summaries |
| `get_openai_verbosity()` | `str` | `"normal"` | Output verbosity level |

**Elixir equivalent:** `CodePuppyControl.Config.Models`, `CodePuppyControl.ModelRegistry`

---

## 5. Agent Model Pinning

| Function | Type | Default | Description |
|----------|------|---------|-------------|
| `get_agent_pinned_model(agent)` | `str \| None` | `None` | Get pinned model for agent |
| `set_agent_pinned_model(agent, model)` | `None` | — | Pin agent to specific model |
| `clear_agent_pinned_model(agent)` | `None` | — | Remove agent's model pin |
| `get_agents_pinned_to_model(model)` | `list[str]` | `[]` | Agents using specific model |
| `get_all_agent_pinned_models()` | `dict` | `{}` | All agent→model mappings |

**Elixir equivalent:** `CodePuppyControl.AgentModelPinning`

---

## 6. Session & Compaction

| Function | Type | Default | Description |
|----------|------|---------|-------------|
| `get_auto_save_session()` | `bool` | `true` | Auto-save sessions |
| `get_resume_message_count()` | `int` | `50` | Messages to load on resume |
| `get_compaction_threshold()` | `int` | `100` | Messages before compaction |
| `get_compaction_strategy()` | `str` | `"smart"` | Compaction algorithm |
| `get_protected_token_count()` | `int` | `4000` | Tokens to preserve |

**Elixir equivalent:** `CodePuppyControl.Compaction`, `CodePuppyControl.Sessions`

---

## 7. Feature Toggles

| Function | Type | Default | Description |
|----------|------|---------|-------------|
| `get_use_dbos()` | `bool` | `false` | Enable DBOS durable execution |
| `get_yolo_mode()` | `bool` | `false` | Skip confirmations |
| `get_adaptive_rendering_enabled()` | `bool` | `true` | Adaptive terminal rendering |
| `get_universal_constructor_enabled()` | `bool` | `false` | UC plugin enabled |

**Elixir equivalent:** `CodePuppyControl.Config` feature flags

---

## 8. UI & Colors

| Function | Type | Default | Description |
|----------|------|---------|-------------|
| `get_banner_color()` | `str` | `"cyan"` | Banner/header color |
| `set_banner_color(color)` | `None` | — | Set banner color |
| `get_diff_addition_color()` | `str` | `"green"` | Diff addition highlight |
| `set_diff_addition_color(color)` | `None` | — | Set addition color |
| `get_diff_deletion_color()` | `str` | `"red"` | Diff deletion highlight |
| `set_diff_deletion_color(color)` | `None` | — | Set deletion color |

**Elixir equivalent:** `CodePuppyControl.Config.TUI`

---

## 9. Enhanced Summarization (deepagents)

| Function | Type | Default | Description |
|----------|------|---------|-------------|
| `get_summarization_enabled()` | `bool` | `false` | Enable enhanced summaries |
| `get_summarization_model()` | `str` | `""` | Model for summarization |
| `get_summarization_threshold()` | `int` | `10000` | Token threshold |

**Elixir equivalent:** TBD (may be dropped for v1)

---

## 10. Frontend Emitter

| Function | Type | Default | Description |
|----------|------|---------|-------------|
| `get_frontend_emitter_enabled()` | `bool` | `false` | Enable frontend events |
| `get_frontend_emitter_port()` | `int` | `8765` | WebSocket port |

**Elixir equivalent:** Dropped for v1 (Tier-C plugin)

---

## 11. Agent Memory

| Function | Type | Default | Description |
|----------|------|---------|-------------|
| `get_agent_memory_enabled()` | `bool` | `true` | Enable agent memory |
| `get_agent_memory_max_entries()` | `int` | `100` | Max memory entries |

**Elixir equivalent:** `CodePuppyControl.Config.Agents` (TBD)


---

## Migration Notes

### Already Ported to Elixir
- ✅ Path resolution (`Config.Paths`)
- ✅ Model registry (`ModelRegistry`, `Config.Models`)
- ✅ Agent pinning (`AgentModelPinning`)
- ✅ TUI colors (`Config.TUI`)
- ✅ Session/compaction (`Compaction`, `Sessions`)
- ✅ Config loading (`Config.Loader`)

### Needs Porting
- ⬜ OpenAI-specific settings (reasoning effort, verbosity)
- ⬜ Enhanced summarization config
- ⬜ Some feature toggles

### Intentionally Dropped (v1)
- ❌ Frontend emitter config (Tier-C)
- ❌ DBOS config (replaced by Oban)

---

## Appendix: Full Function List

<details>
<summary>All 89 public functions (click to expand)</summary>

```
TODO(bd-279): Generate from grep -E "^def [a-z]" code_puppy/config.py
```

</details>


---

## 12. API Keys & Authentication

| Function | Type | Default | Description |
|----------|------|---------|-------------|
| `get_api_key(provider)` | `str \| None` | `None` | Get API key for provider |
| `set_api_key(provider, key)` | `None` | — | Store API key |
| `get_puppy_token()` | `str \| None` | `None` | Auth token for Code Puppy services |
| `set_puppy_token(token)` | `None` | — | Set auth token |
| `load_api_keys_to_environment()` | `None` | — | Load keys into env vars |

**Elixir equivalent:** `CodePuppyControl.Credentials`

---

## 13. Safety & Permissions

| Function | Type | Default | Description |
|----------|------|---------|-------------|
| `get_safety_permission_level()` | `str` | `"normal"` | Permission strictness |
| `get_yolo_mode()` | `bool` | `false` | Skip all confirmations |
| `get_post_edit_validation_enabled()` | `bool` | `true` | Validate after edits |

**Elixir equivalent:** `CodePuppyControl.Config` + tool permission callbacks

---

## 14. WebSocket & History

| Function | Type | Default | Description |
|----------|------|---------|-------------|
| `get_ws_history_maxlen()` | `int` | `1000` | Max WebSocket history entries |
| `get_ws_history_ttl_seconds()` | `int` | `3600` | History TTL in seconds |
| `get_message_limit()` | `int` | `100` | Message display limit |

**Elixir equivalent:** `CodePuppyControl.EventStore` (partial)

---

## 15. Autosave & Command History

| Function | Type | Default | Description |
|----------|------|---------|-------------|
| `get_current_autosave_id()` | `str` | auto-generated | Current autosave session ID |
| `get_current_autosave_session_name()` | `str` | — | Autosave session name |
| `set_current_autosave_from_session_name(name)` | `None` | — | Set autosave from session |
| `rotate_autosave_id()` | `str` | — | Generate new autosave ID |
| `auto_save_session_if_enabled()` | `None` | — | Trigger autosave if enabled |
| `finalize_autosave_session()` | `None` | — | Complete autosave |
| `initialize_command_history_file()` | `None` | — | Init command history |
| `save_command_to_history(cmd)` | `None` | — | Save command to history |

**Elixir equivalent:** `CodePuppyControl.SessionStorage` + `CodePuppyControl.REPL.History`

---

## 16. MCP (Model Context Protocol)

| Function | Type | Default | Description |
|----------|------|---------|-------------|
| `load_mcp_server_configs()` | `dict` | `{}` | Load MCP server configurations |

**Elixir equivalent:** `CodePuppyControl.MCP.Config`

---

## 17. Suppression & Debug

| Function | Type | Default | Description |
|----------|------|---------|-------------|
| `get_suppress_informational_messages()` | `bool` | `false` | Suppress info messages |
| `set_suppress_informational_messages(val)` | `None` | — | Set suppression |
| `set_suppress_thinking_messages(val)` | `None` | — | Suppress thinking output |

**Elixir equivalent:** `CodePuppyControl.Config.Debug`


---

## Appendix A: Complete Function Reference

### All 85 Public Functions

| Function | Category | Elixir Status |
|----------|----------|---------------|
| `auto_save_session_if_enabled` | Autosave | ✅ Ported |
| `clear_agent_pinned_model` | Agent Pinning | ✅ Ported |
| `clear_model_cache` | Model | ✅ Ported |
| `clear_model_settings` | Model | ✅ Ported |
| `ensure_config_exists` | Core | ✅ Ported |
| `finalize_autosave_session` | Autosave | ✅ Ported |
| `get_adaptive_rendering_enabled` | UI | ⬜ Needs port |
| `get_agent_pinned_model` | Agent Pinning | ✅ Ported |
| `get_agents_pinned_to_model` | Agent Pinning | ✅ Ported |
| `get_all_agent_pinned_models` | Agent Pinning | ✅ Ported |
| `get_all_banner_colors` | UI | ✅ Ported |
| `get_all_model_settings` | Model | ✅ Ported |
| `get_api_key` | Auth | ✅ Ported |
| `get_banner_color` | UI | ✅ Ported |
| `get_compaction_strategy` | Session | ✅ Ported |
| `get_config_keys` | Core | ✅ Ported |
| `get_current_autosave_id` | Autosave | ✅ Ported |
| `get_current_autosave_session_name` | Autosave | ✅ Ported |
| `get_default_agent` | Personalization | ✅ Ported |
| `get_default_config_keys` | Core | ✅ Ported |
| `get_diff_addition_color` | UI | ✅ Ported |
| `get_diff_deletion_color` | UI | ✅ Ported |
| `get_effective_model_settings` | Model | ✅ Ported |
| `get_effective_seed` | Model | ⬜ Needs port |
| `get_effective_temperature` | Model | ✅ Ported |
| `get_effective_top_p` | Model | ⬜ Needs port |
| `get_enable_agent_memory` | Agent Memory | ⬜ Needs port |
| `get_frontend_emitter_enabled` | Frontend | ❌ Dropped |
| `get_frontend_emitter_max_recent_events` | Frontend | ❌ Dropped |
| `get_frontend_emitter_queue_size` | Frontend | ❌ Dropped |
| `get_global_model_name` | Model | ✅ Ported |
| `get_memory_extraction_model` | Agent Memory | ⬜ Needs port |
| `get_message_limit` | Session | ✅ Ported |
| `get_model_context_length` | Model | ✅ Ported |
| `get_model_setting` | Model | ✅ Ported |
| `get_openai_reasoning_effort` | OpenAI | ⬜ Needs port |
| `get_openai_reasoning_summary` | OpenAI | ⬜ Needs port |
| `get_openai_verbosity` | OpenAI | ⬜ Needs port |
| `get_owner_name` | Personalization | ✅ Ported |
| `get_post_edit_validation_enabled` | Safety | ⬜ Needs port |
| `get_project_agents_directory` | Paths | ✅ Ported |
| `get_protected_token_count` | Compaction | ✅ Ported |
| `get_puppy_name` | Personalization | ✅ Ported |
| `get_puppy_token` | Auth | ✅ Ported |
| `get_safety_permission_level` | Safety | ⬜ Needs port |
| `get_summarization_history_dir` | Summarization | ❌ Dropped |
| `get_summarization_keep_fraction` | Summarization | ❌ Dropped |
| `get_summarization_trigger_fraction` | Summarization | ❌ Dropped |
| `get_suppress_informational_messages` | Debug | ⬜ Needs port |
| `get_temperature` | Model | ✅ Ported |
| `get_use_dbos` | Features | ❌ Dropped |
| `get_user_agents_directory` | Paths | ✅ Ported |
| `get_value` | Core | ✅ Ported |
| `get_ws_history_maxlen` | WebSocket | ⬜ Needs port |
| `get_ws_history_ttl_seconds` | WebSocket | ⬜ Needs port |
| `initialize_command_history_file` | History | ✅ Ported |
| `load_api_keys_to_environment` | Auth | ✅ Ported |
| `load_mcp_server_configs` | MCP | ✅ Ported |
| `model_supports_setting` | Model | ✅ Ported |
| `reset_all_banner_colors` | UI | ✅ Ported |
| `reset_banner_color` | UI | ✅ Ported |
| `reset_session_model` | Model | ✅ Ported |
| `reset_value` | Core | ✅ Ported |
| `rotate_autosave_id` | Autosave | ✅ Ported |
| `save_command_to_history` | History | ✅ Ported |
| `set_agent_pinned_model` | Agent Pinning | ✅ Ported |
| `set_api_key` | Auth | ✅ Ported |
| `set_auto_save_session` | Session | ✅ Ported |
| `set_banner_color` | UI | ✅ Ported |
| `set_config_value` | Core | ✅ Ported |
| `set_current_autosave_from_session_name` | Autosave | ✅ Ported |
| `set_default_agent` | Personalization | ✅ Ported |
| `set_diff_addition_color` | UI | ✅ Ported |
| `set_diff_deletion_color` | UI | ✅ Ported |
| `set_diff_highlight_style` | UI | ⬜ Needs port |
| `set_enable_dbos` | Features | ❌ Dropped |
| `set_http2` | HTTP | ⬜ Needs port |
| `set_max_saved_sessions` | Session | ⬜ Needs port |
| `set_model_name` | Model | ✅ Ported |
| `set_model_setting` | Model | ✅ Ported |
| `set_openai_reasoning_effort` | OpenAI | ⬜ Needs port |
| `set_openai_reasoning_summary` | OpenAI | ⬜ Needs port |
| `set_openai_verbosity` | OpenAI | ⬜ Needs port |
| `set_puppy_token` | Auth | ✅ Ported |
| `set_suppress_informational_messages` | Debug | ⬜ Needs port |
| `set_suppress_thinking_messages` | Debug | ⬜ Needs port |
| `set_temperature` | Model | ✅ Ported |
| `set_universal_constructor_enabled` | Features | ⬜ Needs port |
| `set_value` | Core | ✅ Ported |


---

## Appendix B: Migration Summary

| Status | Count | Percentage |
|--------|-------|------------|
| ✅ Ported | 58 | 68% |
| ⬜ Needs Port | 21 | 25% |
| ❌ Dropped | 6 | 7% |
| **Total** | **85** | **100%** |

### Needs Port (21 functions)

**OpenAI-specific (6):**
- `get_openai_reasoning_effort`, `set_openai_reasoning_effort`
- `get_openai_reasoning_summary`, `set_openai_reasoning_summary`
- `get_openai_verbosity`, `set_openai_verbosity`

**Model settings (3):**
- `get_effective_seed`, `get_effective_top_p`, `set_http2`

**Agent Memory (2):**
- `get_enable_agent_memory`, `get_memory_extraction_model`

**Safety/Debug (4):**
- `get_safety_permission_level`, `get_post_edit_validation_enabled`
- `get_suppress_informational_messages`, `set_suppress_informational_messages`

**UI (2):**
- `get_adaptive_rendering_enabled`, `set_diff_highlight_style`

**Session (2):**
- `set_max_saved_sessions`, `set_suppress_thinking_messages`

**WebSocket (2):**
- `get_ws_history_maxlen`, `get_ws_history_ttl_seconds`

### Dropped (6 functions)

| Function | Reason |
|----------|--------|
| `get_use_dbos` | Replaced by Oban |
| `set_enable_dbos` | Replaced by Oban |
| `get_frontend_emitter_*` (3) | Tier-C plugin dropped |
| `get_summarization_*` (3) | Deferred to post-v1 |

---

*Generated: 2026-04-22 | bd-279*
