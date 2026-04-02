# ConsensusPlanner Agent 🎯

> **Multi-model ensemble planning with intelligent decision-making** — get better plans by leveraging the wisdom of multiple AI perspectives.

## Overview

The ConsensusPlanner Agent is a meta-agent that orchestrates **multi-model ensemble programming** for critical planning decisions. Unlike standard agents that use a single model perspective, ConsensusPlanner can spawn multiple models (Claude, GPT-4, Gemini, etc.), have them debate approaches, and synthesize a robust execution plan backed by consensus.

### What Makes It Unique?

- **Adaptive Strategy Selection**: Automatically chooses between single model, single-model swarm, or multi-model consensus based on task complexity
- **Model-Agnostic**: Works with any models configured in your Code Puppy setup
- **Intelligent Debate**: Models with different strengths analyze the same problem from different angles
- **Confidence Scoring**: Each plan comes with a confidence score and rationale
- **Best Model Recommendation**: Not only creates a plan, but tells you which model is best suited to execute it

### When to Use ConsensusPlanner

| Scenario | Why ConsensusPlanner? |
|----------|----------------------|
| Architecture decisions | Multiple perspectives catch design flaws early |
| Security planning | Security-minded + pragmatic models balance safety and usability |
| Complex refactoring | Critical analysis prevents regression bugs |
| Strategy planning | Creative + thorough approaches yield innovative yet practical plans |
| High-stakes changes | Consensus-backed plans reduce risk |

## Key Features

### 🧠 Multi-Model Consensus

Spawn multiple models simultaneously and synthesize their perspectives:
- **Claude** for nuanced, safety-conscious analysis
- **GPT-4** for broad knowledge and reasoning
- **Gemini** for different architectural perspectives
- **Custom models** via your own endpoints

### 🎯 Smart Decision Framework

Automatically selects the optimal strategy:

| Strategy | When Used | Example Tasks |
|----------|-----------|---------------|
| **Single Model** | Simple tasks, speed needed, clear best practices | "Add docstring to this function" |
| **Single-Model Swarm** | Moderate complexity, multiple valid approaches | "Refactor this module" |
| **Multi-Model Consensus** | High stakes, architecture, security, complex planning | "Design a new authentication system" |

### 📋 Planning with Debate

Plans aren't just generated—they're **debated**:
1. Each model proposes their approach
2. Models can critique each other's plans
3. Consensus synthesizes the best elements
4. Alternative approaches are documented

### 🏆 Model Selection Intelligence

Not sure which model to use for a task? The ConsensusPlanner can:
- Run a quick comparison across models
- Score each model's confidence for the specific task
- Recommend the best model for execution

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    ConsensusPlannerAgent                        │
│                                                                 │
│  ┌─────────────────┐   ┌─────────────────┐   ┌──────────────┐  │
│  │  Task Analyzer  │   │ Decision Engine │   │  Swarm       │  │
│  │                 │──▶│                 │──▶│  Orchestrator│  │
│  │ • Complexity    │   │ • Single model? │   │              │  │
│  │ • Risk level    │   │ • Swarm?        │   │ • Spawn      │  │
│  │ • Keywords      │   │ • Multi-model?  │   │ • Debate     │  │
│  └─────────────────┘   └─────────────────┘   │ • Synthesize │  │
│                                               └──────────────┘  │
│                        │                                        │
│                        ▼                                        │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │                    Plan Output                           │   │
│  │  • Structured phases    • Confidence score              │   │
│  │  • Model recommendation • Alternative approaches        │   │
│  │  • Risk assessment      • Execution strategy            │   │
│  └─────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│              Swarm Consensus Plugin (integration)               │
│                                                                 │
│  ┌─────────────┐  ┌─────────────┐  ┌────────────────────────┐  │
│  │ Approaches  │  │  Consensus  │  │   Result Synthesis     │  │
│  │ (thorough,  │  │  Detection  │  │   (blending, debate)   │  │
│  │  creative,  │  │             │  │                        │  │
│  │  critical)  │  │             │  │                        │  │
│  └─────────────┘  └─────────────┘  └────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

### How It Integrates with Swarm Consensus

The ConsensusPlanner is built on top of the **Swarm Consensus plugin** (`code_puppy/plugins/swarm_consensus/`):

