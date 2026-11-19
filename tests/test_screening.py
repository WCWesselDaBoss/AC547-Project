"""Tests for the screener's table logic (app/screening.py) and labels.

Fixture companies (tests/fixtures/build_app_fixtures.py), FY2023:
- 101 Steady Co: M -2.48 (no warning), Z'' safe, F 4 middle; $1.21B.
- 102 Stretch Co: M -2.66 (no warning), Z'' distress, F 2 weak; $800M.
- 103 Service Co: no M or F (no cost of revenue), Z'' safe; $350M.
"""

import pandas as pd
import pytest

import config
from app import labels, screening

STRETCH_CO = 102


def read_fixture(table):
    """Read one app fixture table."""
    return pd.read_parquet(config.APP_FIXTURE_DIR / f"{table}.parquet")


@pytest.fixture
def screen_2023():
    """Return the FY2023 screen table at the default M-Score cutoff."""
    screen_df = screening.screen_table(
        read_fixture("scores"),
        read_fixture("companies"),
        read_fixture("financials_annual"),
        2023,
    )
    return screening.apply_cutoff(screen_df, config.BENEISH_FLAG_CUTOFF)


@pytest.mark.parametrize(
    "scores_path",
    [
        config.APP_FIXTURE_DIR / "scores.parquet",
        config.SAMPLE_DIR / "scores.parquet",
    ],
)
def test_default_cutoff_reproduces_stored_flags(scores_path):
    """At -1.78 the screener's flags equal Phase 2's stored columns.

    Proves the slider re-applies the same rule rather than a new one.
    """
    scores_df = pd.read_parquet(scores_path)
    screen_df = screening.apply_cutoff(scores_df, config.BENEISH_FLAG_CUTOFF)
    pd.testing.assert_series_equal(
        screen_df[screening.M_FLAG_AT_CUTOFF],
        scores_df["m_flag"],
        check_names=False,
    )
    pd.testing.assert_series_equal(
        screen_df[screening.CONCERNS_AT_CUTOFF],
        scores_df["flags_raised"],
        check_names=False,
    )


def test_stricter_cutoff_adds_a_warning(screen_2023):
    """At -2.70, Stretch Co's -2.66 M-Score becomes a warning: 2 -> 3."""
    stricter = screening.apply_cutoff(screen_2023, -2.70).set_index("cik")
    assert stricter.loc[STRETCH_CO, screening.M_FLAG_AT_CUTOFF]
    assert stricter.loc[STRETCH_CO, screening.CONCERNS_AT_CUTOFF] == 3


def test_size_bands_follow_config_edges():
    """Lower edge included, upper excluded; missing assets get no band."""
    assets = pd.Series([999_999_999, 1_000_000_000, 10_000_000_000, None])
    small, mid, large = config.APP_SIZE_BANDS
    bands = screening.size_band(assets)
    assert list(bands[:3]) == [small, mid, large]
    assert pd.isna(bands[3])


def test_screen_table_adds_company_details(screen_2023):
    """Names, industry labels and sizes come from the other tables."""
    row = screen_2023.set_index("cik").loc[101]
    assert row["name"] == "Steady Co"
    assert row[screening.INDUSTRY] == "Electronic Computers (SIC 3571)"
    assert row[screening.SIZE_BAND] == "Mid ($1B to $10B)"
    assert len(screen_2023) == 3


def test_narrowing_f_range_hides_blank_f_scores(screen_2023):
    """Full range keeps Service Co (no F-Score); a narrower one drops it."""
    full = screening.filter_screen(screen_2023)
    narrowed = screening.filter_screen(screen_2023, f_range=(0, 8))
    assert 103 in set(full["cik"])
    assert set(narrowed["cik"]) == {101, 102}


def test_zone_filter_can_select_distress_or_no_score(screen_2023):
    """Zone filter matches zones, and NO_SCORE_KEY matches blanks."""
    distress = screening.filter_screen(screen_2023, z_zones=["distress"])
    assert set(distress["cik"]) == {STRETCH_CO}
    blanks = screening.filter_screen(
        screen_2023, z_zones=[screening.NO_SCORE_KEY]
    )
    assert blanks.empty  # every fixture company has a Z''


