from pmdash.digest.summary import build, to_markdown


def test_weekly_summary_builds(gold, fx):
    s = build(gold, fx)
    md = to_markdown(s)
    assert "Descriptive, not predictive" in md
    assert s["regime"].set_index("currency").loc["USD", "regime"] == "Sideways"
    assert "Closest past months" in md
