# Ripple · 观澜 — 方案文档

> A 股 · 深挖单票 · 自由笔记 + 检索
> *观澜索源 — Watch the ripples, trace the source.*

本文件是**沟通介质**，不是实现细节。任何设计变更先改此文档，代码随文档走。
配套 review 记录在 [REVIEW.md](./REVIEW.md)。

---

## 0. 版本记录

| 版本 | 日期 | 变更摘要 |
|---|---|---|
| v0.1 | 2026-08-29 | 初版：定位、架构分层、目录、数据模型、CLI 动词、Milestone |
| v0.2 | 2026-08-29 | 数据源抽象化（可插拔）；向量模型固定本地；补充数据源适配层设计 |
| v0.3 | 2026-08-29 | 自我 review 后修订：Note 组织方式、返回结构规范、Symbol 抽象、chunk 策略、依赖清单等（详见 REVIEW.md 与本次修订处的 v0.3 注） |

---

## 1. 定位与原则

**一句话**：Ripple 是给一个人用的"投资研究 + 模拟交易 + 知识沉淀"操作系统。
不是荐股软件，不是量化平台，是"让你自己的判断随时间变强"的工具。

**三原则**
1. **决策留痕** — 每一次建议都记录理由，事后能复盘
2. **知识可复用** — 笔记会在下一次决策时自动被检索到
3. **模拟先行** — 所有策略先纸面跑通

**边界（v1 不做）**
- 不接实盘券商接口
- 不做多用户 / Web UI
- 不做高频 / 分钟级策略
- 不做全市场扫描（先做深自选池）

---

## 2. 产品形态

- 本地 CLI：`ripple <verb> ...`
- **运行环境**：Python ≥ 3.11
- **数据目录**：默认 `~/.ripple/`，可用环境变量 `RIPPLE_HOME` 覆盖；整目录可 git 版本化
- **配置文件**：`$RIPPLE_HOME/config.yaml`，首次运行自动生成默认值
- 笔记是纯 Markdown 文件（带 frontmatter），SQLite 只做索引
- 向量库本地跑（chromadb + bge-small-zh），无外部依赖

---

## 3. 架构分层

```
┌───────────────────────────────────────────────┐
│  CLI（Typer）                                  │
├───────────────────────────────────────────────┤
│  Application 用例层                            │
│   study / note / sim / review / watch          │
├──────────┬──────────┬──────────┬───────────────┤
│ Analyze  │  Notes   │ Simulate │  Review       │
│ 深挖单票 │ 自由笔记 │ 模拟组合 │  复盘          │
├──────────┴──────────┴──────────┴───────────────┤
│  LLM Adapter（Claude Sonnet 5 / Haiku 4.5）    │
├───────────────────────────────────────────────┤
│  Data Provider 抽象层（★ 重点，见 §5）         │
│   ├─ QuoteProvider      行情                   │
│   ├─ FundamentalProvider 财报/估值             │
│   ├─ DisclosureProvider  公告                  │
│   ├─ NewsProvider        新闻/研报              │
│   └─ MetaProvider        股票元数据             │
├───────────────────────────────────────────────┤
│  Core：Symbol / Cache / Config / Logger        │
├───────────────────────────────────────────────┤
│  Storage  SQLite + Markdown + Chroma           │
└───────────────────────────────────────────────┘
```

---

## 4. 目录布局

代码仓的 `ripple/` 目录 = 顶层 Python 包（standard src-less layout）。

