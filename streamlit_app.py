import os
import pandas as pd
import plotly.express as px
import streamlit as st

# --- Currency helpers ---
def detect_currency(ticker: str) -> str:
    t = (ticker or '').upper()
    if t.endswith('.SR'):
        return 'SAR'
    if t.endswith('.L'):
        return 'GBP'
    if t.endswith('.TO'):
        return 'CAD'
    if t.endswith('.HK'):
        return 'HKD'
    if t.endswith('.F') or t.endswith('.DE'):
        return 'EUR'
    return 'USD'

def fmt_money(amount, ccy: str):
    if amount is None:
        return 'n/a'
    try:
        return f"{ccy} {amount:,.2f}"
    except Exception:
        return f"{ccy} n/a"

from buffett_eval.metrics import scorecard, aggregate_score
from data_providers import get_fmp_fundamentals, get_fmp_quote_price

st.set_page_config(page_title="Buffett Dashboard", page_icon="📈", layout="wide")

# ---- Sidebar: Settings ----
with st.sidebar:
    st.header("⚙️ Settings")
    st.caption("Optional: set FMP API key for fundamentals & live price lookup.")
    api_key = st.text_input("FMP_API_KEY", os.getenv("FMP_API_KEY", ""), type="password", help="Financial Modeling Prep API key (stored only for this session)")
    if api_key:
        os.environ["FMP_API_KEY"] = api_key
    st.markdown("---")
    st.markdown("**Data Sources**") 
    uploaded_portfolio = st.file_uploader("Upload Portfolio Excel", type=["xlsx"]) 
    uploaded_fundamentals = st.file_uploader("(Optional) Upload Fundamentals CSV", type=["csv"], help="Schema in README") 
    st.markdown("---")
    st.caption("Theme colors configured in .streamlit/config.toml")

st.title("📘 Buffett-Style Stock Dashboard")
st.write("Evaluate your holdings and tickers using Buffett-style heuristics.")

tab1, tab2, tab3, tab4 = st.tabs(["📂 Portfolio", "🔎 Stock Lookup", "📊 Comparisons", "📚 Methodology"])

def load_portfolio():
    if uploaded_portfolio is not None:
        return pd.read_excel(uploaded_portfolio)
    st.info("Using sample portfolio from /data/sample_portfolio.xlsx (upload your file in the sidebar).")
    return pd.read_excel("data/sample_portfolio.xlsx")

def fundamentals_for_ticker(ticker: str, uploaded_df: pd.DataFrame | None = None):
    t = ticker.upper()
    if uploaded_df is not None:
        f = uploaded_df[uploaded_df["ticker"].str.upper() == t].sort_values("year")
        if not f.empty:
            return f
    sample = pd.read_csv("data/sample_fundamentals.csv")
    f = sample[sample["ticker"].str.upper() == t].sort_values("year")
    if not f.empty:
        return f
    return get_fmp_fundamentals(t, years=10)

