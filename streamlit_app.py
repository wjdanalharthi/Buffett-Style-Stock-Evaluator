import os
import pandas as pd
import plotly.express as px
import streamlit as st

from buffett_eval.metrics import scorecard, aggregate_score, roe_series, de_series
from data_providers import get_fmp_fundamentals, get_fmp_quote_price
from parquet_store import load_fundamentals, upsert_fundamentals

st.set_page_config(page_title="Buffett Dashboard", page_icon="📈", layout="wide")

# -------------- Helpers --------------
def detect_currency(ticker: str) -> str:
    t = (ticker or '').upper()
    if t.endswith('.SR'): return 'SAR'
    if t.endswith('.L'):  return 'GBP'
    if t.endswith('.TO'): return 'CAD'
    if t.endswith('.HK'): return 'HKD'
    if t.endswith('.F') or t.endswith('.DE'): return 'EUR'
    return 'USD'

def fmt_money(amount, ccy: str):
    if amount is None or (isinstance(amount, float) and pd.isna(amount)): return 'n/a'
    try: return f"{ccy} {amount:,.2f}"
    except Exception: return f"{ccy} n/a"

def fundamentals_cached_first(ticker: str, uploaded_df: pd.DataFrame | None = None) -> pd.DataFrame:
    t = (ticker or '').upper()
    # 1) uploaded slice
    if uploaded_df is not None and 'ticker' in uploaded_df.columns:
        sl = uploaded_df[uploaded_df['ticker'].str.upper() == t].sort_values('year')
        if not sl.empty: return sl
    # 2) parquet
    parq = load_fundamentals(t)
    if parq is not None and not parq.empty:
        return parq.sort_values('year')
    # 3) API
    try:
        with st.spinner(f"Fetching fundamentals for {t}..."):
            tmp = get_fmp_fundamentals(t, years=10)
        if tmp is not None and not tmp.empty:
            upsert_fundamentals(tmp)
            return tmp.sort_values('year')
    except Exception as e:
        st.warning(f"Could not fetch fundamentals for {t}: {e}")
    return pd.DataFrame()

def last_eps(df: pd.DataFrame) -> float | None:
    d = df.sort_values('year')
    try:
        ni = d['net_income'].iloc[-1]
        so = d['shares_outstanding'].iloc[-1]
        if pd.notna(ni) and pd.notna(so) and so != 0:
            return float(ni / so)
    except Exception:
        pass
    return None

# -------------- Sidebar --------------
with st.sidebar:
    st.header("⚙️ Settings")
    api_key = st.text_input("FMP_API_KEY", os.getenv("FMP_API_KEY", ""), type="password")
    if api_key: os.environ["FMP_API_KEY"] = api_key
    st.markdown("---")
    uploaded_portfolio = st.file_uploader("Upload Portfolio Excel", type=["xlsx"])
    uploaded_fundamentals = st.file_uploader("(Optional) Upload Fundamentals CSV", type=["csv"], help="Will be used first")
    upl_df = None
    if uploaded_fundamentals is not None:
        try:
            upl_df = pd.read_csv(uploaded_fundamentals)
            st.caption("Fundamentals CSV loaded for this session (also saved to Parquet when used).")
        except Exception as e:
            st.error(f"Could not read fundamentals CSV: {e}")
    st.markdown("---")
    st.caption("Theme colors configured in .streamlit/config.toml")

st.title("📘 Buffett-Style Stock Dashboard")
st.write("Evaluate your holdings and tickers using Buffett-style heuristics.")

tab1, tab2, tab3, tab4 = st.tabs(["📂 Portfolio", "📊 Comparisons", "🔎 Stock Lookup", "📖 Methodology"])

# -------------- Portfolio --------------
def load_port():
    if uploaded_portfolio is not None:
        return pd.read_excel(uploaded_portfolio)
    st.info("Using sample portfolio from /data/sample_portfolio.xlsx (upload your file in the sidebar).")
    return pd.read_excel("data/sample_portfolio.xlsx")