```
ripple/                           # 代码仓库根
├── DESIGN.md                     # ← 本文档
├── REVIEW.md                     # v0.2 自我 review
├── README.md
├── pyproject.toml
├── ripple/                       # 顶层包
│   ├── __init__.py
│   ├── cli.py                    # Typer 入口
│   ├── core/
│   │   ├── config.py             # 加载/写默认 config.yaml
│   │   ├── paths.py              # 解析 RIPPLE_HOME
│   │   ├── logger.py
│   │   └── symbol.py             # A 股代码 → Symbol
│   ├── providers/                # 数据源适配层（可插拔）
│   │   ├── base.py               # Protocol + 数据类
│   │   ├── registry.py           # 注册 + fallback 路由
│   │   ├── cache.py              # 磁盘缓存 + 重试装饰
│   │   ├── akshare_provider.py
│   │   ├── tushare_provider.py   # 预留占位
│   │   └── eastmoney_scraper.py  # 预留占位
│   ├── models/                   # SQLAlchemy 模型
│   ├── notes/                    # 笔记引擎 + 向量检索
│   │   ├── store.py              # md 文件 CRUD
│   │   ├── embed.py              # bge-small-zh 懒加载
│   │   ├── chunk.py              # 长笔记切段
│   │   └── search.py             # RRF 混合检索
│   ├── analyze/                  # 深挖单票（M2）
│   ├── simulate/                 # 模拟组合（M3）
│   ├── review/                   # 复盘（M4）
│   └── llm/                      # Claude 调用（M2 起）
│       └── prompts/
└── tests/

$RIPPLE_HOME/                     # 用户数据（默认 ~/.ripple/）
├── config.yaml
├── ripple.db                     # SQLite
├── notes/                        # 一笔记一文件
│   └── 2026/08/note_20260829_142011_a1b2c3.md
├── briefs/                       # 生成的研究简报（M2 起）
├── portfolios/                   # 模拟组合（M3 起）
│   └── main.yaml
├── vectors/                      # Chroma 持久化
└── cache/                        # 各数据源原始响应缓存
    └── akshare/
```

**Note 组织方式**：一条笔记一个文件，扁平存放在 `notes/YYYY/MM/<id>.md`。
不再有"按票聚合的 md"，聚合视图由 `ripple note link 600519` 从 frontmatter 查询生成。

---

## 5. 数据源适配层（★ 重点）

### 5.1 设计目标

- **单一数据源必有短板**：akshare 免费但接口不稳；tushare 全但要 token；东财/雪球有反爬
- 系统要能：**同一份业务代码，底层随时切换/组合数据源**
- 新增数据源 = 新增一个 Provider 类 + 注册，不动业务代码

### 5.2 抽象接口

按**能力**切分而非按厂商切分，一个厂商可实现多个能力。所有接口对外只接受纯 6 位 A 股代码（`600519`），内部转成厂商所需格式（见 §14 Symbol）。

```python
# ripple/providers/base.py（简化）
class QuoteProvider(Protocol):
    def daily_kline(code: str, start: date, end: date) -> DataFrame: ...
    def snapshot(code: str) -> Quote: ...

class FundamentalProvider(Protocol):
    def financial_reports(code: str, kind: Literal["income","balance","cash"],
                          periods: int = 8) -> DataFrame: ...
    def valuation(code: str) -> Valuation: ...

class DisclosureProvider(Protocol):
    def announcements(code: str, since: date) -> list[Announcement]: ...

class NewsProvider(Protocol):
    def news(code: str, since: date, limit: int = 50) -> list[NewsItem]: ...

class MetaProvider(Protocol):
    def profile(code: str) -> TickerProfile: ...
    def industry_peers(code: str) -> list[str]: ...

# 所有 Provider 都要实现的健康检查
class BaseProvider(Protocol):
    name: str
    def health(self) -> HealthStatus: ...
```

**返回结构规范**（重要 · v0.3 新增）
业务层只认这些字段名与类型，Provider 内部做映射；缺失字段填 NaN / None。

| 接口 | 结构 | 字段 |
|---|---|---|
| `daily_kline` | DataFrame | `date, open, high, low, close, volume, amount, turnover_pct` |
| `snapshot` | `Quote` | `code, ts, price, open, high, low, prev_close, volume, amount` |
| `financial_reports` | DataFrame | 索引为报告期，列因 kind 而异，但列名统一为中文 pinyin key |
| `valuation` | `Valuation` | `code, ts, pe_ttm, pb, dv_ratio, pe_pct_5y, pb_pct_5y` |
| `TickerProfile` | dataclass | `code, name, exchange, board, industry, list_date, total_mv, float_mv, updated_at` |
| `Announcement` | dataclass | `code, title, url, publish_time, kind` |
| `NewsItem` | dataclass | `code, title, url, publish_time, source, summary` |
| `HealthStatus` | dataclass | `provider, ok, latency_ms, message, checked_at` |