# ---------------- Portfolio Tab ----------------
with tab1:
    st.subheader("Your Portfolio")
    port = load_portfolio()
    required_cols = {"Ticker","Shares","AvgCost"}
    missing = required_cols - set(port.columns)
    if missing:
        st.error(f"Missing required columns: {missing}")
        st.stop()

    # Fundamentals source
    fund = pd.read_csv(uploaded_fundamentals) if uploaded_fundamentals is not None else pd.read_csv("data/sample_fundamentals.csv")

    # Live prices/overrides
    unique_tickers = [t.upper() for t in port["Ticker"].unique()]
    price_map, fetched = {}, {}
    for t in unique_tickers:
        p = get_fmp_quote_price(t)
        if p is not None:
            price_map[t] = p; fetched[t] = "live"
        else:
            price_map[t] = None; fetched[t] = "missing"
    st.caption("Prices are fetched on-demand from FMP when API key is set. You can override missing prices below.")
    override_cols = st.columns(min(3, len(unique_tickers))) if len(unique_tickers) > 0 else []
    for idx, t in enumerate(unique_tickers):
        if price_map[t] is None:
            with override_cols[idx % max(1, len(override_cols))]:
                manual = st.number_input(f"Price override: {t}", min_value=0.0, value=0.0, step=0.01, format="%.2f")
                if manual and manual > 0:
                    price_map[t] = manual; fetched[t] = "manual"

    port["LivePrice"] = port["Ticker"].str.upper().map(price_map)
    port["PriceSource"] = port["Ticker"].str.upper().map(fetched)
    port["Currency"] = port["Ticker"].apply(detect_currency)
    port = port.assign(MarketValue = port["Shares"] * port["LivePrice"], Cost = port["Shares"] * port["AvgCost"])
    port["PL"] = port["MarketValue"] - port["Cost"]
    # Safe weight calc: avoid div-by-zero when there are no prices yet
    total_mv = port["MarketValue"].sum(min_count=1)
    if (pd.isna(total_mv)) or (float(total_mv) <= 0):
        port["Weight"] = float("nan")
    else:
        port["Weight"] = port["MarketValue"] / total_mv
    # Build formatted display columns
    port["LivePrice_fmt"] = port.apply(lambda r: fmt_money(r["LivePrice"], r["Currency"]), axis=1)
    port["MarketValue_fmt"] = port.apply(lambda r: fmt_money(r["MarketValue"], r["Currency"]), axis=1)
    port["Cost_fmt"] = port.apply(lambda r: fmt_money(r["Cost"], r["Currency"]), axis=1)
    port["PL_fmt"] = port.apply(lambda r: fmt_money(r["PL"], r["Currency"]), axis=1)

    c1, c2 = st.columns([2,1], gap="large")
    with c1:
        display_cols = [c for c in port.columns if c not in ["LivePrice","MarketValue","Cost","PL"]]
        # Show formatted monetary columns
        order = [c for c in display_cols if c not in ["LivePrice_fmt","MarketValue_fmt","Cost_fmt","PL_fmt"]] + ["LivePrice_fmt","MarketValue_fmt","Cost_fmt","PL_fmt"]
        st.dataframe(port[order], use_container_width=True, hide_index=True)
        unique_ccy = sorted(port["Currency"].dropna().unique().tolist())
        total_mv = port["MarketValue"].sum(min_count=1)
        if len(unique_ccy) == 1 and pd.notna(total_mv) and float(total_mv) > 0:
            fig_alloc = px.pie(port.dropna(subset=["MarketValue"]), names="Ticker", values="MarketValue", hole=0.4, title=f"Allocation by Ticker ({unique_ccy[0]})")
            st.plotly_chart(fig_alloc, use_container_width=True)
        elif len(unique_ccy) == 1:
            st.info("Add live/override prices to see allocation pie.")
        else:
            st.info("Allocation pie disabled for mixed currencies (needs FX).")
        if "Sector" in port.columns:
            fig_sector = px.bar(port.groupby("Sector", as_index=False)["MarketValue"].sum(), x="Sector", y="MarketValue", title="Market Value by Sector")
            st.plotly_chart(fig_sector, use_container_width=True)
    with c2:
        unique_ccy = sorted(port["Currency"].dropna().unique().tolist())
        total_mv = port["MarketValue"].sum(min_count=1)
        if len(unique_ccy) == 1 and pd.notna(total_mv) and float(total_mv) > 0:
            st.metric("Total Market Value", fmt_money(total_mv, unique_ccy[0]))
            st.metric("Unrealized P/L", fmt_money(port["PL"].sum(), unique_ccy[0]))
        elif len(unique_ccy) == 1:
            st.metric("Total Market Value", "—")
            st.metric("Unrealized P/L", "—")
            st.caption("Add live/override prices to see totals.")
        else:
            st.metric("Total Market Value", "—")
            st.metric("Unrealized P/L", "—")
            st.caption("Totals disabled for mixed currencies. (Set a base currency & FX to enable)")
        st.metric("# Holdings", f"{len(port)}")

    st.markdown("---")
    st.subheader("Buffett Scorecards (last 5y)")
    st.caption("Using your 5 rules over a 5-year window.")

    for tkr in port["Ticker"].unique():
        st.markdown(f"### {tkr}")
        fdf = fund[fund["ticker"].str.upper() == tkr.upper()].sort_values("year")
        if fdf.empty:
            fdf = get_fmp_fundamentals(tkr, years=10) or pd.DataFrame()
        if fdf.empty:
            st.warning("No fundamentals found. Upload CSV or set API key.")
            continue

        results = scorecard(fdf, years=5)
        score = aggregate_score(results)
        cols = st.columns(3)
        cols[0].markdown(f"**Score:** {score:.0%}" if score is not None else "**Score:** n/a")
        cols[1].markdown(f"**Last Year:** {int(fdf['year'].max())}")
        cols[2].markdown(f"**Data Rows:** {len(fdf)}")
        res_df = pd.DataFrame([{"Check": r.name, "Value": r.value, "Pass": r.pass_flag, "Details": r.details} for r in results])
        st.dataframe(res_df, hide_index=True, use_container_width=True)

