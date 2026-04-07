# agent_tools.py
import asyncio
import itertools
import json
import logging
import msgpack
import re
import traceback
from datetime import datetime

# Imports for streaming retry logic (transient HTTP error handling)
import httpcore
import httpx
from functools import partial
from pathlib import Path

from dbos import DBOS, SetWorkflowID
from pydantic import BaseModel

# Import Agent from pydantic_ai to create temporary agents for invocation
from pydantic_ai import Agent, RunContext, UsageLimits
from pydantic_ai.messages import ModelMessage
from pydantic_ai.exceptions import ModelHTTPError

from code_puppy.config import (
    DATA_DIR,
    get_message_limit,
    get_use_dbos,
    get_value)
from code_puppy.messaging import (
    SubAgentInvocationMessage,
    SubAgentResponseMessage,
    emit_error,
    emit_info,
    emit_success,
    get_message_bus,
    get_session_context,
    set_session_context)
from code_puppy.persistence import atomic_write_msgpack
from code_puppy.tools.common import generate_group_id
from code_puppy.tools.subagent_context import subagent_context

# Set to track active subagent invocation tasks
_active_subagent_tasks: set[asyncio.Task] = set()

# Logger for this module
logger = logging.getLogger(__name__)

# Atomic counter for DBOS workflow IDs - ensures uniqueness even in rapid back-to-back calls
# itertools.count() is thread-safe for next() calls
_dbos_workflow_counter = itertools.count()


def _generate_dbos_workflow_id(base_id: str) -> str:
    """Generate a unique DBOS workflow ID by appending an atomic counter.

    DBOS requires workflow IDs to be unique across all executions.
    This function ensures uniqueness by combining the base_id with
    an atomically incrementing counter.

    Args:
        base_id: The base identifier (e.g., group_id from generate_group_id)

    Returns:
        A unique workflow ID in format: {base_id}-wf-{counter}
    """
    counter = next(_dbos_workflow_counter)
    return f"{base_id}-wf-{counter}"

# Constants for streaming retry logic
# These match the test constants in tests/agents/test_streaming_retry.py
MAX_STREAMING_RETRIES = 3
STREAMING_RETRY_DELAYS = [1, 2, 4]
_RETRYABLE_STREAMING_EXCEPTIONS = (
    httpx.RemoteProtocolError,
    httpx.ReadTimeout,
    httpcore.RemoteProtocolError,
)


def _is_transient_model_error(error: ModelHTTPError) -> bool:
    """Check if a ModelHTTPError is a transient infrastructure error.

    Some API proxies return HTTP 400 when the upstream connection drops,
    which is actually a transient infrastructure error, not a real client error.
    """
    if error.status_code == 400:
        body_str = str(error.body or "").lower()
        return "connection prematurely closed" in body_str
    return False


async def _run_with_streaming_retry(run_coro_factory):
    """Wrap agent run with retry logic for transient HTTP errors during streaming.

    Catches and retries transient network errors from LLM providers:
    - httpx.RemoteProtocolError (peer closes connection mid-stream)
    - httpx.ReadTimeout (read timeout during streaming)
    - httpcore.RemoteProtocolError (lower-level connection close)

    These errors occur when the LLM provider or an intermediary proxy drops
    the connection during a streamed response. They are always safe to retry
    since no application state has been mutated.

    The retry uses exponential backoff (1s, 2s, 4s) with up to 3 attempts
    before propagating the error.

    Args:
        run_coro_factory: A callable that returns a coroutine to run.

    Returns:
        The result of the coroutine.

    Raises:
        The last retryable exception if all retries are exhausted.
    """
    last_error = None
    for attempt in range(MAX_STREAMING_RETRIES):
        try:
            return await run_coro_factory()
        except _RETRYABLE_STREAMING_EXCEPTIONS as e:
            last_error = e
            if attempt < MAX_STREAMING_RETRIES - 1:
                delay = STREAMING_RETRY_DELAYS[attempt]
                await asyncio.sleep(delay)
        except ModelHTTPError as e:
            if _is_transient_model_error(e):
                last_error = e
                if attempt < MAX_STREAMING_RETRIES - 1:
                    delay = STREAMING_RETRY_DELAYS[attempt]
                    logger.warning(
                        f"Transient ModelHTTPError (attempt {attempt + 1}/{MAX_STREAMING_RETRIES}): "
                        f"status={e.status_code}, body={e.body}"
                    )
                    await asyncio.sleep(delay)
            else:
                raise
    raise last_error





