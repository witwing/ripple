# Ripple · 观澜 — 方案文档

> A 股 · 深挖单票 · 自由笔记 + 检索
> *观澜索源 — Watch the ripples, trace the source.*

本文件是**沟通介质**，不是实现细节。任何设计变更先改此文档，代码随文档走。

---

## 0. 版本记录

| 版本 | 日期 | 变更摘要 |
|---|---|---|
| v0.1 | 2026-08-29 | 初版：定位、架构分层、目录、数据模型、CLI 动词、Milestone |
| v0.2 | 2026-08-29 | 数据源抽象化（可插拔）；向量模型固定本地；补充数据源适配层设计 |

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
- 数据落在 `~/.ripple/`，整目录可 git 版本化
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
│  Storage  SQLite + Markdown + Chroma           │
└───────────────────────────────────────────────┘
```

---

## 4. 目录布局

```
ripple/                           # 代码仓库
├── DESIGN.md                     # ← 本文档
├── pyproject.toml
├── ripple/
│   ├── cli.py
│   ├── config.py
│   ├── providers/                # § 数据源适配层（可插拔）
│   │   ├── base.py               # 抽象接口
│   │   ├── registry.py           # 注册 + 路由 + 降级
│   │   ├── akshare_provider.py   # 默认实现
│   │   ├── tushare_provider.py   # 预留，未实现
│   │   └── eastmoney_scraper.py  # 预留，未实现
│   ├── models/                   # SQLAlchemy
│   ├── notes/                    # 笔记引擎 + 向量检索
│   ├── analyze/                  # 深挖单票
│   ├── simulate/                 # 模拟组合
│   ├── review/                   # 复盘
│   └── llm/
└── tests/

~/.ripple/                        # 用户数据
├── ripple.db                     # SQLite
├── notes/                        # 纯 Markdown
│   ├── tickers/600519.md
│   ├── themes/白酒周期.md
│   └── daily/2026-08-29.md
├── briefs/                       # 生成的研究简报
├── portfolios/main.yaml
├── vectors/                      # Chroma 持久化
└── cache/                        # 各数据源原始响应缓存
```

---

## 5. 数据源适配层（★ 本次重点）

### 5.1 设计目标

- **单一数据源必有短板**：akshare 免费但接口不稳；tushare 全但要 token；东财/雪球有反爬
- 系统要能：**同一份业务代码，底层随时切换/组合数据源**
- 新增数据源 = 新增一个 Provider 类 + 注册，不动业务代码

### 5.2 抽象接口

按**能力**切分而非按厂商切分，一个厂商可实现多个能力。

```python
# ripple/providers/base.py
class QuoteProvider(Protocol):
    def daily_kline(code: str, start: date, end: date) -> DataFrame: ...
    def snapshot(code: str) -> Quote: ...

class FundamentalProvider(Protocol):
    def financial_reports(code: str, kind: Literal["income","balance","cash"],
                          periods: int = 8) -> DataFrame: ...
    def valuation(code: str) -> Valuation: ...   # PE/PB/股息/分位

class DisclosureProvider(Protocol):
    def announcements(code: str, since: date) -> list[Announcement]: ...

class NewsProvider(Protocol):
    def news(code: str, since: date, limit: int = 50) -> list[NewsItem]: ...

class MetaProvider(Protocol):
    def profile(code: str) -> TickerProfile: ...  # 名称、行业、市值、上市日
    def industry_peers(code: str) -> list[str]: ...
```

**返回类型统一**为 Ripple 内部 dataclass / DataFrame schema，各 Provider 内部做字段映射。业务层永远不接触厂商原生字段。

### 5.3 Provider 注册与路由

```python
# ripple/providers/registry.py
class ProviderRegistry:
    def register(capability: type, provider: Any, priority: int = 100): ...
    def get(capability: type) -> Any: ...   # 拿主 provider
    def all(capability: type) -> list: ...  # 拿全部（按优先级）
```

**路由策略**（config.yaml 可配）
- `primary`：只用第一个，失败即报错
- `fallback`：主源失败自动降级到下一个（默认）
- `cross_check`：多源同时取，Ripple 层做一致性校验（用于关键数据，比如财报）

### 5.4 缓存与限流

每个 Provider 调用都经过统一装饰：
- **磁盘缓存**：按 `(provider, method, args_hash, date)` 缓存原始响应到 `~/.ripple/cache/<provider>/`
- **限流**：token bucket，每个 provider 独立配额
- **重试**：指数退避，可配置

缓存让"下次启动"和"复盘"不用重新拉数据，也让离线调试成为可能。

### 5.5 v1 默认配置

```yaml
providers:
  quote:        [akshare]              # 主源即可
  fundamental:  [akshare]              # 后续 cross_check tushare
  disclosure:   [akshare]              # akshare 拿巨潮公告
  news:         [akshare]              # 东财新闻，后续加 rss
  meta:         [akshare]
