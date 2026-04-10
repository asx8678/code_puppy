"""Base class for adversarial planning phases.

Provides common functionality for all planning phases including
context management, agent invocation, and output handling.

TODO(code_puppy-790): Implement base phase class with full functionality
"""

import logging
from abc import ABC, abstractmethod
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from ..models import PlanningSession

logger = logging.getLogger(__name__)


class BasePhase(ABC):
    """Abstract base class for planning phases.
    
    Each phase in the adversarial planning workflow inherits from
    this base class to ensure consistent implementation patterns.
    """
    
    # Phase identifier (e.g., "0A", "1A", "2B")
    phase_id: str = ""
    
    # Phase display name
    phase_name: str = ""
    
    # Output model class for this phase
    output_model: type | None = None
    
    def __init__(self, session: "PlanningSession"):
        """Initialize phase with planning session context.
        
        Args:
            session: The active planning session
        """
        self.session = session
        self.logger = logging.getLogger(
            f"{__name__}.{self.__class__.__name__}"
        )
    
    @abstractmethod
    def get_system_prompt(self) -> str:
        """Get the system prompt for this phase's agent.
        
        Returns:
            Complete system prompt string
        """
        raise NotImplementedError
    
    @abstractmethod
    def get_context(self) -> dict[str, Any]:
        """Gather context needed for this phase.
        
        Returns:
            Dictionary of context variables for prompt rendering
        """
        raise NotImplementedError
    
    @abstractmethod
    def execute(self) -> Any:
        """Execute this planning phase.
        
        Invokes the appropriate agent, processes the response,
        validates output against the model, and updates session state.
        
        Returns:
            Phase output (instance of output_model)
        """
        raise NotImplementedError
    
    def validate_output(self, output: Any) -> tuple[bool, list[str]]:
        """Validate phase output against the expected model.
        
        Args:
            output: The output to validate
            
        Returns:
            Tuple of (is_valid, list of validation issues)
        """
        if self.output_model is None:
            return True, []
        
        try:
            if isinstance(output, self.output_model):
                return True, []
            else:
                # Attempt to convert to model
                validated = self.output_model.model_validate(output)
                return True, []
        except Exception as e:
            return False, [str(e)]
    
    def update_session(self, output: Any) -> None:
        """Update the session with phase output.
        
        Args:
            output: Validated phase output
        """
        # Subclasses override to store output in appropriate session field
        self.logger.debug(f"Updating session with {self.phase_id} output")
    
    def check_prerequisites(self) -> tuple[bool, str]:
        """Check if phase prerequisites are met.
        
        Returns:
            Tuple of (prereqs_met, reason)
        """
        # Default: no prerequisites
        return True, ""
