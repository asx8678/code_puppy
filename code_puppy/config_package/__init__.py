"""Configuration package for code-puppy (future migration target).

This package is the target structure for refactoring config.py.
Currently NOT active - the original config.py remains the source of truth.

To migrate gradually:
1. Move functions from config.py to appropriate submodules
2. Update config.py to import from this package
3. Eventually rename config_package -> config

Submodules:
- paths: Path resolution and directory helpers
- feature_flags: Feature toggles and flags
- settings: Model settings and configuration values
"""

# This module is intentionally minimal - it's a placeholder for future migration.
# The original config.py (1773 lines) should be gradually refactored here.

__all__ = []
