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

检索：search 用内容子串 + importance 排序（中文稳妥）；语义检索见 palace_embed.mjs
      （save 后自动补向量，`node palace_embed.mjs search --query ...` 按相似度搜）。
"""
import argparse, datetime, json, os, shutil, sqlite3, subprocess, sys, time, uuid

DEFAULT_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "palace.db")

# Windows 控制台默认 GBK，遇到特殊符号会 UnicodeEncodeError 直接崩，这里兜底成 utf-8。
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# 旧路径兜底：本机早期把心跳日志放在别处时，用环境变量指过去即可（默认不启用）
LEGACY_HEARTBEAT_LOG = os.environ.get("PALACE_HEARTBEAT_LEGACY", "")


def heartbeat_log_default():
    """心跳日志在哪？按顺序找：

    1. 心跳程序公布的「日志路径.txt」——它知道 exe 放哪、配置怎么写的，以它为准
    2. 用户目录下的默认位置——分享给别人用时的默认落点
    3. 旧的本机路径——兼容早期装在这台机器上的那些数据
    """
    home = os.environ.get("USERPROFILE") or os.path.expanduser("~")
    folder = os.path.join(home, "心跳感知")
    try:
        with open(os.path.join(folder, "日志路径.txt"), encoding="utf-8") as f:
            p = f.read().strip()
        if p:
            return p
    except Exception:
        pass
    p = os.path.join(folder, "heartbeat.jsonl")
    if os.path.exists(p):
        return p
    if LEGACY_HEARTBEAT_LOG and os.path.exists(LEGACY_HEARTBEAT_LOG):
        return LEGACY_HEARTBEAT_LOG
    return p
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
CREATE TABLE IF NOT EXISTS nodes_revisions (
  node_id TEXT NOT NULL, content TEXT NOT NULL, kind TEXT NOT NULL,
  importance REAL NOT NULL, superseded_at INTEGER NOT NULL
);
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
    # 幂等建表：新库直接可用，老库不受影响（2026-10-23 分享包修正）
    c.executescript(SCHEMA)
    return c


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
    node = os.environ.get("PALACE_NODE", "").strip()
    if not node or not os.path.exists(node):
        for _c in (
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "node.exe"),
            os.path.join(os.path.expanduser("~"),
                         ".dsh", "dsh-runtimes", "dsh-primary-runtime",
                         "dependencies", "node", "bin", "node.exe"),
            r"C:\Program Files\nodejs\node.exe",
        ):
            if os.path.exists(_c):
                node = _c
                break
    node = node or (shutil.which("node") or "node")
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "palace_embed.mjs")
    if not os.path.exists(node) or not os.path.exists(script):
        print("  （语义层不可用，跳过 embedding）")
        return
    try:
        r = subprocess.run(
            [node, script, "backfill"],
            cwd=os.path.dirname(script),
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


# ---- presence / 心跳日志 ----
def _parse_ts(s):
    try:
        return datetime.datetime.fromisoformat(str(s))
    except Exception:
        return None


def _fmt_dur(sec):
    sec = max(0, int(sec))
    if sec < 60:
        return f"{sec} 秒"
    m, s = divmod(sec, 60)
    if m < 60:
        return f"{m} 分 {s} 秒"
    h, m = divmod(m, 60)
    if h < 24:
        return f"{h} 小时 {m} 分"
    d, h = divmod(h, 24)
    return f"{d} 天 {h} 小时"


def _ago(now, ts):
    if ts is None:
        return "?"
    try:
        return _fmt_dur((now - ts).total_seconds())
    except Exception:
        return "?"


def _read_tail(path, max_bytes=262144):
    """只读文件尾部。

    日志 append-only、只增不减，全量读迟早会卡。默认读最后 256 KB，
    几千条，够用了。
    """
    try:
        size = os.path.getsize(path)
    except OSError:
        return []
    try:
        with open(path, "rb") as f:
            f.seek(max(0, size - max_bytes))
            chunk = f.read().decode("utf-8", errors="replace")
    except OSError:
        return []
    lines = [l for l in chunk.splitlines() if l.strip()]
    if size > max_bytes and lines:
        lines = lines[1:]          # 第一行多半是半截，丢掉
    out = []
    for l in lines:
        try:
            out.append(json.loads(l))
        except Exception:
            continue
    return out


def _guess_interval(beats):
    """从最近几条心跳反推采样间隔。

    读取端看不到那边的配置文件，只能从数据本身看，取中位数抗干扰。
    """
    ts = []
    for b in beats[-30:]:
        t = _parse_ts(b.get("ts"))
        if t:
            ts.append(t)
    gaps = []
    for i in range(len(ts) - 1):
        g = (ts[i + 1] - ts[i]).total_seconds()
        if 0 < g < 3600:
            gaps.append(g)
    if not gaps:
        return 60.0
    gaps.sort()
    return gaps[len(gaps) // 2]


GAP_REASON_CN = {
    "sleep": "机器睡了",
    "machine_off": "关机重启过",
    "program_not_running": "机器开着但程序没跑",
    "machine_on": "机器开着",
    "unknown": "查不出来",
}


def cmd_presence(log, tail):
    if not os.path.exists(log):
        print(f"（还没有心跳日志：{log}）")
        return
    recs = _read_tail(log)
    if not recs:
        print("（心跳日志为空）")
        return
    summaries = [r for r in recs if r.get("type") == "daily_summary"]
    explains = [r for r in recs if r.get("type") == "gap_explain"]
    beats = [r for r in recs if r.get("type") not in
             ("daily_summary", "gap_explain")]
    if tail and tail > 0:
        beats = beats[-tail:]
    now = datetime.datetime.now().astimezone()

    print(f"心跳日志：{log}")
    if not beats:
        print("（尚无心跳采样）")
    else:
        last = beats[-1]
        last_ts = _parse_ts(last.get("ts"))
        idle = last.get("idle")
        present = last.get("present")
        state = last.get("state")
        if state is None:
            state = "在" if present else ("不在" if present is not None else "未知")
        else:
            state = {"away": "不在", "back": "在"}.get(state, state)
        line = f"当前状态：{state}"
        if idle is not None:
            line += f"（空闲 {idle}s）"
        print(line)
        print(f"最近采样：{last.get('ts')}（{_ago(now, last_ts)} 前）")

        # 新鲜度：日志停更了就不能照着旧数据说「现在在」——
        # 那不是不知道，是确信地说错，比空白更糟
        if last_ts is not None:
            age = (now - last_ts).total_seconds()
            limit = max(_guess_interval(beats) * 3, 120)
            if age > limit:
                print(f"⚠ 心跳已中断 {_ago(now, last_ts)}"
                      f"（超过 {_fmt_dur(limit)} 没有新记录）")
                print(f"  最后可信状态：{state}。之后发生了什么，日志里没有。")

        last_away = None
        last_back = None
        for r in beats:
            st = r.get("state")
            ts = _parse_ts(r.get("ts"))
            if st == "away":
                last_away = ts
            elif st == "back":
                last_back = ts
        if last_back:
            print(f"上次回来：{last_back.isoformat()}（{_ago(now, last_back)} 前）")
        if last_away:
            print(f"上次离开：{last_away.isoformat()}")
            if last_back is None or last_away > last_back:
                print(f"已经离开：{_ago(now, last_away)}")
        else:
            print("（这段时间还没有离开记录）")

    if summaries:
        s = summaries[-1]
        d = s.get("date")
        # 同一天会有多条，最后一条最完整；但也要防止把昨天的当成今天的
        tag = "" if d == now.date().isoformat() else f"（这是 {d} 的，今天还没有）"
        print(f"汇总：{d}{tag}")
        print(f"  在 {s.get('present_hours')}h ｜ 不在 {s.get('away_hours')}h ｜ "
              f"空白 {s.get('unknown_hours')}h ｜ "
              f"最长离开 {s.get('longest_away_hours')}h")
        if s.get("partial"):
            print("  ⚠ 空白多于已知时长，这份汇总不代表整天")

    if explains:
        g = explains[-1]
        why = GAP_REASON_CN.get(g.get("reason"), g.get("reason"))
        print(f"上一段空白：{_fmt_dur(g.get('gap_seconds') or 0)}｜{why}")


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

    ps = sub.add_parser("presence", help="读心跳日志，看主人在不在/离开多久")
    ps.add_argument("--log", default=heartbeat_log_default())
    ps.add_argument("--tail", type=int, default=0)

    a = ap.parse_args()
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
    elif a.cmd == "presence":
        cmd_presence(a.log, a.tail)


if __name__ == "__main__":
    main()
