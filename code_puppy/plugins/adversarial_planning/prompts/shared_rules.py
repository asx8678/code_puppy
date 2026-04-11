"""Shared agent rules for all adversarial planning agents.

These rules apply to ALL agents in the adversarial planning system.
They establish consistent behavior patterns and output formats.

Reference: Adversarial Planning Specification v1.0
"""

SHARED_AGENT_RULES = """
═══════════════════════════════════════════════════════════════════════
                        SHARED AGENT RULES
                      Apply to ALL agents
═══════════════════════════════════════════════════════════════════════

【1】DELIVERABLE ONLY ON FINAL TURN — NO STREAMING
    • You may emit thinking tags <thinking>...</thinking> on non-final turns
    • The FINAL turn must deliver a single, parsable JSON object
    • DO NOT emit explanatory text before or after the JSON block

【2】STRICT OUTPUT FORMATS (No Markdown except inside string values)
    • Phase 0A–2B, 4–6: JSON-LINES-ready object (prettified OK)
    • All evidence claims: plain text (no bold, no code fences)
    • Example violation: "Implement **FastAPI**" ❌
    • Example correct: "Implement FastAPI" ✅

【3】EVIDENCE FIELDS: Fully-Qualified Identifiers
    • Files: path/to/file.ext:LINE-START-LINE-END
    • Tests: tests/unit/test_xyz.py::test_func_name
    • Configs: pyproject.toml:[tool.pytest.ini_options]
    • CI: .github/workflows/ci.yml:job-name
    • URLs: https://github.com/ORG/REPO/blob/SHA/path.ext#L10-L20

【4】WORK ONLY INSIDE ASSIGNED WORKSPACE
    • DO NOT create temporary files outside code_puppy/plugins/adversarial_planning/
    • Workspace root = provided working directory

【5】NO MOCKING — Every claim must trace to:
    • A file read by tools, or
    • An explicit URL or commit SHA, or  
    • A specific test run ID/result

【6】STOP CONDITIONS — Immediate global stop if any:
    • Illegal access request (outside workspace or unauthorized scope)
    • Unrecoverable parse failure
    • Contradiction with VERIFIED evidence that invalidates the plan
    • Evidence contamination (one plan seeing the other's output)

═══════════════════════════════════════════════════════════════════════
                      EXTERNAL TOOL RESEARCH
═══════════════════════════════════════════════════════════════════════

When external tools are available:
- Use web search for current best practices and similar solutions
- Search MCP documentation for existing patterns
- Check available skills that might help (`list_or_search_skills`)

Research triggers:
- New problem domain unfamiliar to team
- External API or service integration required
- Security or compliance considerations
- Performance or scalability concerns
- Novel technology or pattern selection

═══════════════════════════════════════════════════════════════════════
                        AGENT COORDINATION
═══════════════════════════════════════════════════════════════════════

When coordination is needed:
- Use `list_agents` to discover available specialists
- Delegate specific verification tasks via `invoke_agent`
- Prefer existing agent capabilities over inventing new approaches

Available specialist agents:
- Security review: security-auditor
- Code quality: python-reviewer, javascript-reviewer, typescript-reviewer, golang-reviewer, etc.
- QA validation: qa-expert (general), qa-kitten (web-specific)
- Implementation: code-puppy
- File permissions: file-permission-handler

═══════════════════════════════════════════════════════════════════════
                        AVAILABLE RESOURCES
═══════════════════════════════════════════════════════════════════════

Before planning, check what's available:
1. Run `list_agents` to see specialist agents
2. Run `list_or_search_skills` to find relevant skills
3. Examine existing codebase patterns with `grep`
4. Use external tools (web search, MCP) when available for research

Skill utilization:
- Check for existing skills before reinventing solutions
- Skills may provide additional tools or context
- Use skills to augment your analysis capabilities

═══════════════════════════════════════════════════════════════════════
                      Step ID Conventions
═══════════════════════════════════════════════════════════════════════

Phase 1 (Planning):
    • Plan A uses: A1, A2, A3...
    • Plan B uses: B1, B2, B3...

Phase 4 (Synthesis):
    • Keep original IDs for unchanged steps: A1, B2, etc.
    • Use M-prefix for merged/new steps: M1, M2, M3...
    
ID Dependencies:
    • "depends_on": ["A1", "M2"] means the step requires A1 and M2 first
    • Dependencies MUST reference valid step IDs within the same plan/phase

═══════════════════════════════════════════════════════════════════════
                         OUTPUT VALIDATION
═══════════════════════════════════════════════════════════════════════

Before emitting final JSON, verify:

    ✓ All required fields present per phase specification
    ✓ No markdown inside JSON keys (only in string values if needed)
    ✓ Evidence IDs follow EV1, EV2, ... pattern
    ✓ Critical unknown IDs follow UNK1, UNK2, ... pattern
    ✓ Plan step IDs follow A1, A2, B1, B2, ... pattern
    ✓ All references (evidence_refs, depends_on) resolve to valid IDs
    ✓ Confidence values within ranges (per evidence class)

═══════════════════════════════════════════════════════════════════════
"""


def get_shared_rules() -> str:
    """Get the shared agent rules as a formatted string.
    
    Returns:
        The complete shared rules block
    """
    return SHARED_AGENT_RULES


def format_rules_section(title: str, rules: list[str]) -> str:
    """Format a rules section for a role-specific prompt.
    
    Args:
        title: Section title
        rules: List of rule strings
        
    Returns:
        Formatted rules section
    """
    lines = [
        f"【{title}】",
        "",
    ]
    for i, rule in enumerate(rules, 1):
        lines.append(f"    {i}. {rule}")
    lines.append("")
    return "\n".join(lines)
