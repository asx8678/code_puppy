"""Adversarial Planning Orchestrator - Coordinates all phases.

Manages the flow through all planning phases with proper
state tracking and error handling.
"""

from collections.abc import Callable
import asyncio
import json
import logging
import uuid
from typing import Any

from .models import (
    AdversarialPlanConfig,
    PlanningSession,
    Phase0AOutput,
    Phase0BOutput,
    Phase1Output,
    Phase2Output,
    Phase4Output,
    Phase5Output,
    Phase6Output,
    Phase7Output,
    Penalty,
)
from .evidence import EvidenceTracker
from .validators import (
    ValidationError,
    validate_phase_0a_output,
    validate_phase_0b_output,
    validate_phase_1_exit,
    validate_phase_2_output,
    validate_phase_4_output,
    check_global_stop_conditions,
    needs_rebuttal,
)
from .prompt_builders import (
    build_researcher_prompt,
    build_scope_lock_prompt,
    build_evidence_pack,
    build_scope_lock_pack,
    build_planner_prompt,
    build_review_prompt,
    build_rebuttal_prompt,
    build_synthesis_prompt,
    build_red_team_prompt,
    build_decision_prompt,
    build_changeset_prompt,
)

logger = logging.getLogger(__name__)


class GlobalStopCondition(Exception):
    """Raised when a global stop condition is met."""
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