def _generate_session_hash_suffix() -> str:
    """Generate a unique session ID suffix using uuid4 for collision safety."""
    import uuid

    return uuid.uuid4().hex[:8]


def _sanitize_messages_for_dbos(messages: list[ModelMessage]) -> list[ModelMessage]:
    """Sanitize messages to remove non-serializable objects before DBOS serialization.

    DBOS uses pickle for workflow durability, which cannot serialize coroutines
    or other async objects that may be captured in message metadata fields.
    This function uses pydantic-ai's type adapter to serialize and deserialize
    messages, which strips out non-serializable objects while preserving the
    message structure.

    Args:
        messages: List of ModelMessage objects to sanitize.

    Returns:
        Sanitized list of ModelMessage objects safe for DBOS serialization.
    """
    # Skip expensive JSON round-trip when DBOS is not enabled
    if not get_use_dbos():
        return messages

    if not messages:
        return messages

    try:
        from pydantic_ai.messages import ModelMessagesTypeAdapter

        # Serialize to JSON (this strips non-serializable objects)
        json_data = ModelMessagesTypeAdapter.dump_json(messages)
        # Deserialize back to messages (this creates clean message objects)
        return ModelMessagesTypeAdapter.validate_json(json_data)
    except Exception as e:
        # Log the sanitization failure so we can track if this becomes a recurring issue
        logging.getLogger(__name__).warning(
            f"Message sanitization failed: {e}. Falling back to original messages."
        )
        # If serialization fails, return original messages
        # The error will be caught later during actual DBOS serialization
        return messages


# Regex pattern for kebab-case session IDs
SESSION_ID_PATTERN = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
SESSION_ID_MAX_LENGTH = 128


def _validate_session_id(session_id: str) -> None:
    """Validate that a session ID follows kebab-case naming conventions.

    Args:
        session_id: The session identifier to validate

    Raises:
        ValueError: If the session_id is invalid

    Valid format:
        - Lowercase letters (a-z)
        - Numbers (0-9)
        - Hyphens (-) to separate words
        - No uppercase, no underscores, no special characters
        - Length between 1 and 128 characters

    Examples:
        Valid: "my-session", "agent-session-1", "discussion-about-code"
        Invalid: "MySession", "my_session", "my session", "my--session"
    """
    if not session_id:
        raise ValueError("session_id cannot be empty")

    if len(session_id) > SESSION_ID_MAX_LENGTH:
        raise ValueError(
            f"Invalid session_id '{session_id}': must be {SESSION_ID_MAX_LENGTH} characters or less"
        )

    if not SESSION_ID_PATTERN.match(session_id):
        raise ValueError(
            f"Invalid session_id '{session_id}': must be kebab-case "
            "(lowercase letters, numbers, and hyphens only). "
            "Examples: 'my-session', 'agent-session-1', 'discussion-about-code'"
        )


def _get_subagent_sessions_dir() -> Path:
    """Get the directory for storing subagent session data.

    Returns:
        Path to XDG data directory/subagent_sessions/
    """
    sessions_dir = Path(DATA_DIR) / "subagent_sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    return sessions_dir


