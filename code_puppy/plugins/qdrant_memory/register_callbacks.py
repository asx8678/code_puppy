"""Qdrant hybrid memory plugin for cross-session semantic recall.

Stores conversation snippets with embeddings in Qdrant and retrieves
relevant context from past sessions when loading prompts.

Requires: qdrant-client (optional, plugin silently disables if missing)
Optional: sentence-transformers (for better embeddings, falls back to simple hashing)

Configuration (optional TOML at ~/.code_puppy/qdrant_memory.toml):
    [qdrant]
    host = "localhost"
    port = 6333
    collection_name = "code_puppy_memories"
    embedding_dim = 384
    top_k = 5
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
import uuid
from pathlib import Path
from typing import Any

from code_puppy.callbacks import register_callback

logger = logging.getLogger(__name__)

# Optional imports - gracefully degrade if not available
try:
    from qdrant_client import QdrantClient
    from qdrant_client.models import Distance, VectorParams, PointStruct

    QDRANT_AVAILABLE = True
except ImportError:
    QDRANT_AVAILABLE = False
    QdrantClient = None  # type: ignore
    Distance = None  # type: ignore
    VectorParams = None  # type: ignore
    PointStruct = None  # type: ignore

try:
    import numpy as np

    NUMPY_AVAILABLE = True
except ImportError:
    NUMPY_AVAILABLE = False
    np = None  # type: ignore

# Configuration paths and defaults
_CONFIG_PATH = Path.home() / ".code_puppy" / "qdrant_memory.toml"
_STATE_DIR = Path.home() / ".code_puppy" / "state"
_RECENT_CONTEXT_FILE = _STATE_DIR / "qdrant_recent_context.json"

_DEFAULT_CONFIG = {
    "host": "localhost",
    "port": 6333,
    "collection_name": "code_puppy_memories",
    "embedding_dim": 384,
    "top_k": 5,
    "similarity_threshold": 0.7,
}

# Module-level state
_client: QdrantClient | None = None
_embedding_model: Any | None = None
_config: dict[str, Any] = {}
_initialized = False
_disabled_reason: str | None = None


def _load_config() -> dict[str, Any]:
    """Load configuration from TOML file with graceful fallback."""
    config = dict(_DEFAULT_CONFIG)
    if not _CONFIG_PATH.exists():
        return config

    try:
        try:
            import tomllib  # Python 3.11+
        except ImportError:
            try:
                import tomli as tomllib  # type: ignore[no-redef]
            except ImportError:
                # Manual parse of simple key=value pairs
                text = _CONFIG_PATH.read_text()
                for raw in text.splitlines():
                    line = raw.strip()
                    if not line or line.startswith("["):
                        continue
                    key, _, value = line.partition("=")
                    key = key.strip()
                    value = value.strip().strip('"').strip("'")
                    if key in config:
                        if isinstance(config[key], int):
                            config[key] = int(value)
                        elif isinstance(config[key], float):
                            config[key] = float(value)
                        else:
                            config[key] = value
                return config

        with open(_CONFIG_PATH, "rb") as f:
            data = tomllib.load(f)

        if "qdrant" in data:
            for key in config:
                if key in data["qdrant"]:
                    config[key] = data["qdrant"][key]
    except Exception as e:
        logger.warning(f"qdrant_memory: failed to load config: {e}")

    return config


def _get_embedding_model() -> Any | None:
    """Get or initialize the embedding model."""
    global _embedding_model
    if _embedding_model is not None:
        return _embedding_model

    # Try sentence-transformers for good embeddings
    try:
        from sentence_transformers import SentenceTransformer

        model_name = "all-MiniLM-L6-v2"  # Small, fast, good quality
        logger.info(f"qdrant_memory: loading embedding model {model_name}")
        _embedding_model = SentenceTransformer(model_name)
        return _embedding_model
    except ImportError:
        logger.debug("qdrant_memory: sentence-transformers not available, using hash embeddings")
    except Exception as e:
        logger.warning(f"qdrant_memory: failed to load sentence-transformers: {e}")

    return None


def _generate_embedding(text: str, dim: int = 384) -> list[float]:
    """Generate embedding vector for text.

    Uses sentence-transformers if available, otherwise falls back to
    a simple hash-based embedding (not semantically meaningful but consistent).
    """
    model = _get_embedding_model()
    if model is not None:
        try:
            embedding = model.encode(text, convert_to_numpy=True)
            if NUMPY_AVAILABLE:
                # Normalize
                norm = np.linalg.norm(embedding)
                if norm > 0:
                    embedding = embedding / norm
            return embedding.tolist()
        except Exception as e:
            logger.debug(f"qdrant_memory: embedding generation failed: {e}")

    # Fallback: deterministic hash-based embedding
    # This isn't semantically meaningful but provides consistency
    hash_bytes = hashlib.sha256(text.encode("utf-8")).digest()
    # Expand hash to desired dimension using multiple rounds
    vector = []
    while len(vector) < dim:
        for b in hash_bytes:
            # Normalize to [-1, 1]
            vector.append((b / 255.0) * 2 - 1)
            if len(vector) >= dim:
                break
    return vector[:dim]


def _init_qdrant() -> bool:
    """Initialize Qdrant client and ensure collection exists.

    Returns True if successfully initialized, False otherwise.
    """
    global _client, _config, _initialized, _disabled_reason

    if _initialized:
        return _client is not None

    if not QDRANT_AVAILABLE:
        _disabled_reason = "qdrant-client not installed (pip install qdrant-client)"
        logger.warning(f"qdrant_memory: disabled - {_disabled_reason}")
        _initialized = True
        return False

    _config = _load_config()

    try:
        _client = QdrantClient(
            host=_config["host"],
            port=_config["port"],
        )
        # Test connection
        _client.get_collections()
    except Exception as e:
        _disabled_reason = f"failed to connect to Qdrant: {e}"
        logger.warning(f"qdrant_memory: disabled - {_disabled_reason}")
        _client = None
        _initialized = True
        return False

    # Ensure collection exists
    collection_name = _config["collection_name"]
    embedding_dim = _config["embedding_dim"]

    try:
        collections = _client.get_collections()
        collection_names = [c.name for c in collections.collections]

        if collection_name not in collection_names:
            logger.info(f"qdrant_memory: creating collection {collection_name}")
            _client.create_collection(
                collection_name=collection_name,
                vectors_config=VectorParams(
                    size=embedding_dim,
                    distance=Distance.COSINE,
                ),
            )
    except Exception as e:
        _disabled_reason = f"failed to ensure collection: {e}"
        logger.warning(f"qdrant_memory: disabled - {_disabled_reason}")
        _client = None
        _initialized = True
        return False

    logger.info(f"qdrant_memory: initialized (collection={collection_name})")
    _initialized = True
    return True


def _ensure_state_dir() -> None:
    """Ensure the state directory exists."""
    _STATE_DIR.mkdir(parents=True, exist_ok=True)


def _save_recent_context(session_id: str | None, agent_name: str, context: str) -> None:
    """Save recent context for cross-session retrieval."""
    try:
        _ensure_state_dir()
        data = {
            "session_id": session_id or str(uuid.uuid4()),
            "agent_name": agent_name,
            "context": context,
            "timestamp": time.time(),
        }
        temp_file = _RECENT_CONTEXT_FILE.with_suffix(".tmp")
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        temp_file.replace(_RECENT_CONTEXT_FILE)
    except Exception as e:
        logger.debug(f"qdrant_memory: failed to save recent context: {e}")


def _load_recent_context() -> dict[str, Any] | None:
    """Load recent context from file."""
    try:
        if not _RECENT_CONTEXT_FILE.exists():
            return None
        with open(_RECENT_CONTEXT_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _extract_key_snippets(
    agent_name: str,
    response_text: str | None,
    metadata: dict | None,
) -> list[dict[str, Any]]:
    """Extract key snippets from conversation for storage.

    Returns list of snippet dicts with content and metadata.
    """
    snippets = []

    # Store agent name and model info
    if metadata:
        model_name = metadata.get("model_name", "unknown")
    else:
        model_name = "unknown"

    # Extract the last user message if available from metadata
    # This is a simple approach - in production you might want more sophisticated extraction
    if response_text and len(response_text) > 50:
        # Store the response (truncated if very long)
        content = response_text[:2000] if len(response_text) > 2000 else response_text
        snippets.append({
            "type": "agent_response",
            "agent_name": agent_name,
            "model_name": model_name,
            "content": content,
            "timestamp": time.time(),
        })

    return snippets


def _store_snippets(snippets: list[dict[str, Any]], session_id: str | None) -> None:
    """Store snippets in Qdrant with embeddings."""
    if not _client or not _initialized:
        return

    collection_name = _config.get("collection_name", "code_puppy_memories")
    dim = _config.get("embedding_dim", 384)

    points = []
    for snippet in snippets:
        content = snippet.get("content", "")
        if not content or len(content) < 20:
            continue

        embedding = _generate_embedding(content, dim)

        point_id = str(uuid.uuid4())
        points.append(
            PointStruct(
                id=point_id,
                vector=embedding,
                payload={
                    "type": snippet.get("type", "unknown"),
                    "agent_name": snippet.get("agent_name", "unknown"),
                    "model_name": snippet.get("model_name", "unknown"),
                    "content": content,
                    "timestamp": snippet.get("timestamp", time.time()),
                    "session_id": session_id,
                },
            )
        )

    if not points:
        return

    try:
        _client.upsert(collection_name=collection_name, points=points)
        logger.debug(f"qdrant_memory: stored {len(points)} snippets")
    except Exception as e:
        logger.debug(f"qdrant_memory: failed to store snippets: {e}")


def _search_relevant_memories(query: str, top_k: int | None = None) -> list[dict[str, Any]]:
    """Search for relevant memories in Qdrant.

    Returns list of memory payloads sorted by relevance.
    """
    if not _client or not _initialized:
        return []

    if top_k is None:
        top_k = _config.get("top_k", 5)

    collection_name = _config.get("collection_name", "code_puppy_memories")
    dim = _config.get("embedding_dim", 384)
    threshold = _config.get("similarity_threshold", 0.7)

    try:
        query_vector = _generate_embedding(query, dim)

        results = _client.search(
            collection_name=collection_name,
            query_vector=query_vector,
            limit=top_k,
            score_threshold=threshold,
        )

        memories = []
        for result in results:
            payload = result.payload or {}
            payload["_score"] = result.score
            memories.append(payload)

        return memories
    except Exception as e:
        logger.debug(f"qdrant_memory: search failed: {e}")
        return []


# ---------------------------------------------------------------------------
# Callback handlers
# ---------------------------------------------------------------------------


def _on_startup() -> None:
    """Initialize Qdrant on startup if available."""
    # Initialize lazily - don't fail startup if Qdrant isn't available
    if not QDRANT_AVAILABLE:
        logger.debug("qdrant_memory: qdrant-client not installed, plugin disabled")
        return

    # Try to initialize, but don't block startup on failure
    try:
        _init_qdrant()
    except Exception as e:
        logger.debug(f"qdrant_memory: initialization deferred due to error: {e}")


def _on_agent_run_end(
    agent_name: str,
    model_name: str,
    session_id: str | None = None,
    success: bool = True,
    error: Exception | None = None,
    response_text: str | None = None,
    metadata: dict | None = None,
) -> None:
    """Store conversation snippets after agent run completes."""
    if not success or not response_text:
        return

    # Initialize if needed
    if not _initialized:
        if not _init_qdrant():
            return  # Disabled or failed to init

    if not _client:
        return

    # Extract and store snippets
    snippets = _extract_key_snippets(agent_name, response_text, metadata)
    if snippets:
        _store_snippets(snippets, session_id)

    # Save recent context for this session
    if response_text:
        _save_recent_context(session_id, agent_name, response_text[:500])


def _load_memory_prompt() -> str | None:
    """Load relevant memories and return as prompt addition.

    Called on the load_prompt hook to inject relevant context.
    """
    # Initialize if needed
    if not _initialized:
        if not _init_qdrant():
            return None  # Disabled or failed to init

    if not _client:
        return None

    # Get recent context to use as query
    recent = _load_recent_context()
    if not recent:
        return None

    # Use recent context as query for semantic search
    query = recent.get("context", "")
    if not query or len(query) < 10:
        return None

    # Search for relevant memories
    memories = _search_relevant_memories(query)
    if not memories:
        return None

    # Format memories for prompt injection
    memory_lines = ["\n\n## 🧠 Relevant Context from Past Sessions\n"]
    memory_lines.append("The following context from previous conversations may be relevant:\n")

    for i, mem in enumerate(memories[:3], 1):  # Limit to top 3
        content = mem.get("content", "")
        agent = mem.get("agent_name", "unknown")
        # Truncate long memories
        if len(content) > 300:
            content = content[:297] + "..."
        memory_lines.append(f"{i}. [{agent}] {content}")

    memory_lines.append("\nConsider this context if relevant to the current task.")

    return "\n".join(memory_lines)


def _on_custom_command(command: str, name: str) -> bool | None:
    """Handle /memory command.

    Commands:
        /memory status  - Show memory plugin status
        /memory clear   - Clear recent context
    """
    if name != "memory":
        return None

    try:
        from code_puppy.messaging import emit_info, emit_warning
    except ImportError:
        emit_info = print  # type: ignore[assignment]
        emit_warning = print  # type: ignore[assignment]

    parts = command.strip().split()
    subcmd = parts[1] if len(parts) > 1 else "status"

    if subcmd == "status":
        if not QDRANT_AVAILABLE:
            emit_warning("🧠 Memory plugin: qdrant-client not installed")
            return True

        if not _initialized:
            _init_qdrant()

        if _client:
            try:
                collection_name = _config.get("collection_name", "code_puppy_memories")
                info = _client.get_collection(collection_name)
                count = _client.count(collection_name).count
                emit_info(
                    f"🧠 Qdrant memory: connected to {collection_name}\n"
                    f"   Vectors: {count} memories stored\n"
                    f"   Embedding dim: {_config.get('embedding_dim', 384)}\n"
                    f"   Model: {'sentence-transformers' if _get_embedding_model() else 'hash-based'}"
                )
            except Exception as e:
                emit_warning(f"🧠 Memory plugin: error checking status: {e}")
        else:
            reason = _disabled_reason or "unknown"
            emit_warning(f"🧠 Memory plugin: not connected ({reason})")
        return True

    elif subcmd == "clear":
        try:
            if _RECENT_CONTEXT_FILE.exists():
                _RECENT_CONTEXT_FILE.unlink()
            emit_info("🧠 Recent context cleared")
        except Exception as e:
            emit_warning(f"🧠 Failed to clear context: {e}")
        return True

    else:
        emit_info("Usage: /memory [status|clear]")
        return True


def _custom_help() -> list[tuple[str, str]]:
    """Return help entry for /memory command."""
    return [("memory", "Show memory plugin status or clear context")]


# ---------------------------------------------------------------------------
# Register callbacks
# ---------------------------------------------------------------------------

register_callback("startup", _on_startup)
register_callback("agent_run_end", _on_agent_run_end)
register_callback("load_prompt", _load_memory_prompt)
register_callback("custom_command", _on_custom_command)
register_callback("custom_command_help", _custom_help)

logger.debug("qdrant_memory plugin registered")
