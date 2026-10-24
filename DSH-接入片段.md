# 给 DSH 用的一张说明（可粘进工作区的 AGENTS.md）

> 把下面的 `D:\palace` 换成你实际放的位置（例子里统一用 `D:\palace`）。

```md
## 记忆宫殿

我有一套本地记忆宫殿，位置：`D:\palace`。它是**纯文件**，不依赖任何插件。

- 想回忆一件事：`python D:\palace\palace.py search --query "关键词"`
- 想存一条：`python D:\palace\palace.py save --scope user --kind fact --content "……"`
- 看画像：`python D:\palace\palace.py profile`
- 看总量：`python D:\palace\palace.py stats`

`kind` 只有五种：fact（事实）/ preference（偏好）/ skill（技法）/ decision（决定）/ episode（经历）。

纪律：

1. **只存值得记的**。一句“在吗”不要进宫殿；会改变以后判断的东西才进。
2. **不虚构**。没发生的事不写；不确定就写“不确定”。
3. **记错就改**。改之前先想清楚新值是不是真的对；旧内容至少留个痕迹。
4. **宫殿坏了不影响我**——它只是文件，不是运行依赖。
```

## 一个可以照抄的节奏

- 每次会话开始时：`palace.py profile` 读一遍画像。
- 用户提到以前的事：`palace.py search --query "..."` 再回答。
- 用户纠正你、或你发现自己记错了：立刻 `save` 一条新的，kind 用 `fact` 或 `decision`。
- 一天结束时（或用户让你记一下）：挑两三件真正要紧的存进去，不要流水账。