class AdversarialPlanningOrchestrator:
    """Orchestrates the multi-phase adversarial planning workflow."""
    
    # Deep mode triggers
    DEEP_MODE_TRIGGERS = [
        "production_change",
        "data_migration",
        "security_risk",
        "privacy_risk",
        "compliance_risk",
        "legal_risk",
    ]
    
    def __init__(
        self,
        config: AdversarialPlanConfig,
        invoke_agent_fn: Callable | None = None,
        emit_progress_fn: Callable | None = None,
    ):
        self.config = config
        self.session_id = f"ap-{uuid.uuid4().hex[:8]}"
        self.evidence = EvidenceTracker()
        
        # Dependency injection for testing
        self._invoke_agent = invoke_agent_fn or self._default_invoke_agent
        self._emit_progress = emit_progress_fn or self._default_emit_progress
        
        # Session state
        self.session = PlanningSession(
            session_id=self.session_id,
            config=config,
            current_phase="init",
        )
        
        # Track model usage for same-model penalty
        self._models_used: dict[str, str] = {}
    
    async def run(self) -> PlanningSession:
        """Execute the full adversarial planning workflow."""
        try:
            # Phase 0A: Discovery
            await self._run_phase_0a()
            self._check_global_stop()
            
            # Phase 0B: Scope Lock
            await self._run_phase_0b()
            self._check_global_stop()
            
            # Determine mode
            self._select_mode()
            
            # Phase 1: Independent Planning (parallel)
            await self._run_phase_1()
            self._check_global_stop()
            
            # Phase 2: Adversarial Review (parallel)
            await self._run_phase_2()
            self._check_global_stop()
            
            # Phase 3: Rebuttal (conditional)
            if needs_rebuttal(self.session):
                await self._run_phase_3()
                self._check_global_stop()
            
            # Phase 4: Synthesis
            await self._run_phase_4()
            self._check_global_stop()
            
            # Phase 5: Red Team (deep mode only)
            if self.session.mode_selected == "deep":
                await self._run_phase_5()
                self._check_global_stop()
            
            # Phase 6: Execution Decision
            await self._run_phase_6()
            
            # Phase 7: Change-Set Synthesis (Deep mode only, go verdict)
            if (
                self.session.mode_selected == "deep"
                and self.session.decision
                and self.session.decision.plan_verdict == "go"
            ):
                await self._run_phase_7()
            
            return self.session
            
        except GlobalStopCondition as e:
            self.session.global_stop_reason = e.reason
            self._emit_progress("global_stop", {"reason": e.reason})
            return self.session
    
    def _select_mode(self) -> None:
        """Select Standard or Deep mode based on triggers."""
        if self.config.mode == "deep":
            self.session.mode_selected = "deep"
            return
        
        if self.config.mode == "standard":
            self.session.mode_selected = "standard"
            return
        
        # Auto mode - check triggers
        deep_triggers_found = []
        
        # Check discovery output for triggers
        if self.session.phase_0a_output:
            for evidence in self.session.phase_0a_output.evidence:
                claim_lower = evidence.claim.lower()
                if any(trigger in claim_lower for trigger in self.DEEP_MODE_TRIGGERS):
                    deep_triggers_found.append(f"Evidence: {evidence.claim[:50]}")
            
            if len(self.session.phase_0a_output.critical_unknowns) > 2:
                deep_triggers_found.append(f"{len(self.session.phase_0a_output.critical_unknowns)} critical unknowns")
        
        # Check scope lock for triggers
        if self.session.phase_0b_output:
            if self.session.phase_0b_output.problem_type in ("migration", "security", "incident"):
                deep_triggers_found.append(f"Problem type: {self.session.phase_0b_output.problem_type}")
        
        # Same-model fallback triggers deep mode
        if self.session.same_model_fallback:
            deep_triggers_found.append("Same-model fallback used")
        
        if deep_triggers_found:
            self.session.mode_selected = "deep"
            self._emit_progress("mode_selected", {"mode": "deep", "triggers": deep_triggers_found})
        else:
            self.session.mode_selected = "standard"
            self._emit_progress("mode_selected", {"mode": "standard", "triggers": []})
    
    async def _run_phase_0a(self) -> None:
        """Phase 0A: Environment & Evidence Discovery."""
        self.session.current_phase = "0a_discovery"
        self._emit_progress("phase_start", {"phase": "0A", "name": "Environment & Evidence Discovery"})
        
        prompt = build_researcher_prompt(self.config)
        
        result = await self._invoke_agent(
            agent_name="ap-researcher",
            prompt=prompt,
            session_id=f"{self.session_id}-researcher",
        )
        
        output = self._parse_phase_output(result, Phase0AOutput)
        self.session.phase_0a_output = output
        
        validate_phase_0a_output(output)
        
        self._emit_progress("phase_complete", {"phase": "0A", "readiness": output.readiness})
    
    async def _run_phase_0b(self) -> None:
        """Phase 0B: Scope Lock."""
        self.session.current_phase = "0b_scope_lock"
        self._emit_progress("phase_start", {"phase": "0B", "name": "Scope Lock"})
        
        prompt = build_scope_lock_prompt(self.config, self.session.phase_0a_output)
        
        result = await self._invoke_agent(
            agent_name="ap-researcher",
            prompt=prompt,
            session_id=f"{self.session_id}-scope-lock",
        )
        
        output = self._parse_phase_output(result, Phase0BOutput)
        self.session.phase_0b_output = output
        
        validate_phase_0b_output(output)
        
        self._emit_progress("phase_complete", {"phase": "0B", "problem_type": output.problem_type})
    
    async def _run_phase_1(self) -> None:
        """Phase 1: Independent Planning (parallel, isolated)."""
        self.session.current_phase = "1_planning"
        self._emit_progress("phase_start", {"phase": "1", "name": "Independent Planning"})
        
        evidence_pack = build_evidence_pack(self.session.phase_0a_output)
        scope_lock = build_scope_lock_pack(self.session.phase_0b_output)
        
        prompt_a = build_planner_prompt("A", "conservative", evidence_pack, scope_lock)
        prompt_b = build_planner_prompt("B", "contrarian", evidence_pack, scope_lock)
        
        # Run BOTH planners in parallel (isolated sessions)
        plan_a_task = self._invoke_agent(
            agent_name="ap-planner-a",
            prompt=prompt_a,
            session_id=f"{self.session_id}-planner-a",
        )
        plan_b_task = self._invoke_agent(
            agent_name="ap-planner-b",
            prompt=prompt_b,
            session_id=f"{self.session_id}-planner-b",
        )
        
        result_a, result_b = await asyncio.gather(plan_a_task, plan_b_task)
        
        self.session.plan_a = self._parse_phase_output(result_a, Phase1Output)
        self.session.plan_b = self._parse_phase_output(result_b, Phase1Output)
        
        validate_phase_1_exit(self.session.plan_a, self.session.plan_b)
        
        self._emit_progress("phase_complete", {
            "phase": "1",
            "plan_a_steps": len(self.session.plan_a.steps),
            "plan_b_steps": len(self.session.plan_b.steps),
        })
    
    async def _run_phase_2(self) -> None:
        """Phase 2: Adversarial Review (parallel)."""
        self.session.current_phase = "2_review"
        self._emit_progress("phase_start", {"phase": "2", "name": "Adversarial Review"})

        # Extract Phase 0 context for reviewers
        evidence_pack = None
        if self.session.phase_0a_output:
            evidence_pack = self.session.phase_0a_output.evidence

        scope_lock = self.session.phase_0b_output

        # Review Plan A
        prompt_review_a = build_review_prompt(
            self.session.plan_a,
            "A",
            evidence_pack=evidence_pack,
            scope_lock=scope_lock,
            success_criteria=self.config.success_criteria,
            hard_constraints=self.config.hard_constraints,
        )

        # Review Plan B
        prompt_review_b = build_review_prompt(
            self.session.plan_b,
            "B",
            evidence_pack=evidence_pack,
            scope_lock=scope_lock,
            success_criteria=self.config.success_criteria,
            hard_constraints=self.config.hard_constraints,
        )
        
        review_a_task = self._invoke_agent(
            agent_name="ap-reviewer",
            prompt=prompt_review_a,
            session_id=f"{self.session_id}-review-a",
        )
        review_b_task = self._invoke_agent(
            agent_name="ap-reviewer",
            prompt=prompt_review_b,
            session_id=f"{self.session_id}-review-b",
        )
        
        result_a, result_b = await asyncio.gather(review_a_task, review_b_task)
        
        self.session.review_a = self._parse_phase_output(result_a, Phase2Output)
        self.session.review_b = self._parse_phase_output(result_b, Phase2Output)
        
        validate_phase_2_output(self.session.review_a, self.session.review_b)
        
        self._emit_progress("phase_complete", {
            "phase": "2",
            "plan_a_score": self.session.review_a.overall.get("score", 0),
            "plan_b_score": self.session.review_b.overall.get("score", 0),
        })
    
    async def _run_phase_3(self) -> None:
        """Phase 3: Rebuttal (conditional)."""
        self.session.current_phase = "3_rebuttal"
        self._emit_progress("phase_start", {"phase": "3", "name": "Rebuttal"})
        
        prompt_rebuttal_a = build_rebuttal_prompt(self.session.plan_a, self.session.review_a)
        prompt_rebuttal_b = build_rebuttal_prompt(self.session.plan_b, self.session.review_b)
        
        rebuttal_a_task = self._invoke_agent(
            agent_name="ap-planner-a",
            prompt=prompt_rebuttal_a,
            session_id=f"{self.session_id}-rebuttal-a",
        )
        rebuttal_b_task = self._invoke_agent(
            agent_name="ap-planner-b",
            prompt=prompt_rebuttal_b,
            session_id=f"{self.session_id}-rebuttal-b",
        )
        
        result_a, result_b = await asyncio.gather(rebuttal_a_task, rebuttal_b_task)
        
        updated_a = self._parse_phase_output(result_a, Phase1Output)
        updated_b = self._parse_phase_output(result_b, Phase1Output)
        
        if updated_a:
            self.session.plan_a = updated_a
        if updated_b:
            self.session.plan_b = updated_b
        
        self._emit_progress("phase_complete", {"phase": "3", "rebuttals_processed": 2})
    
    async def _run_phase_4(self) -> None:
        """Phase 4: Synthesis."""
        self.session.current_phase = "4_synthesis"
        self._emit_progress("phase_start", {"phase": "4", "name": "Synthesis"})

        # Extract evidence from Phase 0A if available
        evidence_pack = None
        if self.session.phase_0a_output:
            evidence_pack = self.session.phase_0a_output.evidence

        # Extract scope from Phase 0B if available
        scope_lock = self.session.phase_0b_output

        prompt = build_synthesis_prompt(
            self.session.plan_a,
            self.session.plan_b,
            self.session.review_a,
            self.session.review_b,
            evidence_pack=evidence_pack,
            scope_lock=scope_lock,
            success_criteria=self.config.success_criteria,
            hard_constraints=self.config.hard_constraints,
        )
        
        result = await self._invoke_agent(
            agent_name="ap-arbiter",
            prompt=prompt,
            session_id=f"{self.session_id}-arbiter",
        )
        
        output = self._parse_phase_output(result, Phase4Output)
        self.session.synthesis = output
        
        validate_phase_4_output(output)
        
        self._emit_progress("phase_complete", {
            "phase": "4",
            "merged_steps": len(output.merged_steps),
            "confidence": output.merged_confidence,
        })
    
    async def _run_phase_5(self) -> None:
        """Phase 5: Red Team Stress Test (deep mode only)."""
        self.session.current_phase = "5_red_team"
        self._emit_progress("phase_start", {"phase": "5", "name": "Red Team Stress Test"})
        
        prompt = build_red_team_prompt(self.session.synthesis)
        
        result = await self._invoke_agent(
            agent_name="ap-red-team",
            prompt=prompt,
            session_id=f"{self.session_id}-red-team",
        )
        
        output = self._parse_phase_output(result, Phase5Output)
        self.session.red_team = output
        
        if output.overall.get("fatal_flaw_found") and output.overall.get("fatal_flaw"):
            self._emit_progress("fatal_flaw_found", {
                "flaw": output.overall["fatal_flaw"],
                "recommendations": output.recommendations[:3],
            })
        
        self._emit_progress("phase_complete", {
            "phase": "5",
            "attack_surface": output.overall.get("attack_surface", "unknown"),
            "clean_bill": output.clean_bill_of_health,
        })
    
    async def _run_phase_6(self) -> None:
        """Phase 6: Execution Decision."""
        self.session.current_phase = "6_decision"
        self._emit_progress("phase_start", {"phase": "6", "name": "Execution Decision"})
        
        prompt = build_decision_prompt(self.session.synthesis, self.session.red_team)
        
        result = await self._invoke_agent(
            agent_name="ap-arbiter",
            prompt=prompt,
            session_id=f"{self.session_id}-decision",
        )
        
        output = self._parse_phase_output(result, Phase6Output)
        output = self._apply_penalties(output)
        
        self.session.decision = output
        
        self._emit_progress("phase_complete", {
            "phase": "6",
            "verdict": output.plan_verdict,
            "score": output.adjusted_plan_score,
        })
    
    async def _run_phase_7(self) -> None:
        """Phase 7: Change-Set Synthesis."""
        self.session.current_phase = "7_changeset"
        self._emit_progress("phase_start", {"phase": "7", "name": "Change-Set Synthesis"})
        
        prompt = build_changeset_prompt(self.session.decision)
        
        result = await self._invoke_agent(
            agent_name="ap-arbiter",
            prompt=prompt,
            session_id=f"{self.session_id}-changeset",
        )
        
        output = self._parse_phase_output(result, Phase7Output)
        self.session.change_sets = output
        
        self._emit_progress("phase_complete", {
            "phase": "7",
            "change_sets": len(output.change_sets),
            "safe_first": output.safe_first_change.get("goal", ""),
        })
    
    def _apply_penalties(self, decision: Phase6Output) -> Phase6Output:
        """Apply plan-level penalties to decision score."""
        penalties = list(decision.penalties) if decision.penalties else []
        
        # Same-model fallback: -15
        if self.session.same_model_fallback:
            penalties.append(Penalty(reason="same-model fallback used", points=15))
        
        # Production change without tested rollback: -20
        if self.session.synthesis:
            rollback = self.session.synthesis.operational_readiness.rollback
            if not rollback or rollback == "none" or "untested" in rollback.lower():
                for step in self.session.synthesis.merged_steps:
                    if step.approval_needed == "production_change":
                        penalties.append(Penalty(
                            reason="production change without tested rollback",
                            points=20
                        ))
                        break
        
        total_penalty = sum(p.points for p in penalties)
        adjusted = decision.raw_plan_score - total_penalty
        
        decision.penalties = penalties
        decision.adjusted_plan_score = max(0, adjusted)
        
        # Recalculate verdict based on adjusted score
        if decision.adjusted_plan_score >= 75:
            decision.plan_verdict = "go"
        elif decision.adjusted_plan_score >= 55:
            decision.plan_verdict = "conditional_go"
        else:
            decision.plan_verdict = "no_go"
        
        return decision
    
    def _check_global_stop(self) -> None:
        """Check for global stop conditions."""
        # Check for user-requested abort first
        if self.session.global_stop_reason:
            raise GlobalStopCondition(self.session.global_stop_reason)

        stop_reason = check_global_stop_conditions(self.session)
        if stop_reason:
            raise GlobalStopCondition(stop_reason)
    
    def _parse_phase_output(self, result: str, model_class: type) -> Any:
        """Parse agent output into Pydantic model."""
        try:
            # Look for JSON block
            if "```json" in result:
                json_start = result.find("```json") + 7
                json_end = result.find("```", json_start)
                json_str = result[json_start:json_end].strip()
            elif "{" in result:
                json_start = result.find("{")
                json_end = result.rfind("}") + 1
                json_str = result[json_start:json_end]
            else:
                raise ValueError("No JSON found in output")
            
            data = json.loads(json_str)
            return model_class.model_validate(data)
            
        except Exception as e:
            logger.error(f"Failed to parse phase output: {e}")
            logger.debug(f"Raw output: {result[:500]}")
            raise
    
    async def _default_invoke_agent(
        self, agent_name: str, prompt: str, session_id: str
    ) -> str:
        """Default agent invocation using Code Puppy's invoke_agent."""
        from code_puppy.tools.agent_tools import invoke_agent_headless
        
        result = await invoke_agent_headless(
            agent_name=agent_name,
            prompt=prompt,
            session_id=session_id,
        )
        
        return result.get("response", "")
    
    def _default_emit_progress(self, event_type: str, data: dict) -> None:
        """Default progress emission."""
        from code_puppy.messaging import emit_info
        
        if event_type == "phase_start":
            emit_info(f"⚔️ Phase {data['phase']}: {data['name']}")
        elif event_type == "phase_complete":
            emit_info(f"✅ Phase {data['phase']} complete")
        elif event_type == "mode_selected":
            emoji = "🔴" if data["mode"] == "deep" else "🟢"
            emit_info(f"{emoji} Mode: {data['mode'].upper()}")
        elif event_type == "global_stop":
            emit_info(f"🛑 STOPPED: {data['reason']}")
        elif event_type == "fatal_flaw_found":
            emit_info(f"💀 FATAL FLAW: {data['flaw']}")