1. **Shared Orchestrator**: Uses `SwarmOrchestrator` for multi-agent execution
2. **Consensus Engine**: Leverages the same consensus detection and synthesis logic
3. **Approach System**: Can use the 7 reasoning approaches (thorough, creative, critical, etc.)
4. **Confidence Scoring**: Inherits multi-factor confidence scoring

The ConsensusPlanner **extends** the swarm system with:
- **Model comparison capabilities**: Run the same task on different models
- **Adaptive strategy selection**: Decide when to use consensus vs single model
- **Planning-specific synthesis**: Structure raw responses into execution plans
- **Model recommendation**: Pick the best model for task execution

## Usage

### Slash Commands

#### `/consensus_plan <task>`

Force multi-model consensus planning for any task.

```bash
/consensus_plan Design a caching system for API responses
/consensus_plan Create a database migration strategy
/consensus_plan Plan a security audit for user authentication
```

**Example Output**:
```markdown
🎯 **CONSENSUS PLAN**: Design a caching system for API responses

📊 **DECISION ANALYSIS**:
- Complexity: High
- Risk: Medium
- Strategy: Multi-model consensus
- Models: claude-sonnet-4, gpt-4.1, gemini-2.5-pro

📋 **EXECUTION PLAN**:

### Phase 1: Analysis & Requirements
- [ ] Audit current API endpoints for cacheability
- [ ] Define cache key strategy (URL + user context)
- [ ] Determine TTL requirements per endpoint

### Phase 2: Architecture Design
- [ ] Choose caching layer (Redis vs in-memory)
- [ ] Design cache invalidation strategy
- [ ] Plan for cache warming on deploy

### Phase 3: Implementation
- [ ] Add cache middleware
- [ ] Implement cache-aside pattern
- [ ] Add cache metrics and monitoring

### Phase 4: Testing & Validation
- [ ] Unit tests for cache logic
- [ ] Load testing with cache hit/miss ratios
- [ ] Chaos testing for cache failures

🤖 **MODEL RECOMMENDATION**: claude-sonnet-4 - Best balance of 
security awareness and practical implementation guidance

⚠️ **CONSIDERATIONS**:
- Risk of stale data on rapid updates
- Memory pressure with large payloads
- Distributed cache consistency if multi-region
```

#### `/compare_models <task>`

Run the same task on multiple models and compare their approaches.

```bash
/compare_models How should I structure this Python module?
/compare_models What's the best approach for error handling in async code?
```

**Example Output**:
```
🤖 Model Comparison Results

### 🔥 #1 claude-sonnet-4
**Confidence**: 92%
**Time**: 1,245ms

I recommend a layered architecture with:
1. Repository pattern for data access
2. Service layer for business logic
3. Clear exception hierarchy...

---

### ✅ #2 gpt-4.1
**Confidence**: 85%
**Time**: 890ms

Consider using dependency injection...

---

### ⚠️ #3 gemini-2.5-pro
**Confidence**: 78%
**Time**: 1,567ms

A functional approach with pure functions...

---

🏆 Best Model: claude-sonnet-4 (92% confidence)
```

#### `/model_vote <task>`

Quick model selection via consensus. Each model "votes" on whether they're best suited for the task.

```bash
/model_vote I need to analyze a complex security vulnerability
/model_vote Help me write a recursive algorithm with memoization
```

**Example Output**:
```
🗳️ Running model vote for: I need to analyze a complex security vulnerability...

🎯 Consensus recommends: **claude-sonnet-4**

Rationale: Claude scored highest on security-focused tasks due to 
explicit security training and cautious approach to trust boundaries.
```

#### `/consensus:status`

Show current ConsensusPlanner configuration.

```bash
/consensus:status
```

**Example Output**:
```
## 🎯 Consensus Planner Configuration

✅ **Enabled**: True
🎯 **Complexity Threshold**: 70%
📊 **Swarm Size**: 3 agents
⏱️ **Timeout**: 180s

**Preferred Models**:
  - claude-sonnet-4
  - gpt-4.1
  - gemini-2.5-pro

### Commands
- `/consensus_plan <task>` - Force plan with consensus
- `/compare_models <task>` - Compare model outputs
- `/model_vote <task>` - Get model recommendation
- `/consensus:enable` - Enable consensus planner
- `/consensus:disable` - Disable consensus planner
```

