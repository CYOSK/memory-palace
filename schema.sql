CREATE TABLE IF NOT EXISTS nodes (
  id TEXT PRIMARY KEY, scope TEXT NOT NULL, kind TEXT NOT NULL, content TEXT NOT NULL,
  importance REAL NOT NULL, confidence REAL NOT NULL, status TEXT NOT NULL,
  created_at INTEGER NOT NULL, last_accessed_at INTEGER NOT NULL, access_count INTEGER NOT NULL,
  source_session_id TEXT, source_round INTEGER, source_seq INTEGER, embedding BLOB, outcome TEXT,
  imagery_json TEXT, slot_room TEXT, slot_index INTEGER, imagery_score REAL,
  next_review_at INTEGER, ease_factor REAL, interval_days REAL, review_reps INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS nodes_fts (node_id TEXT UNIQUE, content TEXT);
CREATE TABLE IF NOT EXISTS nodes_revisions (
  node_id TEXT NOT NULL, content TEXT NOT NULL, kind TEXT NOT NULL,
  importance REAL NOT NULL, superseded_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS entities (id TEXT PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL,
  aliases_json TEXT NOT NULL DEFAULT '[]', created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS facts (id TEXT PRIMARY KEY, entity_id TEXT NOT NULL, content TEXT NOT NULL,
  valid_at INTEGER NOT NULL, invalid_at INTEGER, replaced_by TEXT, source_node_id TEXT,
  created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS edges (from_id TEXT NOT NULL, to_id TEXT NOT NULL, type TEXT NOT NULL,
  created_at INTEGER NOT NULL, PRIMARY KEY (from_id, to_id, type));
CREATE TABLE IF NOT EXISTS node_entities (node_id TEXT NOT NULL, entity_id TEXT NOT NULL, PRIMARY KEY (node_id, entity_id));
CREATE TABLE IF NOT EXISTS profile_blocks (scope TEXT PRIMARY KEY, content TEXT NOT NULL,
  version INTEGER NOT NULL, updated_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS op_log (seq INTEGER PRIMARY KEY AUTOINCREMENT, at INTEGER NOT NULL,
  op TEXT NOT NULL, target_id TEXT NOT NULL, detail TEXT);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
