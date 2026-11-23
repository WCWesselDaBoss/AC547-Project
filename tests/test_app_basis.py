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
    assert basis.QUARTERLY_NOTE == (
        "Quarterly scores apply the same formulas and cutoffs as the annual "
        "scores to trailing-twelve-month data from unaudited 10-Q filings. "
        "They have not been backtested: tests 1 to 12 used annual scores "
        "only."
    )
    assert basis.NOT_ENOUGH_DATA == (
        "Not enough quarterly data (needs four complete quarters this "
        "year and last)"
    )


def test_about_quarterly_summary_and_coverage():
    """Three company-quarters of two companies; the latest quarter end
    and available date; coverage counted per company-quarter."""
    from app import about_quarterly

    scores = pd.DataFrame(
        {
            "cik": [1, 1, 2],
            "period_end": pd.to_datetime(
                ["2025-03-31", "2025-06-30", "2025-05-31"]
            ),
            "available_date": pd.to_datetime(
                ["2025-05-01", "2025-08-01", "2025-07-10"]
            ),
            "m_score": [-2.0, float("nan"), -1.0],
            "z_score": [3.0, 2.0, 1.0],
            "f_score": pd.array([5, pd.NA, pd.NA], dtype="Int64"),
            "accruals_ratio": [0.1, 0.1, 0.1],
            "cash_conversion": [1.0, 1.0, 1.0],
        }
    )
    summary = about_quarterly.quarterly_summary(scores)
    assert summary["companies"] == 2
    assert summary["company_quarters"] == 3
    assert summary["latest_quarter_end"] == pd.Timestamp("2025-06-30")
    assert summary["latest_available"] == pd.Timestamp("2025-08-01")
    table = about_quarterly.quarterly_coverage_table(scores)
    assert about_quarterly.QUARTERS_COLUMN in table.columns
    assert table[about_quarterly.QUARTERS_COLUMN].iloc[0] == "2 of 3"
