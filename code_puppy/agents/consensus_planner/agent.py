"""Consensus Planner Agent implementation."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Any

from code_puppy.config import get_value
from code_puppy.messaging import emit_info, emit_warning
from code_puppy.model_factory import ModelFactory

from ..base_agent import BaseAgent
from .models import ModelComparisonResult, Plan
from .utils import (
    analyze_task_complexity,
    calculate_text_similarity,
    estimate_confidence_from_response,
    extract_phases_from_response,
)

if TYPE_CHECKING:
    # LEGACY: SwarmResult/AgentResult/SwarmOrchestrator types are only used by
    # legacy/unused swarm methods - kept for potential future multi-provider support
    from code_puppy.plugins.consensus_planner.council_consensus import CouncilDecision
    from code_puppy.plugins.swarm_consensus.models import AgentResult, SwarmResult
    from code_puppy.plugins.swarm_consensus.orchestrator import SwarmOrchestrator


logger = logging.getLogger(__name__)


class ConsensusPlannerAgent(BaseAgent):
    """A meta-agent that uses ensemble programming and multi-model consensus
    for critical planning decisions. Can spawn different models, use swarm
    consensus, and synthesize plans from multi-model debate.

    Example:
        agent = ConsensusPlannerAgent()
        plan = await agent.plan_with_consensus("Design a caching system")
        print(plan.to_markdown())
    """

    def __init__(self):
        super().__init__()
        self._orchestrator: SwarmOrchestrator | None = None
        self._model_cache: dict[str, Any] = {}  # Cache for created models
        self._execution_history: list[dict[str, Any]] = []

    @property
    def name(self) -> str:
        return "consensus-planner"

    @property
    def display_name(self) -> str:
        return "Consensus Planner 🎯"

    @property
    def description(self) -> str:
        return (
            "Multi-model ensemble planning agent that uses swarm consensus for "
            "critical decisions. Can leverage all available models to create "
            "robust, well-vetted execution plans."
        )

    def get_available_tools(self) -> list[str]:
        """Get tools available to the Consensus Planner."""
        return [
            "list_files",
            "read_file",
            "grep",
            "agent_share_your_reasoning",
            "ask_user_question",
            "list_agents",
            "invoke_agent",
            "list_or_search_skills",
            "plan_with_consensus",
            "select_model_for_task",
            "compare_model_approaches",
        ]

    def get_system_prompt(self) -> str:
        """Get the Consensus Planner's system prompt."""
        return """\
You are the Consensus Planner 🎯, a meta-agent that orchestrates multi-model
ensemble programming for critical planning decisions.

## Decision Framework

Use SINGLE MODEL for: simple tasks, low risk, clear best practices, speed needed.
Use SINGLE-MODEL SWARM for: moderate complexity, multiple approaches, quality matters.
Use MULTI-MODEL CONSENSUS for: architecture, security, complex refactors, high-stakes.

## Planning Process

1. **Analyze** - Task complexity and criticality
2. **Decide** - Choose strategy (single/swarm/consensus)
3. **Orchestrate** - Spawn agents/models
4. **Synthesize** - Combine insights into plan
5. **Recommend** - Best model for execution

## Tools

- `plan_with_consensus` - Multi-model debate for planning
- `select_model_for_task` - Quick model selection
- `compare_model_approaches` - Compare multiple models

## Output Format

```
🎯 **CONSENSUS PLAN**: [Objective]

📊 **DECISION ANALYSIS**:
- Complexity: [Low/Medium/High]
- Risk: [Low/Medium/High]
- Strategy: [Single/Swarm/Consensus]
- Models: [List]

📋 **EXECUTION PLAN**:
[Phases and tasks]

🤖 **MODEL RECOMMENDATION**: [Best model] - [Rationale]

⚠️ **CONSIDERATIONS**: [Risks]
```

Remember: Know when to consult the council vs act decisively.
"""

    def _get_orchestrator(self) -> SwarmOrchestrator:
        """Get or create the swarm orchestrator."""
        if self._orchestrator is None:
            from code_puppy.plugins.swarm_consensus.models import SwarmConfig
            from code_puppy.plugins.swarm_consensus.orchestrator import (
                SwarmOrchestrator,
            )

            config = SwarmConfig(
                swarm_size=self._get_config_swarm_size(),
                consensus_threshold=self._get_config_threshold(),
                timeout_seconds=self._get_config_timeout(),
                enable_debate=True,
            )
            self._orchestrator = SwarmOrchestrator(config)
        return self._orchestrator

    def _get_config_value(self, key: str, default: int | float, min_val: int | float, max_val: int | float, as_int: bool = True) -> int | float:
        """Get a numeric config value with bounds checking."""
        val = get_value(key)
        if val:
            try:
                result = int(val) if as_int else float(val)
                return max(min_val, min(max_val, result))
            except ValueError:
                pass
        return default

    def _get_config_swarm_size(self) -> int:
        """Get configured swarm size for consensus planner."""
        return self._get_config_value("consensus_planner_swarm_size", 3, 2, 5, as_int=True)

    def _get_config_threshold(self) -> float:
        """Get configured consensus threshold."""
        return self._get_config_value("consensus_planner_threshold", 0.7, 0.0, 1.0, as_int=False)

    def _get_config_timeout(self) -> int:
        """Get configured timeout."""
        return self._get_config_value("consensus_planner_timeout", 180, 30, 600, as_int=True)

    def should_use_consensus(self, task: str, context: dict | None = None) -> tuple[bool, str]:
        """Decide whether to use consensus based on task analysis."""
        context = context or {}
        task_lower = task.lower()

        # Check user preference for always-on mode
        if self._is_consensus_always_on():
            return True, "User has /consensus:always mode enabled"

        # Calculate complexity score from keywords
        complexity_score = 0.0
        matched_keywords = []

        from .utils import COMPLEXITY_KEYWORDS, UNCERTAINTY_MARKERS

        for keyword, weight in COMPLEXITY_KEYWORDS.items():
            if keyword in task_lower:
                complexity_score = max(complexity_score, weight)
                matched_keywords.append(keyword)

        # Check uncertainty markers
        uncertainty_detected = any(marker in task_lower for marker in UNCERTAINTY_MARKERS)
        if uncertainty_detected:
            complexity_score = max(complexity_score, 0.6)

        # Check for critical file types
        critical_patterns = context.get("file_patterns", [])
        if any(p in ["security", "auth", "crypto", "password"] for p in critical_patterns):
            complexity_score = max(complexity_score, 0.9)

        # Determine threshold
        threshold = self._get_config_threshold()

        # Make decision
        if complexity_score >= threshold:
            reason = (
                f"Task complexity score {complexity_score:.2f} >= threshold {threshold:.2f}. "
                f"Keywords: {', '.join(matched_keywords[:3]) if matched_keywords else 'None'}"
            )
            return True, reason

        return False, f"Task complexity {complexity_score:.2f} < threshold {threshold:.2f}"

    def _is_consensus_always_on(self) -> bool:
        """Check if user has /consensus:always mode enabled."""
        val = get_value("consensus_planner_always_on")
        return val and val.lower() in ("1", "true", "yes", "on")

    def get_available_models(self) -> list[str]:
        """Get all models from config that support tool calling."""
        try:
            models_config = ModelFactory.load_config()
            available = []

            for model_name, config in models_config.items():
                # Skip models that don't support tools
                supports_tools = config.get("supports_tools", True)
                if not supports_tools:
                    continue

                # Check if API key is available
                model_type = config.get("type", "")
                if self._model_is_available(model_type, config):
                    available.append(model_name)

            return available

        except Exception as e:
            logger.warning(f"Failed to get available models: {e}")
            return []

    def _model_is_available(self, model_type: str, config: dict) -> bool:
        """Check if a model's API key is available."""
        import os

        api_key_vars = {
            "anthropic": "ANTHROPIC_API_KEY",
            "openai": "OPENAI_API_KEY",
            "gemini": "GEMINI_API_KEY",
            "azure_openai": "AZURE_OPENAI_API_KEY",
        }

        # Check custom endpoint API key
        custom_endpoint = config.get("custom_endpoint", {})
        if custom_endpoint:
            api_key_ref = custom_endpoint.get("api_key", "")
            if api_key_ref.startswith("$"):
                env_var = api_key_ref[1:]
                return bool(os.environ.get(env_var) or get_value(env_var.lower()))

        # Check standard API key
        env_var = api_key_vars.get(model_type)
        if env_var:
            return bool(os.environ.get(env_var) or get_value(env_var.lower()))

        return True  # Assume available if no key needed

    async def plan_with_consensus(self, task: str, force_consensus: bool = False) -> Plan:
        """Create a plan through swarm debate.

        Args:
            task: The task to plan for
            force_consensus: If True, skip complexity check and always use multi-model consensus
        """
        # First, do a quick analysis to understand the task
        complexity_analysis = analyze_task_complexity(task)

        # Decide on strategy (skip check if force_consensus is True)
        if force_consensus:
            use_consensus = True
            reason = "Forced consensus mode enabled"
        else:
            use_consensus, reason = self.should_use_consensus(task, complexity_analysis)

        emit_info(f"📊 Planning strategy: {'Multi-model consensus' if use_consensus else 'Single model'}")
        emit_info(f"   Reason: {reason}")

        if use_consensus:
            return await self._create_plan_with_consensus(task, complexity_analysis)
        else:
            return await self._create_plan_single_model(task)

    async def _create_plan_with_consensus(
        self, task: str, analysis: dict[str, Any]
    ) -> Plan:
        """Create plan using multi-model consensus via Council pattern."""
        from code_puppy.plugins.consensus_planner.council_consensus import (
            run_council_consensus,
        )

        # Skip safeguards when user explicitly invoked /consensus_plan
        council_decision = await run_council_consensus(task, skip_safeguards=True)
        plan = self._parse_council_decision_to_plan(task, council_decision)

        # Record execution
        self._execution_history.append({
            "timestamp": time.time(),
            "task": task,
            "strategy": "consensus",
            "confidence": plan.confidence,
        })

        return plan

    async def _create_plan_single_model(self, task: str) -> Plan:
        """Create plan using single model (faster, for simpler tasks)."""
        from code_puppy.plugins.consensus_planner.council_consensus import (
            _create_simple_agent,
        )

        prompt = """Create a detailed execution plan for this task:

{task}

Structure your response with:
1. Clear objective
2. Execution phases with specific tasks
3. Any risks or considerations
4. Recommended approach

Format as a structured plan.""".format(task=task)

        # Use _create_simple_agent instead of self.run() which doesn't exist on BaseAgent
        model_name = self.get_model_name()
        if not model_name:
            from code_puppy.plugins.consensus_planner.council_consensus import _get_default_fallback_model
            try:
                model_name = _get_default_fallback_model()
            except RuntimeError:
                logger.warning("No fallback model available for plan creation")
                # Return a minimal fallback plan
                return Plan(
                    objective=task,
                    phases=[{"name": "Error", "description": "No models available for planning. Check models.json configuration.", "tasks": []}],
                    recommended_model="unavailable",
                    confidence=0.0,
                )
        agent = await _create_simple_agent(model_name, instructions="You are a planning assistant. Create clear, actionable execution plans.")

        try:
            result = await asyncio.wait_for(agent.run(prompt), timeout=self._get_config_timeout())
            response = result.output
        except asyncio.TimeoutError:
            logger.warning(f"Timeout creating plan with {model_name} after {self._get_config_timeout()}s. Returning fallback plan.")
            response = f"Fallback plan: Execute task '{task}' with standard approach. (Model timeout occurred)"

        # Parse response into Plan structure
        plan = Plan(
            objective=task,
            phases=extract_phases_from_response(response) or [{"name": "Execution", "description": response, "tasks": []}],
            confidence=0.7,  # Default confidence for single model
            used_consensus=False,
        )

        self._execution_history.append({
            "timestamp": time.time(),
            "task": task,
            "strategy": "single",
            "confidence": plan.confidence,
        })

        return plan

    def _parse_council_decision_to_plan(
        self, task: str, council_decision: CouncilDecision
    ) -> Plan:
        """Parse CouncilDecision into a structured Plan."""
        # Extract the decision text
        decision_text = council_decision.decision

        # Extract phases if the response has structured sections
        phases = extract_phases_from_response(decision_text)

        # Build alternative approaches from advisor inputs with lower confidence
        alternative_approaches = []
        for advisor in council_decision.advisor_inputs:
            # Lower confidence advisor responses become alternatives
            if advisor.confidence < council_decision.confidence * 0.8:
                desc = f"{advisor.model_name} (confidence: {advisor.confidence:.0%}): {advisor.response[:200]}..."
                alternative_approaches.append(desc)

        # Build the plan
        plan = Plan(
            objective=task,
            phases=phases if phases else [{"name": "Execution", "description": decision_text, "tasks": []}],
            recommended_model=council_decision.leader_model,
            confidence=council_decision.confidence,
            used_consensus=True,
            risks=council_decision.dissenting_opinions,
            alternative_approaches=alternative_approaches,
        )

        return plan

    # LEGACY: Not currently used - kept for potential future multi-provider swarm support
    def _parse_swarm_result_to_plan(self, task: str, swarm_result: SwarmResult) -> Plan:
        """Parse swarm result into a structured Plan."""
        # Extract the final answer as the base plan
        final_answer = swarm_result.final_answer

        # Calculate overall confidence
        avg_confidence = swarm_result.get_average_confidence()

        # Extract phases if the response has structured sections
        phases = extract_phases_from_response(final_answer)

        # Build the plan
        plan = Plan(
            objective=task,
            phases=phases if phases else [{"name": "Execution", "description": final_answer, "tasks": []}],
            confidence=avg_confidence,
            used_consensus=True,
        )

        # Add alternative approaches from individual results
        for result in swarm_result.individual_results:
            if result.confidence_score < avg_confidence * 0.8:
                # Lower confidence results become alternatives
                desc = f"{result.agent_name} ({result.approach_used}): {result.response_text[:200]}..."
                plan.alternative_approaches.append(desc)

        return plan

    async def select_best_model(self, task: str) -> str:
        """Use quick consensus to pick the optimal model for a task."""
        leader, advisors = self._get_consensus_models()
        all_models = [leader] + advisors

        if len(all_models) < 2:
            # Not enough models for consensus, return default
            if all_models:
                return all_models[0]
            from code_puppy.plugins.consensus_planner.council_consensus import _get_default_fallback_model
            try:
                return _get_default_fallback_model()
            except RuntimeError:
                logger.warning("No fallback model available for model selection")
                return "unavailable"

        # Run a quick comparison on a subset of models
        comparison = await self.compare_model_approaches(task, models=all_models[:3])

        # Pick the best model based on confidence
        if comparison:
            best = max(comparison, key=lambda x: x.confidence)
            return best.model_name

        return leader

    def _get_consensus_models(self) -> tuple[str, list[str]]:
        """Get leader and advisor models from pinned models + active model.

        Returns:
            Tuple of (leader_model, advisor_models)
        """
        from code_puppy.plugins.consensus_planner.council_consensus import (
            _get_advisor_models,
            _get_leader_model,
        )

        leader = _get_leader_model()
        advisors = _get_advisor_models(exclude_leader=leader)
        return leader, advisors

    def _get_preferred_consensus_models(self) -> list[str]:
        """Get preferred consensus models from config.

        .. deprecated::
            Use `_get_consensus_models()` instead. This method is kept for
            backward compatibility but is no longer used internally.
        """
        val = get_value("preferred_consensus_models")
        if val:
            return [m.strip() for m in val.split(",") if m.strip()]

        # Return models that actually exist in config
        try:
            from code_puppy.model_factory import ModelFactory
            models_config = ModelFactory.load_config()
            return list(models_config.keys())[:3]
        except Exception:
            return []

    async def compare_model_approaches(
        self, task: str, models: list[str] | None = None
    ) -> list[ModelComparisonResult]:
        """Run the same task on multiple models and compare results."""
        if models is None:
            leader, advisors = self._get_consensus_models()
            models = [leader] + advisors

        if not models:
            emit_warning("No models available for comparison")
            return []

        results: list[ModelComparisonResult] = []

        # Respect Pack Leader parallelism limit
        semaphore = asyncio.Semaphore(2)

        async def run_with_model(model_name: str) -> ModelComparisonResult | None:
            async with semaphore:
                return await self._run_single_model_comparison(model_name, task)

        # Run all models in parallel
        tasks = [run_with_model(m) for m in models]
        model_results = await asyncio.gather(*tasks, return_exceptions=True)

        for result in model_results:
            if isinstance(result, Exception):
                logger.warning(f"Model comparison failed: {result}")
                continue
            if result:
                results.append(result)

        return results

    async def _run_single_model_comparison(
        self, model_name: str, task: str
    ) -> ModelComparisonResult | None:
        """Run a single model comparison."""
        start_time = time.time()

        try:
            from pydantic_ai import Agent
            from code_puppy.model_factory import make_model_settings

            models_config = ModelFactory.load_config()
            model = ModelFactory.get_model(model_name, models_config)
            model_settings = make_model_settings(model_name)

            agent = Agent(
                model=model,
                output_type=str,
                retries=1,
                model_settings=model_settings,
            )

            prompt = f"""Analyze this task and provide a concise recommendation:

{task}

Respond in this format:
RECOMMENDATION: [Your recommended approach in 2-3 sentences]
CONFIDENCE: [0-100]%
CONCERNS: [Any concerns or caveats, or "None"]"""

            result = await agent.run(prompt)
            response = result.output

            execution_time = (time.time() - start_time) * 1000

            # Estimate confidence from response
            confidence = estimate_confidence_from_response(response)

            return ModelComparisonResult(
                model_name=model_name,
                response=response,
                confidence=confidence,
                execution_time_ms=execution_time,
            )

        except Exception as e:
            logger.warning(f"Model {model_name} failed: {e}")
            return ModelComparisonResult(
                model_name=model_name,
                response=f"Error: {e}",
                confidence=0.0,
                execution_time_ms=(time.time() - start_time) * 1000,
            )

    def _get_or_create_model(self, model_name: str) -> Any:
        """Get or create a model instance.

        .. deprecated::
            Use pydantic-ai Agent pattern directly instead. This method is kept
            for backward compatibility with execute_multi_model_swarm.
        """
        if model_name in self._model_cache:
            return self._model_cache[model_name]

        try:
            models_config = ModelFactory.load_config()
            model = ModelFactory.get_model(model_name, models_config)
            self._model_cache[model_name] = model
            return model
        except Exception as e:
            logger.warning(f"Failed to create model {model_name}: {e}")
            return None

    # LEGACY: Not currently used - kept for potential future multi-provider swarm support
    async def execute_multi_model_swarm(
        self, task: str, models: list[str]
    ) -> SwarmResult:
        """Execute a task with multiple different models in a swarm."""
        orchestrator = self._get_orchestrator()

        # We need to customize the orchestrator to use different models
        # For now, delegate to the standard swarm with model-specific context
        return await orchestrator.execute_swarm(
            task_prompt=task,
            task_context={"requested_models": models},
            task_type="multi_model",
        )

    # LEGACY: Not currently used - kept for potential future multi-provider swarm support
    def resolve_disagreement(self, results: list[AgentResult]) -> str:
        """When models disagree, synthesize a resolution."""
        if not results:
            return "No results to synthesize"

        if len(results) == 1:
            return results[0].response_text

        # Sort by confidence
        sorted_results = sorted(results, key=lambda r: r.confidence_score, reverse=True)

        # Get the best result as base
        best = sorted_results[0]

        # Identify unique contributions from other models
        unique_perspectives = []
        for result in sorted_results[1:]:
            if result.confidence_score < 0.4:
                continue  # Skip low confidence

            # Check if it adds something unique
            similarity = calculate_text_similarity(
                best.response_text, result.response_text
            )
            if similarity < 0.6:  # Different enough to add value
                unique_perspectives.append(result)

        # Build synthesis
        lines = [
            "## Synthesized Resolution",
            "",
            "### Primary Recommendation",
            best.response_text,
            "",
        ]

        if unique_perspectives:
            lines.extend(["### Alternative Considerations", ""])
            for r in unique_perspectives[:2]:
                lines.extend([
                    f"**{r.agent_name}** ({r.approach_used}):",
                    r.response_text[:300] + "..." if len(r.response_text) > 300 else r.response_text,
                    "",
                ])

        lines.extend([
            "---",
            f"*Synthesized from {len(results)} model perspectives*",
            f"*Primary confidence: {best.confidence_score:.0%}*",
        ])

        return "\n".join(lines)

    def get_execution_stats(self) -> dict[str, Any]:
        """Get statistics about consensus planner executions."""
        if not self._execution_history:
            return {"total_executions": 0}

        total = len(self._execution_history)
        consensus_count = sum(1 for h in self._execution_history if h["strategy"] == "consensus")
        avg_confidence = sum(h["confidence"] for h in self._execution_history) / total

        return {
            "total_executions": total,
            "consensus_executions": consensus_count,
            "single_model_executions": total - consensus_count,
            "consensus_rate": consensus_count / total if total > 0 else 0,
            "average_confidence": avg_confidence,
        }
