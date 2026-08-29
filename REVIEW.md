# DESIGN.md · v0.2 自我 Review

> 本文件记录设计文档 v0.2 走查时发现的问题与决定。修完的项 → 折进 DESIGN.md v0.3。
> Review 时间：2026-08-29

---

## 一、结构性问题（必修）

### R1. Note 文件组织方式模糊
v0.2 §4 示例给的是 `tickers/600519.md`（看起来"一支票一个文件，内容追加"），
但 §6.1 又说每条 note 有独立 `id`（`note_20260829_142011`）。
→ 二者冲突。
**决定**：一条笔记一个文件，扁平存放：`notes/YYYY/MM/<id>-<slug>.md`。
不再有 `tickers/xxx.md` / `themes/xxx.md` 这种"聚合文件"，聚合视图由 `ripple note link 600519` 查询 frontmatter 生成。这样：
- append 不会破坏 frontmatter
- 一条笔记的"原子性"清晰
- 迁移、删除、去重都简单

### R2. Note ID 精度只到秒，可能冲突
`note_20260829_142011` 秒粒度，一次连着写两条会撞。
**决定**：ID 用 `note_YYYYMMDD_HHMMSS_<6位随机>`。
仍然人类可读，但唯一性由后缀保障。

### R3. `note_index` 表缺 `content_hash`
Reindex 时无法判断哪些 md 变了。
**决定**：`note_index` 加 `content_hash`（sha256 前 16 位）、`file_mtime`。
reindex 时 mtime 变了才重算 embedding，减少启动/reindex 成本。

### R4. Provider ping 语义没定义
CLI 有 `providers ping`，但 Protocol 里没有 `ping()`。
**决定**：在 `BaseProvider`（各 capability 的抽象基类）上加统一 `def health(self) -> HealthStatus`，
默认实现调用一次最便宜的方法（如 meta.profile("600519")），子类可覆盖。

### R5. Provider fallback 与 capability 绑定不清
"fallback" 在 §5 描述为"主源失败降级到下一个"，但如果下一个 provider 没有实现这个 capability 呢？
**决定**：`ProviderRegistry` 按 `(capability, provider)` 注册；fallback 只在**同一 capability 的注册链**里走。
配置文件里就是按 capability 列 provider 名，天然吻合。

### R6. 向量粒度未定义 chunk 策略
§10 说"一条 note 一个向量"，但 bge-small-zh 输入上限 512 token；长笔记会被截断。
**决定**：v1 采取"先整篇 embed；超过 400 token 就按段落（`\n\n` 分隔）切 chunk，取每 chunk 一个向量，chunk_id = `<note_id>#<i>`。检索时若同一 note 多 chunk 命中，只保留最高分那一条"。
避免过度设计（不做 sliding window），但保证不静默截断。

### R7. A 股代码前缀 / 交易所归属未处理
`600519` (SH) / `000001` (SZ) / `300xxx` (SZ 创业板) / `688xxx` (SH 科创板) / `8xxxxx` (北交所)
akshare 的很多函数需要带前缀（如 `sh600519`）。业务层不能自己拼。
**决定**：新增 `ripple/core/symbol.py`：`Symbol.parse("600519") -> Symbol(code="600519", exchange="SH", board="MAIN")`。
所有 Provider 接口对外接受纯 6 位 `code`，内部按需转成厂商格式；未识别的 code 直接报错。

### R8. DataFrame 无 schema 约束
`daily_kline` 返回 `DataFrame` 但没规定列名/类型。多个 provider 出来会各说各话。
**决定**：定义 `KLINE_COLUMNS = ["date", "open", "high", "low", "close", "volume", "amount", "turnover_pct"]`，
Provider 出来的 DataFrame 必须包含这些列（缺失填 NaN），列名一致，index 是 RangeIndex。
在 §5.2 之后追加"返回结构规范"小节。

---

## 二、一致性 / 用词修补（次要）

### R9. 目录混淆：代码仓叫 `ripple/`，包也叫 `ripple/`
标准 Python 布局，OK；但文档要说清楚"代码仓的 `ripple/` 目录 = 顶层包"。
**决定**：§4 加一行注释；不改结构。

