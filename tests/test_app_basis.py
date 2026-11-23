"""Tests for the annual/quarterly switch helpers (app/basis.py)."""

import pandas as pd

from app import basis, labels


def quarterly_scores():
    """Three companies over two quarters."""
    return pd.DataFrame(
        {
            "cik": [1, 2, 1, 3],
            "fiscal_year": [2024, 2024, 2025, 2025],
            "fiscal_quarter": [4, 4, 1, 1],
            "period_end": pd.to_datetime(
                ["2024-12-31", "2025-01-31", "2025-03-31", "2025-04-30"]
            ),
        }
    )


def test_default_is_annual_and_labels():
    """Annual comes first (the default) and periods read FY2024 Q3."""
    assert list(basis.BASIS_LABELS) == [basis.ANNUAL, basis.QUARTERLY]
    assert basis.period_label(2024, 3) == "FY2024 Q3"


def test_quarter_options_latest_first():
    """Each scored quarter once, the latest first."""
    assert basis.quarter_options(quarterly_scores()) == [
        (2025, 1),
        (2024, 4),
    ]


def test_one_quarter_and_its_latest_end():
    """Only FY2025 Q1 rows; companies end the quarter on different
    dates, and the latest is reported."""
    rows = basis.one_quarter(quarterly_scores(), 2025, 1)
    assert rows["cik"].tolist() == [1, 3]
    assert basis.latest_quarter_end(quarterly_scores(), 2025, 1) == (
        pd.Timestamp("2025-04-30")
    )
    assert basis.latest_quarter_end(quarterly_scores(), 2020, 1) is None


def test_missing_quarterly_verdicts_say_why():
    """A "No score" verdict becomes the not-enough-data label; real
    verdicts are untouched."""
    shown = pd.DataFrame({"Check": [labels.NO_SCORE, "🟢 No warning"]})
    out = basis.label_missing_quarterly(shown, ["Check"])
    assert out["Check"].tolist() == [
        basis.NOT_ENOUGH_DATA_SHORT,
        "🟢 No warning",
    ]


def test_quarterly_tables_present(tmp_path):
    """All four quarterly tables are needed for quarterly mode."""
    assert not basis.quarterly_tables_present(tmp_path)
    for table in basis.QUARTERLY_TABLES:
        (tmp_path / f"{table}.parquet").write_bytes(b"")
    assert basis.quarterly_tables_present(tmp_path)


def test_required_texts():
    """The note and the missing-score message are the agreed wording."""
    assert "have NOT been backtested" in basis.QUARTERLY_NOTE
    assert basis.NOT_ENOUGH_DATA == (
        "Not enough quarterly data (needs four complete quarters this "
        "year and last)"
    )
