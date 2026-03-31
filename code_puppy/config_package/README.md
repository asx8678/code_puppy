# Config Package Structure (Future Migration)

This package is the **target structure** for refactoring `config.py`.

## Current Status
- Original `config.py`: 1773 lines, 99 functions
- This package: Placeholder structure for gradual migration

## Intended Structure

```
config_package/           # Will become config/ after full migration
├── __init__.py           # Re-exports for backward compatibility
├── paths.py              # Path resolution & directory helpers
│   ├── CONFIG_DIR, DATA_DIR, etc.
│   ├── ensure_directories_exist()
│   └── get_user_agents_directory()
├── feature_flags.py      # Feature toggles
│   ├── get_use_dbos()
│   ├── get_pack_agents_enabled()
│   └── get_yolo_mode()
├── token_budget.py       # Token management
│   ├── get_protected_token_count()
│   └── get_message_limit()
└── settings.py           # Model & app settings
    ├── get_global_model_name()
    ├── get_temperature()
    └── set_model_name()
```

## Migration Plan

1. **Phase 1** (Current): Create module stubs, establish import patterns
2. **Phase 2**: Move path functions to `paths.py`, re-export from `config.py`
3. **Phase 3**: Move feature flags to `feature_flags.py`
4. **Phase 4**: Move settings to `settings.py`
5. **Phase 5**: Rename `config_package` -> `config`, update all imports

## Backward Compatibility

During migration, `config.py` will import from submodules and re-export
to maintain `from code_puppy.config import X` compatibility.
