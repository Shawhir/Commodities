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