### Programmatic API

#### Basic Planning

```python
import asyncio
from code_puppy.agents.consensus_planner import ConsensusPlannerAgent

async def create_plan():
    agent = ConsensusPlannerAgent()
    
    # Let the agent decide if consensus is needed
    plan = await agent.plan_with_consensus(
        "Design a rate limiting system"
    )
    
    print(plan.to_markdown())
    print(f"Confidence: {plan.confidence:.0%}")
    print(f"Recommended model: {plan.recommended_model}")
    print(f"Used consensus: {plan.used_consensus}")

asyncio.run(create_plan())
```

#### Force Consensus

```python
from code_puppy.agents.consensus_planner import ConsensusPlannerAgent

async def force_consensus():
    agent = ConsensusPlannerAgent()
    
    # Bypass complexity check and force multi-model consensus
    plan = await agent._create_plan_with_consensus(
        task="Plan a security audit",
        analysis={"forced": True}
    )
    
    return plan
```

#### Model Comparison

```python
from code_puppy.agents.consensus_planner import ConsensusPlannerAgent

async def compare_approaches():
    agent = ConsensusPlannerAgent()
    
    results = await agent.compare_model_approaches(
        task="Design an error handling strategy",
        models=["claude-sonnet-4", "gpt-4.1", "gemini-2.5-pro"]
    )
    
    for result in results:
        print(f"{result.model_name}: {result.confidence:.0%} confidence")
        print(f"  Time: {result.execution_time_ms:.0f}ms")
        print(f"  Approach: {result.response[:200]}...")
        print()
    
    # Get best model
    best = max(results, key=lambda x: x.confidence)
    print(f"Best model: {best.model_name}")
```

#### Model Selection

```python
from code_puppy.agents.consensus_planner import ConsensusPlannerAgent

async def select_best_model():
    agent = ConsensusPlannerAgent()
    
    best_model = await agent.select_best_model(
        "Analyze this complex algorithm for optimization opportunities"
    )
    
    print(f"Recommended model: {best_model}")
```

#### Check Execution Stats

```python
from code_puppy.agents.consensus_planner import ConsensusPlannerAgent

agent = ConsensusPlannerAgent()

# ... run some plans ...

stats = agent.get_execution_stats()
print(f"Total executions: {stats['total_executions']}")
print(f"Consensus rate: {stats['consensus_rate']:.0%}")
print(f"Average confidence: {stats['average_confidence']:.0%}")
```

### As a Tool Inside Other Agents

The ConsensusPlanner registers three tools that any agent can use:

#### `plan_with_consensus`

```python
# Inside an agent's run method
async def my_agent_run(self, prompt: str):
    # For complex planning tasks, use consensus
    if "design" in prompt.lower() or "architecture" in prompt.lower():
        plan_result = await plan_with_consensus(
            task=prompt,
            force_consensus=False  # Let it decide based on complexity
        )
        
        return f"""
Here's the consensus-backed plan:

{plan_result['markdown']}

Recommended model for execution: {plan_result['recommended_model']}
"""
```

#### `select_model_for_task`

```python
# Pick the best model for a specific subtask
model_selection = await select_model_for_task(
    task="Analyze this code for security vulnerabilities"
)

best_model = model_selection['recommended_model']
comparison = model_selection['comparison']
```

#### `compare_model_approaches`

```python
# Compare how different models approach the same problem
comparison = await compare_model_approaches(
    task="Should I use inheritance or composition here?",
    models=["claude-sonnet-4", "gpt-4.1"]
)

for result in comparison['results']:
    print(f"{result['model']}: {result['confidence']:.0%}")
```

## Decision Framework

### Complexity Analysis

The ConsensusPlanner analyzes tasks to determine strategy:

```python
# Keywords that trigger higher complexity scores
COMPLEXITY_KEYWORDS = {
    "architecture": 0.8,
    "security": 0.9,
    "refactor": 0.6,
    "design": 0.7,
    "critical": 0.9,
    "migration": 0.8,
    "performance": 0.6,
    # ... more keywords
}

# Uncertainty markers suggest consensus needed
UNCERTAINTY_MARKERS = [
    "not sure", "unclear", "might be", 
    "trade-off", "balance between"
]
```

### Decision Matrix

