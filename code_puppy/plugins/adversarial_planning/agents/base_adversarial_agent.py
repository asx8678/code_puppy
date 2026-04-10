"""Base class for all adversarial planning agents.

Provides shared behavior, structured JSON output enforcement,
evidence-labeling requirements, and role-based tool restrictions.
"""

from abc import ABC

from code_puppy import callbacks
from code_puppy.agents.base_agent import BaseAgent
from code_puppy.plugins.adversarial_planning.prompts.shared_rules import get_shared_rules


class BaseAdversarialAgent(BaseAgent, ABC):
    """Base class for all adversarial planning agents.
    
    All adversarial planning agents extend this class to get:
    - Structured JSON output enforcement
    - Shared rules from prompts/shared_rules.py
    - Evidence-labeling requirements
    - Role-based tool restrictions
    - Integration with standard prompt system (on_load_prompt)
    
    Subclasses must define:
    - ROLE_NAME: Unique identifier for this role
    - ROLE_DESCRIPTION: What this agent does
    - ALLOWED_TOOLS: List of tool names this agent can use
    - OUTPUT_SCHEMA: JSON schema description for validation
    """
    
    # Subclasses must define these class attributes
    ROLE_NAME: str = ""
    ROLE_DESCRIPTION: str = ""
    ALLOWED_TOOLS: list[str] = []
    OUTPUT_SCHEMA: str = ""  # JSON schema description
    
    @property
    def name(self) -> str:
        """Unique identifier for the agent."""
        return f"ap-{self.ROLE_NAME}"
    
    @property
    def display_name(self) -> str:
        """Human-readable name for the agent."""
        # Replace hyphens with spaces and title-case each word
        formatted = self.ROLE_NAME.replace("-", " ").title()
        return f"AP {formatted} ⚔️"
    
    @property
    def description(self) -> str:
        """Brief description of what this agent does."""
        return self.ROLE_DESCRIPTION
    
    def get_available_tools(self) -> list[str]:
        """Get list of tool names that this agent should have access to.
        
        Returns:
            List of tool names to register for this agent.
            Role-based restrictions are enforced here - planners only
            get read tools, not write tools.
        """
        return self.ALLOWED_TOOLS
    
    def get_system_prompt(self) -> str:
        """Get the complete system prompt for this agent.
        
        Assembles:
        1. Shared adversarial planning rules
        2. Role-specific prompt
        3. Output requirements and schema
        4. Evidence classification reference
        5. External tool research guidance
        6. Agent coordination instructions
        7. Skill utilization guidance
        8. Standard prompt additions from plugins (on_load_prompt)
        
        This integration with callbacks.on_load_prompt() ensures adversarial agents
        receive the same plugin-injected content as standard agents:
        - File mention support (@file syntax)
        - Agent memory integration
        - Other plugin-instructed additions
        
        Returns:
            Complete system prompt with all components integrated.
        """
        from . import get_role_prompt
        
        role_prompt = get_role_prompt(self.ROLE_NAME)
        shared_rules = get_shared_rules()
        
        # Build base prompt
        result = f"""{shared_rules}

{role_prompt}

## Output Requirements

You MUST output valid JSON matching this structure:
{self.OUTPUT_SCHEMA}

Label every material claim with evidence class: verified, inference, assumption, or unknown.
Include source locators for all verified claims (file:line or URL).

## Evidence Classification Reference

- VERIFIED (90-100): Directly observed or confirmed
  Examples: file reads, test runs, CI checks, explicit config values
  
- INFERENCE (70-89): Reasonable conclusion from verified facts
  Examples: "Based on FastAPI use [EV1], API is async-first"
  Must chain to base facts: [Based on EV1, EV2] <inference>
  
- ASSUMPTION (50-69): Accepted without verification (contains risk)
  Examples: "Prod DB will be reachable" (not tested)
  Mark explicit and plan to verify
  
- UNKNOWN (0-49): Recognized gap in knowledge
  Examples: "Stripe API version not documented"
  Must create CriticalUnknown with probe path

## External Tool Research

When external tools are available, you SHOULD use them for research:
- **Web Search**: Use for researching best practices, similar solutions, and current patterns
- **MCP/Documentation Tools**: Use for searching documentation, API references, and existing implementations
- **Other External Tools**: Use any available external tools that would help with the task
- **User Requests**: Always honor direct user requests to use external tools

Research areas:
- Best practices for the problem domain
- Similar solutions and their outcomes
- Current framework/library patterns
- Security considerations and common pitfalls
- Performance optimization strategies

## Agent Coordination

Use `list_agents` to discover available specialists that can help:
- Security review: security-auditor
- Code quality: python-reviewer, javascript-reviewer, typescript-reviewer, golang-reviewer, etc.
- QA validation: qa-expert (general), qa-kitten (web-specific)
- Implementation: code-puppy
- File permissions: file-permission-handler

When coordination is needed:
- Use `invoke_agent` to delegate specific verification tasks
- Leverage existing agent capabilities rather than reimplementing
- Prefer specialists for domain-specific work

## Skill Utilization

Before planning, check what's available:
1. Run `list_or_search_skills` to find relevant capabilities
2. Use existing skills rather than reinventing solutions
3. Skills may provide additional tools or context for your analysis
"""
        
        # Integrate with standard prompt system
        # This includes file mentions, agent memory, and other plugin additions
        prompt_additions = callbacks.on_load_prompt()
        # Filter None values — callbacks may return None or fail gracefully
        prompt_additions = [p for p in prompt_additions if p is not None]
        if prompt_additions:
            result += "\n" + "\n".join(prompt_additions)
        
        return result