def _save_session_history(
    session_id: str,
    message_history: list[ModelMessage],
    agent_name: str,
    initial_prompt: str | None = None) -> None:
    """Save session history to filesystem.

    Args:
        session_id: The session identifier (must be kebab-case)
        message_history: List of messages to save
        agent_name: Name of the agent being invoked
        initial_prompt: The first prompt that started this session (for .txt metadata)

    Raises:
        ValueError: If session_id is not valid kebab-case format
    """
    # Validate session_id format before saving
    _validate_session_id(session_id)

    sessions_dir = _get_subagent_sessions_dir()

    # Save msgpack file with JSON-serializable message history.
    # Use dump_python to get serializable dicts directly (avoids JSON round-trip).
    # This eliminates triple serialization: dump_python → msgpack instead of
    # dump_json → msgpack → validate_json.
    from pydantic_ai.messages import ModelMessagesTypeAdapter
    payload = {
        "format": "pydantic-ai-json",
        "payload": ModelMessagesTypeAdapter.dump_python(message_history, mode="json"),
    }
    msgpack_path = sessions_dir / f"{session_id}.msgpack"
    atomic_write_msgpack(msgpack_path, payload)

    # Save or update txt file with metadata
    txt_path = sessions_dir / f"{session_id}.txt"
    if not txt_path.exists() and initial_prompt:
        # Only write initial metadata on first save
        metadata = {
            "session_id": session_id,
            "agent_name": agent_name,
            "initial_prompt": initial_prompt,
            "created_at": datetime.now().isoformat(),
            "message_count": len(message_history),
        }
        with open(txt_path, "w") as f:
            json.dump(metadata, f, indent=2)
    elif txt_path.exists():
        # Update message count on subsequent saves
        try:
            with open(txt_path, "r") as f:
                metadata = json.load(f)
            metadata["message_count"] = len(message_history)
            metadata["last_updated"] = datetime.now().isoformat()
            with open(txt_path, "w") as f:
                json.dump(metadata, f, indent=2)
        except Exception:
            pass  # If we can't update metadata, no big deal


def _load_session_history(session_id: str) -> list[ModelMessage]:
    """Load session history from filesystem.

    Args:
        session_id: The session identifier (must be kebab-case)

    Returns:
        List of ModelMessage objects, or empty list if session doesn't exist

    Raises:
        ValueError: If session_id is not valid kebab-case format
    """
    # Validate session_id format before loading
    _validate_session_id(session_id)

    sessions_dir = _get_subagent_sessions_dir()

    # Try msgpack first (new format), fall back to legacy pickle
    msgpack_path = sessions_dir / f"{session_id}.msgpack"
    pkl_path = sessions_dir / f"{session_id}.pkl"

    if msgpack_path.exists():
        try:
            raw = msgpack_path.read_bytes()
            data = msgpack.unpackb(raw, raw=False)
            from pydantic_ai.messages import ModelMessagesTypeAdapter
            if isinstance(data, dict) and data.get("format") == "pydantic-ai-json":
                payload = data.get("payload", [])
                # payload is already Python dicts from dump_python, validate them
                return ModelMessagesTypeAdapter.validate_python(payload)
            return ModelMessagesTypeAdapter.validate_python(data)
        except Exception:
            pass  # Fall through to pickle or return empty

    # SECURITY FIX j0ha/l1en: Pickle completely removed - RCE vulnerability
    if pkl_path.exists():
        # Legacy pickle format no longer supported due to security (RCE risk)
        # Files must be migrated to msgpack format
        return []

    return []


class AgentInfo(BaseModel):
    """Information about an available agent."""

    name: str
    display_name: str
    description: str


class ListAgentsOutput(BaseModel):
    """Output for the list_agents tool."""

    agents: list[AgentInfo]
    error: str | None = None


class AgentInvokeOutput(BaseModel):
    """Output for the invoke_agent tool."""

    response: str | None
    agent_name: str
    session_id: str | None = None
    error: str | None = None