with tab1:
    st.subheader("Your Portfolio")
    port = load_port()
    need = {"Ticker","Shares","AvgCost"}
    miss = need - set(port.columns)
    if miss:
        st.error(f"Missing required columns: {miss}")
        st.stop()

    # Fetch prices on demand
    unique_tickers = [t.upper() for t in port["Ticker"].unique()]
    price_map, fetched = {}, {}
    fetch_now = st.button("Fetch live prices", type="primary")
    if fetch_now:
        with st.spinner("Fetching live prices…"):
            for t in unique_tickers:
                p = get_fmp_quote_price(t)
                if p is not None:
                    price_map[t] = p; fetched[t] = "live"
                else:
                    price_map[t] = None; fetched[t] = "missing"
    else:
        for t in unique_tickers:
            price_map[t] = None; fetched[t] = "missing"
    st.caption("Click 'Fetch live prices' or enter manual overrides when missing.")

    override_cols = st.columns(min(3, max(1, len(unique_tickers))))
    for idx, t in enumerate(unique_tickers):
        if price_map[t] is None:
            with override_cols[idx % len(override_cols)]:
                manual = st.number_input(f"Price override: {t}", min_value=0.0, value=0.0, step=0.01, format="%.2f")
                if manual and manual > 0:
                    price_map[t] = manual; fetched[t] = "manual"

    port["LivePrice"] = port["Ticker"].str.upper().map(price_map)
    port["PriceSource"] = port["Ticker"].str.upper().map(fetched)
    port["Currency"] = port["Ticker"].apply(detect_currency)
    port = port.assign(MarketValue = port["Shares"] * port["LivePrice"], Cost = port["Shares"] * port["AvgCost"])
    port["PL"] = port["MarketValue"] - port["Cost"]
    total_mv = port["MarketValue"].sum(min_count=1)
    port["Weight"] = port["MarketValue"] / total_mv if (pd.notna(total_mv) and total_mv and total_mv > 0) else float("nan")

    port["LivePrice_fmt"] = port.apply(lambda r: fmt_money(r["LivePrice"], r["Currency"]), axis=1)
    port["MarketValue_fmt"] = port.apply(lambda r: fmt_money(r["MarketValue"], r["Currency"]), axis=1)
    port["Cost_fmt"] = port.apply(lambda r: fmt_money(r["Cost"], r["Currency"]), axis=1)
    port["PL_fmt"] = port.apply(lambda r: fmt_money(r["PL"], r["Currency"]), axis=1)

    order = ["Ticker","Company","Sector","Shares","AvgCost","LivePrice_fmt","PriceSource","MarketValue_fmt","Cost_fmt","PL_fmt","Weight","Currency"]
    show_cols = [c for c in order if c in port.columns]
    st.dataframe(port[show_cols], use_container_width=True, hide_index=True)

    # ---- Portfolio-wide Entry Checks (P/B, Net-Net, P/E relative) ----
    st.markdown("### Best Entry Checks (portfolio)")
    industry_pe_port = st.number_input("Industry P/E (used for all tickers here; refine per ticker in Stock Lookup)", min_value=0.0, value=20.0, step=0.1)
    rows = []
    for t in unique_tickers:
        price = price_map.get(t)
        if price is None and "LivePrice" in port.columns:
            try:
                price = float(port.loc[port["Ticker"].str.upper()==t, "LivePrice"].iloc[0])
            except Exception:
                price = None
        fdf = fundamentals_cached_first(t, upl_df)
        if fdf is None or fdf.empty:
            continue
        fdf5 = fdf.sort_values("year").tail(5)
        last = fdf5.iloc[-1]
        so = last.get("shares_outstanding")
        eq = last.get("shareholders_equity")
        ca = last.get("current_assets")
        tl = last.get("total_liabilities")
        ni = last.get("net_income")
        eps = (ni / so) if (pd.notna(so) and so) else None
        bvps = (eq / so) if (pd.notna(eq) and pd.notna(so) and so) else None
        ncavps = ((ca - tl) / so) if (pd.notna(ca) and pd.notna(tl) and pd.notna(so) and so) else None
        pb_th = 0.8 * bvps if bvps is not None else None
        nn_th = (2/3) * ncavps if ncavps is not None else None
        pe_company = (price / eps) if (price and eps and eps>0) else None
        pe_th = 0.70 * industry_pe_port if industry_pe_port and industry_pe_port>0 else None
        pb_pass = (price is not None and pb_th is not None and price <= pb_th)
        nn_pass = (price is not None and nn_th is not None and price <= nn_th)
        pe_pass = (pe_company is not None and pe_th is not None and pe_company <= pe_th)
        rows.append({
            "Ticker": t,
            "Price": price,
            "BVPS": bvps,
            "PB Threshold": pb_th,
            "P/B Pass": "✅" if pb_pass else ("❌" if (price is not None and pb_th is not None) else "—"),
            "NCAV/share": ncavps,
            "Net-Net Threshold": nn_th,
            "Net-Net Pass": "✅" if nn_pass else ("❌" if (price is not None and nn_th is not None) else "—"),
            "EPS": eps,
            "Industry P/E": industry_pe_port,
            "Company P/E": pe_company,
            "P/E Threshold": pe_th,
            "P/E Pass": "✅" if pe_pass else ("❌" if (pe_company is not None and pe_th is not None) else "—"),
            "Any PASS": "✅" if (pb_pass or nn_pass or pe_pass) else "❌"
        })
    if rows:
        df_checks = pd.DataFrame(rows)
        st.dataframe(df_checks, use_container_width=True, hide_index=True)
    else:
        st.info("No fundamentals found for any ticker. Upload a fundamentals CSV or set the API key and try again.")

        # Sector distribution (by Shares for display)
        if "Sector" in port.columns:
            try:
                st.plotly_chart(px.bar(port.groupby("Sector", as_index=False).agg({"Shares":"sum"}), x="Sector", y="Shares", title="Holdings by Sector"), use_container_width=True)
            except Exception:
                pass

        # Scorecards per holding (5y) based on fundamentals (cache-first)
        st.markdown("---")

