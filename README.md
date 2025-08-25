# Buffett-Style Stock Dashboard

An implementation of the book "Warren Buffett and the Interpretation of Financial Statements: The Search for the Company with a Durable Competitive Advantage". 
This app evaluate stocks using a simplified Warren Buffett methodology over a 5‑year window.  
It is built with **Streamlit**, uses **on-demand live prices**, and persists fundamentals in **Parquet files** (no SQL, no Streamlit caches).

## ✨ Features
- **Portfolio view** with manual or on-demand live prices (via Financial Modeling Prep).
- **Stock Lookup** with a 5-rule Buffett-style scorecard and **Best Entry Points** (P/B, Graham Net-Net, P/E relative).
- **Comparisons**: multi-line charts across holdings (ROE ≥ 15%, D/E ≤ 50%, Equity growth, Profit growth, FCF ≥ 0).
- **Parquet persistence**: `.cache/fundamentals/<TICKER>.parquet` for fast repeat lookups.
- **Currency-aware labels** for common suffixes (e.g., `.SR` → SAR).

> **Note**: This tool is for educational purposes and not investment advice.

## 🚀 Quickstart

### 1) Requirements
- Python **3.10+** recommended

### 2) Create a virtual environment & install
```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 3) Provide your FMP API key
You can paste it in the sidebar input when the app runs, or set it in your shell:
```bash
export FMP_API_KEY=your_key_here      # PowerShell: $Env:FMP_API_KEY="your_key_here"
```
Alternatively, for local dev you can store it in **.streamlit/secrets.toml** (this file is gitignored):
```toml
# .streamlit/secrets.toml
FMP_API_KEY = "your_key_here"
```

### 4) Run
```bash
streamlit run streamlit_app.py
```

## 📂 Project structure (key files)
```
.
├── streamlit_app.py               # Main app
├── data_providers.py              # HTTP fetchers (with timeout & retries)
├── parquet_store.py               # Parquet persistence (load/upsert per ticker)
├── buffett_eval/
│   ├── __init__.py
│   └── metrics.py                 # 5-rule scorecard logic
├── data/
│   ├── sample_portfolio.xlsx      # Example portfolio (no live prices)
│   └── sample_fundamentals.csv    # Example fundamentals
├── .streamlit/
│   └── config.toml                # Theme
├── requirements.txt
├── README.md
└── .gitignore
```

## 🧾 Data formats

### Portfolio Excel (minimal columns)
| Column  | Type   | Notes                      |
|--------:|:-------|:---------------------------|
| Ticker  | string | e.g., `AAPL`, `MSFT`, `2222.SR` |
| Shares  | number |                            |
| AvgCost | number | average cost per share     |

Optional: `Company`, `Sector`, etc.

### Fundamentals CSV (per row per **year**)
Required columns (case-sensitive):
```
ticker, company, year, revenue, net_income, shareholders_equity,
total_debt, shares_outstanding, free_cash_flow, current_assets, total_liabilities
```

## 🧠 Buffett-style rules (5y window)
- **Equity growing** (CAGR > 0)
- **Debt-to-Equity < 50%** (latest year)
- **Profit (Net Income) growing** (CAGR > 0)
- **ROE ≥ 15%** in ≥ 4 of 5 years
- **FCF positive** in all 5 years

**Best Entry Points (not in score):**
- **P/B**: buy if **Price ≤ 0.8 × BVPS** (BVPS = Equity / Shares).
- **Graham Net-Net**: buy if **Price ≤ ⅔ × NCAV/share** (NCAV = Current Assets − Total Liabilities).
- **P/E (relative)**: buy if **Current P/E ≤ 0.70 × Reference P/E** (industry preferred; fallback to company 5y median P/E).

## 💾 Caching
- Fundamentals are stored under `.cache/fundamentals/<TICKER>.parquet`.
- The app loads from **uploaded CSV**, then **Parquet cache**, then **API** (and saves back to Parquet).

## 🌍 Currencies
Basic heuristics: `.SR`→SAR, `.L`→GBP, `.TO`→CAD, `.HK`→HKD, `.F`/`.DE`→EUR; else default USD.  
You can extend `detect_currency()` in `streamlit_app.py` for more exchanges.

## 🛠 Troubleshooting
- **No data / Missing NCAV**: Ensure your fundamentals CSV includes `current_assets` & `total_liabilities`, or supply an FMP key.
- **Rate limits / timeouts**: The app uses timeouts and light retries; try again or throttle lookups.
- **Mixed currencies**: Portfolio totals are disabled for mixed-ccy portfolios (FX conversion not yet implemented).
- **Charts show NaN/inf**: Usually equity is zero/negative; the app guards divisions, but verify your data.

## 🔧 Customization
- Change thresholds (ROE 15%, D/E 50%) in `metrics.py` and chart reference lines in `streamlit_app.py`.
- Add a **Cache Manager** panel to list/delete Parquet files if desired.

## 📄 License
Choose what fits your needs (MIT/Apache-2.0/BSD-3-Clause).

— Generated on 2025-08-24
