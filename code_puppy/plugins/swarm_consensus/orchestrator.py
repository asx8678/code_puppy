"""
Core orchestration logic for Agent Swarm Consensus.

The SwarmOrchestrator manages the lifecycle of a swarm execution:
spawning agents with different approaches, executing them in parallel,
aggregating results, and synthesizing consensus.
"""

import asyncio
import copy
import logging
import time
import uuid
from typing import TYPE_CHECKING, Any

from .approaches import apply_approach, reset_agent_approach
from .config import get_swarm_timeout_seconds
from .consensus import detect_consensus, generate_debate_transcript, synthesize_results
from .models import AgentResult, SwarmConfig, SwarmResult
from .scoring import calculate_confidence, score_by_consistency

if TYPE_CHECKING:
    from code_puppy.agents.base_agent import BaseAgent

logger = logging.getLogger(__name__)

# Respect Pack Leader parallelism limit
MAX_PARALLEL_AGENTS = 2


class SwarmOrchestrator:
    """Orchestrates multi-agent swarm execution with consensus.

    The orchestrator manages spawning agents with different reasoning
    approaches, running them in parallel (respecting MAX_PARALLEL_AGENTS),
    and synthesizing their outputs into a consensus answer.

    Example:
        config = SwarmConfig(swarm_size=3, consensus_threshold=0.7)
        orchestrator = SwarmOrchestrator(config)
        result = await orchestrator.execute_swarm(
            task_prompt="Refactor this function",
            task_context={"file_path": "example.py"}
        )
    """

    def __init__(self, config: SwarmConfig | None = None):
        """Initialize the orchestrator.

        Args:
            config: Swarm configuration (uses defaults if None)
        """
        self.config = config or SwarmConfig()
        self._agents: list["BaseAgent"] = []
        self._execution_start_time: float = 0.0

    async def execute_swarm(
        self,
        task_prompt: str,
        task_context: dict[str, Any] | None = None,
        task_type: str = "default",
    ) -> SwarmResult:
        """Execute the full swarm consensus workflow.

        This is the main entry point for swarm execution. It:
        1. Spawns agents with different reasoning approaches
        2. Executes them in parallel (respecting MAX_PARALLEL_AGENTS)
        3. Scores and aggregates results
        4. Detects consensus and synthesizes final answer
        5. Generates debate transcript

        Args:
            task_prompt: The main task to solve
            task_context: Additional context (file paths, etc.)
            task_type: Type of task for approach selection

        Returns:
            SwarmResult: Complete results including consensus
        """
        task_context = task_context or {}
        self._execution_start_time = time.time()

        logger.info(
            f"Starting swarm execution: size={self.config.swarm_size}, "
            f"threshold={self.config.consensus_threshold}"
        )

        try:
            # Step 1: Spawn agents with approaches
            approaches = self._select_approaches(task_type)
            agents = self._spawn_agents(approaches)

            # Step 2: Execute agents in parallel with rate limiting
            agent_results = await self._execute_agents_parallel(agents, task_prompt, task_context)

            # Step 3: Score and aggregate
            swarm_result = self._aggregate_results(agent_results)

            # Step 4: Generate debate transcript if enabled
            if self.config.enable_debate:
                swarm_result.debate_transcript = generate_debate_transcript(agent_results)

            # Cleanup: reset agent configurations
            self._cleanup_agents()

            elapsed_ms = (time.time() - self._execution_start_time) * 1000
            swarm_result.execution_stats = {
                "total_time_ms": elapsed_ms,
                "agents_spawned": len(agents),
                "successful_runs": len([r for r in agent_results if r.response_text]),
                "task_type": task_type,
            }

            logger.info(
                f"Swarm execution complete: consensus={swarm_result.consensus_reached}, "
                f"time={elapsed_ms:.0f}ms"
            )

            return swarm_result

        except Exception as e:
            logger.exception("Swarm execution failed")
            self._cleanup_agents()
            return SwarmResult(
                individual_results=[],
                consensus_reached=False,
                final_answer=f"Swarm execution failed: {e}",
                execution_stats={"error": str(e)},
            )

    def _select_approaches(self, task_type: str) -> list[Any]:
        """Select reasoning approaches for this task.

        Args:
            task_type: Type of task being executed

        Returns:
            list: Approach configurations to use
        """
        if self.config.approaches:
            return self.config.approaches[: self.config.swarm_size]

        from .approaches import get_approaches_for_task

        return get_approaches_for_task(task_type, self.config.swarm_size)

    @staticmethod
    def _agent_identity(agent: "BaseAgent") -> str:
        """Get the swarm identity for an agent.

        Returns the _swarm_identity attribute if set (for deepcopied
        swarm agents), otherwise falls back to the agent's own name.
        """
        return getattr(agent, "_swarm_identity", agent.name)

    def _spawn_agents(self, approaches: list[Any]) -> list["BaseAgent"]:
        """Spawn agents with different reasoning approaches.

        Args:
            approaches: List of approach configurations

        Returns:
            list: Configured agent instances
        """
        agents: list["BaseAgent"] = []

        # Import agent loading functions here to avoid circular imports
        from code_puppy.agents.agent_manager import get_current_agent_name, load_agent

        # Get the current agent name to use as the base for swarm agents
        try:
            base_agent_name = get_current_agent_name()
        except Exception:
            base_agent_name = "code-puppy"  # Fallback to default agent

        for i, approach in enumerate(approaches):
            try:
                # Load a fresh agent instance from the registry
                agent = load_agent(base_agent_name)

                # Deep copy to avoid mutating shared agent instances.
                # Without this, concurrent swarm executions would race on
                # system_prompt and temperature attributes.
                agent = copy.deepcopy(agent)

                # Assign a fresh ID so deepcopied agents don't share UUIDs.
                agent.id = str(uuid.uuid7())

                # Use a separate identity attribute instead of overwriting
                # the read-only ``name`` property on BaseAgent.
                agent._swarm_identity = f"swarm_agent_{i}_{approach.name}"

                # Apply approach configuration
                apply_approach(agent, approach)

                agents.append(agent)
                logger.debug(
                    f"Spawned agent {self._agent_identity(agent)} "
                    f"with approach {approach.name}"
                )

            except Exception as e:
                logger.warning(
                    f"Failed to spawn agent {i} with approach {approach.name}: {e}"
                )

        self._agents = agents
        return agents

    async def _execute_agents_parallel(
        self,
        agents: list["BaseAgent"],
        task_prompt: str,
        task_context: dict[str, Any],
    ) -> list[AgentResult]:
        """Execute all agents in parallel with rate limiting.

        Respects MAX_PARALLEL_AGENTS to avoid overwhelming the system.

        Args:
            agents: Agents to execute
            task_prompt: The task prompt
            task_context: Additional context

        Returns:
            list: Agent results
        """
        timeout = get_swarm_timeout_seconds()
        semaphore = asyncio.Semaphore(MAX_PARALLEL_AGENTS)

        async def run_with_semaphore(agent: "BaseAgent") -> AgentResult:
            async with semaphore:
                return await self._run_agent(agent, task_prompt, task_context, timeout)

        # Create tasks for all agents
        tasks = [run_with_semaphore(agent) for agent in agents]

        # Execute with timeout
        try:
            results = await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            logger.error(f"Swarm execution timed out after {timeout}s")
            results = []

        # Filter out exceptions
        agent_results: list[AgentResult] = []
        for i, result in enumerate(results):
            identity = self._agent_identity(agents[i])
            if isinstance(result, Exception):
                logger.warning(f"Agent {identity} failed: {result}")
                agent_results.append(
                    AgentResult(
                        agent_name=identity,
                        response_text=f"Error: {result}",
                        confidence_score=0.0,
                        approach_used=getattr(agents[i], "_swarm_approach", "unknown"),
                    )
                )
            else:
                agent_results.append(result)

        return agent_results

    async def _run_agent(
        self,
        agent: "BaseAgent",
        task_prompt: str,
        task_context: dict[str, Any],
        timeout: int,
    ) -> AgentResult:
        """Execute a single agent with timing and error handling.

        Args:
            agent: The agent to run
            task_prompt: The task prompt
            task_context: Additional context
            timeout: Timeout in seconds

        Returns:
            AgentResult: The agent's result
        """
        start_time = time.time()
        approach = getattr(agent, "_swarm_approach", "default")
        identity = self._agent_identity(agent)

        try:
            # Build the full prompt with context
            full_prompt = self._build_agent_prompt(task_prompt, task_context)

            # Execute the agent
            response = await agent.run_with_mcp(full_prompt)

            execution_time_ms = (time.time() - start_time) * 1000

            # Create result with placeholder confidence (calculated later)
            result = AgentResult(
                agent_name=identity,
                response_text=response,
                confidence_score=0.0,  # Will be calculated in aggregation
                approach_used=approach,
                execution_time_ms=execution_time_ms,
            )

            # Calculate confidence immediately
            result.confidence_score = calculate_confidence(result)

            logger.debug(
                f"Agent {identity} completed in {execution_time_ms:.0f}ms "
                f"(confidence: {result.confidence_score:.2f})"
            )

            return result

        except Exception as e:
            execution_time_ms = (time.time() - start_time) * 1000
            logger.warning(f"Agent {identity} failed after {execution_time_ms:.0f}ms: {e}")

            return AgentResult(
                agent_name=identity,
                response_text=f"Error during execution: {e}",
                confidence_score=0.0,
                approach_used=approach,
                execution_time_ms=execution_time_ms,
            )

    def _build_agent_prompt(self, task_prompt: str, task_context: dict[str, Any]) -> str:
        """Build the full prompt with context for agents.

        Args:
            task_prompt: Base task prompt
            task_context: Additional context

        Returns:
            str: Full formatted prompt
        """
        parts = [task_prompt]

        # Add context if present
        if task_context:
            parts.extend(["", "### Context"])
            for key, value in task_context.items():
                parts.append(f"- {key}: {value}")

        return "\n".join(parts)

    def _aggregate_results(self, results: list[AgentResult]) -> SwarmResult:
        """Aggregate agent results into swarm consensus.

        Args:
            results: Individual agent results

        Returns:
            SwarmResult: Aggregated result with consensus
        """
        if not results:
            return SwarmResult(
                consensus_reached=False,
                final_answer="No agents returned results",
            )

        # Calculate consistency scores
        consistency_scores = score_by_consistency(results)

        # Blend individual confidence with consistency
        for result in results:
            consistency = consistency_scores.get(result.agent_name, 0.5)
            # Weight: 60% own confidence, 40% consistency with others
            result.confidence_score = (result.confidence_score * 0.6) + (consistency * 0.4)

        # Build confidence map
        confidence_map = {r.agent_name: r.confidence_score for r in results}

        # Detect consensus
        threshold = self.config.consensus_threshold
        if self.config.require_unanimous:
            threshold = 1.0

        consensus_reached, final_answer = detect_consensus(results, threshold)

        # If no consensus, synthesize from all results
        if not consensus_reached and not final_answer:
            final_answer = synthesize_results(results)

        return SwarmResult(
            individual_results=results,
            consensus_reached=consensus_reached,
            final_answer=final_answer,
            confidence_scores=confidence_map,
        )

    def _cleanup_agents(self) -> None:
        """Reset agent configurations after execution."""
        for agent in self._agents:
            try:
                reset_agent_approach(agent)
            except Exception as e:
                logger.debug(
                    f"Failed to reset agent {self._agent_identity(agent)}: {e}"
                )

        self._agents = []

    def get_status(self) -> dict[str, Any]:
        """Get current orchestrator status.

        Returns:
            dict: Status information
        """
        return {
            "config": {
                "swarm_size": self.config.swarm_size,
                "consensus_threshold": self.config.consensus_threshold,
                "timeout": self.config.timeout_seconds,
            },
            "active_agents": len(self._agents),
            "parallelism_limit": MAX_PARALLEL_AGENTS,
        }