def register_list_agents(agent):
    """Register the list_agents tool with the provided agent.

    Args:
        agent: The agent to register the tool with
    """

    @agent.tool
    def list_agents(context: RunContext) -> ListAgentsOutput:
        """List all available sub-agents that can be invoked."""
        # Generate a group ID for this tool execution
        group_id = generate_group_id("list_agents")

        from rich.text import Text

        from code_puppy.config import get_banner_color

        list_agents_color = get_banner_color("list_agents")

        try:
            from code_puppy.agents import get_agent_descriptions, get_available_agents

            # Get available agents and their descriptions from the agent manager
            agents_dict = get_available_agents()
            descriptions_dict = get_agent_descriptions()

            # Convert to list of AgentInfo objects
            agents = [
                AgentInfo(
                    name=name,
                    display_name=display_name,
                    description=descriptions_dict.get(name, "No description available"))
                for name, display_name in agents_dict.items()
            ]

            # Quiet output - banner and count on same line
            agent_count = len(agents)
            emit_info(
                Text.from_markup(
                    f"[bold white on {list_agents_color}] LIST AGENTS [/bold white on {list_agents_color}] "
                    f"[dim]Found {agent_count} agent(s).[/dim]"
                ),
                message_group=group_id)

            return ListAgentsOutput(agents=agents)

        except Exception as e:
            error_msg = f"Error listing agents: {str(e)}"
            emit_error(error_msg, message_group=group_id)
            return ListAgentsOutput(agents=[], error=error_msg)

    return list_agents


