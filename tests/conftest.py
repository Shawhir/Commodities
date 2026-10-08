from pathlib import Path

import pandas as pd
import pytest

from pmdash import config
from pmdash.storage import db
from pmdash.data import import_files

FIX = Path(__file__).parent / "fixtures"
GOLD = FIX / "gold_monthly_2026-10-08.csv"
FX = FIX / "usdchf_monthly_2026-10-08.csv"


@pytest.fixture(scope="session")
def con():
    c = db.connect(":memory:")
    import_files(c, GOLD, FX)
    return c


@pytest.fixture(scope="session")
def gold(con):
    return db.get_monthly(con, "gold_usd_monthly")


@pytest.fixture(scope="session")
def fx(con):
    return db.get_monthly(con, "usdchf_monthly")


@pytest.fixture(scope="session")
def thresholds():
    return dict(config.load("thresholds"), float_start="1971-08")
