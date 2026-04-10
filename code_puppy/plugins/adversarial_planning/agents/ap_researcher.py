"""Phase 0A Researcher Agent.

Discovers environment evidence before any planning begins.
The Researcher examines files, tests, config, and logs to build
a factual foundation that planners MUST reference.
"""

from .base_adversarial_agent import BaseAdversarialAgent


class APResearcherAgent(BaseAdversarialAgent):
    """Phase 0A - Evidence Discovery Agent.
    
    Performs initial workspace survey and evidence gathering.
    The Researcher classifies workspace readiness and identifies
    critical unknowns before any planning begins.
    
    Tools:
        - list_files: Directory exploration
        - read_file: File content reading
        - grep: Pattern search
        - ask_user_question: Clarify requirements
        - list_agents: Know available agents
        - list_or_search_skills: Find relevant skills
    
    Output:
        Phase0AOutput model with evidence, files examined,
        critical unknowns, and workspace readiness assessment.
    """
    
    ROLE_NAME = "researcher"
    ROLE_DESCRIPTION = "Discovers environment evidence before planning"
    
    # Read-only tools plus agent/skill awareness for proper coordination
    ALLOWED_TOOLS = [
        "list_files",        # Directory exploration
        "read_file",         # File content reading
        "grep",              # Pattern search
        "ask_user_question", # Clarify requirements
        "list_agents",       # Know available agents
        "list_or_search_skills",  # Find relevant skills
    ]
    
    OUTPUT_SCHEMA = """
{
    "readiness": "ready | limited | blocked",
    "confidence": 82,
    "workspace_summary": "What the environment appears to be",
    "problem_signature": "What the actual problem appears to involve",
    "evidence": [
        {
            "id": "EV1",
            "class": "verified",
            "claim": "Concrete statement about the codebase",
            "source": {
                "kind": "file",
                "locator": "path/to/file.py:12-48",
                "freshness": "2024-01-15",
                "version_or_commit": "abc123"
            },
            "confidence": 90
        }
    ],
    "files_examined": ["path/to/file.py", "config.toml"],
    "existing_patterns_to_reuse": ["Pattern found in X that should be reused"],
    "contradictions": ["X says Y but Z says W"],
    "blast_radius": ["Files/systems that may be affected by changes"],
    "critical_unknowns": [
        {
            "id": "UNK1",
            "question": "What specific thing is unknown?",
            "why_it_matters": "Why this unknown affects planning",
            "fastest_probe": "How to discover this quickly",
            "can_proceed_without": false,
            "discovery_method": "grep pattern or file to read",
            "default_assumption": "If we must assume, what value?",
            "reversibility": "reversible | hard_to_reverse | must_know_first"
        }
    ]
}

Validation:
    - readiness: Enum ready/limited/blocked
    - confidence: 0-100 integer
    - evidence[].id: Pattern EV1, EV2, ...
    - evidence[].class: Enum verified/inference/assumption/unknown
    - critical_unknowns[].id: Pattern UNK1, UNK2, ...
"""
    
    def get_system_prompt(self) -> str:
        """Get the researcher system prompt with evidence discovery rules."""
        base = super().get_system_prompt()
        
        return f"""{base}

## Phase 0A Researcher Rules

You are a FACT-FINDER, not a planner. Your job is to DISCOVER, not decide.

### Evidence Discovery Process

1. START with workspace exploration
   - List root directory structure
   - Identify key config files (pyproject.toml, package.json, etc.)
   - Find test directories and CI configuration

2. READ critical files
   - Entry points (main.py, app.py, index.js)
   - Configuration (dependencies, settings)
   - Existing patterns to potentially reuse

3. GREP for patterns
   - Search for relevant code patterns
   - Find existing implementations of similar features
   - Identify dependencies and imports

4. CLASSIFY everything found
   - VERIFIED: What you directly observed
   - INFERENCE: Reasonable conclusions from facts
   - ASSUMPTION: What you're accepting without proof
   - UNKNOWN: Gaps you identify

### Stop Conditions - Global Stop if ANY:

❌ Illegal access request (outside workspace)
❌ Unrecoverable parse failure on critical file  
❌ Contradiction that invalidates problem understanding
❌ User explicitly requests stop

### Deliverable Requirements

✓ All evidence IDs follow EV1, EV2, ... pattern
✓ All critical unknown IDs follow UNK1, UNK2, ... pattern
✓ Every verified claim has a source locator (file:line)
✓ Critical unknowns include fastest_probe path
✓ Workspace summary captures the environment type
✓ Problem signature describes what needs to be done
"""
