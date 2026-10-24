import { pipeline, env } from "@xenova/transformers";
import { DatabaseSync } from "node:sqlite";

import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const HERE = dirname(fileURLToPath(import.meta.url));
const DB = process.env.PALACE_DB || join(HERE, "palace.db");
const MODEL_DIR =
  (process.env.PALACE_MODEL_DIR || join(HERE, "models")).replace(/\\/g, "/") + "/";

env.localModelPath = MODEL_DIR;
env.allowRemoteModels = false;
env.allowLocalModels = true;

const ROOMS = { fact: "事实厅", preference: "偏好阁", skill: "技法坊", decision: "决策堂", episode: "事件廊" };

let _ex = null;
async function getEx() {
  if (!_ex) _ex = await pipeline("feature-extraction", "Xenova/bge-small-zh-v1.5", { quantized: true });
  return _ex;
}

async function embed(ex, texts, batch = 16) {
  const out = [];
  for (let i = 0; i < texts.length; i += batch) {
    const chunk = texts.slice(i, i + batch);
    const r = await ex(chunk, { pooling: "cls", normalize: true });
    const dim = r.dims[r.dims.length - 1];
    for (let j = 0; j < chunk.length; j++) out.push(Float32Array.from(r.data.slice(j * dim, (j + 1) * dim)));
  }
  return out;
}

function blobToF32(b) {
  if (!b) return null;
  const u8 = b instanceof Uint8Array ? b : new Uint8Array(b);
  return new Float32Array(u8.buffer, u8.byteOffset, Math.floor(u8.byteLength / 4));
}

function f32ToU8(v) {
  return new Uint8Array(v.buffer, v.byteOffset, v.byteLength);
}

async function backfill() {
  const db = new DatabaseSync(DB);
  const rows = db.prepare("SELECT id, content FROM nodes WHERE embedding IS NULL").all();
  if (!rows.length) { console.log("没有缺 embedding 的节点"); db.close(); return; }
  console.log(`embedding ${rows.length} nodes ...`);
  const ex = await getEx();
  const vecs = await embed(ex, rows.map((r) => r.content));
  const upd = db.prepare("UPDATE nodes SET embedding=? WHERE id=?");
  for (let i = 0; i < rows.length; i++) upd.run(f32ToU8(vecs[i]), rows[i].id);
  console.log(`done: ${vecs.length} x ${vecs[0].length}`);
  db.close();
}

async function search(query, limit = 10, scope = null, kind = null) {
  const db = new DatabaseSync(DB);
  const ex = await getEx();
  const qv = (await embed(ex, [query]))[0];
  let sql = "SELECT id, scope, kind, content, importance, status, slot_room, slot_index, embedding FROM nodes WHERE embedding IS NOT NULL";
  const args = [];
  if (scope) { sql += " AND scope=?"; args.push(scope); }
  if (kind) { sql += " AND kind=?"; args.push(kind); }
  const rows = db.prepare(sql).all(...args);
  db.close();
  const scored = [];
  for (const r of rows) {
    const v = blobToF32(r.embedding);
    if (!v || v.length !== qv.length) continue;
    let dot = 0;
    for (let i = 0; i < v.length; i++) dot += qv[i] * v[i];
    scored.push([dot, r]);
  }
  scored.sort((a, b) => b[0] - a[0]);
  if (!scored.length) { console.log("（没有可用的 embedding，先跑 backfill）"); return; }
  for (let i = 0; i < Math.min(limit, scored.length); i++) {
    const [score, r] = scored[i];
    const room = ROOMS[r.kind] || r.kind;
    console.log(`[${i + 1}] ${score.toFixed(3)} ${room}#${r.slot_index} [${r.kind}|${r.scope}|${r.importance.toFixed(2)}|${r.status}]`);
    console.log("    " + r.content.replace(/\n/g, " ").slice(0, 220));
  }
}

async function main() {
  const args = process.argv.slice(2);
  const cmd = args[0];
  const get = (k, d) => { const i = args.indexOf(k); return i >= 0 ? args[i + 1] : d; };
  if (cmd === "backfill") await backfill();
  else if (cmd === "search") await search(get("--query", ""), parseInt(get("--limit", "10")), get("--scope", null), get("--kind", null));
  else if (cmd === "embed") {
    const v = (await embed(await getEx(), [get("--query", "")]))[0];
    let s = 0; for (let i = 0; i < v.length; i++) s += v[i] * v[i];
    console.log(`dim=${v.length} norm=${Math.sqrt(s).toFixed(4)}`);
  } else console.log("用法: backfill | search --query ... | embed --query ...");
}

main().catch((e) => { console.error(e); process.exit(1); });
