# Agent Swarm Consensus Plugin

> **Ensemble programming with multiple AI perspectives** — get better answers by harnessing the wisdom of the swarm.

## Overview

The Agent Swarm Consensus plugin enables **ensemble programming** by running multiple AI agents with different reasoning approaches simultaneously, then synthesizing their responses into a consensus answer. Like having a team of specialists review your code or problem from different angles before making a decision.

### Why Use Swarm Consensus?

- **Catch blind spots**: One agent might miss what another catches
- **Multiple perspectives**: Security, performance, creativity, pragmatism — all at once
- **Higher confidence**: Consensus-backed answers are more reliable
- **Better solutions**: Synthesis often produces better results than any single agent
- **Reduce hallucinations**: Disagreement between agents flags uncertain areas

## Features

- **Multi-Agent Execution**: Spawn 2-7 agents with different reasoning approaches
- **Intelligent Consensus**: Automatically detect when agents agree and synthesize the best answer
- **7 Reasoning Approaches**: thorough, creative, critical, pragmatic, security, performance, minimalist
- **Confidence Scoring**: Linguistic analysis and cross-agent consistency checks
- **Real-Time TUI**: Visual swarm execution with progress bars and agent status
- **Debating Mode**: Generate debate transcripts showing points of agreement/disagreement
- **Parallel Execution**: Respects Pack Leader limit (MAX_PARALLEL_AGENTS=2) for efficiency
- **Configurable Thresholds**: Adjust consensus sensitivity and swarm size
- **Task-Type Selection**: Automatically selects best approaches for different tasks

## Installation

The plugin auto-registers on startup — no manual installation needed.

```
code_puppy/plugins/swarm_consensus/
├── __init__.py              # Package marker
├── register_callbacks.py    # Plugin registration and slash commands
├── orchestrator.py          # Core swarm execution logic
├── consensus.py             # Consensus detection and synthesis
├── scoring.py               # Confidence scoring algorithms
├── approaches.py            # 7 reasoning approaches
├── models.py                # Data models (SwarmResult, AgentResult)
├── config.py                # Configuration management
└── README.md                # This file
```

The plugin registers automatically via `register_callbacks.py`:
- `/swarm` slash commands via `custom_command` hook
- Help menu entries via `custom_command_help` hook
- Tool registration via `register_tools` hook (for programmatic access)

## Usage

### Slash Commands

#### `/swarm <task>`
Run swarm consensus on a task. Spawns multiple agents with different approaches and returns the synthesized answer.

```bash
/swarm refactor this function to use async/await
/swarm review this code for security issues
/swarm design a database schema for a blog
```

#### `/swarm:interactive`
Launch the visual TUI for real-time swarm execution. Shows agent progress, confidence scores, and consensus formation.

```bash
/swarm:interactive
```

#### `/swarm:status`
Display current swarm configuration.

```bash
/swarm:status
```

Output:
```
## 🤖 Agent Swarm Consensus Status

✅ Enabled: True
📊 Swarm Size: 3 agents
🎯 Consensus Threshold: 70%
⏱️ Timeout: 300s

### Available Approaches
- thorough: Deep analysis with attention to edge cases
- creative: Novel solutions and out-of-the-box thinking
- critical: Security-focused, finds vulnerabilities
- pragmatic: Balanced approach, practical solutions
- security: Specialized security review
- performance: Optimization-focused analysis
- minimalist: Simple, clean solutions
```

#### `/swarm:enable`
Enable automatic swarm mode. When enabled, critical tasks can automatically trigger swarm consensus.

```bash
/swarm:enable
```

#### `/swarm:disable`
Disable automatic swarm mode.

```bash
/swarm:disable
```

### Programmatic API

Access swarm consensus programmatically through the `run_swarm_consensus` tool:

```python
# Inside an agent or plugin
result = await run_swarm_consensus(
    task_prompt="Refactor this function to use async/await",
    task_type="refactor",
    swarm_size=3,
    consensus_threshold=0.7,
)

print(result["final_answer"])
print(f"Consensus reached: {result['consensus_reached']}")
print(f"Average confidence: {result['confidence_scores']}")
```

