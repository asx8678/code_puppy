"""Code Puppy Scheduler - Run scheduled prompts automatically.

# DEPRECATED: Use Elixir scheduler. This module is retained for backward compatibility only.
# The Elixir scheduler at CodePuppyControl.Scheduler is now the production implementation.
# This Python module will be removed once all callers are migrated (tracked).

This module provides a cross-platform scheduler daemon that executes
Code Puppy prompts on configurable schedules (intervals, cron expressions).

Components:
    - config: Task definitions and JSON persistence
    - daemon: Background scheduler process
    - executor: Task execution logic
    - platform: Cross-platform daemon management

DEPRECATED: All new code should use the Elixir scheduler via transport layer.
"""

import warnings

# Emit deprecation warning when this module is imported
warnings.warn(
    "code_puppy.scheduler is deprecated. Use the Elixir scheduler (CodePuppyControl.Scheduler) instead. "
    "This module is retained for backward compatibility and will be removed in a future release. "
    "See documentation for details.",
    DeprecationWarning,
    stacklevel=2,
)

from code_puppy.scheduler.config import (
    SCHEDULER_LOG_DIR,
    SCHEDULER_PID_FILE,
    SCHEDULES_FILE,
    ScheduledTask,
    add_task,
    delete_task,
    get_task,
    load_tasks,
    save_tasks,
    toggle_task,
    update_task,
)
from code_puppy.scheduler.daemon import start_daemon_background

__all__ = [
    "ScheduledTask",
    "load_tasks",
    "save_tasks",
    "add_task",
    "update_task",
    "delete_task",
    "get_task",
    "toggle_task",
    "start_daemon_background",
    "SCHEDULES_FILE",
    "SCHEDULER_PID_FILE",
    "SCHEDULER_LOG_DIR",
]
