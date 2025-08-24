import os, requests, pandas as pd
from typing import Optional, Dict
from parquet_store import load_fundamentals, upsert_fundamentals



def _get_json(url: str, timeout: int = 12, retries: int = 2, backoff: float = 0.6):
    import requests, time
    last_err = None
    for i in range(retries + 1):
        try:
            r = requests.get(url, timeout=timeout)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            last_err = e
            if i < retries:
                time.sleep(backoff * (2 ** i))
            else:
                raise e
def load_local_fundamentals(csv_path: str) -> pd.DataFrame:
    return pd.read_csv(csv_path)

def get_fmp_fundamentals(ticker: str, years: int = 10) -> Optional[pd.DataFrame]:
    api_key = os.getenv("FMP_API_KEY")
    if not api_key:
        return None
    base = "https://financialmodelingprep.com/api/v3"
    income = _get_json(f"{base}/income-statement/{ticker}?period=annual&limit={years}&apikey={api_key}")
    balance = _get_json(f"{base}/balance-sheet-statement/{ticker}?period=annual&limit={years}&apikey={api_key}")
    cash = _get_json(f"{base}/cash-flow-statement/{ticker}?period=annual&limit={years}&apikey={api_key}")

    if not (isinstance(income, list) and isinstance(balance, list) and isinstance(cash, list)):
        return None

    rows = []
    for i in range(min(len(income), len(balance), len(cash))):
        y = int(income[i]['calendarYear'])
        rows.append({
            'ticker': ticker.upper(),
            'company': income[i].get('symbol', ticker.upper()),
            'year': y,
            'revenue': income[i].get('revenue'),
            'net_income': income[i].get('netIncome'),
            'shareholders_equity': balance[i].get('totalStockholdersEquity'),
            'current_assets': balance[i].get('totalCurrentAssets'),
            'total_liabilities': balance[i].get('totalLiabilities'),
            'total_debt': (balance[i].get('shortTermDebt', 0) or 0) + (balance[i].get('longTermDebt', 0) or 0),
            'shares_outstanding': income[i].get('weightedAverageShsOut'),
            'free_cash_flow': cash[i].get('freeCashFlow')
        })
    df = pd.DataFrame(rows).sort_values('year')
    return df if not df.empty else None

def get_fmp_quote_price(ticker: str) -> Optional[float]:
    api_key = os.getenv("FMP_API_KEY")
    if not api_key:
        return None
    base = "https://financialmodelingprep.com/api/v3"
    q = _get_json(f"{base}/quote/{ticker.upper()}?apikey={api_key}")
    try:
        return float(q[0]["price"])
    except Exception:
        return None


def get_fmp_historical_pe(ticker: str, years: int = 10) -> Optional[list[float]]:
    """Fetch annual historical P/E ratios from FMP /ratios endpoint."""
    api_key = os.getenv("FMP_API_KEY")
    if not api_key:
        return None
    base = "https://financialmodelingprep.com/api/v3"
    try:
        ratios = _get_json(f"{base}/ratios/{ticker.upper()}?period=annual&limit={years}&apikey={api_key}")
        if not isinstance(ratios, list):
            return None
        pe_vals = []
        for r in ratios:
            val = r.get("priceEarningsRatio")
            if val is not None:
                try:
                    pe_vals.append(float(val))
                except Exception:
                    pass
        return pe_vals if pe_vals else None
    except Exception:
        return None

def get_fmp_5y_median_pe(ticker: str) -> Optional[float]:
    vals = get_fmp_historical_pe(ticker, years=5)
    if not vals:
        return None
    s = pd.Series(vals).dropna()
    return float(s.median()) if not s.empty else None