def register_invoke_agent(agent):
    """Register the invoke_agent tool with the provided agent.

    Args:
        agent: The agent to register the tool with
    """

    @agent.tool
    async def invoke_agent(
        context: RunContext, agent_name: str, prompt: str, session_id: str | None = None
    ) -> AgentInvokeOutput:
        """Invoke a specific sub-agent with a given prompt.

        Returns:
            AgentInvokeOutput: Contains response, agent_name, session_id, and error fields.
        """
        from code_puppy.agents.agent_manager import load_agent

        # Validate user-provided session_id if given
        if session_id is not None:
            try:
                _validate_session_id(session_id)
            except ValueError as e:
                # Return error immediately if session_id is invalid
                group_id = generate_group_id("invoke_agent", agent_name)
                emit_error(str(e), message_group=group_id)
                return AgentInvokeOutput(
                    response=None, agent_name=agent_name, error=str(e)
                )

        # Generate a group ID for this tool execution
        group_id = generate_group_id("invoke_agent", agent_name)

        # Check if this is an existing session or a new one
        # For user-provided session_id, check if it exists
        # For None, we'll generate a new one below
        if session_id is not None:
            message_history = _load_session_history(session_id)
            is_new_session = len(message_history) == 0
        else:
            message_history = []
            is_new_session = True

        # Generate or finalize session_id
        if session_id is None:
            # Auto-generate a session ID with hash suffix for uniqueness
            # Example: "qa-expert-session-a3f2b1"
            hash_suffix = _generate_session_hash_suffix()
            # Sanitize agent_name: replace underscores with hyphens for kebab-case compliance
            sanitized_agent_name = agent_name.replace("_", "-").lower()
            session_id = f"{sanitized_agent_name}-session-{hash_suffix}"
        elif is_new_session:
            # User provided a base name for a NEW session - append hash suffix
            # Example: "review-auth" -> "review-auth-a3f2b1"
            hash_suffix = _generate_session_hash_suffix()
            session_id = f"{session_id}-{hash_suffix}"
        # else: continuing existing session, use session_id as-is

        # Lazy imports to avoid circular dependency
        from code_puppy.agents.subagent_stream_handler import subagent_stream_handler

        # Emit structured invocation message via MessageBus
        bus = get_message_bus()
        bus.emit(
            SubAgentInvocationMessage(
                agent_name=agent_name,
                session_id=session_id,
                prompt=prompt,
                is_new_session=is_new_session,
                message_count=len(message_history))
        )

        # Save current session context and set the new one for this sub-agent
        previous_session_id = get_session_context()
        set_session_context(session_id)

        # Set terminal session for browser-based terminal tools
        # This uses contextvars which properly propagate through async tasks
        from code_puppy.tools.browser.terminal_tools import (
            _terminal_session_var,
            set_terminal_session)

        terminal_session_token = set_terminal_session(f"terminal-{session_id}")

        # Set browser session for browser tools (qa-kitten, etc.)
        # This allows parallel agent invocations to each have their own browser
        from code_puppy.tools.browser.browser_manager import (
            set_browser_session)

        browser_session_token = set_browser_session(f"browser-{session_id}")

        try:
            # Lazy import to break circular dependency with messaging module
            from code_puppy.model_factory import ModelFactory, make_model_settings

            # Load the specified agent config
            agent_config = load_agent(agent_name)

            # Get the current model for creating a temporary agent
            model_name = agent_config.get_model_name()
            models_config = ModelFactory.load_config()

            # Only proceed if we have a valid model configuration
            if model_name not in models_config:
                raise ValueError(f"Model '{model_name}' not found in configuration")

            model = ModelFactory.get_model(model_name, models_config)

            # Guard against None model (e.g. missing API keys) — get_model
            # should raise ValueError in this case, but defend in depth since
            # DBOSAgent will produce a confusing error if model is None.
            if model is None:
                raise ValueError(
                    f"Failed to initialize model '{model_name}' for agent "
                    f"'{agent_name}'. Check that required API keys are set."
                )

            # Create a temporary agent instance to avoid interfering with current agent state
            instructions = agent_config.get_full_system_prompt()

            # Add AGENTS.md content to subagents
            puppy_rules = agent_config.load_puppy_rules()
            if puppy_rules:
                instructions += f"\n\n{puppy_rules}"

            # Apply prompt additions (like file permission handling) to temporary agents
            from code_puppy import callbacks
            from code_puppy.model_utils import prepare_prompt_for_model

            prompt_additions = callbacks.on_load_prompt()
            # Filter out None values that can occur when callbacks fail
            prompt_additions = [p for p in prompt_additions if p is not None]
            if len(prompt_additions):
                instructions += "\n" + "\n".join(prompt_additions)

            # Handle claude-code models: swap instructions, and prepend system prompt only on first message
            prepared = prepare_prompt_for_model(
                model_name,
                instructions,
                prompt,
                prepend_system_to_user=is_new_session,  # Only prepend on first message
            )
            instructions = prepared.instructions
            prompt = prepared.user_prompt

            import uuid as _uuid

            subagent_name = f"temp-invoke-agent-{session_id}-{_uuid.uuid4().hex[:8]}"
            model_settings = make_model_settings(model_name)

            # Get MCP servers for sub-agents (same as main agent)
            from code_puppy.mcp_ import get_mcp_manager

            mcp_servers = []
            mcp_disabled = get_value("disable_mcp_servers")
            if not (
                mcp_disabled and str(mcp_disabled).lower() in ("1", "true", "yes", "on")
            ):
                manager = get_mcp_manager()
                mcp_servers = manager.get_servers_for_agent()

            if get_use_dbos():
                from pydantic_ai.durable_exec.dbos import DBOSAgent

                # For DBOS, create agent without MCP servers (to avoid serialization issues)
                # and add them at runtime
                temp_agent = Agent(
                    model=model,
                    instructions=instructions,
                    output_type=str,
                    retries=3,
                    toolsets=[],  # MCP servers added separately for DBOS
                    history_processors=[agent_config.message_history_accumulator],
                    model_settings=model_settings)

                # Register the tools that the agent needs
                from code_puppy.tools import register_tools_for_agent

                agent_tools = agent_config.get_available_tools()
                register_tools_for_agent(temp_agent, agent_tools, model_name=model_name)

                # Wrap with DBOS - no streaming for sub-agents
                dbos_agent = DBOSAgent(
                    temp_agent,
                    name=subagent_name)
                temp_agent = dbos_agent

                # Store MCP servers to add at runtime
                subagent_mcp_servers = mcp_servers
            else:
                # Non-DBOS path - include MCP servers directly in the agent
                temp_agent = Agent(
                    model=model,
                    instructions=instructions,
                    output_type=str,
                    retries=3,
                    toolsets=mcp_servers,
                    history_processors=[agent_config.message_history_accumulator],
                    model_settings=model_settings)

                # Register the tools that the agent needs
                from code_puppy.tools import register_tools_for_agent

                agent_tools = agent_config.get_available_tools()
                register_tools_for_agent(temp_agent, agent_tools, model_name=model_name)

                subagent_mcp_servers = None

            # Run the temporary agent with the provided prompt as an asyncio task
            # Pass the message_history from the session to continue the conversation
            workflow_id = None  # Track for potential cancellation

            # Always use subagent_stream_handler to silence output and update console manager
            # This ensures all sub-agent output goes through the aggregated dashboard
            stream_handler = partial(subagent_stream_handler, session_id=session_id)

            # Wrap the agent run in subagent context for tracking
            with subagent_context(agent_name):
                if get_use_dbos():
                    # Generate a unique workflow ID for DBOS - ensures no collisions in back-to-back calls
                    workflow_id = _generate_dbos_workflow_id(group_id)

                    # Add MCP servers to the DBOS agent's toolsets
                    # (temp_agent is discarded after this invocation, so no need to restore)
                    if subagent_mcp_servers:
                        temp_agent._toolsets = (
                            temp_agent._toolsets + subagent_mcp_servers
                        )

                    with SetWorkflowID(workflow_id):
                        task = asyncio.create_task(
                            _run_with_streaming_retry(
                                lambda: temp_agent.run(
                                    prompt,
                                    message_history=message_history,
                                    usage_limits=UsageLimits(
                                        request_limit=get_message_limit()
                                    ),
                                    event_stream_handler=stream_handler)
                            )
                        )
                        _active_subagent_tasks.add(task)
                else:
                    task = asyncio.create_task(
                        _run_with_streaming_retry(
                            lambda: temp_agent.run(
                                prompt,
                                message_history=message_history,
                                usage_limits=UsageLimits(request_limit=get_message_limit()),
                                event_stream_handler=stream_handler)
                        )
                    )
                    _active_subagent_tasks.add(task)

                try:
                    result = await task
                finally:
                    _active_subagent_tasks.discard(task)
                    if task.cancelled():
                        if get_use_dbos() and workflow_id:
                            await DBOS.cancel_workflow_async(workflow_id)

            # Extract the response from the result
            response = result.output

            # Update the session history with the new messages from this interaction
            # The result contains all_messages which includes the full conversation
            updated_history = result.all_messages()

            # Sanitize messages to remove non-serializable objects (coroutines, etc.)
            # This is necessary because DBOS uses pickle for workflow durability
            updated_history = _sanitize_messages_for_dbos(updated_history)

            # Save to filesystem (include initial prompt only for new sessions)
            _save_session_history(
                session_id=session_id,
                message_history=updated_history,
                agent_name=agent_name,
                initial_prompt=prompt if is_new_session else None)

            # Emit structured response message via MessageBus
            bus.emit(
                SubAgentResponseMessage(
                    agent_name=agent_name,
                    session_id=session_id,
                    response=response,
                    message_count=len(updated_history))
            )

            # Emit clean completion summary
            emit_success(
                f"✓ {agent_name} completed successfully", message_group=group_id
            )

            return AgentInvokeOutput(
                response=response, agent_name=agent_name, session_id=session_id
            )

        except Exception as e:
            # Emit clean failure summary
            emit_error(f"✗ {agent_name} failed: {str(e)}", message_group=group_id)

            # Full traceback for debugging
            error_msg = f"Error invoking agent '{agent_name}': {traceback.format_exc()}"
            emit_error(error_msg, message_group=group_id)

            return AgentInvokeOutput(
                response=None,
                agent_name=agent_name,
                session_id=session_id,
                error=error_msg)

        finally:
            # Restore the previous session context
            set_session_context(previous_session_id)
            # Reset terminal session context
            _terminal_session_var.reset(terminal_session_token)
            # Reset browser session context
            from code_puppy.tools.browser.browser_manager import (
                _browser_session_var)

            _browser_session_var.reset(browser_session_token)

    return invoke_agent
