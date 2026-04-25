"""API routers for Code Puppy REST endpoints.

This package contains the FastAPI router modules for different API domains:
    - config: Configuration management endpoints
    - commands: Command execution endpoints
    - sessions: Session management endpoints
    - agents: Agent-related endpoints
    - runtime: Dashboard runtime orchestration and approvals
"""

from code_puppy.api.routers import agents, commands, config, runtime, sessions

__all__ = ["config", "commands", "sessions", "agents", "runtime"]