# -------------- Comparisons --------------
with tab2:
    st.subheader("Comparisons (5y)")
    
    # ---- Buffett Scorecards moved from Portfolio ----
    st.markdown("### Buffett Scorecards (last 5y)")
    st.caption("Using your 5 rules over a 5-year window.")
    # Build list of tickers from the portfolio on this tab
    port_cmp = pd.read_excel(uploaded_portfolio) if uploaded_portfolio is not None else pd.read_excel("data/sample_portfolio.xlsx")
    tickers_cmp = [t.upper() for t in port_cmp["Ticker"].unique()]
    for tkr in tickers_cmp:
        st.markdown(f"**{tkr}**")
        fdf = fundamentals_cached_first(tkr, upl_df)
        if fdf is None or fdf.empty:
            st.warning("No fundamentals available. Upload CSV or set API key and try again.")
            continue
        fdf5 = fdf.sort_values("year").tail(5)
        results = scorecard(fdf5)
        colA, colB, colC, colD, colE = st.columns(5)
        cols = [colA, colB, colC, colD, colE]
        for c, r in zip(cols, results):
            with c:
                if r.pass_flag is True:
                    st.success(f"✅ {r.name}")
                elif r.pass_flag is False:
                    st.warning(f"❌ {r.name}")
                else:
                    st.info(f"ℹ️ {r.name}")
                st.caption(r.details or " ")
    st.markdown("---")
    st.caption("Charts use whatever fundamentals are available (uploaded CSV or Parquet cache).")
    port = pd.read_excel(uploaded_portfolio) if uploaded_portfolio is not None else pd.read_excel("data/sample_portfolio.xlsx")
    tickers = [t.upper() for t in port["Ticker"].unique()]

    # Load dfs
    dfs = {}
    for t in tickers:
        d = fundamentals_cached_first(t, upl_df)
        if d is not None and not d.empty:
            dfs[t] = d.sort_values("year").tail(5)

    if not dfs:
        st.info("No fundamentals available. Upload CSV or analyze tickers in Stock Lookup to populate the Parquet cache.")
    else:
        # ROE chart
        dd = []
        for t, d in dfs.items():
            for y, v in zip(d["year"], (d["net_income"] / d["shareholders_equity"].replace(0, pd.NA))*100):
                dd.append({"Ticker": t, "year": y, "ROE_%": float(v) if pd.notna(v) else None})
        fig = px.line(pd.DataFrame(dd), x="year", y="ROE_%", color="Ticker", title="Is Return on Equity consistently over 15%?")
        fig.add_hline(y=15, line_dash="dot")
        st.plotly_chart(fig, use_container_width=True)

        # D/E chart
        dd = []
        for t, d in dfs.items():
            for y, v in zip(d["year"], (d["total_debt"]/d["shareholders_equity"].replace(0, pd.NA))*100):
                dd.append({"Ticker": t, "year": y, "DE_%": float(v) if pd.notna(v) else None})
        fig = px.line(pd.DataFrame(dd), x="year", y="DE_%", color="Ticker", title="Is Debt to Equity below 50%?")
        fig.add_hline(y=50, line_dash="dot")
        st.plotly_chart(fig, use_container_width=True)

        # Equity growth
        dd = []
        for t, d in dfs.items():
            for y, v in zip(d["year"], d["shareholders_equity"]):
                dd.append({"Ticker": t, "year": y, "Equity": v})
        st.plotly_chart(px.line(pd.DataFrame(dd), x="year", y="Equity", color="Ticker", title="Is Equity growing overtime?"), use_container_width=True)

        # Profit growth
        dd = []
        for t, d in dfs.items():
            for y, v in zip(d["year"], d["net_income"]):
                dd.append({"Ticker": t, "year": y, "Profit": v})
        st.plotly_chart(px.line(pd.DataFrame(dd), x="year", y="Profit", color="Ticker", title="Is Profit growing overtime?"), use_container_width=True)

        # FCF
        dd = []
        for t, d in dfs.items():
            for y, v in zip(d["year"], d["free_cash_flow"]):
                dd.append({"Ticker": t, "year": y, "FCF": v})
        fig = px.line(pd.DataFrame(dd), x="year", y="FCF", color="Ticker", title="Is Free Cash Flow positive?")
        fig.add_hline(y=0, line_dash="dot")
        st.plotly_chart(fig, use_container_width=True)

