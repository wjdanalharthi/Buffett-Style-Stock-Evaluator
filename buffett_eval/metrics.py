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

# ===== User's 5-rule Buffett scorecard (5y) =====

def de_latest(df: pd.DataFrame) -> MetricResult:
    """Latest Debt/Equity (D/E). Pass if < 50%."""
    df2 = df.sort_values('year')
    last_eq = df2['shareholders_equity'].iloc[-1]
    last_debt = df2['total_debt'].iloc[-1]
    ratio = None
    if pd.notna(last_eq) and last_eq != 0 and pd.notna(last_debt):
        ratio = float(last_debt / last_eq)
    pass_flag = (ratio is not None) and (ratio < 0.50)
    return MetricResult(
        name="Debt-to-Equity < 50% (latest)",
        value=float(ratio) if ratio is not None else None,
        pass_flag=bool(pass_flag),
        details=f"D/E={ratio:.2f}" if ratio is not None else "n/a"
    )

def equity_growth_5y(df: pd.DataFrame) -> MetricResult:
    """Equity growth over 5y. Pass if CAGR > 0."""
    df2 = df.sort_values('year').tail(5)
    if len(df2) < 2:
        return MetricResult("Equity growing (5y)", None, None, "insufficient data")
    first, last = df2['shareholders_equity'].iloc[0], df2['shareholders_equity'].iloc[-1]
    if pd.isna(first) or pd.isna(last) or first <= 0 or last <= 0:
        return MetricResult("Equity growing (5y)", None, None, "insufficient data")
    cg = (last / first) ** (1/(len(df2)-1)) - 1
    return MetricResult(
        name="Equity growing (5y)",
        value=float(cg),
        pass_flag=bool(cg > 0),
        details=f"CAGR={cg:.2%}"
    )

def profit_growth_5y(df: pd.DataFrame) -> MetricResult:
    """Net income growth over 5y. Pass if CAGR > 0."""
    df2 = df.sort_values('year').tail(5)
    if len(df2) < 2:
        return MetricResult("Profit growing (5y)", None, None, "insufficient data")
    first, last = df2['net_income'].iloc[0], df2['net_income'].iloc[-1]
    if pd.isna(first) or pd.isna(last) or first <= 0 or last <= 0:
        return MetricResult("Profit growing (5y)", None, None, "insufficient data")
    cg = (last / first) ** (1/(len(df2)-1)) - 1
    return MetricResult(
        name="Profit growing (5y)",
        value=float(cg),
        pass_flag=bool(cg > 0),
        details=f"CAGR={cg:.2%}"
    )

def roe_consistent_5y(df: pd.DataFrame, min_target: float = 0.15) -> MetricResult:
    """ROE ≥ 15% in at least 4 of the last 5 years."""
    df2 = df.sort_values('year').tail(5)
    roe_full = (df2['net_income'] / df2['shareholders_equity'].replace(0, pd.NA))
    roe = roe_full.dropna()
    if roe.empty:
        return MetricResult("ROE ≥ 15% (5y)", None, None, "no data")
    pass_ratio = (roe >= min_target).mean()
    details = "; ".join([f"{int(y)}: {v:.1%}" if pd.notna(v) else f"{int(y)}: n/a" for y, v in zip(df2['year'], roe_full)])
    return MetricResult(
        name="ROE ≥ 15% (5y)",
        value=float(pass_ratio),
        pass_flag=bool(pass_ratio >= 0.80),
        details=details
    )

def fcf_positive_5y(df: pd.DataFrame) -> MetricResult:
    """FCF positive for all last 5 years."""
    df2 = df.sort_values('year').tail(5)
    pos_ratio = (df2['free_cash_flow'] > 0).mean() if len(df2) > 0 else 0.0
    all_pos = bool(pos_ratio == 1.0)
    return MetricResult(
        name="FCF positive (5y)",
        value=float(pos_ratio),
        pass_flag=all_pos,
        details=f"positive_years={pos_ratio:.0%}"
    )

def scorecard(df: pd.DataFrame, years: int = 5) -> List[MetricResult]:
    checks = [
        equity_growth_5y(df),
        de_latest(df),
        profit_growth_5y(df),
        roe_consistent_5y(df, 0.15),
        fcf_positive_5y(df),
    ]
    return checks

def aggregate_score(results: List[MetricResult]) -> float:
    flags = [r.pass_flag for r in results if r.pass_flag is not None]
    return sum(flags) / len(flags) if flags else None
