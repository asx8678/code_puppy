"""Data models for the Consensus Planner Agent."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ModelComparisonResult:
    """Result from comparing multiple models on the same task.

    Attributes:
        model_name: The model used
        response: The model's response
        confidence: Estimated confidence (0.0-1.0)
        execution_time_ms: How long the model took
        approach: The reasoning approach used
    """

    model_name: str
    response: str
    confidence: float = 0.0
    execution_time_ms: float = 0.0
    approach: str = "default"


@dataclass
class Plan:
    """A structured plan created through consensus.

    Attributes:
        objective: Clear statement of what needs to be accomplished
        phases: List of plan phases with tasks
        recommended_model: The model recommended for execution
        confidence: Overall confidence in the plan (0.0-1.0)
        alternative_approaches: Other valid approaches considered
        risks: Identified risks and mitigations
        used_consensus: Whether this plan was created via consensus
    """

    objective: str
    phases: list[dict[str, Any]] = field(default_factory=list)
    recommended_model: str = ""
    confidence: float = 0.0
    alternative_approaches: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    used_consensus: bool = False

    def to_markdown(self) -> str:
        """Convert plan to markdown format."""
        lines = [
            f"# 📋 Consensus Plan: {self.objective}",
            "",
            f"**Confidence**: {'🟢' if self.confidence >= 0.8 else '🟡' if self.confidence >= 0.6 else '🔴'} {self.confidence:.0%}",
            f"**Created via Consensus**: {'Yes ✅' if self.used_consensus else 'No'}",
            f"**Recommended Model**: {self.recommended_model or 'Default'}",
            "",
            "## Execution Phases",
            "",
        ]

        for i, phase in enumerate(self.phases, 1):
            phase_name = phase.get('name', f'Phase {i}')
            lines.extend([
                f"### Phase {i}: {phase_name}",
                "",
                f"{phase.get('description', 'No description')}",
                "",
            ])
            tasks = phase.get('tasks', [])
            if tasks:
                lines.append("**Tasks:**")
                for task in tasks:
                    lines.append(f"- [ ] {task}")
                lines.append("")

        if self.risks:
            lines.extend([
                "## ⚠️ Risks & Mitigations",
                "",
            ])
            for risk in self.risks:
                lines.append(f"- {risk}")
            lines.append("")

        if self.alternative_approaches:
            lines.extend([
                "## 🔄 Alternative Approaches Considered",
                "",
            ])
            for alt in self.alternative_approaches:
                lines.append(f"- {alt}")
            lines.append("")

        return "\n".join(lines)
