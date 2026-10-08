from pmdash.testing.snapshot_check import check


def test_snapshot_figures_confirmed(gold, fx):
    df = check(gold, fx, "2026-09")
    checkable = df[~df.status.str.startswith("not checkable")]
    assert (checkable.status == "confirmed").all(), checkable[checkable.status != "confirmed"]
    assert (df.status.str.startswith("not checkable")).sum() == 3
