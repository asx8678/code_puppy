"""Rich output rendering for Adversarial Planning results."""

import logging
from typing import Any

from .models import (
    PlanningSession,
    Phase0AOutput,
    Phase0BOutput,
    Phase1Output,
    Phase2Output,
    Phase4Output,
    Phase5Output,
    Phase6Output,
    Phase7Output,
    EvidenceClass,
)

logger = logging.getLogger(__name__)


class AdversarialPlanningRenderer:
    """Renders adversarial planning results in various formats."""
    
    def __init__(self, session: PlanningSession):
        self.session = session
    
    def render_full(self) -> str:
        """Render full planning session results."""
        sections = []
        
        # Header
        sections.append(self._render_header())
        
        # Evidence Summary
        if self.session.phase_0a_output:
            sections.append(self._render_evidence_summary())
        
        # Scope Lock
        if self.session.phase_0b_output:
            sections.append(self._render_scope_lock())
        
        # Plan Comparison
        if self.session.plan_a and self.session.plan_b:
            sections.append(self._render_plan_comparison())
        
        # Review Summary
        if self.session.review_a and self.session.review_b:
            sections.append(self._render_review_summary())
        
        # Synthesis
        if self.session.synthesis:
            sections.append(self._render_synthesis())
        
        # Red Team (if deep mode)
        if self.session.red_team:
            sections.append(self._render_red_team())
        
        # Decision
        if self.session.decision:
            sections.append(self._render_decision())
        
        # Change Sets
        if self.session.change_sets:
            sections.append(self._render_change_sets())
        
        return "\n\n".join(sections)
    
    def render_summary(self) -> str:
        """Render executive summary only."""
        lines = []
        
        # Verdict Banner
        if self.session.decision:
            verdict = self.session.decision.plan_verdict
            score = self.session.decision.adjusted_plan_score
            
            emoji = {"go": "🟢", "conditional_go": "🟡", "no_go": "🔴"}.get(verdict, "❓")
            banner = f"{emoji} **VERDICT: {verdict.upper().replace('_', ' ')}** (Score: {score}/100)"
            lines.append(banner)
        elif self.session.global_stop_reason:
            lines.append(f"🛑 **STOPPED**: {self.session.global_stop_reason}")
        else:
            lines.append("⏳ **Planning in progress...**")
        
        # Mode
        mode = self.session.mode_selected or "pending"
        lines.append(f"\n**Mode**: {mode.upper()}")
        
        # Key Numbers
        if self.session.synthesis:
            lines.append(f"**Merged Steps**: {len(self.session.synthesis.merged_steps)}")
            lines.append(f"**Confidence**: {self.session.synthesis.merged_confidence}%")
            lines.append(f"**Estimated Hours**: {self.session.synthesis.estimated_hours_80pct}")
        
        # Blockers
        blockers = self._count_blockers()
        if blockers > 0:
            lines.append(f"\n⚠️ **Blockers**: {blockers}")
        
        # Quick Wins
        if self.session.decision and self.session.decision.quick_wins:
            lines.append(f"\n**Quick Wins**:")
            for win in self.session.decision.quick_wins[:3]:
                lines.append(f"  • {win}")
        
        # Monday Morning Actions
        if self.session.decision and self.session.decision.monday_morning_actions:
            lines.append(f"\n**Next Actions**:")
            for action in self.session.decision.monday_morning_actions[:5]:
                lines.append(f"  1. {action}")
        
        return "\n".join(lines)
    
    def render_traceability_matrix(self) -> str:
        """Render constraint/criteria traceability matrix."""
        if not self.session.synthesis:
            return "No synthesis available."
        
        lines = ["## Traceability Matrix\n"]
        
        # Constraints
        lines.append("### Constraints Coverage\n")
        lines.append("| Constraint | Covered By |")
        lines.append("|------------|------------|")
        
        for item in self.session.synthesis.traceability.get("constraints", []):
            constraint = item.get("constraint", "?")
            covered = ", ".join(item.get("covered_by", []))
            lines.append(f"| {constraint} | {covered} |")
        
        # Criteria
        lines.append("\n### Success Criteria Coverage\n")
        lines.append("| Criterion | Validated By |")
        lines.append("|-----------|--------------|")
        
        for item in self.session.synthesis.traceability.get("criteria", []):
            criterion = item.get("criterion", "?")
            validated = ", ".join(item.get("validated_by", []))
            lines.append(f"| {criterion} | {validated} |")
        
        return "\n".join(lines)
    
    def _render_header(self) -> str:
        """Render session header."""
        lines = [
            "# ⚔️ Adversarial Planning Results",
            "",
            f"**Session ID**: `{self.session.session_id}`",
            f"**Mode**: {(self.session.mode_selected or 'pending').upper()}",
            f"**Current Phase**: {self.session.current_phase}",
        ]
        
        if self.session.global_stop_reason:
            lines.append(f"**Status**: 🛑 STOPPED - {self.session.global_stop_reason}")
        
        return "\n".join(lines)
    
    def _render_evidence_summary(self) -> str:
        """Render Phase 0A evidence summary."""
        output = self.session.phase_0a_output
        
        # Count by class
        counts = {cls: 0 for cls in EvidenceClass}
        for e in output.evidence:
            counts[e.evidence_class] += 1
        
        lines = [
            "## 📊 Evidence Discovery (Phase 0A)",
            "",
            f"**Readiness**: {output.readiness.upper()}",
            f"**Confidence**: {output.confidence}%",
            "",
            "### Evidence by Class",
            f"- ✅ Verified: {counts[EvidenceClass.VERIFIED]}",
            f"- 🔄 Inference: {counts[EvidenceClass.INFERENCE]}",
            f"- ⚠️ Assumption: {counts[EvidenceClass.ASSUMPTION]}",
            f"- ❓ Unknown: {counts[EvidenceClass.UNKNOWN]}",
            "",
            f"**Files Examined**: {len(output.files_examined)}",
            f"**Patterns to Reuse**: {len(output.existing_patterns_to_reuse)}",
            f"**Critical Unknowns**: {len(output.critical_unknowns)}",
        ]
        
        if output.contradictions:
            lines.append(f"\n⚠️ **Contradictions Found**: {len(output.contradictions)}")
            for c in output.contradictions[:3]:
                lines.append(f"  - {c}")
        
        return "\n".join(lines)
    
    def _render_scope_lock(self) -> str:
        """Render Phase 0B scope lock."""
        output = self.session.phase_0b_output
        
        lines = [
            "## 🎯 Scope Lock (Phase 0B)",
            "",
            f"**Problem**: {output.normalized_problem}",
            f"**Type**: {output.problem_type}",
            "",
            "### Constraints",
        ]
        
        for c in output.hard_constraints[:5]:
            lines.append(f"- {c}")
        
        lines.append("\n### In Scope")
        for s in output.in_scope[:5]:
            lines.append(f"- {s}")
        
        lines.append("\n### Out of Scope")
        for s in output.out_of_scope[:5]:
            lines.append(f"- {s}")
        
        return "\n".join(lines)
    
    def _render_plan_comparison(self) -> str:
        """Render side-by-side plan comparison."""
        plan_a = self.session.plan_a
        plan_b = self.session.plan_b
        
        lines = [
            "## 📋 Plan Comparison (Phase 1)",
            "",
            "| Aspect | Plan A (Conservative) | Plan B (Contrarian) |",
            "|--------|----------------------|---------------------|",
            f"| Approach | {plan_a.approach_summary[:40]}... | {plan_b.approach_summary[:40]}... |",
            f"| Steps | {len(plan_a.steps)} | {len(plan_b.steps)} |",
            f"| Hours (80%) | {plan_a.estimated_hours_80pct} | {plan_b.estimated_hours_80pct} |",
            f"| Calendar Days | {plan_a.estimated_calendar_days} | {plan_b.estimated_calendar_days} |",
            f"| Assumptions | {len(plan_a.assumptions)} | {len(plan_b.assumptions)} |",
        ]
        
        return "\n".join(lines)
    
    def _render_review_summary(self) -> str:
        """Render Phase 2 review summary."""
        review_a = self.session.review_a
        review_b = self.session.review_b
        
        lines = [
            "## 🔍 Adversarial Review (Phase 2)",
            "",
            "| Metric | Plan A Review | Plan B Review |",
            "|--------|---------------|---------------|",
            f"| Score | {review_a.overall.get('score', '?')} | {review_b.overall.get('score', '?')} |",
            f"| Ship Readiness | {review_a.overall.get('ship_readiness', '?')} | {review_b.overall.get('ship_readiness', '?')} |",
            f"| Codebase Fit | {review_a.overall.get('codebase_fit', '?')} | {review_b.overall.get('codebase_fit', '?')} |",
            f"| Blockers | {len(review_a.blockers)} | {len(review_b.blockers)} |",
        ]
        
        # Fatal flaws
        flaw_a = review_a.overall.get("fatal_flaw")
        flaw_b = review_b.overall.get("fatal_flaw")
        
        if flaw_a or flaw_b:
            lines.append("\n### ⚠️ Fatal Flaws")
            if flaw_a:
                lines.append(f"- **Plan A**: {flaw_a}")
            if flaw_b:
                lines.append(f"- **Plan B**: {flaw_b}")
        
        return "\n".join(lines)
    
    def _render_synthesis(self) -> str:
        """Render Phase 4 synthesis."""
        synth = self.session.synthesis
        
        lines = [
            "## 🔀 Synthesis (Phase 4)",
            "",
            f"**Merged Problem**: {synth.merged_problem}",
            f"**Approach**: {synth.merged_approach}",
            f"**Confidence**: {synth.merged_confidence}%",
            "",
            "### Merged Steps",
        ]
        
        for step in synth.merged_steps[:10]:
            reversible = "↩️" if step.reversible else "⚠️"
            line = f"- [{step.id}] {reversible} {step.what} ({step.effort_hours_80pct}h)"
            
            # Show provenance if present
            if step.source_plan:
                line += f" [from: {step.source_plan}]"
            
            lines.append(line)
            
            # Show survival reason as sub-line if present
            if step.survival_reason:
                lines.append(f"    └─ {step.survival_reason}")
        
        if len(synth.merged_steps) > 10:
            lines.append(f"  ... and {len(synth.merged_steps) - 10} more steps")
        
        # Dissent log
        if synth.dissent_log:
            lines.append("\n### 📝 Dissent Log")
            for dissent in synth.dissent_log:
                lines.append(f"- **Rejected**: {dissent.get('alternative', '?')}")
                lines.append(f"  **Reason**: {dissent.get('why_rejected', '?')}")
        
        return "\n".join(lines)
    
    def _render_red_team(self) -> str:
        """Render Phase 5 red team results."""
        rt = self.session.red_team
        
        emoji = "✅" if rt.clean_bill_of_health else "⚠️"
        
        lines = [
            "## 🔴 Red Team Stress Test (Phase 5)",
            "",
            f"**Attack Surface**: {rt.overall.get('attack_surface', 'unknown').upper()}",
            f"**Most Vulnerable**: {rt.overall.get('most_vulnerable_area', 'N/A')}",
            f"{emoji} **Clean Bill of Health**: {rt.clean_bill_of_health}",
        ]
        
        if rt.overall.get("fatal_flaw_found"):
            lines.append(f"\n💀 **FATAL FLAW**: {rt.overall.get('fatal_flaw', 'Unknown')}")
        
        # Top attacks
        if rt.attacks:
            lines.append("\n### Top Attacks")
            for attack in rt.attacks[:5]:
                impact_emoji = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}.get(
                    attack.impact, "⚪"
                )
                lines.append(f"- {impact_emoji} **{attack.category}**: {attack.description[:60]}...")
        
        return "\n".join(lines)
    
    def _render_decision(self) -> str:
        """Render Phase 6 decision."""
        dec = self.session.decision
        
        verdict_emoji = {"go": "🟢", "conditional_go": "🟡", "no_go": "🔴"}.get(dec.plan_verdict, "❓")
        
        lines = [
            "## ⚖️ Execution Decision (Phase 6)",
            "",
            f"### {verdict_emoji} VERDICT: **{dec.plan_verdict.upper().replace('_', ' ')}**",
            "",
            f"**Raw Score**: {dec.raw_plan_score}",
        ]
        
        # Penalties
        if dec.penalties:
            lines.append("**Penalties**:")
            for p in dec.penalties:
                lines.append(f"  - {p.reason}: -{p.points}")
        
        lines.append(f"**Adjusted Score**: {dec.adjusted_plan_score}")
        
        if dec.plan_condition:
            lines.append(f"\n⚠️ **Condition**: {dec.plan_condition}")
        
        # Execution order
        if dec.execution_order:
            lines.append("\n### Execution Order")
            for i, step_id in enumerate(dec.execution_order[:10], 1):
                lines.append(f"  {i}. {step_id}")
        
        # Quick wins
        if dec.quick_wins:
            lines.append("\n### 🎯 Quick Wins")
            for win in dec.quick_wins[:5]:
                lines.append(f"  - {win}")
        
        # Monday morning actions
        if dec.monday_morning_actions:
            lines.append("\n### 📅 Monday Morning Actions")
            for action in dec.monday_morning_actions[:5]:
                lines.append(f"  1. {action}")
        
        # Dissenting note
        if dec.dissenting_note:
            lines.append(f"\n📝 **Dissent**: {dec.dissenting_note}")
        
        return "\n".join(lines)
    
    def _render_change_sets(self) -> str:
        """Render Phase 7 change sets."""
        cs = self.session.change_sets
        
        lines = [
            "## 📦 Change Sets (Phase 7)",
            "",
            f"**Total Change Sets**: {len(cs.change_sets)}",
        ]
        
        # Safe first change
        if cs.safe_first_change:
            lines.append("\n### ✅ Safe First Change")
            lines.append(f"**Goal**: {cs.safe_first_change.get('goal', 'N/A')}")
            lines.append(f"**Why First**: {cs.safe_first_change.get('why_first', 'N/A')}")
            files = cs.safe_first_change.get("files", [])
            if files:
                lines.append(f"**Files**: {', '.join(files[:5])}")
        
        # Verification sequence
        if cs.verification_sequence:
            lines.append("\n### 🧪 Verification Sequence")
            for i, step in enumerate(cs.verification_sequence, 1):
                lines.append(f"  {i}. {step}")
        
        return "\n".join(lines)
    
    def _count_blockers(self) -> int:
        """Count total blockers across all phases."""
        count = 0
        
        if self.session.review_a:
            count += len(self.session.review_a.blockers)
        if self.session.review_b:
            count += len(self.session.review_b.blockers)
        if self.session.synthesis:
            count += len(self.session.synthesis.blockers)
        
        return count
    
    # === Export Methods ===
    
    def to_json(self) -> str:
        """Export full session as JSON."""
        return self.session.model_dump_json(indent=2)
    
    def to_markdown(self) -> str:
        """Export as markdown document."""
        return self.render_full()
    
    def to_minimal(self) -> str:
        """Export minimal summary."""
        return self.render_summary()


def render_session(session: PlanningSession, format: str = "summary") -> str:
    """Convenience function to render a session.
    
    Args:
        session: The planning session to render
        format: "full", "summary", "traceability", "json", "markdown", "minimal"
        
    Returns:
        Rendered string
    """
    renderer = AdversarialPlanningRenderer(session)
    
    if format == "full":
        return renderer.render_full()
    elif format == "summary":
        return renderer.render_summary()
    elif format == "traceability":
        return renderer.render_traceability_matrix()
    elif format == "json":
        return renderer.to_json()
    elif format == "markdown":
        return renderer.to_markdown()
    elif format == "minimal":
        return renderer.to_minimal()
    else:
        return renderer.render_summary()
