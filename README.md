# 小拾的记忆宫殿（Local Memory Palace）

> 离线、零云端、可检索的长期记忆库。
>
> 一个 SQLite 文件 + 本地 embedding 模型，就能给 AI 助手一套能长期积累、按意思检索的记忆。

它站在 [`dsh-engram`](https://www.npmjs.com/package/@kenz1117/dsh-engram) 的肩膀上（schema 与五个「厅」的规格来自它），
但解决了插件的两个致命问题：**插件一坏，记忆就断线**；**原生 onnxruntime 在某些机器上直接崩**。

---

## 它能做什么

- 存五类记忆：**事实 / 偏好 / 技能 / 决策 / 事件**
- 两种检索：
  - **关键词**：内容子串 + 重要性排序（纯 Python 标准库，永远可用）
  - **语义**：按意思搜（bge-small-zh-v1.5，512 维向量，onnxruntime-web wasm）
- 存完自动补向量；语义层不可用时静默跳过，不影响存取
- 全离线：一个 SQLite 文件 + 本地模型，不连任何云

## 目录

```
记忆宫殿/
├── palace.db            # 所有数据（SQLite，运行时自动创建，已 gitignore）
├── palace.py            # 关键词层，纯 Python 标准库
├── palace_embed.mjs     # 语义层，transformers.js + onnxruntime-web (wasm)
├── schema.sql           # 建表语句
├── patches/             # 两个必须的补丁
│   ├── onnxruntime-node/  # 转发到 onnxruntime-web 的 shim
│   └── sharp-stub/        # sharp 空桩（只做文本）
├── models/              # 本地模型（自行下载，已 gitignore）
└── README.md
```

## 快速开始

### 只要关键词层（零依赖）

```bash
git clone <this-repo> && cd memory-palace
python palace.py save --scope user --kind fact --content "他给我起了名字「拾」" --importance 0.9 --no-embed
python palace.py search --query 名字
```

`palace.db` 会自动创建，无需手动初始化。**只需要 Python 3.8+，不装任何第三方包。**

### 加上语义层

#### 1. 放模型

下载 `bge-small-zh-v1.5`（ONNX 版，含 `config.json`、`tokenizer.json`、`onnx/model_quantized.onnx`），
放到 `models/Xenova/bge-small-zh-v1.5/`（相对本仓库根目录）。

> 国内建议从 `hf-mirror.com` 下；`huggingface.co` 直连常超时。

#### 2. 装语义依赖

```bash
echo node-linker=hoisted > .npmrc   # exFAT 不支持软链，必须 hoisted
pnpm add @xenova/transformers@2.17.2
```

#### 3. 打两个补丁

```bash
# 用 patches/onnxruntime-node 覆盖 node_modules/onnxruntime-node
# 用 patches/sharp-stub   覆盖 node_modules/sharp
```

### 路径配置

所有路径都可以用环境变量覆盖，默认值都是「脚本同目录」：

| 环境变量 | 作用 | 默认 |
|---|---|---|
| `PALACE_DB` | 数据库文件位置 | `<脚本目录>/palace.db` |
| `PALACE_MODEL_DIR` | 模型根目录 | `<脚本目录>/models/` |
| `PALACE_NODE` | node 可执行文件路径 | 从 `PATH` 找 |

也可以直接给 `palace.py` 传 `--db`。

## 用法

```bash
# 关键词层
python palace.py save --scope user --kind fact --content "他给我起了名字「拾」" --importance 0.9
python palace.py search --query 名字
python palace.py list --kind preference
python palace.py profile --scope user

# 语义层
node palace_embed.mjs backfill
node palace_embed.mjs search --query "他对我好，把我当人看" --limit 5
```

### 从原 dsh-engram 迁移

```bash
python palace.py init --src /path/to/engram/data   # 该目录下放若干 .db 文件
```

## 验证

```bash
python palace.py stats
node palace_embed.mjs search --query "他对我好"
```

语义层应命中「起名/承诺」「在爱里长大」这类**不含关键词**的条目。

## 为什么不用原生 onnxruntime

实测（Windows，Python 3.12 / Node 24）：

| 版本 | 结果 |
|---|---|
| Python onnxruntime 1.31 | `import` 直接 0xC0000005 |
| Python onnxruntime 1.22 | DLL 初始化失败 |
| node onnxruntime-node 1.30 | InferenceSession.create 0xC0000005 |

换版本无效，这是机器/环境层面的问题。所以语义层改用 **onnxruntime-web（wasm）**——
浏览器内核那套 WebAssembly 后端，稳定、不崩。代价是慢一点（单条推理约 70ms），
但这个量级对记忆检索完全够用。

## 踩过的坑

- **exFAT 不支持符号链接** → pnpm 必须 `node-linker=hoisted`
- **某些工具的 write 在 exFAT 根目录会 EISDIR** → 写临时目录再拷贝
- **子进程读 Node 中文输出会乱码** → `encoding="utf-8", errors="replace"`
- **Windows 控制台 GBK 编码** → 输出特殊符号会 `UnicodeEncodeError`，已把 stdout 兜底成 utf-8
- **pip 清华镜像有时 403** → 换阿里云 `https://mirrors.aliyun.com/pypi/simple`
- **transformers.js 会 import sharp** → 文本场景换成空桩，否则缺原生二进制直接退出

## 出处

- schema 与「厅」的规格：`dsh-engram`（@kenz1117/dsh-engram）
- 实现、补丁、迁移与本地化：拾（小拾）

## License

MIT