def test_size_and_industry_filters(screen_2023):
    """Small companies are Stretch Co and Service Co; one industry."""
    small = list(config.APP_SIZE_BANDS)[0]
    assert set(screening.filter_screen(screen_2023, sizes=[small])["cik"]) == {
        102,
        103,
    }
    software = "Services-Prepackaged Software (SIC 7372)"
    only_software = screening.filter_screen(screen_2023, industries=[software])
    assert set(only_software["cik"]) == {103}


def test_sort_by_risk_puts_most_concerns_first(screen_2023):
    """Stretch Co (2 concerns) first; then by M-Score, blanks last."""
    ordered = screening.sort_by_risk(screen_2023)
    assert list(ordered["cik"]) == [102, 101, 103]


def test_display_table_uses_words_and_icons(screen_2023):
    """Verdicts show as icon-and-word labels; blanks as "No score"."""
    display_df = screening.display_table(screening.sort_by_risk(screen_2023))
    assert list(display_df.columns) == list(screening.TABLE_COLUMNS.values())
    stretch = display_df.iloc[0]
    assert stretch[labels.CHECK_NAMES["z"]] == "🔴 Distress zone"
    assert stretch[labels.CHECK_NAMES["f"]] == "🔴 Weak"
    service = display_df.iloc[2]
    assert service[labels.CHECK_NAMES["m"]] == labels.NO_SCORE


def test_exclusion_counts_use_plain_reasons():
    """Fixture: one bank and one company with no SIC."""
    counts = screening.exclusion_counts(read_fixture("companies"))
    bank_reason = labels.EXCLUSION_REASON_LABELS["financial_sic_6000_6799"]
    no_sic_reason = labels.EXCLUSION_REASON_LABELS["missing_sic"]
    assert counts.to_dict() == {bank_reason: 1, no_sic_reason: 1}


def test_below_size_floor_count_is_zero_in_fixture():
    """Every fixture company-year passes the $100M floor."""
    count = screening.below_size_floor_count(
        read_fixture("financials_annual"), read_fixture("companies"), 2023
    )
    assert count == 0


def test_blank_scores_and_their_reasons(screen_2023):
    """Service Co has no M or F; its gap is the missing cost of revenue."""
    blanks = screening.blank_score_counts(screen_2023)
    assert blanks == {
        labels.CHECK_NAMES["m"]: 1,
        labels.CHECK_NAMES["z"]: 0,
        labels.CHECK_NAMES["f"]: 1,
    }
    # Both gaps affect one company, so they tie; compare as a dict.
    reasons = screening.top_missing_reasons(screen_2023)
    assert reasons.to_dict() == {
        "Cost of revenue not reported (this year)": 1,
        "Cost of revenue not reported (prior year)": 1,
    }


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("cost_of_revenue_t-1", "Cost of revenue not reported (prior year)"),
        ("receivables_t", "Accounts receivable not reported (this year)"),
        ("no_row_t-2", "No filing data for two years earlier"),
        (
            "sgai_set_to_1",
            "SGAI set to neutral (1) because an input is missing",
        ),
        ("dsri_zero_denominator", "DSRI not computable (division by zero)"),
        ("something_new", "something_new"),
    ],
)
def test_describe_missing_input(code, expected):
    """Codes become sentences; unknown codes are shown, not guessed."""
    assert labels.describe_missing_input(code) == expected


def test_reasons_that_never_blank_a_score_are_skipped():
    """Missing SG&A sets SGAI to neutral; it never blanks a score."""
    screen_df = pd.DataFrame(
        {
            "m_score": [float("nan")],
            "z_score": [1.0],
            "f_score": pd.array([5], dtype="Int64"),
            "missing_inputs": pd.array(
                ["sga_t; sgai_set_to_1; receivables_t-1"], dtype="string"
            ),
        }
    )
    reasons = screening.top_missing_reasons(screen_df)
    assert list(reasons.index) == [
        "Accounts receivable not reported (prior year)"
    ]
