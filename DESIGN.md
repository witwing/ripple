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
| v0.4 | 2026-08-29 | M2 落地前的补充：`study` 完整流程细化、Brief markdown schema、Advice 结构、LLM 适配层契约、`--no-llm` dry-run 语义 |
| v0.5 | 2026-08-30 | 数据聚合第一批：新增 metrics/index 两个 capability；profile 从 12 字段扩到 27（补 ROE/毛利率/净利率/负债率/OCF比+相对沪深300）；同行对比表；briefer prompt 加同行段与"善用相对量"约束 |
| v0.6 | 2026-08-30 | 数据聚合第二批：新增 capital/institution/research 三个 capability；profile 扩到 38 字段（+融资余额、股东户数环比、公募加减仓、卖方共识 EPS/PE 中位、评级分布）；BriefContext + capital_summary + consensus_summary；briefer 7 段结构 |
| v0.7 | 2026-09-01 | 报告美化：新增 dashboard.py（信号灯🟢🟡🔴 + 分位条 + 四维星级评分，纯规则）；简报改为 8-9 段结构（信号面板/关键指标/同行/资金面/动态/历史观点/价值评分/短中长期洞察/价值分析/结论）；结论 JSON 扩展 horizon_views + value_scores；CLI 展示周期观点与星级评分 |
| v0.8 | 2026-09-01 | 可视化仪表盘：新增 render.py（matplotlib PNG，深色主题 + Noto CJK）；study 生成一张图表——信号灯行 / 估值分位条 / 四维评分点阵 / 同行 ROE×PE 散点 / 近一年 vs 沪深300 归一化走势；图表与简报同目录 |
| v0.9 | 2026-09-01 | 图文分工固化：新增 digest.py（只抽判断章节：动作条+周期观点+短中长期洞察+价值分析，不重复图里的数据）。标准输出 = 图(事实层) + 判断精炼(判断层)，两者不冗余。CLI study 默认打印判断精炼（--no-digest 关闭） |
| v0.10 | 2026-09-01 | M3 模拟组合：portfolio/position/trade/nav_point 模型；A股交易规则（整手+佣金+印花税+过户费）；移动加权成本 + 已实现/浮动盈亏；mark-to-market 净值 vs 沪深300；CLI sim init/buy/sell/status/report/history；见 §8b |

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

### 8.1 步骤

```
1. Fetch     ─ 通过 Provider 拉：K线 / 财报 / 估值 / 公告 / 新闻
              （命中缓存则跳过；--refresh 强制绕过缓存）
2. Snapshot  ─ 落 SQLite snapshot 表（每类一条），带 source + fetched_at
3. Recall    ─ 从 notes/ 用向量+关键词混合检索出 top-K 相关笔记
              （query 由 ticker 名 + 行业 + 常见标签拼装）
4. Profile   ─ 纯 Python 计算基本面画像（无 LLM），返回结构化 dict：
                · price_change_1m / 3m / 1y
                · pe_ttm / pb / dv_ratio / pe_pct_5y
                · roe_ttm / gross_margin_ttm / net_margin_ttm
                · fcf_ttm / debt_ratio
                · 近 4 季营收/净利/增速
                · 数据缺失字段为 None，不猜
5. Narrate   ─ LLM 生成研究简报（Sonnet 5）：
                · 输入 = profile + recall notes 摘要 + 最近公告标题 + 新闻标题
                · 输出 = Markdown（结构见 §8.3）
                · --no-llm 时用 fallback：把上下文按模板直接渲染出来（不调用 API）
              → briefs/YYYYMMDD/<code>_<HHMMSS>.md
6. Advise    ─ 从简报里抽出结构化 Advice（JSON 段），持久化到 advice 表
```

### 8.2 输入到 LLM 的上下文（M2 定型）

```
{
  "ticker": {"code": "600519", "name": "贵州茅台", "industry": "白酒"},
  "profile": { ... §8.1 里的字段 ... },
  "recent_kline_summary": "近 20 日振幅 3.2%，近 3 个月 +8.4%",
  "announcements": [{"date":"2026-08-15","title":"..."}] (最多 10),
  "news":         [{"date":"2026-08-20","title":"..."}] (最多 10),
  "recalled_notes": [
    {"id":"note_...", "created":"2026-06-01", "excerpt":"..." , "score": 0.31}
  ]  (最多 8),
  "user_stance": "由 recalled notes 汇总的用户历史观点，1-2 句"
}
```

### 8.3 Brief Markdown Schema

生成的简报文件必须能被机器再解析（M4 复盘会用到）：

```markdown
---
id: brief_YYYYMMDD_HHMMSS_<6位>
ticker: 600519
name: 贵州茅台
created: 2026-08-29T15:00:00+08:00
model: claude-sonnet-5
llm_mode: live | dry-run
cited_note_ids: [note_..., note_...]
data_sources:
  - {provider: akshare, kind: quote,       fetched_at: 2026-08-29T14:55:00+08:00}
  - {provider: akshare, kind: fundamental, fetched_at: 2026-08-29T14:55:00+08:00}
---

# 贵州茅台 (600519) 研究简报

## 一、事实速览
（价格 / 估值 / 财务快照，机器渲染，无观点）

## 二、近期动态
（公告 + 新闻的要点整理）

## 三、我的历史观点
（从 recalled notes 汇总）

## 四、判断
（LLM 综合推理）

## 五、结论

```json
{
  "action": "watch|buy|hold|sell",
  "size_pct": 0-100,
  "confidence": 0.0-1.0,
  "horizon_days": 30,
  "rationale": "一句话"
}
```
```

