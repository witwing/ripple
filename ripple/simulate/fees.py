"""A 股交易费用规则（模拟）。

- 佣金：成交额 × 万 2.5，最低 5 元（买卖都收）
- 印花税：仅卖出，成交额 × 万 5
- 过户费：成交额 × 万 0.1（沪深简化统一）
"""
from __future__ import annotations

from dataclasses import dataclass

COMMISSION_RATE = 0.00025   # 万 2.5
COMMISSION_MIN = 5.0        # 最低 5 元
STAMP_TAX_RATE = 0.0005     # 万 5，仅卖出
TRANSFER_FEE_RATE = 0.00001  # 万 0.1


@dataclass
class Fees:
    commission: float
    stamp_tax: float
    transfer_fee: float

    @property
    def total(self) -> float:
        return round(self.commission + self.stamp_tax + self.transfer_fee, 2)


def compute_fees(price: float, qty: int, side: str) -> Fees:
    turnover = price * qty
    commission = max(turnover * COMMISSION_RATE, COMMISSION_MIN)
    stamp = turnover * STAMP_TAX_RATE if side == "sell" else 0.0
    transfer = turnover * TRANSFER_FEE_RATE
    return Fees(
        commission=round(commission, 2),
        stamp_tax=round(stamp, 2),
        transfer_fee=round(transfer, 2),
    )