# ---------------- Lookup Tab ----------------
with tab2:
    st.subheader("Lookup a Ticker")
    if "lookup_run" not in st.session_state:
        st.session_state["lookup_run"] = False
    if "lookup_target" not in st.session_state:
        st.session_state["lookup_target"] = "AAPL"
    # Use a keyed input so it persists across reruns
    tkr_input = st.text_input("Ticker", key="lookup_input", value=st.session_state.get("lookup_target", "AAPL"))
    tkr_input = (tkr_input or "").strip().upper()
    analyze_clicked = st.button("Analyze", type="primary", key="lookup_analyze")
    if analyze_clicked:
        st.session_state["lookup_target"] = tkr_input
        st.session_state["lookup_run"] = True
    if st.session_state.get("lookup_run", False):
        tkr = st.session_state.get("lookup_target", tkr_input)

        fdf = None
        if uploaded_fundamentals is not None:
            tmp = pd.read_csv(uploaded_fundamentals); fdf = tmp[tmp["ticker"].str.upper() == tkr].sort_values("year")
        if fdf is None or fdf.empty:
            tmp = pd.read_csv("data/sample_fundamentals.csv"); fdf = tmp[tmp["ticker"].str.upper() == tkr].sort_values("year")
        if fdf is None or fdf.empty:
            fdf = get_fmp_fundamentals(tkr, years=10)

        if fdf is None or fdf.empty:
            st.error("Couldn't find fundamentals. Upload CSV or set FMP_API_KEY.")
        else:
            st.success(f"Found {len(fdf)} rows for {tkr}. Last year: {int(fdf['year'].max())}")
            # --- Scorecard at top ---
            results = scorecard(fdf, years=5)
            st.markdown("### Buffett Scorecard (5y) — Your 5 Rules")
            st.metric("Score", f"{aggregate_score(results):.0%}")
            res_df = pd.DataFrame([{"Check": r.name, "Value": r.value, "Pass": r.pass_flag, "Details": r.details} for r in results])
            st.dataframe(res_df, hide_index=True, use_container_width=True)

            # Price for P/E (optional, context only)
            fetched_price = get_fmp_quote_price(tkr)
            price_input = st.number_input("Assumed Price (if empty, live price used when available)", value=float(fetched_price) if fetched_price else 0.0, step=0.01, format="%.2f")
            price = price_input if price_input > 0 else fetched_price

            # --- Best Entry Points (Net-Net & P/B) ---
            st.markdown("### 💡 Best Entry Points")
            st.caption("Conservative buy signals from Graham & Buffett-style balance-sheet checks.")

            # Compute BVPS
            try:
                last_row = fdf.sort_values("year").iloc[-1]
                equity = float(last_row.get("shareholders_equity")) if last_row.get("shareholders_equity") is not None else None
                shares = float(last_row.get("shares_outstanding")) if last_row.get("shares_outstanding") is not None else None
            except Exception:
                equity, shares = None, None

            bvps = (equity / shares) if (equity is not None and shares not in (None, 0)) else None
            pb_ratio = (price / bvps) if (price is not None and bvps not in (None, 0)) else None
            pb_pass = (pb_ratio is not None) and (pb_ratio <= 0.80)

            # Compute NCAV per share if current assets & total liabilities available
            ca = float(last_row.get("current_assets")) if ('current_assets' in fdf.columns and last_row.get("current_assets") is not None) else None
            tl = float(last_row.get("total_liabilities")) if ('total_liabilities' in fdf.columns and last_row.get("total_liabilities") is not None) else None
            ncav = (ca - tl) if (ca is not None and tl is not None) else None
            ncavps = (ncav / shares) if (ncav is not None and shares not in (None, 0)) else None
            netnet_threshold = (2/3) * ncavps if ncavps is not None else None
            netnet_pass = (price is not None and netnet_threshold is not None and price <= netnet_threshold)

            cA, cB = st.columns(2)
            with cA:
                st.markdown("**P/B Entry** — *Buy if Price ≤ 0.8 × BVPS*")
                t_ccy = detect_currency(tkr)
                st.metric("Price", fmt_money(price, t_ccy) if price is not None else "n/a")
                st.metric("BVPS", fmt_money(bvps, t_ccy) if bvps is not None else "n/a")
                st.metric("Price / BVPS", f"{pb_ratio:.2f}" if pb_ratio is not None else "n/a")
                if pb_pass:
                    st.success("✅ PASS — Price ≤ 0.8 × BVPS")
                else:
                    st.warning("❌ FAIL — Needs ≤ 0.8× BVPS")

                st.caption("**Why it works:** Buy quality below book value (equity). **Watchouts:** Intangible-heavy firms and buybacks can distort book value; negative equity ⇒ n/a.")

            with cB:
                st.markdown("**Graham Net-Net** — *Buy if Price ≤ ⅔ × NCAV/share*")
                t_ccy = detect_currency(tkr)
                st.metric("Price", fmt_money(price, t_ccy) if price is not None else "n/a")
                st.metric("NCAV/share", f"${ncavps:,.2f}" if ncavps is not None else "n/a")
                st.metric("⅔ × NCAV/share", f"${netnet_threshold:,.2f}" if netnet_threshold is not None else "n/a")
                if netnet_pass:
                    st.success("✅ PASS — Price ≤ ⅔ × NCAV/share")
                else:
                    if 'current_assets' in fdf.columns and 'total_liabilities' in fdf.columns:
                        st.warning("❌ FAIL — Above ⅔ × NCAV/share (or NCAV negative)")
                    else:
                        st.info("ℹ️ NCAV requires **current_assets** and **total_liabilities**. Provide FMP_API_KEY or include these columns in your fundamentals CSV.")
            st.markdown("---")

            # --- P/E Entry (relative to industry or 5y median) ---
            st.markdown("### 💡 P/E Entry (Relative)")
            st.caption("Buy when **Current P/E ≤ 0.70 × Reference P/E** (30% margin of safety). Reference = Industry average P/E (preferred) or Company 5-year median P/E.")

            # EPS (LFY) and Current P/E
            eps_lfy = None
            try:
                eps_lfy = float(fdf["net_income"].iloc[-1] / fdf["shares_outstanding"].iloc[-1])
            except Exception:
                eps_lfy = None
            current_pe = (price / eps_lfy) if (price is not None and eps_lfy not in (None, 0)) else None

            # Reference P/E: user-provided industry P/E (preferred)
            col_industry, col_fallback = st.columns([1,1])
            with col_industry:
                industry_pe = st.number_input("Industry average P/E (optional)", min_value=0.0, value=0.0, step=0.1, format="%.1f")
                ref_pe = industry_pe if industry_pe > 0 else None
            with col_fallback:
                ref_pe_median = None
                try:
                    from data_providers import get_fmp_5y_median_pe
                    ref_pe_median = get_fmp_5y_median_pe(tkr)
                except Exception:
                    ref_pe_median = None
                st.caption(f"5-year median P/E (FMP): {ref_pe_median:.1f}" if ref_pe_median is not None else "5-year median P/E: n/a (set FMP_API_KEY)")

            reference_pe = ref_pe if ref_pe is not None else ref_pe_median
            required_pe = (0.70 * reference_pe) if reference_pe is not None else None
            price_threshold = (eps_lfy * required_pe) if (eps_lfy is not None and required_pe is not None) else None
            pe_pass = (price is not None and price_threshold is not None and price <= price_threshold)

            c1, c2, c3 = st.columns(3)
            c1.metric("Current P/E", f"{current_pe:.1f}" if current_pe is not None else "n/a")
            c2.metric("Reference P/E", f"{reference_pe:.1f}" if reference_pe is not None else "n/a")
            c3.metric("Required P/E (−30%)", f"{required_pe:.1f}" if required_pe is not None else "n/a")

            c4, c5 = st.columns(2)
            c4.metric("EPS (LFY)", f"{eps_lfy:.2f}" if eps_lfy is not None else "n/a")
            c5.metric("Price Threshold", fmt_money(price_threshold, detect_currency(tkr)) if price_threshold is not None else "n/a")

            if pe_pass:
                st.success("✅ PASS — Price ≤ EPS × (0.70 × Reference P/E)")
            else:
                st.warning("❌ FAIL — Needs to be below threshold (or provide Industry P/E / set API key)")
            st.markdown("---")

            # --- Window control + 2x2 grid with PASS/FAIL badges ---
            lookup_window = st.slider("Years to show (most recent)", 4, 10, 5, key="lookup_window")
            dfw = fdf.sort_values("year").tail(lookup_window)

            def badge(pass_bool: bool, text: str):
                if pass_bool: st.success(f"✅ PASS — {text}")
                else: st.error(f"❌ FAIL — {text}")

            # ROE
            roe_pct = (dfw["net_income"] / dfw["shareholders_equity"]).replace([float("inf")], None) * 100.0
            roe_pass_ratio = (roe_pct >= 15).mean() if roe_pct.notna().any() else 0
            roe_pass = roe_pass_ratio >= 0.80

            # D/E
            de_pct = (dfw["total_debt"] / dfw["shareholders_equity"]).replace([float("inf")], None) * 100.0
            latest_de = float(de_pct.dropna().iloc[-1]) if de_pct.dropna().shape[0] else None
            de_pass = (latest_de is not None) and (latest_de <= 50)

            # Equity trend
            eq_series = dfw["shareholders_equity"]
            eq_pass = (len(eq_series) > 1) and (eq_series.iloc[-1] > eq_series.iloc[0])

            # Profit trend
            ni_series = dfw["net_income"]
            ni_pass = (len(ni_series) > 1) and (ni_series.iloc[-1] > ni_series.iloc[0])

            # FCF positive all years
            fcf_series = dfw["free_cash_flow"]
            fcf_pass = (fcf_series > 0).mean() == 1.0 if fcf_series.notna().any() else False

            g1c1, g1c2 = st.columns(2)
            g2c1, g2c2 = st.columns(2)

            with g1c1:
                badge(roe_pass, f"ROE ≥ 15% in {roe_pass_ratio:.0%} of last {lookup_window} years")
                fig_roe_q = px.line(dfw.assign(ROE_pct=roe_pct), x="year", y="ROE_pct", markers=True, title="Is Return on Equity consistently over 15%?")
                fig_roe_q.update_layout(yaxis_title="ROE (%)", xaxis_title="Year"); fig_roe_q.add_hline(y=15, line_dash="dash")
                st.plotly_chart(fig_roe_q, use_container_width=True)

            with g1c2:
                badge(de_pass, f"Latest D/E = {latest_de:.1f}%" if latest_de is not None else "Latest D/E = n/a")
                fig_de_q = px.line(dfw.assign(Debt_to_Equity_pct=de_pct), x="year", y="Debt_to_Equity_pct", markers=True, title="Is Debt to Equity below 50%?")
                fig_de_q.update_layout(yaxis_title="Debt/Equity (%)", xaxis_title="Year"); fig_de_q.add_hline(y=50, line_dash="dash")
                st.plotly_chart(fig_de_q, use_container_width=True)

            with g2c1:
                badge(eq_pass, "Equity increased vs 5y start")
                fig_eq_q = px.line(dfw, x="year", y="shareholders_equity", markers=True, title="Is Equity growing overtime?")
                fig_eq_q.update_layout(yaxis_title="Shareholders' Equity", xaxis_title="Year"); st.plotly_chart(fig_eq_q, use_container_width=True)

            with g2c2:
                badge(ni_pass, "Profit increased vs 5y start")
                fig_profit_q = px.line(dfw, x="year", y="net_income", markers=True, title="Is Profit growing overtime?")
                fig_profit_q.update_layout(yaxis_title="Net Income", xaxis_title="Year"); st.plotly_chart(fig_profit_q, use_container_width=True)

            st.info("Free Cash Flow check uses last 5 years entirely positive to pass.")
            fig_fcf_q = px.line(dfw, x="year", y="free_cash_flow", markers=True, title="Is Free Cash Flow positive?")
            fig_fcf_q.update_layout(yaxis_title="Free Cash Flow", xaxis_title="Year"); fig_fcf_q.add_hline(y=0, line_dash="dash")
            st.plotly_chart(fig_fcf_q, use_container_width=True)
            # --- Raw fundamentals (last 5 fiscal years) ---
            df5 = fdf.sort_values("year").tail(5)
            st.markdown("### Last 5 years (raw fundamentals)")
            st.dataframe(df5, use_container_width=True, hide_index=True)