#### Direct Module Usage

```python
import asyncio
from code_puppy.plugins.swarm_consensus.orchestrator import SwarmOrchestrator
from code_puppy.plugins.swarm_consensus.models import SwarmConfig

async def run_swarm():
    config = SwarmConfig(
        swarm_size=3,
        consensus_threshold=0.7,
        timeout_seconds=300,
        enable_debate=True,
    )
    
    orchestrator = SwarmOrchestrator(config)
    result = await orchestrator.execute_swarm(
        task_prompt="Design a rate limiter",
        task_type="feature_design",
    )
    
    print(result.final_answer)
    print(f"Average confidence: {result.get_average_confidence():.2f}")
    
    # Access individual agent results
    for agent in result.individual_results:
        print(f"{agent.agent_name} ({agent.approach_used}): {agent.confidence_score:.2f}")

asyncio.run(run_swarm())
```

### TUI Interactive Mode

The interactive mode provides a rich visual interface:

```bash
/swarm:interactive
```

Features:
- **Real-time agent status**: See which agents are running, completed, or failed
- **Progress bars**: Visual progress for each agent in the swarm
- **Confidence meters**: Live-updating confidence scores
- **Consensus visualization**: Watch consensus form in real-time
- **Detailed results**: Expandable sections for each agent's contribution
- **Action buttons**: Accept, reject, or re-run the swarm

## Configuration

Configuration is managed via `puppy.cfg` (local or `~/.code_puppy/`) or environment variables.

### Config File (`puppy.cfg`)

```ini
[swarm_consensus]
enabled = true
swarm_size = 3
consensus_threshold = 0.7
timeout = 300
```

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `CODE_PUPPY_SWARM_ENABLED` | Enable swarm mode | `false` |
| `CODE_PUPPY_SWARM_SWARM_SIZE` | Number of agents | `3` |
| `CODE_PUPPY_SWARM_CONSENSUS_THRESHOLD` | Agreement threshold (0.0-1.0) | `0.7` |
| `CODE_PUPPY_SWARM_TIMEOUT` | Timeout in seconds | `300` |

### Programmatic Configuration

```python
from code_puppy.plugins.swarm_consensus.config import (
    set_swarm_enabled,
    set_swarm_size,
    set_consensus_threshold,
    set_swarm_timeout_seconds,
)

# Enable swarm mode
set_swarm_enabled(True)

# Configure swarm size
set_swarm_size(5)

# Set consensus threshold (70%)
set_consensus_threshold(0.7)

# Set timeout to 5 minutes
set_swarm_timeout_seconds(300)
```

### Configuration Parameters

| Parameter | Range | Description |
|-----------|-------|-------------|
| `swarm_size` | 2-7 | Number of agents to spawn. More agents = more perspectives but longer execution. |
| `consensus_threshold` | 0.0-1.0 | Minimum agreement ratio to declare consensus. Higher = stricter agreement required. |
| `timeout` | 10+ seconds | Maximum time to wait for all agents. Agents may still return after timeout. |
| `enable_debate` | true/false | Generate debate transcript showing points of agreement/disagreement. |
| `require_unanimous` | true/false | If true, all agents must agree (threshold becomes 1.0). |

## Reasoning Approaches

The plugin provides 7 distinct reasoning approaches, each representing a different cognitive perspective:

### 🔍 Thorough
**Description**: Detailed, step-by-step analysis with comprehensive coverage  
**Temperature**: 0.3 (focused)  
**Best for**: Complex problems, edge case analysis, comprehensive reviews  
**Mindset**: "Leave no stone unturned. Check every assumption."

### 💡 Creative
**Description**: Outside-the-box thinking and novel perspectives  
**Temperature**: 0.8 (exploratory)  
**Best for**: Feature design, architecture decisions, novel solutions  
**Mindset**: "Question conventional wisdom. Borrow from other domains."

### 🔎 Critical
**Description**: Devil's advocate, finding flaws and questioning assumptions  
**Temperature**: 0.4 (analytical)  
**Best for**: Code review, security analysis, catching blind spots  
**Mindset**: "What could go wrong? Find the weaknesses before they become problems."