### R10. `~/.ripple/` 路径硬编码
写死不利于测试和多环境。
**决定**：数据目录用 `platformdirs.user_data_dir("ripple")`，可通过 `RIPPLE_HOME` 环境变量覆盖。
默认在 Linux 就是 `~/.local/share/ripple/`；示例文档仍写 `~/.ripple/` 便于阅读，但代码使用 `platformdirs`。
Actually — reconsider: the user asked for it to be `git`-able and `~/.ripple/` is more intuitive to grep. **改决定：默认就用 `~/.ripple/`，`RIPPLE_HOME` 覆盖**。platformdirs 只用于 config 的 fallback。

### R11. 配置文件位置未指明
**决定**：`~/.ripple/config.yaml`，首次运行 CLI 自动生成默认值。

### R12. Python 版本 / 依赖清单
DESIGN.md 完全没提。
**决定**：加 §13 "依赖 & 工具链"：Python ≥ 3.11、typer、SQLAlchemy 2、akshare、chromadb、sentence-transformers、python-frontmatter、pyyaml、rich、pytest。

### R13. `note new` 没 `$EDITOR` 时怎么办
**决定**：CLI 加 `--body "..."` 直接给正文；无 body 且无 EDITOR 时退化到读取 stdin，最后 fallback vi/nano。

### R14. `note recall` 输出格式未定
**决定**：默认 rich Table，列 = 时间 / tickers / tags / 相似度 / 摘要（前 80 字）；`--json` 出机器可读。

### R15. 混合检索的重排算法
**决定**：v1 用 RRF（Reciprocal Rank Fusion，k=60），足够简单且效果稳。之后可换。

---

## 三、范围问题

### R16. M1 范围
v0.2 M1 = 骨架 + `watch` + `note new/recall`。
**决定**：保持不塞 `study`。`study` 是价值验证核心，独立成 M2 更容易迭代。
但 M1 要加：`note link`、`note reindex`、`providers list/ping`、`cache clear` — 这些是"骨架体检工具"。

### R17. Ticker 元数据首次入库
`watch add 600519` 时要不要立刻拉 meta.profile 落库？
**决定**：要。这是最小的"数据源真的能用"的端到端 smoke。失败就报错，让用户立刻知道数据源问题。

---

## 四、暂不处理（列出但推迟）

- 舆情 / 社媒 Provider 抽象：等 study 跑起来看有没有真需求
- Note 的 `mood` / `horizon` 字段：先用 `tags` 硬扛
- CLI 动词换 `dig` / `probe` 替代 `study`：`study` 语义最贴，保留
- 项目内数据目录 vs `~/.ripple/`：保留后者
- 配置项 hot reload：v1 用不到

---

## 五、v0.3 的动作清单

对 DESIGN.md 的编辑：

1. §0 版本记录：新增 v0.3
2. §2 产品形态：加 "Python ≥ 3.11"、"配置在 `~/.ripple/config.yaml`"、"数据目录可用 `RIPPLE_HOME` 覆盖"
3. §4 目录布局：
   - 把 `tickers/600519.md` / `themes/白酒周期.md` / `daily/2026-08-29.md` 换成 `notes/2026/08/note_xxx.md`
   - 加 `~/.ripple/config.yaml` 一行
4. §5.2 后追加"返回结构规范"（KLINE_COLUMNS 等）
5. §5 追加"Provider 健康检查"小节：`health()` 方法
6. §5.3 补充：fallback 只在同一 capability 注册链内走
7. §6.1 Note 规范：ID 加 6 位后缀；文件路径规则明确；说明"一笔记一文件"
8. §6.2 note_index 加 `content_hash` / `file_mtime`
9. §10 向量粒度：加"超 400 token 按段落切 chunk，chunk_id = note_id#i"
10. §10 检索：写清用 RRF (k=60)
11. §11 M1 交付更细：追加 note link/reindex、providers、cache
12. 新增 §13 依赖 & 工具链
13. 新增 §14 A 股代码规范（Symbol 抽象）
14. 更新 §12 待确认清单：标出哪些已在 v0.3 自决

---

## 六、Review 心态

一次自我 review 不是要把所有问题解决，是**把"隐式假设"变成"显式决定"**。
上述 17 项里，绝大多数是我在设计时"心里知道但没写下来"的东西。写下来之后，
未来无论是我改还是别人接手，都能少绕很多路。

M1 代码会严格按 v0.3 走。任何编码时发现的额外问题，回来再修 DESIGN。
