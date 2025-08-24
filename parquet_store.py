import os, re
import pandas as pd

CACHE_DIR = os.getenv("CACHE_DIR", ".cache")
FUND_DIR = os.path.join(CACHE_DIR, "fundamentals")
os.makedirs(FUND_DIR, exist_ok=True)

SAFE = re.compile(r"[^A-Z0-9._-]")

def _file_for(ticker: str) -> str:
    t = (ticker or "").upper()
    t = SAFE.sub("_", t)
    return os.path.join(FUND_DIR, f"{t}.parquet")

def load_fundamentals(ticker: str) -> pd.DataFrame:
    path = _file_for(ticker)
    if not os.path.exists(path):
        return pd.DataFrame()
    try:
        return pd.read_parquet(path)
    except Exception:
        return pd.DataFrame()

def upsert_fundamentals(df: pd.DataFrame) -> None:
    if df is None or df.empty:
        return
    required = ["ticker","year","revenue","net_income","shareholders_equity","total_debt",
                "shares_outstanding","free_cash_flow","current_assets","total_liabilities","company"]
    out = df.copy()
    for col in required:
        if col not in out.columns:
            out[col] = None
    out["ticker"] = out["ticker"].astype(str).str.upper()
    for tkr, chunk in out.groupby(out["ticker"]):
        path = _file_for(tkr)
        if os.path.exists(path):
            try:
                old = pd.read_parquet(path)
            except Exception:
                old = pd.DataFrame(columns=required)
            if not old.empty:
                old = old[~old["year"].isin(chunk["year"])]
                merged = pd.concat([old, chunk], ignore_index=True)
            else:
                merged = chunk
        else:
            merged = chunk
        merged = merged.sort_values("year")
        merged.to_parquet(path, index=False)