### 5.3 Provider 注册与路由

```python
# ripple/providers/registry.py
class ProviderRegistry:
    def register(capability: type, provider: Any, priority: int = 100): ...
    def get(capability: type) -> Any: ...   # 拿主 provider
    def all(capability: type) -> list: ...  # 全部（按优先级降序）
```

**路由策略**（config.yaml 可配）
- `primary`：只用第一个，失败即报错
- `fallback`：主源抛异常自动降级到下一个同 capability 的 provider（默认）
- `cross_check`：多源同时取，Ripple 层做一致性校验（关键数据，如财报）

Fallback 只在**同一 capability 的注册链**里走；跨 capability 不降级。

### 5.4 缓存与限流

每个 Provider 调用都经过统一装饰（`ripple/providers/cache.py`）：
- **磁盘缓存**：按 `(provider, method, args_hash, date_bucket)` 缓存到 `$RIPPLE_HOME/cache/<provider>/`；`date_bucket` 对高频接口按日划分
- **限流**：token bucket，每个 provider 独立配额（默认 5 req/s，可配）
- **重试**：指数退避（1s → 2s → 4s），默认最多 3 次
- **健康检查**：`ripple providers ping` 调用每个 provider 的 `health()`

缓存让"下次启动"和"复盘"不用重新拉数据，也让离线调试成为可能。

### 5.5 v1 默认配置

```yaml
providers:
  quote:        [akshare]
  fundamental:  [akshare]
  disclosure:   [akshare]
  news:         [akshare]
  meta:         [akshare]
strategy: fallback
cache:
  enabled: true
  ttl_hours:
    daily_kline: 12
    snapshot: 0.1
    financial_reports: 240
    valuation: 12
    profile: 240
    announcements: 6
    news: 1
rate_limit:
  akshare: 5   # req/s
```

后续加 tushare：`pip install tushare` → 新增 `tushare_provider.py` → 在 config 里追加即可。业务代码零改动。

### 5.6 数据鲜度与来源标注

- 每份数据落库时都带 `source`、`fetched_at`
- 简报和 Advice 会在正文脚注里标出"本次分析基于 [akshare @ 2026-08-29 15:30] 的数据"
- 便于事后追责：如果判断错了，是数据错了还是我错了

---

## 6. 核心数据模型

### 6.1 Note（自由笔记 · 系统的灵魂）

**文件即事实**，DB 只是索引，Chroma 只是向量副本。三者可从 Markdown 单向重建。

```markdown
---
id: note_20260829_142011_a1b2c3
created: 2026-08-29T14:20:11+08:00
tickers: [600519]
themes: [白酒, 消费复苏]
tags: [基本面, 渠道调研]
source: 自己 | 雪球@xxx | 研报-中信-20260810
confidence: 0.7
---

正文自由写，支持 [[note_xxx]] 和 [[600519]] 双向链接。
```

**ID 规则**：`note_YYYYMMDD_HHMMSS_<6位随机>`，人类可读 + 唯一。
**文件路径**：`$RIPPLE_HOME/notes/YYYY/MM/<id>.md`。

### 6.2 SQLite 表（第一版）

| 表 | 关键字段 | 说明 |
|---|---|---|
| ticker | code, name, exchange, board, industry, list_date, meta_json, updated_at | 元数据缓存 |
| snapshot | code, ts, kind(quote/fin/val), payload_json, source | 时间序列快照 |
| watch | code, added_at, note | 自选池 |
| note_index | id, path, tickers, themes, tags, confidence, created, updated, file_mtime, content_hash | 由 md 扫描生成 |
| brief | id, ticker, created, model, path, cited_note_ids | 简报索引（M2 起） |
| advice | id, brief_id, ticker, action, size_pct, confidence, rationale, created | 建议（M2 起） |
| trade | id, portfolio_id, ticker, side, price, qty, ts, advice_id? | 模拟成交（M3 起） |
| portfolio | id, name, cash, nav_json | 模拟组合（M3 起） |
| review | id, advice_id, actual_return_pct, verdict, lesson_note_id, created | 复盘（M4 起） |

