"""The quarterly upgrade must not change any annual table.

test_annual_tables_match_the_baseline compares every table recorded in
data/logs/annual_baseline.json (made before any quarterly change by
python -m src.pipeline.annual_baseline) with the table on disk now. A
table whose file is not on this machine (for example data/processed/ on
a teammate's computer) is skipped, not failed.
"""

import json

import pandas as pd
import pytest

import config
from src.pipeline import annual_baseline


def test_fingerprint_ignores_a_rewrite_but_catches_a_change(tmp_path):
    """Writing the same table again gives the same fingerprint; changing
    one cell, reordering rows or changing a type gives a different one."""
    table = pd.DataFrame({"cik": [1, 2], "value": [10.0, 20.0]})
    first, again = tmp_path / "a.parquet", tmp_path / "b.parquet"
    table.to_parquet(first)
    table.to_parquet(again)
    base = annual_baseline.table_fingerprint(first)
    assert annual_baseline.table_fingerprint(again) == base
    assert base["rows"] == 2

    def fingerprint_of(frame):
        path = tmp_path / "changed.parquet"
        frame.to_parquet(path)
        return annual_baseline.table_fingerprint(path)["sha256"]

    assert fingerprint_of(table.assign(value=[10.0, 20.5])) != base["sha256"]
    assert fingerprint_of(table.iloc[::-1]) != base["sha256"]
    assert fingerprint_of(table.astype({"cik": "int32"})) != base["sha256"]


def load_baseline():
    """Return the recorded baseline, or skip if it was never made here."""
    path = annual_baseline.BASELINE_PATH
    if not path.exists():
        pytest.skip("no annual baseline on this machine")
    return json.loads(path.read_text())["tables"]


def test_annual_tables_match_the_baseline():
    """Every recorded annual table that exists here is unchanged: same
    rows, columns, types and cell values."""
    checked = 0
    for name, recorded in load_baseline().items():
        path = config.PROJECT_ROOT / name
        if not path.exists():
            continue
        now = annual_baseline.table_fingerprint(path)
        assert now["rows"] == recorded["rows"], f"{name}: row count changed"
        assert (
            now["columns"] == recorded["columns"]
        ), f"{name}: columns changed"
        assert now["dtypes"] == recorded["dtypes"], f"{name}: types changed"
        assert now["sha256"] == recorded["sha256"], f"{name}: contents changed"
        checked += 1
    if checked == 0:
        pytest.skip("none of the recorded tables are on this machine")
