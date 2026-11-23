"""Tests for quarterly (TTM) scores (src/scores/quarterly_scores.py),
with one fake company whose numbers can be checked by hand."""

import pandas as pd
import pytest

from src.pipeline import ttm
from src.scores import quarterly_scores as qs

# Q2 rows for FY2024 to FY2026 (calendar year), plus the FY2025 Q4 row
# that supplies the prior fiscal year end for FY2026 Q2.
ROWS = [
    # year, quarter, period_end, available_date, net_income, accession
    (2024, 2, "2024-06-30", "2024-08-01", 40.0, "q2-24"),
    (2025, 2, "2025-06-30", "2026-09-01", 50.0, "q2-25"),  # filed late
    (2025, 4, "2025-12-31", "2026-02-20", 60.0, "k-25"),
    (2026, 2, "2026-06-30", "2026-08-01", 100.0, "q2-26"),
]


def fake_ttm():
    """Return financials_ttm rows: total assets 1,000 everywhere; Z''
    inputs chosen so X1 = 0.2, X2 = 0.3, X3 = 0.15 and X4 = 1.0."""
    records = []
    for year, quarter, end, available, net_income, _ in ROWS:
        record = {column: float("nan") for column in ttm.TTM_COLUMNS}
        record.update(
            cik=1,
            fiscal_year=year,
            fiscal_quarter=quarter,
            period_end=pd.Timestamp(end),
            available_date=pd.Timestamp(available),
            passes_size_floor=True,
            derived_items=pd.NA,
            total_assets=1000.0,
            net_income=net_income,
            cfo=120.0,
            current_assets=400.0,
            current_liabilities=200.0,
            retained_earnings=300.0,
            operating_income=150.0,
            stockholders_equity=500.0,
            total_liabilities=500.0,
            shares_outstanding=100.0,
        )
        records.append(record)
    table = pd.DataFrame(records)[ttm.TTM_COLUMNS]
    return table.astype({"derived_items": "string"})


def fake_accessions():
    """Return the filing behind each row's share count."""
    return pd.DataFrame(
        {
            "cik": 1,
            "period_end": pd.to_datetime([row[2] for row in ROWS]),
            "accession": [row[5] for row in ROWS],
        }
    )


def fake_share_facts():
    """The FY2026 Q2 10-Q reports 100 shares at the prior fiscal year end
    (Dec 31, 2025) and, as a decoy, 50 at June 30, 2025 (the t-1 row's
    date); option C must use the year-end count, so signal 7 passes."""
    return pd.DataFrame(
        {
            "cik": 1,
            "line_item": "shares_outstanding",
            "accession": ["q2-26", "q2-26", "q2-26"],
            "period_end": pd.to_datetime(
                ["2026-06-30", "2025-12-31", "2025-06-30"]
            ),
            "value": [100.0, 100.0, 50.0],
        }
    )


def fake_companies():
    """One included company with an SIC code."""
    return pd.DataFrame(
        {
            "cik": [1],
            "sic": pd.array([3571], dtype="Int64"),
            "is_excluded": [False],
        }
    )


@pytest.fixture(scope="module")
def built():
    """Return (scores, drivers, log) for the fake company."""
    return qs.build_quarterly_scores(
        fake_ttm(), fake_accessions(), fake_share_facts(), fake_companies()
    )


def score_row(scores, year, quarter):
    """Return one scores_quarterly row."""
    match = scores[
        (scores["fiscal_year"] == year) & (scores["fiscal_quarter"] == quarter)
    ]
    assert len(match) == 1
    return match.iloc[0]


def test_every_quarter_is_scored_including_fy2026(built):
    """All four rows are scored; FY2026 is kept (no FY2025 limit), and
    basis is TTM."""
    scores, _, log = built
    assert len(scores) == 4
    assert scores["fiscal_year"].max() == 2026
    assert set(scores["basis"]) == {"TTM"}
    assert log["scored_company_quarters"] == 4


def test_z_score_uses_the_row_itself(built):
    """Z'' = 6.56(0.2) + 3.26(0.3) + 6.72(0.15) + 1.05(1.0) = 4.348."""
    scores, _, _ = built
    assert score_row(scores, 2026, 2)["z_score"] == pytest.approx(4.348)


