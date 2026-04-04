"""DuckDB schema definitions for analytics tracking.

Defines tables for storing turns, tool calls, and file accesses.
"""

# SQL to create tables
CREATE_TABLES_SQL = """
-- Sequences for auto-incrementing IDs
CREATE SEQUENCE IF NOT EXISTS seq_turn_id START 1;
CREATE SEQUENCE IF NOT EXISTS seq_call_id START 1;
CREATE SEQUENCE IF NOT EXISTS seq_access_id START 1;

-- Turns table: one row per agent run
CREATE TABLE IF NOT EXISTS turns (
    turn_id INTEGER PRIMARY KEY DEFAULT nextval('seq_turn_id'),
    session_id VARCHAR,
    agent_name VARCHAR NOT NULL,
    model_name VARCHAR NOT NULL,
    started_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    ended_at TIMESTAMP,
    success BOOLEAN,
    input_tokens INTEGER DEFAULT 0,
    output_tokens INTEGER DEFAULT 0,
    duration_ms INTEGER,
    error TEXT
);

-- Tool calls table: one row per tool invocation
CREATE TABLE IF NOT EXISTS tool_calls (
    call_id INTEGER PRIMARY KEY DEFAULT nextval('seq_call_id'),
    turn_id INTEGER REFERENCES turns(turn_id),
    tool_name VARCHAR NOT NULL,
    started_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    ended_at TIMESTAMP,
    duration_ms INTEGER,
    success BOOLEAN,
    error TEXT
);

-- File accesses table: one row per file operation
CREATE TABLE IF NOT EXISTS file_accesses (
    access_id INTEGER PRIMARY KEY DEFAULT nextval('seq_access_id'),
    turn_id INTEGER REFERENCES turns(turn_id),
    tool_name VARCHAR NOT NULL,
    file_path VARCHAR NOT NULL,
    operation VARCHAR NOT NULL,  -- read, write, delete, etc.
    accessed_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_turns_session ON turns(session_id);
CREATE INDEX IF NOT EXISTS idx_turns_agent ON turns(agent_name);
CREATE INDEX IF NOT EXISTS idx_turns_model ON turns(model_name);
CREATE INDEX IF NOT EXISTS idx_turns_started ON turns(started_at);
CREATE INDEX IF NOT EXISTS idx_tool_calls_turn ON tool_calls(turn_id);
CREATE INDEX IF NOT EXISTS idx_tool_calls_name ON tool_calls(tool_name);
CREATE INDEX IF NOT EXISTS idx_file_accesses_turn ON file_accesses(turn_id);
CREATE INDEX IF NOT EXISTS idx_file_accesses_path ON file_accesses(file_path);
"""
