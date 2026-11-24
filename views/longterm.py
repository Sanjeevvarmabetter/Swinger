import streamlit as st

from tradingos import longterm as lt
from tradingos.ui import components as ui

ui.render_top_bar(show_refresh=False)

st.markdown("## Long-Term Investment Portfolio")
ui.show_flash()

st.markdown(
    f'<div style="background:rgba(56,189,248,0.08);border:1px solid rgba(56,189,248,0.3);border-radius:6px;padding:12px 16px;margin-bottom:12px;">'
    f'  <div style="font-weight:700;color:#38BDF8;font-size:0.92rem;margin-bottom:3px;">🏦 PHYSICALLY ISOLATED FROM SWING TRADING</div>'
    f'  <div style="font-size:0.80rem;color:#CBD5E1;line-height:1.4;">'
    f'    Stored independently in <code>data/longterm.db</code>. These assets are never included in swing-trading equity, '
    f'    never used for position sizing, and never liquidated to fund speculative trades.'
    f'  </div>'
    f'</div>',
    unsafe_allow_html=True,
)

with st.expander("Add holding"):
    with st.form("lt_add", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        ac = c1.selectbox("Asset class", lt.ASSET_CLASSES)
        src = c2.selectbox("Price source", ["yfinance", "mfapi", "manual"],
                           help="yfinance: VTI, QQQM, RELIANCE.NS, GOLDBEES.NS, GC=F · mfapi: Indian MF scheme code "
                                "(AMFI, via api.mfapi.in) · manual: enter value yourself")
        cur = c3.selectbox("Currency", ["USD", "INR"])
        c1, c2 = st.columns(2)
        sym = c1.text_input("Symbol / scheme code / label", help="e.g. VTI, QQQM, INFY.NS, 120503 (MF scheme code)")
        name = c2.text_input("Name")
        c1, c2, c3 = st.columns(3)
        qty = c1.number_input("Quantity / units", 0.0, step=1.0, format="%.4f")
        cost = c2.number_input("Average cost per unit", 0.0, step=1.0, format="%.4f")
        mp = c3.number_input("Manual price (if manual)", 0.0, step=1.0, format="%.4f")
        notes = st.text_input("Notes")
        if st.form_submit_button("Add") and sym.strip():
            lt.add_holding(ac, sym, name, qty, cost, cur, src, mp or None, notes)
            ui.flash(f"{sym.strip()} added.")
            st.rerun()

rate, rate_date = lt.usd_inr_rate()
with st.spinner("Valuing holdings…"):
    df = lt.valuation(rate)
if df.empty:
    ui.empty_state("No long-term holdings recorded (e.g. VTI, QQQM, Indian mutual funds, Indian stocks, gold).")
    st.stop()

if rate:
    st.caption(f"USD/INR {rate:.2f} (Yahoo, as of {rate_date}) — used only to show a combined INR view.")
    tot = df["Value (INR)"].dropna().sum()
    st.metric("Total long-term value (INR, priced holdings)", f"₹{tot:,.0f}")
    alloc = df.dropna(subset=["Value (INR)"]).groupby("Asset class")["Value (INR)"].sum()
    if len(alloc):
        import plotly.express as px
        from tradingos.ui.charts import _layout
        fig = px.pie(values=alloc.values, names=alloc.index, hole=0.55, title="Allocation by asset class")
        st.plotly_chart(_layout(fig, 320), width="stretch")
st.dataframe(df.drop(columns=["id"]), hide_index=True, width="stretch")
missing = df[df["Price"].isna()]
if len(missing):
    st.warning("No price for: " + ", ".join(missing["Symbol"]) + ". Check the symbol/source or set a manual price.")

c1, c2, c3 = st.columns(3)
hid = c1.selectbox("Holding", df["id"], format_func=lambda i: f"{df.set_index('id').loc[i, 'Symbol']}")
newp = c2.number_input("Set manual price", 0.0, step=1.0)
if c2.button("Update manual price") and newp > 0:
    lt.update_manual_price(int(hid), newp)
    st.rerun()
if c3.button("🗑 Delete holding"):
    lt.delete_holding(int(hid))
    st.rerun()
ui.disclaimer()
