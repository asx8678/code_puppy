# ConsensusPlanner Auto-Spawn Examples

This document shows how to use the automatic ConsensusPlanner spawning integration from the main Code Puppy agent.

## Overview

The auto-spawn system allows the main agent to:
1. **Manually invoke** consensus when the agent decides it's needed
2. **Get auto-detected** when uncertainty markers appear in responses
3. **Use for validation** before making critical decisions

## Configuration

Add to your `puppy.cfg`:

```ini
[DEFAULT]
# Enable/disable auto-spawn (default: true)
consensus_auto_spawn_enabled = true

# Which triggers to enable (default: uncertainty,error,complexity)
consensus_auto_spawn_triggers = uncertainty,error,complexity

# Confidence threshold for triggering (default: 0.6)
consensus_uncertainty_threshold = 0.6

# Ask before auto-spawning (default: true)
consensus_ask_before_spawn = true
```

## Usage Examples

### 1. Manual Invocation

The agent can explicitly call consensus when stuck or uncertain:

```python
# When the agent encounters a complex architecture decision
response = await invoke_consensus_planner(
    task="Design a caching system for high-traffic API with Redis fallback",
    reason="Need multi-model validation for architecture decision",
    models=["claude-sonnet-4", "gpt-4.1", "gemini-2.5-pro"]
)

# The response includes:
# - Structured plan with phases
# - Recommended model for execution
# - Confidence score
# - Alternative approaches considered
# - Identified risks
```

### 2. Detecting When Consensus Might Help

The agent can check if consensus would help before proceeding:

```python
# Analyze the current response
analysis = await detect_consensus_need(
    agent_response="I'm not sure about the best approach here...",
    context={"task": "Database migration strategy"}
)

if analysis["needs_consensus"]:
    print(f"Low confidence detected: {analysis['confidence_score']:.2f}")
    print(f"Trigger: {analysis['trigger_type']}")
    print(f"Matched patterns: {analysis['matched_patterns']}")
    
    # Agent can then choose to invoke consensus
    result = await invoke_consensus_planner(
        task="Database migration strategy",
        reason=analysis["reason"]
    )
```

### 3. Auto-Spawn with Context

Programmatic auto-spawn with trigger context:

```python
result = await auto_spawn_consensus(
    task="Refactor the authentication module",
    trigger_context={
        "trigger_type": "complexity",
        "matched_patterns": ["refactor", "authentication", "security"],
        "confidence_score": 0.45
    }
)

if result["spawned"]:
    print("Consensus plan created:")
    print(result["plan"]["markdown"])
else:
    print(f"Not spawned: {result['reason']}")
```

### 4. Agent Self-Correction Pattern

When the agent detects its own uncertainty, it can escalate:

```python
# In the agent's response generation
if "I'm not sure" in draft_response or "might be" in draft_response:
    # Check if we should use consensus
    check = detect_issue_need_consensus(draft_response)
    
    if check.needs_consensus:
        # Let me get a second opinion from the council
        consensus_result = await invoke_consensus_planner(
            task=current_task,
            reason=f"Detected uncertainty: {check.reason}"
        )
        
        # Use the consensus plan to inform my response
        return f"I've consulted multiple models on this. {consensus_result['plan']['markdown']}"
```

### 5. Error Recovery with Consensus

When errors occur, use consensus to find the best fix:

```python
# After an error is detected
error_context = {
    "error": "ModuleNotFoundError: No module named 'asyncpg'",
    "task": "Setting up database connection"
}

# Check if error patterns suggest consensus
if detect_issue_need_consensus(str(error)):
    result = await invoke_consensus_planner(
        task=f"Fix this error: {error_context['error']} in context of {error_context['task']}",
        reason="Error detected, seeking multi-model input on best fix"
    )
    
    # Use the recommended approach from consensus
    recommended_approach = result["plan"]["phases"][0]["description"]
```

