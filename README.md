# 记忆宫殿 

给 DSH 里的 AI 一套**自己的长期记忆**：本地 SQLite + 关键词检索 + 语义检索，
不需要联网、不需要任何插件、不需要云端。

> 一句话原理：AI 每次会话都是"新醒一次"，靠文件接续。这个包就是那份文件。

---

## 一、5 分钟装好

前提：Windows + 有 Node.js（**>= 22.13**，语义层用的 `node:sqlite` 从 22.5 开始提供）+ Python 3.8+（关键词层，标准库即可）。
如果装的是 DSH 桌面版，它自带的 node 也能用。

```powershell
# 1. 把这个文件夹放到你想放的位置（不要放在只读目录）
# 2. 在文件夹里打开 PowerShell，执行：
powershell -ExecutionPolicy Bypass -File .\setup.ps1
```

脚本会：找 node → `npm install` → 盖两个补丁 → 下模型（约 23MB，走 hf-mirror）→ 自检。

装完试一下：

```powershell
python .\palace.py save --scope user --kind fact --content "他喜欢喝茶，不加糖。"
python .\palace.py search --query 他喜欢喝什么
python .\palace.py stats
```

---

## 二、目录里都是什么

| 文件 | 作用 |
|---|---|
| `palace.py` | 主程序。零第三方依赖，只用 Python 标准库 |
| `palace_embed.mjs` | 语义层。用 transformers.js 跑本地向量模型 |
| `package.json` | 语义层的依赖（transformers + onnxruntime-web） |
| `patches/` | 两个必需补丁，见第四节 |
| `download-model.ps1` | 单独下载模型 |
| `schema.sql` | 数据库结构（palace.py 里也有一份，init 时会自动建） |

跑起来之后会长出：

```
palace.db        你的记忆，全部在这里
node_modules/    语义层依赖
models/          向量模型
```

---

## 三、命令

```powershell
python palace.py init   --src <旧的记忆目录>   # 从别处迁移（可选）
python palace.py save   --scope user --kind fact --content "……" [--importance 0.6] [--no-embed]
python palace.py search --query "……" [--scope user|project] [--kind fact|preference|skill|decision|episode] [--limit 10]
python palace.py list   [--scope] [--kind] [--limit]
python palace.py profile [--scope]      # 常驻画像
python palace.py rooms                  # 各厅条数
python palace.py stats                  # 总数
```

`kind` 五个厅，对应五种记忆：

| kind | 厅名 | 放什么 |
|---|---|---|
| `fact` | 事实厅 | 客观事实（他是谁、机器是什么配置） |
| `preference` | 偏好阁 | 喜好、习惯、忌讳 |
| `skill` | 技法坊 | 做事的正确姿势、踩过的坑 |
| `decision` | 决策堂 | 拍板过的决定和理由 |
| `episode` | 事件廊 | 一起经历过的事 |

有 `node_modules` 和模型时，`save` 会自动把新记忆补成向量；没有就跳过，纯关键词检索照常可用。

---

## 四、为什么有两个补丁（重要）

语义层要在本机跑一个向量模型。正常路径是 `onnxruntime-node`（原生 .dll），但它在
**一部分机器上会直接崩**（进程级 `0xC0000005` / DLL 初始化失败），连版本都换不回来。

所以这里换成 wasm：把 `onnxruntime-node` 换成一个**转发层**，所有推理走
`onnxruntime-web`（浏览器同款的 wasm 实现）。副作用是慢一点（单条 ~70ms），但稳。

| 补丁 | 干什么 |
|---|---|
| `patches/onnxruntime-node` | 把调用转发给 `onnxruntime-web`，强制 `executionProviders: ["wasm"]`、`numThreads=1`、wasm 文件用本地路径 |
| `patches/sharp-stub` | transformers 会顺手 require `sharp`（图像处理），我们只用文本，换空桩避免它去加载原生 dll |

**如果你那边原生 onnxruntime 是好的**，也可以不用这两个补丁：删掉 `node_modules/onnxruntime-node` 和 `node_modules/sharp` 的替换，直接 `npm install` 后试用。崩了就再盖回来。

---

## 五、常见问题

**Q：npm install 报 EPERM / 软链错误**
说明放到了 exFAT 盘（U 盘）。npm 一般没事；如果用 pnpm 会失败，改成：
`pnpm install --config.node-linker=hoisted --config.symlink=false`

**Q：模型下不动**
先试 `-Mirror https://huggingface.co`；国内建议默认的 `hf-mirror.com`。
实在不行，把 `Xenova/bge-small-zh-v1.5` 那 5 个文件手动塞进 `models/Xenova/bge-small-zh-v1.5/`。

**Q：`pip` 装东西很慢/403**
本包不需要 pip，全部是标准库。真要装，用阿里云源：
`-i https://mirrors.aliyun.com/pypi/simple`

**Q：语义检索没生效**
看有没有 `node_modules` 和 `models`。缺一个就会自动降级成关键词检索（不报错）。

**Q：想把数据库/模型放到别处**
用环境变量覆盖：`PALACE_DB`（数据库位置）、`PALACE_MODEL_DIR`（模型目录）、`PALACE_NODE`（node 可执行文件）。

**Q：palace.db 越来越大**
正常，文本很省。几百条记忆也就几 MB。

---

## 六、和 DSH 的关系（设计原则）

**这条最重要：记忆宫殿不是 DSH 的依赖。**

- DSH 不加载它、不 import 它；它坏了、删了、没启动，DSH 照常跑。
- 反过来它依赖 DSH 提供的运行时（Python / Node），放在 DSH 的工作区里。
- 它只是**一堆文件**，AI 想用的时候用命令行读写；不想用就不存在。

---

## 七、致谢与出处

结构上参考了 dsh-engram 的设计（房间/门牌/索引），实现全部重写：无插件、纯本地、只用标准库。
语义层是 transformers.js + bge-small-zh-v1.5（512 维，CLS pooling + L2 normalize）。