| Task Characteristics | Strategy | Models | Time |
|---------------------|----------|--------|------|
| Low complexity (<0.5) | Single model | 1 | ~1-2s |
| Medium complexity (0.5-0.7) | Single-model swarm | 2-3 | ~3-5s |
| High complexity (>0.7) | Multi-model consensus | 2-3 | ~5-10s |
| Critical security | Multi-model consensus | 3+ | ~8-15s |

### Threshold Configuration

```python
# Complexity threshold (0.0-1.0)
# Tasks scoring above this use multi-model consensus
consensus_planner_threshold = 0.7  # Default

# Always-on mode (bypasses complexity check)
consensus_planner_always_on = false  # Default
```

## Configuration

### Config File (`puppy.cfg`)

```ini
[consensus_planner]
enabled = true
threshold = 0.7
swarm_size = 3
timeout = 180
always_on = false

[models]
preferred_consensus_models = claude-sonnet-4, gpt-4.1, gemini-2.5-pro
```

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `CODE_PUPPY_CONSENSUS_PLANNER_ENABLED` | Enable consensus planner | `true` |
| `CODE_PUPPY_CONSENSUS_PLANNER_THRESHOLD` | Complexity threshold (0.0-1.0) | `0.7` |
| `CODE_PUPPY_CONSENSUS_PLANNER_SWARM_SIZE` | Number of agents in swarm | `3` |
| `CODE_PUPPY_CONSENSUS_PLANNER_TIMEOUT` | Timeout in seconds | `180` |
| `CODE_PUPPY_CONSENSUS_PLANNER_ALWAYS_ON` | Always use consensus | `false` |
| `CODE_PUPPY_PREFERRED_CONSENSUS_MODELS` | Comma-separated model list | `claude-sonnet-4,gpt-4.1,gemini-2.5-pro` |

### Runtime Configuration

```python
from code_puppy.config import set_config_value

# Adjust threshold
set_config_value("consensus_planner_threshold", "0.8")

# Change swarm size
set_config_value("consensus_planner_swarm_size", "5")

# Enable always-on mode
set_config_value("consensus_planner_always_on", "true")

# Set preferred models
set_config_value("preferred_consensus_models", "claude-opus-4,gpt-4.1")
```

### Configuration Parameters

| Parameter | Range | Description |
|-----------|-------|-------------|
| `threshold` | 0.0-1.0 | Complexity score above which to use multi-model consensus |
| `swarm_size` | 2-5 | Number of agents when using swarm (Pack Leader limit respected) |
| `timeout` | 30-600 | Maximum seconds to wait for consensus |
| `always_on` | true/false | Skip complexity check, always use consensus |
| `preferred_consensus_models` | List | Models to use for consensus (must support tools) |

## Use Cases

### When to Use ConsensusPlanner

| Scenario | Why It Helps |
|----------|-------------|
| **Architecture Reviews** | Multiple perspectives catch integration issues |
| **Security Planning** | Security + pragmatic models balance safety and usability |
| **Database Migrations** | Critical analysis prevents data loss scenarios |
| **API Design** | Creative + minimalist approaches yield elegant solutions |
| **Refactoring Strategy** | Thorough + pragmatic ensures no regressions |
| **Performance Optimization** | Performance + thorough covers measurement and edge cases |
| **Feature Roadmapping** | Strategic planning benefits from diverse perspectives |

### When NOT to Use It

| Scenario | Why Skip It |
|----------|-------------|
| Simple file operations | Overkill for basic tasks |
| Clear-cut fixes | No benefit from debate |
| Time-critical emergencies | Speed matters more than consensus |
| Documentation updates | Single model is sufficient |
| Routine maintenance | Established patterns don't need debate |

### Real-World Examples

#### Example 1: Security Architecture

```bash
/consensus_plan Design a zero-trust authentication system for our microservices
```

**What happens**:
1. **Security approach**: Identifies trust boundary concerns
2. **Thorough approach**: Maps all authentication flows
3. **Pragmatic approach**: Evaluates operational complexity
4. **Consensus**: Balances security rigor with maintainability

#### Example 2: Database Migration

```bash
/consensus_plan Create a zero-downtime migration strategy from PostgreSQL 13 to 16
```

**What happens**:
1. **Thorough approach**: Identifies all breaking changes
2. **Critical approach**: Finds potential data loss scenarios
3. **Pragmatic approach**: Designs rollback strategy
4. **Consensus**: Synthesizes safe migration plan with checkpoints