def test_prior_year_is_the_same_quarter_a_year_earlier(built):
    """FY2026 Q2 ROA (100 / 1,000 beginning assets) is compared with
    FY2025 Q2 (50 / 1,000), not with FY2025 Q4 (60): improved. FY2025
    Q4 has no Q4 a year earlier, so it cannot be compared."""
    scores, _, _ = built
    assert bool(score_row(scores, 2026, 2)["f_roa_improved"]) is True
    assert pd.isna(score_row(scores, 2025, 4)["f_roa_improved"])


def test_signal_7_uses_the_prior_year_end_in_q1_to_q3(built):
    """FY2026 Q2: 100 shares now vs 100 at Dec 31, 2025 in the same 10-Q
    passes (the decoy 50 at June 30, 2025 is not used, or it would
    fail), and the row is noted."""
    scores, _, _ = built
    row = score_row(scores, 2026, 2)
    assert bool(row["f_no_new_shares"]) is True
    assert qs.SHARE_NOTE in row["missing_inputs"]


def test_prior_year_end_share_facts_relabels_only_the_year_end():
    """The year-end count (100) is labeled with the t-1 row's date (June
    30, 2025); the decoy count at that date itself is not passed on."""
    rows = qs.with_accession(fake_ttm(), fake_accessions())
    q2 = rows[rows["fiscal_quarter"] == 2]
    facts = qs.prior_year_end_share_facts(q2, rows, fake_share_facts())
    assert facts["value"].tolist() == [100.0]
    assert facts["period_end"].tolist() == [pd.Timestamp("2025-06-30")]
    assert facts["accession"].tolist() == ["q2-26"]


def test_score_available_date_is_the_latest_input_row(built):
    """FY2026 Q2 uses its own row (Aug 1, 2026), FY2025 Q2 (filed late,
    Sept 1, 2026) and FY2024 Q2: the score is available Sept 1, 2026."""
    scores, _, _ = built
    assert score_row(scores, 2026, 2)["available_date"] == pd.Timestamp(
        "2026-09-01"
    )


def test_column_order_and_types(built):
    """Quarter columns follow the keys; types follow section 4."""
    scores, drivers, _ = built
    assert list(scores.columns) == qs.SCORES_QUARTERLY_COLUMNS
    assert list(drivers.columns) == qs.DRIVERS_QUARTERLY_COLUMNS
    assert scores["fiscal_quarter"].dtype == "int64"
    assert scores["basis"].dtype == "string"
    assert scores["available_date"].dtype == "datetime64[ns]"


def run_stages(monkeypatch, argv):
    """Return the stage names run_pipeline would run for argv."""
    import run_pipeline

    calls = []
    monkeypatch.setattr(
        run_pipeline,
        "run_stage",
        lambda name, function, *a, **k: calls.append(name),
    )
    run_pipeline.main(argv)
    return calls


def test_pipeline_adds_quarterly_stages_only_on_request(monkeypatch):
    """Without --quarterly no quarterly stage runs; with it, the three
    quarterly stages run after the annual returns stage and before the
    sample, in order; --scores-only --quarterly rebuilds only the
    quarterly scores."""
    plain = run_stages(monkeypatch, ["--skip-download"])
    assert not [name for name in plain if name.startswith("Q")]
    full = run_stages(monkeypatch, ["--skip-download", "--quarterly"])
    quarterly = [name for name in full if name.startswith("Q")]
    assert quarterly == [
        "Q1. facts_quarterly",
        "Q2. financials_ttm and ttm_sources",
        "Q3. quarterly scores and drivers",
    ]
    assert full.index("8. returns") < full.index(quarterly[0])
    assert full.index(quarterly[-1]) < full.index("9. sample")
    assert [n for n in full if not n.startswith("Q")] == plain
    scores_only = run_stages(monkeypatch, ["--scores-only", "--quarterly"])
    assert [n for n in scores_only if n.startswith("Q")] == [
        "Q3. quarterly scores and drivers"
    ]