`## 五、结论` 后紧跟一个 fenced ```json 代码块，作为 Advice 的机器可读源。
解析失败时降级：action=watch, confidence=0.0, rationale="LLM 未产出结构化结论"。

### 8.4 dry-run（`--no-llm`）

不调用任何 LLM API 也能跑完全流程：
- 前 5 步全部真跑（拉数据 / 落库 / 检索 / 计算 profile）
- 第 5 步 Narrate 用**模板渲染** context，写出可读的 Markdown，`llm_mode: dry-run`
- 第 6 步 Advise 固定给 `action=watch, confidence=0.0, rationale="dry-run"`

价值：没有 ANTHROPIC_API_KEY 也能验证整条链路；CI 与本地开发默认走这条。

---

## 8b. 模拟组合（M3）

**目标**：把 study 出的 Advice 变成可跟踪的纸面持仓，事后能算盈亏、比基准。不接实盘。

### 8b.1 A 股交易规则（模拟但真实）

- **整手**：买入按 100 股整数倍；不足一手拒绝
- **佣金**：成交额 × 万分之 2.5，最低 5 元（买卖都收）
- **印花税**：仅卖出，成交额 × 万分之 5
- **过户费**：成交额 × 万分之 0.1（沪深都按此简化）
- 费用合计在成交时从现金扣除；买入总成本 = 价 × 量 + 费；卖出净得 = 价 × 量 − 费

### 8b.2 成本与盈亏

- **成本基础**：移动加权平均成本（买入摊薄，卖出不改单位成本）
- **已实现盈亏**：卖出时 =（卖出净得 − 卖出量 × 单位成本）
- **浮动盈亏**：持仓量 ×（现价 − 单位成本）
- 费用计入成本 / 冲减收益，使盈亏口径贴近真实

### 8b.3 数据模型（在既有表上扩展）

| 表 | 字段 | 说明 |
|---|---|---|
| portfolio | id, name, cash, init_cash, created | 一个模拟组合；init_cash 用于算总收益 |
| position | portfolio_id, code, qty, avg_cost, updated | 当前持仓（买卖后即时维护） |
| trade | id, portfolio_id, code, side, price, qty, fee, realized_pnl, ts, advice_id? | 每笔成交流水 |
| nav_point | portfolio_id, date, nav, cash, holdings_value | 每次快照的净值点，画曲线用 |

### 8b.4 CLI

```bash
ripple sim init [--cash 1000000]        # 建默认组合（幂等）
ripple sim buy  600519 100 [--price 1300] [--from-advice adv_xxx]
ripple sim sell 600519 100 [--price 1350]
ripple sim status                       # 持仓表 + 现金 + 浮动盈亏
ripple sim report [--snapshot]          # 净值、总收益、vs 沪深300；--snapshot 落一个 nav_point
ripple sim history [--code 600519]      # 成交流水
```

- `--price` 缺省时用 quote provider 拉现价（模拟"市价单"）
- `--from-advice` 把这笔交易关联到某条 study 建议，M4 复盘时用
- mark-to-market 用 quote.snapshot 现价；拉不到就用最近成交价兜底

---


| 场景 | 模型 | 理由 |
|---|---|---|
| study 研究简报 | Claude Sonnet 5 | 主力，需要综合推理 |
| study 建议生成 | Claude Sonnet 5 | 与简报同一次调用 |
| 笔记自动打标签 | Claude Haiku 4.5 | 高频、任务简单 |
| 每日扫描（后续） | Claude Haiku 4.5 | 频次高、成本敏感 |
| 复盘总结 | Claude Sonnet 5 | 需要跨文档推理 |

所有 prompt 集中在 `ripple/llm/prompts/*.md`，独立于代码。

### 9.1 LLM 适配层契约（M2 定型）

```python
# ripple/llm/client.py
class LLMClient(Protocol):
    def complete(system: str, user: str, model: str | None = None,
                 max_tokens: int = 4096) -> str: ...

def get_client(cfg: Config) -> LLMClient: ...    # 按 config + env 选实现
```

具体实现：
- `AnthropicClient`：走 `anthropic` SDK；`ANTHROPIC_API_KEY` 必需；模型 id 从 config 读
- `DryRunClient`：无 API key 或 `--no-llm` 时使用；`complete()` 直接把 user prompt 前缀 `"[DRY-RUN]\n"` 返回，让上层的模板渲染能识别并走 fallback 路径

选择顺序：`--no-llm` 参数 > `RIPPLE_NO_LLM=1` 环境变量 > `ANTHROPIC_API_KEY` 是否存在。

### 9.2 Prompt 组织

```
ripple/llm/prompts/
├── briefer.md       # 生成研究简报
└── advisor.md       # （M2 内嵌到 briefer 里，v1 不单调）
```

prompt 文件里用 `{{key}}` 占位，客户端 python 侧做替换（避免引入 jinja）。

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
| **M1** ✅ | 骨架能跑 | CLI 脚手架、config、SQLite、akshare provider（meta+quote 最小）、`watch add/list/remove`、`note new/recall/link/reindex`、`providers list/ping`、`cache clear` |
| **M2** ⏳ | 深挖闭环 | akshare provider 补齐 fundamental/disclosure/news；`analyze` 模块；LLM 适配层（含 dry-run）；`ripple study <code>` 从拉数据到生成 Brief + Advice，端到端 |
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
