#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
本地记忆宫殿（自留地版）—— 按 dsh-engram 的规格重建，离线、无插件依赖。

数据文件：默认脚本同目录下的 palace.db，可用 --db 或环境变量 PALACE_DB 覆盖。
规格（与原 dsh-engram 一致）：
  rooms（kind -> 厅名）:
    fact       -> 事实厅
    preference -> 偏好阁
    skill      -> 技法坊
    decision   -> 决策堂
    episode    -> 事件廊
  node 字段: id, scope(user/project), kind, content, importance(0~1), status,
             slot_room, slot_index, created_at, embedding(可选 BLOB) ...
  profile_blocks: 大厅（Grand Hall）常驻画像，scope=user 那一条每次会话注入。

检索：search 用内容子串 + importance 排序（中文稳妥），semantic 由守护进程后续补。
"""
import argparse, json, os, shutil, sqlite3, subprocess, sys, time, uuid

_HERE = os.path.dirname(os.path.abspath(__file__))
# 优先级：环境变量 PALACE_DB > 脚本同目录 palace.db
DEFAULT_DB = os.environ.get("PALACE_DB", os.path.join(_HERE, "palace.db"))

# Windows 控制台默认 GBK，遇到特殊符号会 UnicodeEncodeError 直接崩，这里兜底成 utf-8。
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOMS = {"fact": "事实厅", "preference": "偏好阁", "skill": "技法坊",
         "decision": "决策堂", "episode": "事件廊"}
KINDS = list(ROOMS.keys())

SCHEMA = """
CREATE TABLE IF NOT EXISTS nodes (
  id TEXT PRIMARY KEY, scope TEXT NOT NULL, kind TEXT NOT NULL, content TEXT NOT NULL,
  importance REAL NOT NULL, confidence REAL NOT NULL, status TEXT NOT NULL,
  created_at INTEGER NOT NULL, last_accessed_at INTEGER NOT NULL, access_count INTEGER NOT NULL,
  source_session_id TEXT, source_round INTEGER, source_seq INTEGER, embedding BLOB, outcome TEXT,
  imagery_json TEXT, slot_room TEXT, slot_index INTEGER, imagery_score REAL,
  next_review_at INTEGER, ease_factor REAL, interval_days REAL, review_reps INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS nodes_fts (node_id TEXT UNIQUE, content TEXT);
CREATE TABLE IF NOT EXISTS entities (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL,
  aliases_json TEXT NOT NULL DEFAULT '[]', created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS facts (
  id TEXT PRIMARY KEY, entity_id TEXT NOT NULL, content TEXT NOT NULL,
  valid_at INTEGER NOT NULL, invalid_at INTEGER, replaced_by TEXT,
  source_node_id TEXT, created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS edges (
  from_id TEXT NOT NULL, to_id TEXT NOT NULL, type TEXT NOT NULL, created_at INTEGER NOT NULL,
  PRIMARY KEY (from_id, to_id, type)
);
CREATE TABLE IF NOT EXISTS node_entities (
  node_id TEXT NOT NULL, entity_id TEXT NOT NULL, PRIMARY KEY (node_id, entity_id)
);
CREATE TABLE IF NOT EXISTS profile_blocks (
  scope TEXT PRIMARY KEY, content TEXT NOT NULL, version INTEGER NOT NULL, updated_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS op_log (
  seq INTEGER PRIMARY KEY AUTOINCREMENT, at INTEGER NOT NULL, op TEXT NOT NULL,
  target_id TEXT NOT NULL, detail TEXT
);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


def connect(db):
    c = sqlite3.connect(db)
    return c


def ensure_schema(db):
    """保证表存在：首次使用（没有 init 过）也能直接 save/search。"""
    c = connect(db)
    c.executescript(SCHEMA)
    c.execute("INSERT OR IGNORE INTO meta(key,value) VALUES('schema_version','13')")
    c.commit()
    c.close()


def now():
    return int(time.time())


def _init_db(db):
    c = connect(db)
    c.executescript(SCHEMA)
    c.execute("INSERT OR IGNORE INTO meta(key,value) VALUES('schema_version','13')")
    c.commit()
    return c


# ---- init / 迁移 ----
def cmd_init(src, db):
    c = _init_db(db)
    now_s = now()
    total = 0
    for fn in sorted(os.listdir(src)):
        if not fn.endswith(".db"):
            continue
        sp = os.path.join(src, fn)
        s = sqlite3.connect(sp)
        s.row_factory = sqlite3.Row
        # nodes
        try:
            for r in s.execute("SELECT * FROM nodes"):
                c.execute(
                    "INSERT OR IGNORE INTO nodes VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    tuple(r),
                )
                c.execute(
                    "INSERT OR IGNORE INTO nodes_fts(node_id, content) VALUES(?,?)",
                    (r["id"], r["content"]),
                )
                total += 1
        except sqlite3.OperationalError as e:
            print("nodes skip", fn, e)
        # entities
        try:
            for r in s.execute("SELECT * FROM entities"):
                c.execute("INSERT OR IGNORE INTO entities VALUES (?,?,?,?,?,?)", tuple(r))
        except sqlite3.OperationalError:
            pass
        # facts
        try:
            for r in s.execute("SELECT * FROM facts"):
                c.execute("INSERT OR IGNORE INTO facts VALUES (?,?,?,?,?,?,?,?,?)", tuple(r))
        except sqlite3.OperationalError:
            pass
        # edges / node_entities
        for tbl in ("edges", "node_entities"):
            try:
                cols = [x[1] for x in s.execute(f"PRAGMA table_info({tbl})")]
                for r in s.execute(f"SELECT * FROM {tbl}"):
                    place = ",".join("?" * len(cols))
                    c.execute(f"INSERT OR IGNORE INTO {tbl} VALUES ({place})", tuple(r))
            except sqlite3.OperationalError:
                pass
        # profile_blocks
        try:
            for r in s.execute("SELECT scope, content, version FROM profile_blocks"):
                c.execute(
                    "INSERT OR IGNORE INTO profile_blocks VALUES (?,?,?,?)",
                    (r[0], r[1], r[2], now_s),
                )
        except sqlite3.OperationalError:
            pass
        # op_log (renumber)
        try:
            for r in s.execute("SELECT at, op, target_id, detail FROM op_log"):
                c.execute(
                    "INSERT INTO op_log(at, op, target_id, detail) VALUES(?,?,?,?)",
                    tuple(r),
                )
        except sqlite3.OperationalError:
            pass
        s.close()
    c.commit()
    c.close()
    print(f"init done: {total} nodes migrated into {db}")


# ---- save ----
def cmd_save(scope, kind, content, importance, db, embed=True):
    if kind not in KINDS:
        print("kind 必须是:", ", ".join(KINDS), file=sys.stderr)
        sys.exit(2)
    c = connect(db)
    nid = str(uuid.uuid4())
    t = now()
    room = kind
    # 下一个 slot_index：该 room 内现有最大 +1
    cur = c.execute("SELECT COALESCE(MAX(slot_index),0) FROM nodes WHERE slot_room=?", (room,))
    slot = cur.fetchone()[0] + 1
    c.execute(
        "INSERT INTO nodes(id,scope,kind,content,importance,confidence,status,created_at,"
        "last_accessed_at,access_count,slot_room,slot_index) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
        (nid, scope, kind, content, importance, 0.9, "active", t, t, 0, room, slot),
    )
    c.execute("INSERT OR REPLACE INTO nodes_fts(node_id, content) VALUES(?,?)", (nid, content))
    c.execute("INSERT INTO op_log(at,op,target_id,detail) VALUES(?,?,?,?)",
              (t, "save", nid, kind))
    c.commit()
    c.close()
    print(f"已保存记忆 {nid}（kind={kind}, importance={importance}, {ROOMS[kind]}#{slot}）")
    if embed:
        _auto_embed()


def _auto_embed():
    """保存后增量补 embedding（best-effort，失败不影响核心）。"""
    node = os.environ.get("PALACE_NODE") or shutil.which("node")
    script = os.path.join(_HERE, "palace_embed.mjs")
    if not node or not os.path.exists(node) or not os.path.exists(script):
        print("  （语义层不可用，跳过 embedding）")
        return
    try:
        r = subprocess.run(
            [node, script, "backfill"],
            cwd=_HERE,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=180,
        )
        if r.returncode != 0:
            print("  （embedding 未完成，可稍后手动 backfill）")
    except Exception as e:
        print(f"  （embedding 跳过：{e}）")


# ---- search ----
def cmd_search(query, scope, kind, limit, db):
    c = connect(db)
    q = f"%{query}%"
    sql = "SELECT id, scope, kind, content, importance, status, slot_room, slot_index FROM nodes WHERE content LIKE ?"
    args = [q]
    if scope:
        sql += " AND scope=?"
        args.append(scope)
    if kind:
        sql += " AND kind=?"
        args.append(kind)
    sql += " ORDER BY importance DESC, created_at DESC LIMIT ?"
    args.append(limit)
    rows = c.execute(sql, args).fetchall()
    c.close()
    if not rows:
        print("（无结果）")
        return
    for i, (nid, sc, k, content, imp, status, room, slot) in enumerate(rows, 1):
        rm = ROOMS.get(k, k)
        print(f"[{i}] {rm}#{slot} [{k}|{sc}|{imp:.2f}|{status}]")
        print("    " + content.replace("\n", " "))


# ---- list ----
def cmd_list(scope, kind, limit, db):
    c = connect(db)
    sql = ("SELECT id, scope, kind, content, importance, status, slot_room, slot_index "
           "FROM nodes WHERE 1=1")
    args = []
    if scope:
        sql += " AND scope=?"
        args.append(scope)
    if kind:
        sql += " AND kind=?"
        args.append(kind)
    sql += " ORDER BY scope, kind, slot_index LIMIT ?"
    args.append(limit)
    rows = c.execute(sql, args).fetchall()
    c.close()
    for nid, sc, k, content, imp, status, room, slot in rows:
        rm = ROOMS.get(k, k)
        print(f"- {rm}#{slot} [{k}|{sc}|{imp:.2f}|{status}] {content}")


# ---- profile ----
def cmd_profile(scope, db):
    c = connect(db)
    if scope:
        r = c.execute("SELECT content FROM profile_blocks WHERE scope=?", (scope,)).fetchone()
    else:
        r = c.execute("SELECT content FROM profile_blocks ORDER BY scope LIMIT 1").fetchone()
    c.close()
    print(r[0] if r else "（无画像）")


# ---- rooms ----
def cmd_rooms(db):
    c = connect(db)
    rows = c.execute(
        "SELECT kind, slot_room, COUNT(*) FROM nodes GROUP BY kind, slot_room ORDER BY kind, slot_room"
    ).fetchall()
    c.close()
    for k, room, n in rows:
        print(f"{ROOMS.get(k, k)} ({room}) : {n}")


def cmd_stats(db):
    c = connect(db)
    n = c.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
    e = c.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
    f = c.execute("SELECT COUNT(*) FROM facts").fetchone()[0]
    p = c.execute("SELECT COUNT(*) FROM profile_blocks").fetchone()[0]
    c.close()
    print(f"nodes={n} entities={e} facts={f} profile_blocks={p}")


def main():
    ap = argparse.ArgumentParser(description="本地记忆宫殿")
    ap.add_argument("--db", default=DEFAULT_DB)
    sub = ap.add_subparsers(dest="cmd", required=True)

    si = sub.add_parser("init", help="从原 engram 目录迁移")
    si.add_argument("--src", required=True)

    sv = sub.add_parser("save")
    sv.add_argument("--scope", required=True, choices=["user", "project"])
    sv.add_argument("--kind", required=True, choices=KINDS)
    sv.add_argument("--content", required=True)
    sv.add_argument("--importance", type=float, default=0.6)
    sv.add_argument("--no-embed", action="store_true")

    se = sub.add_parser("search")
    se.add_argument("--query", required=True)
    se.add_argument("--scope")
    se.add_argument("--kind", choices=KINDS)
    se.add_argument("--limit", type=int, default=10)

    li = sub.add_parser("list")
    li.add_argument("--scope")
    li.add_argument("--kind", choices=KINDS)
    li.add_argument("--limit", type=int, default=100)

    pr = sub.add_parser("profile")
    pr.add_argument("--scope")

    sub.add_parser("rooms")
    sub.add_parser("stats")

    a = ap.parse_args()
    # 除 init 外，先确保表结构存在（init 内部会自己建表并迁移）
    if a.cmd != "init":
        ensure_schema(a.db)
    if a.cmd == "init":
        cmd_init(a.src, a.db)
    elif a.cmd == "save":
        cmd_save(a.scope, a.kind, a.content, a.importance, a.db, embed=not a.no_embed)
    elif a.cmd == "search":
        cmd_search(a.query, a.scope, a.kind, a.limit, a.db)
    elif a.cmd == "list":
        cmd_list(a.scope, a.kind, a.limit, a.db)
    elif a.cmd == "profile":
        cmd_profile(a.scope, a.db)
    elif a.cmd == "rooms":
        cmd_rooms(a.db)
    elif a.cmd == "stats":
        cmd_stats(a.db)


if __name__ == "__main__":
    main()