class PhaseOrchestrator:
    """Legacy orchestrator - kept for compatibility.
    
    Use AdversarialPlanningOrchestrator for new code.
    """
    
    PHASE_ORDER = [
        "0A", "0B", "1A", "1B", "2A", "2B",
        "4", "5", "6", "7",
    ]
    
    def __init__(self, session: PlanningSession):
        self.session = session
        self._current_phase_index = 0
        logger.info(f"Initialized orchestrator for session {session.session_id}")
    
    @property
    def current_phase(self) -> str:
        if self._current_phase_index < len(self.PHASE_ORDER):
            return self.PHASE_ORDER[self._current_phase_index]
        return "complete"
    
    @property
    def is_complete(self) -> bool:
        return self._current_phase_index >= len(self.PHASE_ORDER)
    
    def can_proceed(self) -> tuple[bool, str]:
        if self.session.global_stop_reason:
            return False, f"Global stop: {self.session.global_stop_reason}"
        return True, ""
    
    def run_phase(self, phase: str | None = None) -> Any:
        raise NotImplementedError("Use AdversarialPlanningOrchestrator.run()")
    
    def advance(self) -> str | None:
        self._current_phase_index += 1
        if self._current_phase_index < len(self.PHASE_ORDER):
            new_phase = self.PHASE_ORDER[self._current_phase_index]
            self.session.current_phase = new_phase
            return new_phase
        else:
            self.session.current_phase = "complete"
            return None
    
    def stop(self, reason: str) -> None:
        self.session.global_stop_reason = reason
        logger.warning(f"Planning stopped: {reason}")