# ---------------- Comparisons Tab ----------------
with tab3:
    st.subheader("Compare Buffett Metrics Across Holdings — 5-Year View")

    # Load portfolio & fundamentals
    port = load_portfolio()
    fund_all = pd.read_csv(uploaded_fundamentals) if uploaded_fundamentals is not None else pd.read_csv("data/sample_fundamentals.csv")

    # Combine fundamentals for portfolio tickers
    tickers = sorted([t.upper() for t in port["Ticker"].unique()])
    combined = []
    for t in tickers:
        fdf = fund_all[fund_all["ticker"].str.upper() == t].sort_values("year")
        if fdf.empty:
            fdf = get_fmp_fundamentals(t, years=10) or pd.DataFrame()
        if not fdf.empty:
            fdf = fdf.assign(ticker=t)
            combined.append(fdf)

    if not combined:
        st.warning("No fundamentals found for your holdings.")
    else:
        allfund = pd.concat(combined, ignore_index=True).sort_values(["ticker","year"])

        # Limit to last 5 fiscal years per ticker
        df5 = allfund.groupby("ticker").tail(5).copy()

        # 1) ROE — Is Return on Equity consistently over 15%?
        df5["roe_pct"] = (df5["net_income"] / df5["shareholders_equity"]).replace([float("inf")], None) * 100.0
        fig_roe = px.line(df5, x="year", y="roe_pct", color="ticker", markers=True, title="Is Return on Equity consistently over 15%?")
        fig_roe.update_layout(yaxis_title="ROE (%)", xaxis_title="Year")
        fig_roe.add_hline(y=15, line_dash="dash")
        st.plotly_chart(fig_roe, use_container_width=True)

        # 2) Debt-to-Equity — Is Debt to Equity below 50%?
        df5["de_pct"] = (df5["total_debt"] / df5["shareholders_equity"]).replace([float("inf")], None) * 100.0
        fig_de = px.line(df5, x="year", y="de_pct", color="ticker", markers=True, title="Is Debt to Equity below 50%?")
        fig_de.update_layout(yaxis_title="Debt/Equity (%)", xaxis_title="Year")
        fig_de.add_hline(y=50, line_dash="dash")
        st.plotly_chart(fig_de, use_container_width=True)

        # 3) Equity — Is Equity growing overtime?
        fig_eq = px.line(df5, x="year", y="shareholders_equity", color="ticker", markers=True, title="Is Equity growing overtime?")
        fig_eq.update_layout(yaxis_title="Shareholders' Equity", xaxis_title="Year")
        st.plotly_chart(fig_eq, use_container_width=True)

        # 4) Profit — Is Profit growing overtime?
        fig_profit = px.line(df5, x="year", y="net_income", color="ticker", markers=True, title="Is Profit growing overtime?")
        fig_profit.update_layout(yaxis_title="Net Income", xaxis_title="Year")
        st.plotly_chart(fig_profit, use_container_width=True)

        # 5) Free Cash Flow — Is Free Cash Flow positive? (show 0 reference)
        fig_fcf = px.line(df5, x="year", y="free_cash_flow", color="ticker", markers=True, title="Is Free Cash Flow positive?")
        fig_fcf.update_layout(yaxis_title="Free Cash Flow", xaxis_title="Year")
        fig_fcf.add_hline(y=0, line_dash="dash")
        st.plotly_chart(fig_fcf, use_container_width=True)