### 6. Pre-Commit Validation

Before making critical changes, validate with consensus:

```python
async def validate_critical_change(change_description: str) -> dict:
    """Validate a critical change with multi-model consensus."""
    
    # Use model comparison for validation
    comparison = await compare_model_approaches(
        task=f"Review this change for issues: {change_description}",
        models=["claude-sonnet-4", "gpt-4.1"]
    )
    
    # Check if models agree
    confidences = [r["confidence"] for r in comparison["results"]]
    avg_confidence = sum(confidences) / len(confidences)
    
    if avg_confidence < 0.7:
        # Low agreement - escalate to full consensus plan
        plan = await invoke_consensus_planner(
            task=f"Review and improve: {change_description}",
            reason=f"Low model agreement ({avg_confidence:.2f}), seeking consensus"
        )
        return {"validated": False, "plan": plan}
    
    return {"validated": True, "comparison": comparison}
```

## Trigger Patterns

The auto-spawn system recognizes these patterns:

### Uncertainty Markers (high priority)
- "not sure", "unclear", "might be", "could be"
- "possibly", "probably", "i think", "maybe"
- "uncertain", "don't know", "hard to say"

### Error Patterns (critical priority)
- "error", "failed", "failure", "exception"
- "doesn't work", "not working", "broken"
- "crash", "bug", "timeout", "stuck"

### Complexity Markers (medium priority)
- "complex", "architecture", "design pattern"
- "refactor", "restructure", "strategy"
- "trade-off", "optimization", "security"

### Self-Correction (medium priority)
- "wait", "actually", "on second thought"
- "reconsider", "let me check", "correction"

## Integration Flow

```
┌─────────────────────────────────────────────────────────────┐
│  Main Agent Response                                        │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│  detect_issue_need_consensus()                            │
│  - Pattern matching on response                             │
│  - Score calculation                                        │
│  - Trigger type detection                                   │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
              ┌───────────────────────┐
              │ Confidence Score < 0.6? │
              └───────────────────────┘
                   │            │
              Yes ▼            ▼ No
                   │            │
      ┌────────────▼──┐       ┌▼────────────┐
      │ Needs Consensus│       │ Continue    │
      └────────────┬──┘       └─────────────┘
                   │
                   ▼
      ┌──────────────────────────────┐
      │ User confirmation?            │
      │ (if ask_before_spawn=True)   │
      └────────────┬─────────────────┘
                   │
              Yes ▼
                   │
                   ▼
      ┌──────────────────────────────┐
      │ invoke_consensus_planner()    │
      │ - Multi-model debate          │
      │ - Plan synthesis              │
      │ - Return structured plan      │
      └───────────────────────────────┘
```

## Best Practices

1. **Don't overuse**: Reserve consensus for genuinely uncertain or complex situations
2. **Preserve context**: Always pass full task context to get relevant results
3. **Check confidence**: Use the confidence score to decide if consensus is needed
4. **Respect user choice**: Keep `ask_before_spawn=True` for non-critical tasks
5. **Monitor patterns**: Watch which triggers fire most often to tune thresholds

## API Reference

### Tools Available to Agents

- `invoke_consensus_planner(task, reason, models=None)` - Manual invocation
- `auto_spawn_consensus(task, trigger_context=None)` - Programmatic auto-spawn
- `detect_consensus_need(agent_response, context=None)` - Analyze if consensus helps
- `plan_with_consensus(task, force_consensus=False)` - Create execution plan
- `compare_model_approaches(task, models=None)` - Compare model responses
- `select_model_for_task(task)` - Get model recommendation

### Configuration Functions

- `get_consensus_auto_spawn_enabled()` - Check if auto-spawn is on
- `get_consensus_auto_spawn_triggers()` - Get enabled trigger types
- `get_consensus_uncertainty_threshold()` - Get confidence threshold
- `get_consensus_ask_before_spawn()` - Check confirmation setting