#### Example 3: Model Selection

```bash
/model_vote I need to implement a complex recursive descent parser
```

**What happens**:
1. Each model analyzes the task complexity
2. Models score their own suitability
3. GPT-4 might win on algorithmic tasks
4. Claude might win on safety-critical parsing

#### Example 4: Comparing Approaches

```bash
/compare_models Should we use event sourcing or traditional CRUD for our order system?
```

**What happens**:
1. Each model advocates for their preferred approach
2. Trade-offs are surfaced explicitly
3. You get multiple perspectives before deciding

## Integration with Swarm Consensus

The ConsensusPlanner is built on the **Swarm Consensus plugin**, creating a layered architecture:

### Shared Components

```
┌─────────────────────────────────────────────────────────────┐
│                    ConsensusPlannerAgent                      │
│  ┌──────────────┐  ┌──────────────┐  ┌─────────────────────┐ │
│  │ Task Analyzer│  │Model Selector│  │ Plan Synthesizer   │ │
│  └──────────────┘  └──────────────┘  └─────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│              SwarmOrchestrator (shared)                     │
│  ┌──────────────┐  ┌──────────────┐  ┌─────────────────────┐ │
│  │Agent Spawner │  │Parallel Exec │  │ Consensus Engine   │ │
│  └──────────────┘  └──────────────┘  └─────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    Base Agent System                        │
└─────────────────────────────────────────────────────────────┘
```

### What ConsensusPlanner Adds

| Feature | Swarm Consensus | ConsensusPlanner |
|---------|-----------------|------------------|
| Multi-agent execution | ✅ | ✅ (inherits) |
| Consensus detection | ✅ | ✅ (inherits) |
| Confidence scoring | ✅ | ✅ (inherits) |
| Task complexity analysis | ❌ | ✅ |
| Model comparison | ❌ | ✅ |
| Model recommendation | ❌ | ✅ |
| Structured plan output | ❌ | ✅ |
| Adaptive strategy selection | ❌ | ✅ |

### Using Both Together

You can use Swarm Consensus directly for raw multi-agent execution, and ConsensusPlanner for planning-specific tasks:

```python
# For general multi-agent tasks
from code_puppy.plugins.swarm_consensus import SwarmOrchestrator

orchestrator = SwarmOrchestrator()
result = await orchestrator.execute_swarm(
    task_prompt="Review this code",
    task_type="code_review"
)

# For planning tasks
from code_puppy.agents.consensus_planner import ConsensusPlannerAgent

agent = ConsensusPlannerAgent()
plan = await agent.plan_with_consensus("Design our caching strategy")
```

## Examples

### Example 1: Complete Planning Workflow

```python
import asyncio
from code_puppy.agents.consensus_planner import ConsensusPlannerAgent

async def plan_caching_system():
    agent = ConsensusPlannerAgent()
    
    # Step 1: Create plan with consensus
    plan = await agent.plan_with_consensus(
        "Design a multi-tier caching system for our API gateway"
    )
    
    # Step 2: Display the plan
    print(plan.to_markdown())
    
    # Step 3: Get recommended model for implementation
    best_model = plan.recommended_model
    print(f"\n🤖 Recommended model for implementation: {best_model}")
    
    # Step 4: Check if we should use consensus for implementation
    use_consensus, reason = agent.should_use_consensus(
        task="Implement the caching system",
        context={"file_patterns": ["api", "gateway", "cache"]}
    )
    print(f"\n📊 Use consensus for implementation? {use_consensus}")
    print(f"   Reason: {reason}")
    
    # Step 5: View execution history
    stats = agent.get_execution_stats()
    print(f"\n📈 Execution stats: {stats}")

asyncio.run(plan_caching_system())
```

### Example 2: Model Comparison Before Decision