`content_hash` + `file_mtime`：reindex 时判断 md 是否变了，避免重算 embedding。

---

## 7. CLI 动词（v1）

```bash
# 自选池
ripple watch add 600519
ripple watch list
ripple watch remove 600519

# 深挖单票（M2）
ripple study 600519 [--refresh] [--no-llm]

# 自由笔记
ripple note new [--ticker 600519] [--theme 白酒] [--body "..."]
ripple note recall "白酒 渠道" [--k 8] [--json]
ripple note link 600519             # 展示某票关联的所有笔记
ripple note reindex                 # 从 md 重建索引 + 向量

# 模拟组合（M3）
ripple sim buy  600519 100 [--from-advice adv_xxx]
ripple sim sell 600519 100
ripple sim status
ripple sim report [--since 2026-01-01]

# 复盘（M4）
ripple review week
ripple review advice adv_xxx

# 数据源
ripple providers list               # 当前生效的 provider 与优先级
ripple providers ping               # 探测每个源的连通性
ripple cache clear [--provider akshare]
```

`note new` 编辑器选择顺序：`--body` 直接给 > 读 stdin > `$EDITOR` > `vi`。
`note recall` 输出默认 rich Table（时间/tickers/tags/相似度/摘要 80 字），`--json` 出机器可读。

---

## 8. `ripple study <code>` 完整流程（M2 起）

```
1. Fetch     ─ 通过 Provider 拉：K线 / 财报 / 估值 / 公告 / 新闻
              （命中缓存则跳过；多源可做 cross_check）
2. Snapshot  ─ 落 SQLite snapshot 表 + 文件缓存
3. Recall    ─ 从 notes/ 用向量+关键词混合检索出 top-k 相关笔记
4. Profile   ─ 计算基本面画像（ROE / 现金流 / 分红 / 估值分位）
5. Narrate   ─ Claude Sonnet 5 生成研究简报（引用 note 和数据源）
              → briefs/600519_20260829.md
6. Advise    ─ 综合出 Advice：action / size / confidence / rationale
              → 写入 advice 表，输出到终端
```

---

## 9. LLM 使用策略

| 场景 | 模型 | 理由 |
|---|---|---|
| study 研究简报 | Claude Sonnet 5 | 主力，需要综合推理 |
| study 建议生成 | Claude Sonnet 5 | 与简报同一次调用 |
| 笔记自动打标签 | Claude Haiku 4.5 | 高频、任务简单 |
| 每日扫描（后续） | Claude Haiku 4.5 | 频次高、成本敏感 |
| 复盘总结 | Claude Sonnet 5 | 需要跨文档推理 |

所有 prompt 集中在 `ripple/llm/prompts/*.md`，独立于代码。

---

## 10. 向量与检索

- **模型**：`BAAI/bge-small-zh-v1.5`（本地跑，中文效果好，512 维，CPU 可用）
- **加载**：`sentence-transformers`，首次调用时懒加载
- **向量库**：`chromadb` PersistentClient，落 `$RIPPLE_HOME/vectors/`
- **粒度**：
  - 短笔记（正文 ≤ 400 token）→ 整篇一个向量，`chunk_id = <note_id>`
  - 长笔记 → 按 `\n\n` 段落切成多个 chunk，`chunk_id = <note_id>#<i>`
  - 检索时若同一 note 多 chunk 命中，只保留最高分那条（去重）
- **混合检索**：
  1. 向量 top-K（默认 K=20）
  2. 关键词 / 标签过滤（tickers / themes / tags 精确匹配加权）
  3. **RRF 融合**（k=60）→ 返回 top-8

