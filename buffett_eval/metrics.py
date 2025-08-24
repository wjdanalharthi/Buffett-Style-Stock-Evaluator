from __future__ import annotations
from dataclasses import dataclass
from typing import List
import pandas as pd

@dataclass
class MetricResult:
    name: str
    value: float | str | None
    pass_flag: bool | None
    details: str = ""

def _cagr(first: float, last: float, periods: int) -> float | None:
    if first is None or last is None: return None
    if first <= 0 or last <= 0 or periods <= 0: return None
    try:
        return (last / first) ** (1/periods) - 1
    except Exception:
        return None

def roe_series(df: pd.DataFrame):
    s = df["net_income"] / df["shareholders_equity"].replace(0, pd.NA)
    return s

def de_series(df: pd.DataFrame):
    s = df["total_debt"] / df["shareholders_equity"].replace(0, pd.NA)
    return s

def equity_growth_5y(df: pd.DataFrame) -> MetricResult:
    d = df.sort_values("year").tail(5)
    if len(d) < 2: return MetricResult("Equity growing (5y)", None, None, "insufficient data")
    first, last = d["shareholders_equity"].iloc[0], d["shareholders_equity"].iloc[-1]
    c = _cagr(first, last, len(d)-1)
    if c is None: return MetricResult("Equity growing (5y)", None, None, "insufficient data")
    return MetricResult("Equity growing (5y)", float(c), bool(c > 0), f"CAGR {c:.2%}")

def profit_growth_5y(df: pd.DataFrame) -> MetricResult:
    d = df.sort_values("year").tail(5)
    if len(d) < 2: return MetricResult("Profit growing (5y)", None, None, "insufficient data")
    first, last = d["net_income"].iloc[0], d["net_income"].iloc[-1]
    c = _cagr(first, last, len(d)-1)
    if c is None: return MetricResult("Profit growing (5y)", None, None, "insufficient data")
    return MetricResult("Profit growing (5y)", float(c), bool(c > 0), f"CAGR {c:.2%}")

def de_latest(df: pd.DataFrame) -> MetricResult:
    d = df.sort_values("year")
    eq = d["shareholders_equity"].iloc[-1]
    debt = d["total_debt"].iloc[-1]
    ratio = None
    if pd.notna(eq) and eq != 0 and pd.notna(debt):
        ratio = float(debt / eq)
    ok = (ratio is not None) and (ratio < 0.50)
    return MetricResult("Debt-to-Equity < 50% (latest)", float(ratio) if ratio is not None else None, bool(ok), f"D/E {ratio:.2f}" if ratio is not None else "n/a")

def roe_consistent_5y(df: pd.DataFrame, min_target: float = 0.15) -> MetricResult:
    d = df.sort_values("year").tail(5)
    full = (d["net_income"] / d["shareholders_equity"].replace(0, pd.NA))
    clean = full.dropna()
    if clean.empty: return MetricResult("ROE ≥ 15% (5y)", None, None, "no data")
    pass_ratio = (clean >= min_target).mean()
    details = "; ".join([f"{int(y)}: {v:.1%}" if pd.notna(v) else f"{int(y)}: n/a" for y, v in zip(d["year"], full)])
    return MetricResult("ROE ≥ 15% (5y)", float(pass_ratio), bool(pass_ratio >= 0.80), details)

def fcf_positive_5y(df: pd.DataFrame) -> MetricResult:
    d = df.sort_values("year").tail(5)
    pos_ratio = (d["free_cash_flow"] > 0).mean() if len(d) > 0 else 0.0
    all_pos = bool(pos_ratio == 1.0)
    return MetricResult("FCF positive (5y)", float(pos_ratio), all_pos, f"positive_years={pos_ratio:.0%}")

def scorecard(df: pd.DataFrame) -> List[MetricResult]:
    return [equity_growth_5y(df), de_latest(df), profit_growth_5y(df), roe_consistent_5y(df, 0.15), fcf_positive_5y(df)]

def aggregate_score(results: List[MetricResult]) -> float | None:
    flags = [r.pass_flag for r in results if r.pass_flag is not None]
    return sum(flags) / len(flags) if flags else None
