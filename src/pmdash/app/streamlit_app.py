"""Thin Streamlit front end. Run: streamlit run src/pmdash/app/streamlit_app.py

All numbers come from pmdash.digest / modules; this file only lays them out,
so a static HTML export could replace it.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from pmdash import DISCLAIMER, config, data  # noqa: E402
from pmdash.digest.summary import build  # noqa: E402
from pmdash.regime.labeller import episodes, label_from_config  # noqa: E402
from pmdash.storage import db  # noqa: E402

st.set_page_config(page_title="Precious metals", layout="wide")
st.caption(DISCLAIMER)


@st.cache_resource
def _con():
    return db.connect(config.db_path())


con = _con()
try:
    gold, fx = data.load_monthly(con)
except RuntimeError as e:
    st.error(str(e))
    st.stop()

stale = {k: v.get("stale_after_days") for k, v in config.load("sources")["sources"].items()}
health = db.health_table(con, stale)
summary = build(gold, fx, health, data.load_macro(con))

pages = ["Weekly summary", "Market detail", "Triggers", "Regime history", "Analogues", "Data health"]
page = st.sidebar.radio("Page", pages)   # opens to the weekly summary, not live prices
currency = st.sidebar.radio("Currency", ["CHF", "USD"])
price = (gold * fx).dropna() if currency == "CHF" else gold

if page == "Weekly summary":
    st.title(f"Weekly summary (data to {summary['as_of']})")
    st.subheader("Regime (monthly closes)")
    st.dataframe(summary["regime"], hide_index=True)
    st.subheader("Stretch")
    t = summary["stretch"][currency]
    st.dataframe(t.style.format("{:.3g}"))
    st.subheader("Key lines")
    st.dataframe(summary["level_states"])
    for n in summary["level_notes"]:
        st.caption(n)
    res = summary["analogues"]
    st.subheader("Closest past months")
    st.write(res.summary())
    st.dataframe(pd.DataFrame([{"month": str(m.month), "distance": round(m.distance, 2), "key moment": m.key_moment,
                                "next 12m USD": m.outcomes.get("fwd_12m_usd"),
                                "next 12m CHF": m.outcomes.get("fwd_12m_chf"),
                                "differences": "; ".join(m.differences)} for m in res.matches[:3]]), hide_index=True)
    st.subheader("Not yet available")
    for p in summary["pending"]:
        st.write("- " + p)

elif page == "Market detail":
    st.title(f"Gold in {currency} (monthly averages)")
    start = st.slider("From year", 1971, int(price.index[-1].year) - 1, 2015)
    p = price[str(start):]
    df = pd.DataFrame({"price": p, "10m average": p.rolling(10).mean()}, index=p.index.to_timestamp())
    st.line_chart(df)
    lab = label_from_config(price, config.load("thresholds"))[str(start):]
    lab.index = lab.index.to_timestamp()
    st.line_chart(lab[["er"]])
    st.dataframe(lab.tail(24))

elif page == "Triggers":
    st.title("Triggers")
    df = con.execute("SELECT * FROM triggers ORDER BY close_date DESC LIMIT 200").df()
    if df.empty:
        st.info("No stored triggers. Run `pmdash check-levels`.")
    else:
        st.dataframe(df, hide_index=True)
    st.caption("Linked panels (snapshot, geopolitics, agent report, analogues, journal) arrive in phase 8.")

elif page == "Regime history":
    st.title("Regime history (USD price, section 8 rules)")
    th = config.load("thresholds")
    lab = label_from_config(gold, th)["1971-08":]
    st.bar_chart(lab["regime"].value_counts(normalize=True))
    eps = episodes(lab["regime"], min_months=th["regime"]["sideways_episode_min_months"],
                   gap_merge=th["regime"]["sideways_gap_merge_months"])
    st.dataframe(pd.DataFrame([{"start": str(e.start), "end": str(e.end), "months": e.months} for e in eps]),
                 hide_index=True)
    rd = config.DATA_DIR / "research"
    for name in ("regime_study_summary.csv", "regime_study_per_regime.csv"):
        if (rd / name).exists():
            st.subheader(name)
            st.dataframe(pd.read_csv(rd / name))

elif page == "Analogues":
    res = summary["analogues"]
    st.title(f"Analogues for {res.target}")
    st.write(res.summary())
    st.dataframe(pd.DataFrame([{"month": str(m.month), "distance": round(m.distance, 2),
                                **{f"d_{g}": round(v, 2) for g, v in m.group_distance.items()},
                                "key moment": m.key_moment, **m.outcomes,
                                "differences": "; ".join(m.differences)} for m in res.matches]), hide_index=True)
    st.subheader("Key moments by distance")
    st.dataframe(pd.DataFrame(res.key_moments), hide_index=True)
    oos = config.DATA_DIR / "research" / "analogue_oos_summary.csv"
    if oos.exists():
        st.subheader("Out-of-sample test")
        st.dataframe(pd.read_csv(oos), hide_index=True)

elif page == "Data health":
    st.title("Data health")
    st.dataframe(health, hide_index=True)