with tab3:
    st.subheader("Lookup a Ticker")
    if "lookup_run" not in st.session_state: st.session_state["lookup_run"] = False
    if "lookup_target" not in st.session_state: st.session_state["lookup_target"] = "AAPL"

    tkr = st.text_input("Ticker", value=st.session_state.get("lookup_target","AAPL")).strip().upper()
    industry_pe = st.number_input("Industry P/E (for P/E relative rule)", min_value=0.0, value=20.0, step=0.1)
    analyze_clicked = st.button("Analyze", type="primary")
    if analyze_clicked:
        st.session_state["lookup_target"] = tkr
        st.session_state["lookup_run"] = True

    if st.session_state.get("lookup_run", False):
        fdf = fundamentals_cached_first(tkr, upl_df)
        if fdf is None or fdf.empty:
            st.warning("No fundamentals available. Upload CSV or set API key and try again.")
        else:
            fdf5 = fdf.sort_values("year").tail(5)

            # ---- Scorecard first ----
            st.markdown("### Buffett Scorecard (5y)")
            res = scorecard(fdf5)
            c1,c2,c3,c4,c5 = st.columns(5)
            for c, r in zip([c1,c2,c3,c4,c5], res):
                with c:
                    if r.pass_flag is True: st.success(f"✅ {r.name}")
                    elif r.pass_flag is False: st.warning(f"❌ {r.name}")
                    else: st.info(f"ℹ️ {r.name}")
                    st.caption(r.details)

            # ---- 2×2 charts + FCF ----
            st.markdown("### Trends (5y)")
            a1,a2 = st.columns(2)
            a3,a4 = st.columns(2)

            # ROE with 15% ref
            with a1:
                roe = roe_series(fdf5)
                fig = px.line(pd.DataFrame({"year": fdf5["year"], "ROE": roe*100}), x="year", y="ROE", title="Is Return on Equity consistently over 15%?")
                fig.add_hline(y=15, line_dash="dot")
                st.plotly_chart(fig, use_container_width=True)
            # D/E with 50% ref
            with a2:
                de = de_series(fdf5)
                fig = px.line(pd.DataFrame({"year": fdf5["year"], "DE": de*100}), x="year", y="DE", title="Is Debt to Equity below 50%?")
                fig.add_hline(y=50, line_dash="dot")
                st.plotly_chart(fig, use_container_width=True)
            # Equity growth
            with a3:
                fig = px.line(fdf5, x="year", y="shareholders_equity", title="Is Equity growing overtime?")
                st.plotly_chart(fig, use_container_width=True)
            # Profit growth
            with a4:
                fig = px.line(fdf5, x="year", y="net_income", title="Is Profit growing overtime?")
                st.plotly_chart(fig, use_container_width=True)

            # FCF positive
            fig = px.line(fdf5, x="year", y="free_cash_flow", title="Is Free Cash Flow positive?")
            fig.add_hline(y=0, line_dash="dot")
            st.plotly_chart(fig, use_container_width=True)

            # ---- Entry heuristics ----
            # ---- Entry heuristics ----
            st.markdown("### Best Entry Points")
            price = get_fmp_quote_price(tkr)
            if price is None:
                price = st.number_input("Manual current price", min_value=0.0, value=0.0, step=0.01)
            st.caption(f"Current price used: {price if price else 'n/a'}")
            
            last = fdf5.sort_values("year").iloc[-1]
            eps = (last["net_income"] / last["shares_outstanding"]) if (pd.notna(last["shares_outstanding"]) and last["shares_outstanding"]!=0) else None
            bvps = (last["shareholders_equity"] / last["shares_outstanding"]) if (pd.notna(last["shares_outstanding"]) and last["shares_outstanding"]!=0) else None
            ncavps = ((last["current_assets"] - last["total_liabilities"]) / last["shares_outstanding"]) if (pd.notna(last["shares_outstanding"]) and last["shares_outstanding"]!=0) else None
            
            # P/B
            st.write("**Price-to-Book (≤ 0.8×BVPS)**")
            pb_th = 0.8 * bvps if bvps is not None else None
            st.metric("BVPS", f"{bvps:,.2f}" if bvps is not None else "n/a")
            st.metric("Threshold", f"{pb_th:,.2f}" if pb_th is not None else "n/a")
            if (price is not None and pb_th is not None and price <= pb_th):
                st.success("✅ PASS")
            else:
                st.warning("❌ FAIL")
            
            # Net-Net
            st.write("**Graham Net-Net (≤ 2/3×NCAV/share)**")
            nn_th = (2/3) * ncavps if ncavps is not None else None
            st.metric("NCAV/share", f"{ncavps:,.2f}" if ncavps is not None else "n/a")
            st.metric("Threshold", f"{nn_th:,.2f}" if nn_th is not None else "n/a")
            if (price is not None and nn_th is not None and price <= nn_th):
                st.success("✅ PASS")
            else:
                st.warning("❌ FAIL")
            
            # P/E relative
            st.write("**P/E relative (≤ 0.70×Industry P/E)**")
            pe = (price / eps) if (price and eps and eps>0) else None
            pe_th = 0.70 * industry_pe if industry_pe and industry_pe>0 else None
            st.metric("Company P/E", f"{pe:,.2f}" if pe is not None else "n/a")
            st.metric("Threshold", f"{pe_th:,.2f}" if pe_th is not None else "n/a")
            if (pe is not None and pe_th is not None and pe <= pe_th):
                st.success("✅ PASS")
            else:
                st.warning("❌ FAIL")
            
        st.markdown("### Raw 5-year fundamentals")
        st.dataframe(fdf5, use_container_width=True, hide_index=True)

# -------------- Methodology --------------
with tab4:
    st.markdown("""
    ### Scorecard (5y)
    1) Equity (book value) growing  
    2) Debt-to-Equity < 50% (latest)  
    3) Profit (Net Income) growing  
    4) ROE ≥ 15% in ≥ 4/5 years  
    5) FCF positive every year

    ### Entry methods
    - **Graham Net-Net**: NCAV/share = (Current Assets − Total Liabilities)/Shares; buy if Price ≤ 2/3 × NCAV/share.  
      *Shortcoming*: Rare in modern markets; often distressed firms.
    - **Price-to-Book**: BVPS = Equity/Shares; buy if Price ≤ 0.8 × BVPS.  
      *Shortcoming*: Intangible-heavy businesses can look expensive vs book.
    - **P/E relative**: Buy if Company P/E ≤ 0.70 × Industry P/E.  
      *Shortcoming*: EPS can be cyclical or temporarily depressed; industry P/E varies by source.
    """)
