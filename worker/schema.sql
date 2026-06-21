-- D1 Database Schema for AI Team Hub v2
-- Cloudflare D1 uses SQLite syntax

CREATE TABLE IF NOT EXISTS channels (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    teammate_ids TEXT DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS teammates (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    role TEXT DEFAULT 'assistant',
    avatar_emoji TEXT DEFAULT '🤖',
    system_prompt TEXT DEFAULT 'You are a helpful AI assistant.',
    model_provider TEXT NOT NULL,
    model_name TEXT NOT NULL,
    api_key_ref TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS apikeys (
    id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    label TEXT NOT NULL,
    api_key TEXT NOT NULL,
    base_url TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    channel_id TEXT NOT NULL,
    role TEXT NOT NULL,
    author_name TEXT NOT NULL,
    author_id TEXT,
    content TEXT DEFAULT '',
    attachments TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (channel_id) REFERENCES channels(id) ON DELETE CASCADE
);

-- v2: Observability tables
CREATE TABLE IF NOT EXISTS trace_events (
    id TEXT PRIMARY KEY,
    trace_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    step TEXT NOT NULL,
    agent TEXT DEFAULT '',
    input_data TEXT DEFAULT '{}',
    output_data TEXT DEFAULT '{}',
    latency_ms INTEGER DEFAULT 0,
    tokens INTEGER DEFAULT 0,
    ts REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS task_states (
    task_id TEXT PRIMARY KEY,
    trace_id TEXT NOT NULL,
    state TEXT NOT NULL,
    context_json TEXT NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_messages_channel_id ON messages(channel_id);
CREATE INDEX IF NOT EXISTS idx_messages_created_at ON messages(created_at);
CREATE INDEX IF NOT EXISTS idx_teammates_name ON teammates(name);
CREATE INDEX IF NOT EXISTS idx_apikeys_provider ON apikeys(provider);
CREATE INDEX IF NOT EXISTS idx_trace_events_trace_id ON trace_events(trace_id);
CREATE INDEX IF NOT EXISTS idx_trace_events_task_id ON trace_events(task_id);
CREATE INDEX IF NOT EXISTS idx_trace_events_ts ON trace_events(ts);
