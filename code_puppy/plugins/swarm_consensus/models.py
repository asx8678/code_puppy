"""
Data models for Agent Swarm Consensus.

Defines the core dataclasses that represent swarm configuration,
agent results, and consensus outcomes.
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ApproachConfig:
    """Configuration for a specific reasoning approach.

    Each approach represents a different cognitive lens through which
    an agent analyzes a problem - like having team members with
    different specialties and perspectives.

    Attributes:
        name: Unique identifier for this approach (e.g., "thorough", "creative")
        system_prompt_modifier: Text to prepend/append to system prompt
        temperature_override: Optional temperature setting for this approach
        description: Human-readable description of this approach's mindset
    """

    name: str
    system_prompt_modifier: str
    temperature_override: float | None = None
    description: str = ""


@dataclass
class SwarmConfig:
    """Configuration for a swarm consensus execution.

    Attributes:
        swarm_size: Number of agents to spawn (default: 3)
        consensus_threshold: Minimum confidence to declare consensus (0.0-1.0)
        timeout_seconds: Maximum time to wait for all agents
        approaches: List of approach configs to use (or None for auto-selection)
        enable_debate: Whether to generate debate transcript
        require_unanimous: If True, all agents must agree; else use threshold
    """

    swarm_size: int = 3
    consensus_threshold: float = 0.7
    timeout_seconds: int = 300
    approaches: list[ApproachConfig] | None = None
    enable_debate: bool = True
    require_unanimous: bool = False

    def __post_init__(self):
        """Validate configuration values."""
        if self.swarm_size < 2:
            raise ValueError("Swarm size must be at least 2 for consensus")
        if not 0.0 <= self.consensus_threshold <= 1.0:
            raise ValueError("Consensus threshold must be between 0.0 and 1.0")
        if self.timeout_seconds < 10:
            raise ValueError("Timeout must be at least 10 seconds")


@dataclass
class AgentResult:
    """Result from a single agent in the swarm.

    Attributes:
        agent_name: Identifier for this agent instance
        response_text: The agent's output/answer
        confidence_score: Calculated confidence (0.0-1.0)
        approach_used: Which reasoning approach was applied
        execution_time_ms: How long the agent took to respond
        metadata: Additional agent-specific data
    """

    agent_name: str
    response_text: str
    confidence_score: float = 0.0
    approach_used: str = "default"
    execution_time_ms: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        """Ensure confidence score is normalized."""
        self.confidence_score = max(0.0, min(1.0, self.confidence_score))


@dataclass
class SwarmResult:
    """Aggregated result from the entire swarm execution.

    This is the main output from a swarm consensus run,
    containing individual agent results and the synthesized outcome.

    Attributes:
        individual_results: List of all agent responses
        consensus_reached: Whether the swarm achieved consensus
        final_answer: The synthesized/collaborative answer
        confidence_scores: Map of agent name to confidence score
        debate_transcript: Optional transcript of agent "debate"
        execution_stats: Performance and timing information
    """

    individual_results: list[AgentResult] = field(default_factory=list)
    consensus_reached: bool = False
    final_answer: str = ""
    confidence_scores: dict[str, float] = field(default_factory=dict)
    debate_transcript: str = ""
    execution_stats: dict[str, Any] = field(default_factory=dict)

    def get_best_result(self) -> AgentResult | None:
        """Return the agent result with highest confidence."""
        if not self.individual_results:
            return None
        return max(self.individual_results, key=lambda r: r.confidence_score)

    def get_average_confidence(self) -> float:
        """Calculate average confidence across all agents."""
        if not self.confidence_scores:
            return 0.0
        return sum(self.confidence_scores.values()) / len(self.confidence_scores)

    def get_agreement_ratio(self) -> float:
        """Calculate what fraction of agents agree with final answer."""
        if not self.individual_results or not self.final_answer:
            return 0.0
        agreeing = sum(
            1
            for r in self.individual_results
            if self._responses_similar(r.response_text, self.final_answer)
        )
        return agreeing / len(self.individual_results)

    @staticmethod
    def _responses_similar(a: str, b: str, threshold: float = 0.6) -> bool:
        """Simple similarity check - can be enhanced with embeddings."""
        # Normalize and compare
        a_norm = a.strip().lower()
        b_norm = b.strip().lower()
        if a_norm == b_norm:
            return True
        # Simple word overlap ratio
        a_words = set(a_norm.split())
        b_words = set(b_norm.split())
        if not a_words or not b_words:
            return False
        overlap = len(a_words & b_words)
        return overlap / max(len(a_words), len(b_words)) >= threshold