strategy: fallback
```

后续加 tushare 只需：`pip install tushare` → 新增 `tushare_provider.py` → 在 config 里追加即可。**业务代码零改动**。

### 5.6 数据鲜度与来源标注

- 每份数据落库时都带上 `source`、`fetched_at` 字段
- 简报和 Advice 会在正文脚注里标出"本次分析基于 [akshare @ 2026-08-29 15:30] 的数据"
- 便于事后追责：如果判断错了，是数据错了还是我错了

---

## 6. 核心数据模型

### 6.1 Note（自由笔记 · 系统的灵魂）

**文件即事实，DB 只是索引，Chroma 只是向量副本。三者可从 Markdown 单向重建。**

```markdown
---
id: note_20260829_142011
created: 2026-08-29T14:20:11+08:00
tickers: [600519]
themes: [白酒, 消费复苏]
tags: [基本面, 渠道调研]
source: 自己 | 雪球@xxx | 研报-中信-20260810
confidence: 0.7
---

正文自由写，支持 [[note_xxx]] 和 [[600519]] 双向链接。
```

### 6.2 SQLite 表（第一版）

| 表 | 关键字段 | 说明 |
|---|---|---|
| ticker | code, name, industry, list_date, meta_json, updated_at | 元数据缓存 |
| snapshot | code, ts, kind(quote/fin/val), payload_json, source | 时间序列快照 |
| note_index | id, path, tickers, themes, tags, created, updated | 由 md 扫描生成 |
| brief | id, ticker, created, model, path, cited_note_ids | 简报索引 |
| advice | id, brief_id, ticker, action, size_pct, confidence, rationale, created | 建议 |
| trade | id, portfolio_id, ticker, side, price, qty, ts, advice_id? | 模拟成交 |
| portfolio | id, name, cash, nav_json | 模拟组合 |
| review | id, advice_id, actual_return_pct, verdict, lesson_note_id, created | 复盘 |

---

## 7. CLI 动词（v1）

```bash
# 自选池
ripple watch add 600519
ripple watch list
ripple watch remove 600519

# 深挖单票（核心闭环）
ripple study 600519 [--refresh] [--no-llm]

# 自由笔记
ripple note new [--ticker 600519] [--theme 白酒]
ripple note recall "白酒 渠道"
ripple note link 600519             # 展示某票关联的所有笔记
ripple note reindex                 # 从 md 重建索引 + 向量

# 模拟组合
ripple sim buy  600519 100 [--from-advice adv_xxx]
ripple sim sell 600519 100
ripple sim status
ripple sim report [--since 2026-01-01]

# 复盘
ripple review week
ripple review advice adv_xxx

# 数据源
ripple providers list               # 看当前生效的 provider 与优先级
ripple providers ping               # 探测每个源的连通性
ripple cache clear [--provider akshare]
```

---

## 8. `ripple study <code>` 完整流程

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

## 10. 向量模型

- **模型**：`BAAI/bge-small-zh-v1.5`（本地跑，中文效果好，512 维，CPU 也行）
- **加载**：`sentence-transformers`
- **向量库**：`chromadb`，持久化到 `~/.ripple/vectors/`
- **粒度**：一条 note 一个向量；后续如果 note 过长再考虑段落切分
- **检索**：混合检索 = 向量 top-k + 关键词/标签过滤 → 重排取前 8 条

---

## 11. Milestone

| 编号 | 目标 | 交付 |
|---|---|---|
| **M1** | 骨架能跑 | CLI 脚手架、config、SQLite 初始化、akshare provider、`watch/note new/note recall` |
| **M2** | 深挖闭环 | `study <code>` 从拉数据到生成 Brief + Advice，端到端 |
| **M3** | 模拟组合 | `sim buy/sell/status/report`，Advice ↔ Trade 关联 |
| **M4** | 复盘回环 | `review week` 自动跑 + lesson note 自动入库 |
| **M5+** | 可选增强 | 定时扫描、事件订阅、Web 只读面板、多数据源 cross_check |

每个 M 完成后本文档同步更新一次「实际交付 vs 计划」小节。

---

## 12. 待确认清单

- [ ] 命名与 slogan 是否确定（Ripple · 观澜 / Watch the ripples, trace the source）
- [ ] 目录布局 `~/.ripple/` 是否 OK，还是想放到项目内
- [ ] Provider 抽象是否够用（是否需要单独抽出「舆情/社媒」能力）
- [ ] Note frontmatter 字段是否够用（要不要加 `mood`/`horizon` 之类）
- [ ] CLI 动词命名是否顺手（例如 `study` 用 `dig` / `probe` 是否更好）
- [ ] M1 的范围是否合适（要不要把 `study` 的最简版一起塞进 M1）
