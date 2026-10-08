from pmdash.digest.summary import build, to_markdown


def test_weekly_summary_builds(gold, fx):
    s = build(gold, fx)
    md = to_markdown(s)
    assert "Descriptive, not predictive" in md
    assert s["regime"].set_index("currency").loc["USD", "regime"] == "Sideways"
    assert "Closest past months" in md


def test_summary_with_failed_source_in_health(gold, fx):
    from pmdash.storage import db
    con = db.connect()
    db.record_health(con, "ok_source", ok=True, rows_added=1)
    db.record_health(con, "blocked_source", ok=False, error="403")
    md = to_markdown(build(gold, fx, db.health_table(con)))
    assert "blocked_source | - |" in md
