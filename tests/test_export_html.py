import json
import re

from pmdash.export.html import build_payload, render


def test_html_export_is_self_contained(gold, fx):
    payload = build_payload(gold, fx, include_oos=False)
    html = render(payload)
    assert html.startswith("<!doctype html>")
    assert "__PMDASH_DATA__" not in html
    data = json.loads(re.search(r'<script type="application/json" id="pmdash-data">(.*?)</script>', html, re.S).group(1))
    assert data["as_of"] == "2026-09"
    assert data["series"]["months"][0] == "1971-08"
    assert {r["currency"]: r["regime"] for r in data["regime"]} == {"CHF": "Up", "USD": "Sideways"}
    assert all(L["label"] for L in data["lines"])
    # only allowed external hosts: Google Fonts
    hosts = set(re.findall(r'(?:src|href)="https?://([^/"]+)', html))
    assert hosts <= {"fonts.googleapis.com", "fonts.gstatic.com"}


def test_fragment_has_no_document_wrapper(gold, fx):
    html = render(build_payload(gold, fx, include_oos=False), fragment=True)
    assert "<html" not in html and html.lstrip().startswith("<title>")


def test_price_strip_converts_to_francs_with_latest_known_rate():
    import pandas as pd
    from pmdash.export.html import price_strip
    days = pd.bdate_range("2024-01-01", "2025-01-10")
    close = pd.Series(range(100, 100 + len(days)), index=days, dtype=float)
    fx = pd.Series(0.9, index=days[:-3])            # franc rate a few days behind the price
    rows = price_strip({"gold": (pd.DataFrame({"close": close}), "test")}, fx)
    r = rows[0]
    assert r["date"] == str(days[-1].date())
    assert r["CHF"]["price"] == r["USD"]["price"] * 0.9
    assert r["fx"]["date"] == str(days[-4].date())
    assert r["USD"]["chg_1d"] == close.iloc[-1] / close.iloc[-2] - 1
    assert price_strip({"gold": (None, None)}, fx) == []