### 🔧 Pragmatic
**Description**: Focus on practical implementation and delivery  
**Temperature**: 0.5 (balanced)  
**Best for**: Refactoring, maintenance tasks, production code  
**Mindset**: "Working code beats perfect theory. Consider the maintenance burden."

### 🛡️ Security
**Description**: Security-focused review with adversarial mindset  
**Temperature**: 0.3 (careful)  
**Best for**: Security reviews, input validation, trust boundary analysis  
**Mindset**: "Assume input is malicious. Security is not a feature you add later."

### ⚡ Performance
**Description**: Performance-optimized solutions and resource efficiency  
**Temperature**: 0.4 (analytical)  
**Best for**: Optimization, algorithm review, resource-constrained environments  
**Mindset**: "Measure, don't guess. Consider Big-O and scalability."

### 🎯 Minimalist
**Description**: Simplicity-first, minimal solutions  
**Temperature**: 0.4 (focused)  
**Best for**: API design, library code, reducing complexity  
**Mindset**: "The best code is no code. Fewer moving parts = fewer failures."

## How It Works

### Step-by-Step Consensus Process

1. **Task Analysis**: The orchestrator analyzes the task type to select appropriate reasoning approaches

2. **Agent Spawning**: Creates multiple agent instances, each configured with a different approach
   - Modifies system prompts with approach-specific mindset
   - Adjusts temperature settings per approach
   - Tags agents with their approach for later reference

3. **Parallel Execution**: Runs all agents concurrently (respecting MAX_PARALLEL_AGENTS=2)
   - Each agent analyzes the task from their perspective
   - Execution time and responses are recorded

4. **Confidence Scoring**: Each response is scored based on:
   - Linguistic certainty markers ("definitely", "maybe", etc.)
   - Structural quality (lists, headers, code blocks)
   - Absence of hedging language
   - Cross-agent consistency

5. **Consensus Detection**: Groups similar responses and calculates agreement ratio
   - Uses text similarity and code block comparison
   - Determines if consensus threshold is met

6. **Result Synthesis**: Produces final answer
   - If consensus: synthesizes from agreeing agents
   - If no consensus: blends all responses weighted by confidence
   - Generates debate transcript showing perspectives

7. **Cleanup**: Resets agent configurations to original state

### Task Type Mappings

The plugin automatically selects approaches based on task type:

| Task Type | Default Approaches |
|-----------|-------------------|
| `refactor` | thorough, pragmatic, critical, minimalist |
| `security_review` | security, critical, thorough |
| `feature_design` | creative, pragmatic, thorough |
| `bug_fix` | thorough, pragmatic, critical |
| `performance_optimize` | performance, pragmatic, minimalist |
| `code_review` | critical, security, pragmatic, thorough |
| `architecture` | creative, pragmatic, performance, security |
| `testing` | thorough, critical, security |
| `default` | thorough, creative, pragmatic |

## Use Cases

### When to Use Swarm vs Single Agent

| Scenario | Recommendation | Reason |
|----------|---------------|--------|
| Quick syntax question | Single agent | Faster, no need for consensus |
| Critical security fix | **Swarm** | Multiple security perspectives |
| Architecture decision | **Swarm** | Benefits from creative + pragmatic balance |
| Refactoring legacy code | **Swarm** | Catch edge cases, maintainability concerns |
| Simple file operations | Single agent | Overkill for basic tasks |
| Code review before merge | **Swarm** | Critical + security + pragmatic coverage |
| Exploratory debugging | **Swarm** | Multiple angles often find the bug |
| Documentation updates | Single agent | Straightforward, consensus not needed |

### Specific Use Cases

1. **Pre-Merge Code Review**
   ```bash
   /swarm review this PR for security issues, bugs, and best practices
   ```

2. **Refactoring Decision**
   ```bash
   /swarm should I extract this into a separate module or keep it inline?
   ```

3. **Security Analysis**
   ```bash
   /swarm analyze this authentication flow for vulnerabilities
   ```

4. **Architecture Review**
   ```bash
   /swarm evaluate this microservices architecture - what are the tradeoffs?
   ```

