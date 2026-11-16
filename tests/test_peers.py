"""Tests for src/scores/peers.py.

The 3-company fixture is too small for peer groups, so these tests build
tiny tables by hand and lower min_size so terciles stay checkable.
"""

import numpy as np
import pandas as pd
import pytest

from src.scores import peers


def make_scored(sics, total_assets, m_scores, fiscal_year=2023):
    """Return a minimal scored table: one row per company."""
    n = len(sics)
    scored_df = pd.DataFrame(
        {
            "cik": np.arange(1, n + 1, dtype="int64"),
            "fiscal_year": fiscal_year,
            "sic": pd.array(sics, dtype="Int64"),
            "total_assets": total_assets,
            "m_score": m_scores,
        }
    )
    for score in peers.RANKED_SCORES:
        if score not in scored_df:
            scored_df[score] = np.nan
    return scored_df


def test_industry_code_is_first_two_sic_digits():
    """3571 (computers) -> 35; 100 (crops) -> 1, shown as 'SIC 01'."""
    sic = pd.Series([3571, 100], dtype="Int64")
    assert peers.industry_code(sic).tolist() == [35, 1]


def test_size_bucket_terciles_and_ties():
    """Six companies: rank fractions 1/6 ... 6/6.
    <= 1/3 small (ranks 1, 2); <= 2/3 mid (3, 4); else large (5, 6).
    Two companies with equal assets always share a bucket."""
    buckets = peers.size_bucket(pd.Series([100, 200, 300, 400, 500, 600.0]))
    assert buckets.tolist() == ["small", "small", "mid", "mid"] + [
        "large",
        "large",
    ]
    tied = peers.size_bucket(pd.Series([100, 200, 200, 400, 500, 600.0]))
    assert tied[1] == tied[2]


def test_percentile_within_hand_example():
    """Values 10, 20, 20, 40 (+ one blank). Average ranks 1, 2.5, 2.5, 4.
    (rank - 1) / (4 - 1) * 100 -> 0, 50, 50, 100. Blank stays blank."""
    result = peers.percentile_within(pd.Series([10, 20, 20, 40, np.nan]))
    assert result.tolist()[:4] == [0.0, 50.0, 50.0, 100.0]
    assert np.isnan(result[4])


def test_percentile_needs_at_least_two_values():
    """One company alone has no peers to be ranked against: blank."""
    result = peers.percentile_within(pd.Series([5.0, np.nan]))
    assert result.isna().all()


def test_full_size_groups_when_big_enough():
    """Six industry-35 companies, min_size 2: every tercile has 2, so each
    company is ranked within its size group ("SIC 35 small", etc.)."""
    scored_df = make_scored([3571] * 6, [100, 200, 300, 400, 500, 600.0], 0.0)
    result = peers.assign_peer_groups(scored_df, min_size=2)
    assert (
        result["peer_group"].tolist()
        == ["SIC 35 small"] * 2 + ["SIC 35 mid"] * 2 + ["SIC 35 large"] * 2
    )
    assert (result["peer_group_level"] == "industry_size").all()
    assert (result["peer_group_size"] == 2).all()


def test_small_groups_fall_back_to_industry_and_rank_against_it():
    """Seven industry-35 companies, min_size 3. Rank fractions k/7:
    small = ranks 1-2 (2 firms), mid = 3-4 (2), large = 5-7 (3).
    Small and mid have < 3, so they fall back to all 7 of industry 35;
    large keeps its own group of 3.

    m_score = 1..7 in asset order. Company 1 (fallback) ranks against
    all 7: (1 - 1)/(7 - 1) = 0. Company 4 (fallback): 3/6 = 50.
    Company 5 (large group of 3, values 5, 6, 7): (1 - 1)/2 = 0.
    """
    scored_df = make_scored(
        [3571] * 7,
        [100, 200, 300, 400, 500, 600, 700.0],
        [1, 2, 3, 4, 5, 6, 7.0],
    )
    grouped = peers.assign_peer_groups(scored_df, min_size=3)
    ranked = peers.add_percentile_ranks(grouped).set_index("cik")
    assert ranked.loc[1, "peer_group"] == "SIC 35"
    assert ranked.loc[1, "peer_group_level"] == "industry"
    assert ranked.loc[1, "peer_group_size"] == 7
    assert ranked.loc[5, "peer_group"] == "SIC 35 large"
    assert ranked.loc[5, "peer_group_size"] == 3
    assert ranked.loc[1, "m_score_pctile"] == 0.0
    assert ranked.loc[4, "m_score_pctile"] == pytest.approx(50.0)
    assert ranked.loc[5, "m_score_pctile"] == 0.0
    assert ranked.loc[7, "m_score_pctile"] == 100.0


def test_missing_assets_falls_back_to_industry():
    """No total assets -> no size bucket -> ranked within the industry."""
    scored_df = make_scored([3571] * 3, [100, np.nan, 300.0], [1, 2, 3.0])
    result = peers.assign_peer_groups(scored_df, min_size=1)
    assert result.loc[1, "peer_group"] == "SIC 35"
    assert result.loc[1, "peer_group_level"] == "industry"


def test_industries_and_years_are_ranked_separately():
    """Same values in two industries, or two years, never mix."""
    scored_df = pd.concat(
        [
            make_scored([3571, 3571], [100, 200.0], [1, 2.0]),
            make_scored([7372, 7372], [100, 200.0], [1, 2.0]),
            make_scored([3571, 3571], [100, 200.0], [1, 2.0], 2022),
        ],
        ignore_index=True,
    )
    scored_df["cik"] = np.arange(1, 7)
    ranked = peers.add_percentile_ranks(
        peers.assign_peer_groups(scored_df, min_size=5)
    )
    assert ranked["m_score_pctile"].tolist() == [0, 100] * 3