# ---------------- Methodology Tab ----------------
with tab4:
    st.subheader("Heuristics Used (Editable)")
    st.markdown("""
**Best Entry Points (Valuation — not part of quality score):**

- **P/B Entry:** Buy when **Price ≤ 0.8 × BVPS**. BVPS = Shareholders’ Equity / Shares Outstanding.
  - **Pros:** Simple, robust for asset-heavy/financial firms. 
  - **Shortcomings:** Intangible-heavy firms (tech/brands) can look expensive on P/B; buybacks reduce book value; negative equity ⇒ rule n/a.
- **Graham Net-Net (NCAV):** Buy when **Price ≤ ⅔ × NCAV/share**. NCAV = Current Assets − Total Liabilities.
  - **Pros:** Very conservative; strong downside protection if liquidation value is real.
  - **Shortcomings:** Rare in modern markets; asset quality/catalysts matter; may be value traps; requires **current_assets** and **total_liabilities** data.

---

**Checks implemented (5-year window):**
- **Equity (book value) growing** (CAGR > 0)
- **Debt-to-Equity < 50%** (latest)
- **Profit (Net Income) growing** (CAGR > 0)
- **ROE ≥ 15%** in at least **4 of 5** years
- **Free Cash Flow positive** in **all 5** years

**Valuation shown (not part of score):**
- **EPS (LFY)** = last year's NI / shares outstanding
- **P/E (LFY)** = price / EPS(LFY)

> This is **not** investment advice—always verify with official filings.
    """)
