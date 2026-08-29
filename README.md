# Ripple · 观澜

> *观澜索源 — Watch the ripples, trace the source.*

A 股 · 深挖单票 · 自由笔记 + 检索。
一个人的投资研究、模拟交易与知识沉淀操作系统。

- 方案：[DESIGN.md](./DESIGN.md)
- 本次 review：[REVIEW.md](./REVIEW.md)
- 分支：`dev` 开发 / `main` 发布

## 状态

**M1 已落地**（骨架能跑）。当前可用：

```bash
# 安装
python3.11 -m pip install -e .

# 自选池
ripple watch add 600519          # 加入并首次拉 profile 落库
ripple watch list
ripple watch remove 600519

# 自由笔记
ripple note new --ticker 600519 --theme 白酒 --tag 渠道 --body "..."
echo "..." | ripple note new --ticker 600519   # 也可从 stdin
ripple note new --ticker 600519                # 无 --body 无 stdin → 开 $EDITOR
ripple note recall "白酒 渠道"                  # 关键词 + 向量混合检索
ripple note recall "ticker:600519 tag:渠道"    # 支持字段过滤语法
ripple note link 600519                         # 某支票关联的所有笔记
ripple note reindex                             # 从 md 全量重建索引

# 数据源
ripple providers list
ripple providers ping
ripple cache clear [--provider akshare]
```

Milestone 进度见 [DESIGN.md §11](./DESIGN.md#11-milestone)。

## 数据位置

默认 `~/.ripple/`，可用 `RIPPLE_HOME=/some/path` 覆盖。整个目录可以用 git 管理。

```
$RIPPLE_HOME/
├── config.yaml
├── ripple.db
├── notes/YYYY/MM/note_*.md
├── vectors/                  # Chroma 持久化
└── cache/<provider>/         # 原始响应缓存
```

## 开发

```bash
python3.11 -m pip install -e '.[dev]'
pytest -q
```