5. **Performance Optimization**
   ```bash
   /swarm how can I improve the performance of this database query?
   ```

## Architecture

### Component Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    SwarmOrchestrator                        │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐  │
│  │   Config    │  │  Approach   │  │   ConsensusEngine   │  │
│  │  (models)   │  │  Selector   │  │    (consensus)      │  │
│  └─────────────┘  └─────────────┘  └─────────────────────┘  │
│                                                             │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐  │
│  │   Agent     │  │  Confidence │  │  Result Synthesis   │  │
│  │   Spawner   │  │   Scoring   │  │     (consensus)     │  │
│  └─────────────┘  └─────────────┘  └─────────────────────┘  │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              Parallel Execution Engine               │   │
│  │         (asyncio + MAX_PARALLEL_AGENTS=2)            │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

### Key Components

#### SwarmOrchestrator (`orchestrator.py`)
The main entry point for swarm execution. Manages the full lifecycle: spawning agents, executing them in parallel, aggregating results, and cleaning up.

#### Approach Selector (`approaches.py`)
Maps task types to appropriate reasoning approaches. Applies approach configurations (system prompt modifiers, temperature) to agents.

#### Consensus Engine (`consensus.py`)
Detects when agents agree using text similarity and code block comparison. Synthesizes final answers from multiple responses.

#### Confidence Scoring (`scoring.py`)
Multi-factor scoring system combining linguistic analysis, structural quality, and cross-agent consistency.

#### Configuration Manager (`config.py`)
Handles settings via puppy.cfg or environment variables with sensible defaults.

#### Data Models (`models.py`)
Type-safe dataclasses for SwarmConfig, AgentResult, and SwarmResult.

## Examples

### Example 1: Security Review

```bash
/swarm review this authentication middleware for security vulnerabilities
```

**What happens**:
1. Security approach identifies potential JWT validation bypass
2. Critical approach questions the token refresh logic
3. Thorough approach checks all edge cases in error handling
4. Consensus highlights 2 confirmed issues, 1 flagged for review

### Example 2: Refactoring Decision

```python
# Programmatic usage
from code_puppy.plugins.swarm_consensus.orchestrator import SwarmOrchestrator
from code_puppy.plugins.swarm_consensus.models import SwarmConfig

config = SwarmConfig(swarm_size=4, consensus_threshold=0.7)
orchestrator = SwarmOrchestrator(config)

result = await orchestrator.execute_swarm(
    task_prompt="Should I extract this 200-line function into a class?",
    task_type="refactor",
)

print(f"Consensus: {result.consensus_reached}")
print(f"Final recommendation: {result.final_answer}")
```

**What happens**:
1. Thorough approach lists all responsibilities of the function
2. Pragmatic approach weighs maintenance burden vs clarity
3. Critical approach identifies potential bugs during extraction
4. Minimalist approach questions if it's needed at all
5. Synthesized answer: "Extract into 3 smaller functions, not a class"

### Example 3: Feature Design

```bash
/swarm design a caching strategy for this API endpoint
```

**What happens**:
1. Creative approach suggests a novel cache invalidation strategy
2. Performance approach analyzes hit rates and TTL tradeoffs
3. Pragmatic approach evaluates operational complexity
4. Consensus synthesizes a balanced approach with fallback options

### Example 4: Analyzing Results

```python
# Deep dive into swarm results
from code_puppy.plugins.swarm_consensus.models import SwarmResult

async def analyze_result():
    result: SwarmResult = await orchestrator.execute_swarm(...)
    
    # Get the best individual agent
    best = result.get_best_result()
    print(f"Best agent: {best.agent_name} with {best.confidence_score:.2f} confidence")
    
    # Average confidence across swarm
    avg = result.get_average_confidence()
    print(f"Swarm average confidence: {avg:.2f}")
    
    # Agreement ratio
    agreement = result.get_agreement_ratio()
    print(f"Agreement ratio: {agreement:.0%}")
    
    # Debate transcript
    if result.debate_transcript:
        print("\nPoints of disagreement:")
        print(result.debate_transcript)
```

### Example 5: Custom Configuration

