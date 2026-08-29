"""A 股代码 → Symbol。业务层只接受纯 6 位 code，内部按需转厂商格式。

归属规则（v1，遇到新前缀再补）：
- 6xxxxx → SH, MAIN；688xxx → SH, STAR
- 000xxx / 001xxx / 002xxx / 003xxx → SZ, MAIN
- 300xxx / 301xxx → SZ, CHINEXT
- 8xxxxx / 4xxxxx / 9xxxxx → BJ, BSE
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Symbol:
    code: str
    exchange: str
    board: str

    @classmethod
    def parse(cls, code: str) -> "Symbol":
        c = code.strip().upper()
        # 允许 sh600519 / SH600519 / 600519.SH / 600519 混合输入
        if "." in c:
            c = c.split(".", 1)[0]
        if c[:2] in ("SH", "SZ", "BJ") and c[2:].isdigit():
            c = c[2:]
        if not (len(c) == 6 and c.isdigit()):
            raise ValueError(f"未识别的 A 股代码：{code!r}")

        prefix1 = c[0]
        prefix3 = c[:3]

        if prefix1 == "6":
            exch = "SH"
            board = "STAR" if prefix3 == "688" else "MAIN"
        elif prefix3 in ("300", "301"):
            exch, board = "SZ", "CHINEXT"
        elif prefix3 in ("000", "001", "002", "003"):
            exch, board = "SZ", "MAIN"
        elif prefix1 in ("4", "8", "9"):
            exch, board = "BJ", "BSE"
        else:
            raise ValueError(f"未识别的 A 股代码前缀：{code!r}")

        return cls(code=c, exchange=exch, board=board)

    # ---- 厂商格式 ----
    def to_akshare(self) -> str:
        # akshare 大部分接口用 "sh600519" 或 "600519"，各接口不一，这里给带前缀的通用形
        return f"{self.exchange.lower()}{self.code}"

    def to_tushare(self) -> str:
        return f"{self.code}.{self.exchange}"

    def __str__(self) -> str:
        return self.code