---

## 11. Milestone

| 编号 | 目标 | 交付 |
|---|---|---|
| **M1** | 骨架能跑 | CLI 脚手架、config、SQLite、akshare provider（meta+quote 最小）、`watch add/list/remove`、`note new/recall/link/reindex`、`providers list/ping`、`cache clear` |
| **M2** | 深挖闭环 | `study <code>` 从拉数据到生成 Brief + Advice，端到端 |
| **M3** | 模拟组合 | `sim buy/sell/status/report`，Advice ↔ Trade 关联 |
| **M4** | 复盘回环 | `review week` 自动跑 + lesson note 自动入库 |
| **M5+** | 可选增强 | 定时扫描、事件订阅、Web 只读面板、多数据源 cross_check |

每个 M 完成后本文档同步更新一次「实际交付 vs 计划」小节。

---

## 12. 待确认清单

- [x] 命名与 slogan：**Ripple · 观澜 / Watch the ripples, trace the source** — 已定
- [x] 目录布局：**默认 `~/.ripple/`，`RIPPLE_HOME` 可覆盖** — 已定（v0.3）
- [ ] Provider 抽象是否够用（是否需要单独抽出「舆情/社媒」能力）— 推迟到 study 跑起来看真需求
- [ ] Note frontmatter 字段是否够用（要不要加 `mood`/`horizon` 之类）— 用 `tags` 硬扛，v1 先不加
- [x] CLI 动词：保留 `study`（语义最贴）— 已定
- [x] M1 范围：不塞 `study`，但加 note link/reindex + providers + cache — 已定（v0.3）

---

## 13. 依赖与工具链

- **Python**：≥ 3.11
- **运行时依赖**：
  - `typer` — CLI 框架
  - `rich` — 终端渲染
  - `SQLAlchemy` ≥ 2.0 — ORM
  - `akshare` — 数据源
  - `pandas` — 数据操作
  - `chromadb` — 向量库
  - `sentence-transformers` — bge-small-zh 加载器
  - `python-frontmatter` — Markdown frontmatter 解析
  - `pyyaml` — 配置
  - `platformdirs` — 路径 fallback
  - `httpx` — 简单 HTTP（后续给 news scraper 用）
- **开发依赖**：`pytest`、`pytest-cov`、`ruff`、`mypy`
- **构建**：`pyproject.toml`（PEP 621），入口 `ripple = "ripple.cli:app"`

---

## 14. A 股代码规范

统一在 `ripple/core/symbol.py` 处理。

```python
@dataclass(frozen=True)
class Symbol:
    code: str          # "600519" 六位纯数字
    exchange: str      # "SH" | "SZ" | "BJ"
    board: str         # "MAIN" | "STAR" | "CHINEXT" | "BSE"

    @classmethod
    def parse(cls, code: str) -> "Symbol": ...

    def to_akshare(self) -> str: ...   # "sh600519"
    def to_tushare(self) -> str: ...   # "600519.SH"
    def to_qmt(self) -> str: ...       # 等后续需要
```

**归属规则**（v1，可能不全，遇到新前缀再补）
- `6xxxxx` → SH，MAIN；`688xxx` → SH，STAR
- `000xxx / 001xxx / 002xxx / 003xxx` → SZ，MAIN
- `300xxx / 301xxx` → SZ，CHINEXT
- `8xxxxx / 4xxxxx / 9xxxxx` → BJ，BSE

未识别代码 → `ValueError`，业务层不吃哑巴亏。

---

## 15. 参与开发的约定

- 任何设计变更**先改 DESIGN.md** 对应章节，在 §0 版本记录追加一行
- 每次 review 单独落一个 `REVIEW_v0.x.md`（本次是 REVIEW.md，之后编号）
- 代码不引入未在 §13 声明的依赖
- Provider 只做"厂商 → Ripple 内部结构"的映射，不做业务判断
- 所有面向用户的字符串（错误信息、CLI 帮助）都用中文