```python
import asyncio
from code_puppy.agents.consensus_planner import ConsensusPlannerAgent

async def compare_before_deciding():
    agent = ConsensusPlannerAgent()
    
    # First, compare models on a sample task
    task = "Should we use Redis or in-memory caching?"
    comparison = await agent.compare_model_approaches(task)
    
    # Analyze results
    for result in comparison:
        print(f"{result.model_name}:")
        print(f"  Confidence: {result.confidence:.0%}")
        print(f"  Time: {result.execution_time_ms:.0f}ms")
        print(f"  Response preview: {result.response[:150]}...")
        print()
    
    # Pick best model based on confidence + speed
    sorted_results = sorted(
        comparison,
        key=lambda x: (x.confidence, -x.execution_time_ms),
        reverse=True
    )
    
    best = sorted_results[0]
    print(f"🏆 Best choice: {best.model_name}")
    print(f"   Confidence: {best.confidence:.0%}")
    print(f"   Speed: {best.execution_time_ms:.0f}ms")

asyncio.run(compare_before_deciding())
```

### Example 3: Custom Configuration for Critical Tasks

```python
import asyncio
from code_puppy.config import set_config_value
from code_puppy.agents.consensus_planner import ConsensusPlannerAgent
from code_puppy.plugins.swarm_consensus.models import SwarmConfig

async def critical_security_planning():
    # Configure for high-stakes security planning
    set_config_value("consensus_planner_threshold", "0.5")  # Lower threshold
    set_config_value("consensus_planner_swarm_size", "5")   # More agents
    set_config_value("preferred_consensus_models", 
                     "claude-opus-4,gpt-4.1,gemini-2.5-pro")
    
    agent = ConsensusPlannerAgent()
    
    # Force consensus regardless of complexity
    plan = await agent._create_plan_with_consensus(
        task="Design a secure key management system for customer data encryption",
        analysis={"forced": True, "criticality": "high"}
    )
    
    # The plan will have high confidence due to more models
    print(f"Plan confidence: {plan.confidence:.0%}")
    print(f"Models used: {len(plan.phases[0].get('tasks', []))} approaches")
    
    # Alternative approaches are especially valuable for security
    if plan.alternative_approaches:
        print("\n🔄 Alternative approaches considered:")
        for alt in plan.alternative_approaches:
            print(f"  - {alt}")

asyncio.run(critical_security_planning())
```

### Example 4: Building a Custom Agent with Consensus

```python
from code_puppy.agents.base_agent import BaseAgent
from code_puppy.agents.consensus_planner import ConsensusPlannerAgent

class ArchitectureAgent(BaseAgent):
    """An agent that uses consensus for all architecture decisions."""
    
    def __init__(self):
        super().__init__()
        self.consensus_planner = ConsensusPlannerAgent()
    
    async def run(self, prompt: str) -> str:
        # Check if this is an architecture task
        if self._is_architecture_task(prompt):
            # Use consensus planning
            plan = await self.consensus_planner.plan_with_consensus(prompt)
            return self._format_architecture_response(plan)
        else:
            # Use standard execution
            return await super().run(prompt)
    
    def _is_architecture_task(self, prompt: str) -> bool:
        keywords = ["design", "architecture", "system", "structure"]
        return any(kw in prompt.lower() for kw in keywords)
    
    def _format_architecture_response(self, plan) -> str:
        return f"""
# Architecture Recommendation

{plan.to_markdown()}

---
*This recommendation was developed through multi-model consensus 
with {plan.confidence:.0%} confidence.*
"""
```

### Example 5: Disagreement Resolution

```python
import asyncio
from code_puppy.agents.consensus_planner import ConsensusPlannerAgent
from code_puppy.plugins.swarm_consensus.models import AgentResult

async def resolve_disagreement():
    agent = ConsensusPlannerAgent()
    
    # Simulate results with disagreement
    mock_results = [
        AgentResult(
            agent_name="claude-sonnet-4",
            response="Use Redis for distributed caching",
            confidence_score=0.9,
            approach_used="security"
        ),
        AgentResult(
            agent_name="gpt-4.1",
            response="Use in-memory caching for simplicity",
            confidence_score=0.7,
            approach_used="pragmatic"
        ),
        AgentResult(
            agent_name="gemini-2.5-pro",
            response="Use Redis with fallback to in-memory",
            confidence_score=0.8,
            approach_used="creative"
        ),
    ]
    
    # Resolve the disagreement
    resolution = agent.resolve_disagreement(mock_results)
    print("Synthesized Resolution:")
    print(resolution)

asyncio.run(resolve_disagreement())
```

## Best Practices

### ✅ DO:

