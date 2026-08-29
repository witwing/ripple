"""长笔记分段。粗糙但足够 v1：按 \\n\\n 切段，超阈值再按行合并。"""
from __future__ import annotations


def approx_tokens(text: str) -> int:
    """极简估算：中文按字数、其余按 3.5 char/token。够 chunk 决策用。"""
    zh = sum(1 for c in text if "一" <= c <= "鿿")
    other = len(text) - zh
    return int(zh + other / 3.5)


def chunk(body: str, max_tokens: int = 400) -> list[str]:
    if not body or not body.strip():
        return []
    if approx_tokens(body) <= max_tokens:
        return [body.strip()]

    paras = [p.strip() for p in body.split("\n\n") if p.strip()]
    if not paras:
        return [body.strip()]

    out: list[str] = []
    buf: list[str] = []
    buf_tokens = 0
    for p in paras:
        t = approx_tokens(p)
        if buf and buf_tokens + t > max_tokens:
            out.append("\n\n".join(buf))
            buf, buf_tokens = [], 0
        buf.append(p)
        buf_tokens += t
    if buf:
        out.append("\n\n".join(buf))

    # 极端情况：单段就超过 max_tokens，直接放进去（bge 会自己截断，日志层面已警告不再拆行）
    return out