```python
# Create a specialized swarm for security reviews
from code_puppy.plugins.swarm_consensus.models import SwarmConfig, ApproachConfig

# Define custom approach
custom_security = ApproachConfig(
    name="compliance_security",
    system_prompt_modifier="""
You are a compliance-focused security reviewer. Check for:
1. SOC 2 Type II requirements
2. GDPR data handling
3. PCI-DSS if payment-related
4. Audit trail completeness
""",
    temperature_override=0.2,
)

config = SwarmConfig(
    swarm_size=3,
    approaches=[custom_security, APPROACH_SECURITY, APPROACH_CRITICAL],
    consensus_threshold=0.8,  # Higher bar for security
    require_unanimous=True,
)
```

## Best Practices

### ✅ DO:

- **Use for critical decisions**: Architecture, security, refactoring
- **Start with 3 agents**: Good balance of coverage vs speed
- **Review debate transcripts**: Shows where agents disagree
- **Adjust thresholds for context**: Security = higher threshold
- **Use appropriate task types**: Helps select best approaches
- **Check confidence scores**: Low scores flag uncertain areas

### ❌ DON'T:

- **Don't swarm everything**: Simple tasks don't need consensus
- **Don't ignore disagreement**: If agents disagree, investigate why
- **Don't set threshold too high**: 0.7-0.8 is usually optimal
- **Don't use with tiny prompts**: Waste of resources for trivial tasks
- **Don't ignore execution stats**: Failed agents indicate system issues

## Troubleshooting

### Agents Timing Out

```bash
# Increase timeout
export CODE_PUPPY_SWARM_TIMEOUT=600
# Or in puppy.cfg: timeout = 600
```

### No Consensus Reached

- Lower the threshold: `set_consensus_threshold(0.6)`
- Increase swarm size for more perspectives
- Check if the task is ambiguous (clarify the prompt)

### Low Confidence Scores

- Check that task type matches the actual task
- Review debate transcript for areas of uncertainty
- Consider running with different approaches

### Performance Issues

- Reduce swarm_size for faster execution
- Disable debate generation if not needed
- Check network connectivity to model APIs

## API Reference

### SwarmOrchestrator

```python
class SwarmOrchestrator:
    def __init__(self, config: SwarmConfig | None = None)
    
    async def execute_swarm(
        self,
        task_prompt: str,
        task_context: dict[str, Any] | None = None,
        task_type: str = "default",
    ) -> SwarmResult
```

### SwarmResult

```python
@dataclass
class SwarmResult:
    individual_results: list[AgentResult]
    consensus_reached: bool
    final_answer: str
    confidence_scores: dict[str, float]
    debate_transcript: str
    execution_stats: dict[str, Any]
    
    def get_best_result(self) -> AgentResult | None
    def get_average_confidence(self) -> float
    def get_agreement_ratio(self) -> float
```

### ApproachConfig

```python
@dataclass
class ApproachConfig:
    name: str
    system_prompt_modifier: str
    temperature_override: float | None = None
    description: str = ""
```

## Contributing

When modifying this plugin:

1. **Keep files under 600 lines**: Split into submodules when needed
2. **Maintain approach balance**: Don't bias toward any single perspective
3. **Test consensus logic**: Changes to similarity detection affect all results
4. **Update this README**: Keep documentation in sync with changes
5. **Follow YAGNI**: Don't add complexity without clear benefit

## Future Enhancements

Potential improvements on the roadmap:

- **Adaptive Swarm Sizing**: Automatically adjust based on task complexity
- **Embeddings-based Similarity**: More accurate consensus detection
- **Hierarchical Swarms**: Meta-swarm that manages sub-swarms
- **Custom Approach Designer**: UI for creating new reasoning approaches
- **Swarm Replay**: Re-run with same or different approaches
- **Confidence Calibration**: Adjust scoring based on historical accuracy

## Further Reading

- `code_puppy/callbacks.py` - Hook system that enables this plugin
- `code_puppy/command_line/swarm_commands.py` - Built-in slash commands
- `code_puppy/tui/screens/swarm_screen.py` - TUI implementation
- Plugin directory: `code_puppy/plugins/swarm_consensus/`