- **Use for planning, not execution**: Consensus is for deciding *what* to do, not doing it
- **Check confidence scores**: Low scores (<60%) suggest you should clarify the task
- **Review alternative approaches**: They often contain valuable insights
- **Adjust thresholds by domain**: Security = lower threshold, docs = higher threshold
- **Compare models when uncertain**: `/compare_models` helps you understand different perspectives
- **Use model recommendations**: The recommended model is usually best for execution
- **Enable always-on for critical work**: When quality matters more than speed

### ❌ DON'T:

- **Don't use for simple tasks**: It's overkill for "fix this typo"
- **Don't ignore low confidence**: It means models disagree—investigate why
- **Don't skip the plan review**: The markdown output has valuable context
- **Don't always force consensus**: Let the complexity analyzer do its job
- **Don't use with incompatible models**: Ensure all models support tool calling
- **Don't ignore execution stats**: Track your consensus usage patterns

## Troubleshooting

### Plan Has Low Confidence

**Symptoms**: Confidence score < 60%

**Causes & Solutions**:
- Task is ambiguous → Clarify the prompt
- Models disagree significantly → Review alternative approaches
- Task is novel → Consider breaking into smaller subtasks
- Configuration issue → Check `preferred_consensus_models` are available

### Timeout Errors

**Symptoms**: `Consensus planning timed out`

**Solutions**:
```bash
# Increase timeout
/set consensus_planner_timeout 300
```

### No Models Available

**Symptoms**: `No models available for consensus`

**Check**:
```bash
/consensus:status
```

**Solutions**:
- Verify models are configured in `puppy.cfg`
- Check API keys are set: `echo $ANTHROPIC_API_KEY`
- Ensure models support tool calling

### Consensus Always Triggered

**Symptoms**: Every task uses consensus, even simple ones

**Solutions**:
```bash
# Check threshold isn't too low
/set consensus_planner_threshold 0.8

# Disable always-on mode if enabled
/set consensus_planner_always_on false
```

### Models Give Very Different Answers

**Symptoms**: High disagreement, low consensus

**This is actually expected** for ambiguous or opinion-based tasks. Consider:
- Clarifying constraints in the prompt
- Using `/compare_models` to understand differences
- Making the decision yourself with the multiple perspectives

## API Reference

### ConsensusPlannerAgent

```python
class ConsensusPlannerAgent(BaseAgent):
    def __init__(self)
    
    # Core planning methods
    async def plan_with_consensus(self, task: str) -> Plan
    async def _create_plan_with_consensus(self, task: str, analysis: dict) -> Plan
    async def _create_plan_single_model(self, task: str) -> Plan
    
    # Model selection methods
    async def select_best_model(self, task: str) -> str
    async def compare_model_approaches(self, task: str, models: list[str] | None = None) -> list[ModelComparisonResult]
    
    # Decision methods
    def should_use_consensus(self, task: str, context: dict | None = None) -> tuple[bool, str]
    def resolve_disagreement(self, results: list[AgentResult]) -> str
    
    # Utility methods
    def get_available_models(self) -> list[str]
    def get_execution_stats(self) -> dict[str, Any]
```

### Plan

```python
@dataclass
class Plan:
    objective: str
    phases: list[dict[str, Any]]
    recommended_model: str
    confidence: float
    alternative_approaches: list[str]
    risks: list[str]
    used_consensus: bool
    
    def to_markdown(self) -> str
```

### ModelComparisonResult

```python
@dataclass
class ModelComparisonResult:
    model_name: str
    response: str
    confidence: float
    execution_time_ms: float
    approach: str
```

## Contributing

When modifying the ConsensusPlanner:

1. **Keep files under 600 lines**: Split into submodules when needed
2. **Maintain decision framework logic**: Changes to complexity analysis affect all users
3. **Test with multiple models**: Ensure it works with your configured models
4. **Update this README**: Documentation should match implementation
5. **Follow the plugin pattern**: New features should use the callback system

## See Also

- [Swarm Consensus Plugin](../../plugins/swarm_consensus/README.md) — The underlying multi-agent system
- [Base Agent](../base_agent.py) — Parent class with core agent functionality
- [Agent Manager](../agent_manager.py) — How agents are loaded and managed
- [Callbacks](../../callbacks.py) — Hook system that enables this plugin

---

**Built with ❤️ by the Code Puppy team**

*Part of the Code Puppy multi-agent ecosystem*
