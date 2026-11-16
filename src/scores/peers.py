"""Peer groups and percentile ranks within each peer group.

A peer group is the 2-digit SIC industry (e.g. 73 = business services)
plus a size bucket: small, mid or large, the terciles of total assets
among that industry's scored companies in the same fiscal year. Size
matters because a $150M software firm and Microsoft have very different
normal ratios, even in the same industry.

Fallback: if the industry-size group has fewer than
config.MIN_PEER_GROUP_SIZE companies (or total assets is missing, so no
size bucket exists), the company is ranked against its whole 2-digit
industry for that year instead. peer_group_level records which was used
and peer_group_size how many companies were in it, so the dashboard can
warn when a rank rests on very few peers.

Percentile rank = the share of the OTHER companies in the peer group with
a lower value, ties counting half, times 100. So 0 = lowest in the group,
100 = highest, 50 = middle. Only companies with a value for that score
are ranked; a blank score gets a blank rank. A group with one valid
value has no "others", so its rank is blank.

Direction is the raw score's: a high m_score percentile means MORE
manipulation risk; a high z_score or f_score percentile means stronger.
"""

import numpy as np
import pandas as pd

import config

SIZE_LABELS = ["small", "mid", "large"]
RANKED_SCORES = [
    "m_score",
    "z_score",
    "f_score",
    "accruals_ratio",
    "cash_conversion",
]
LEVEL_INDUSTRY_SIZE = "industry_size"
LEVEL_INDUSTRY = "industry"


def percentile_column(score):
    """Return the scores-table column holding a score's percentile."""
    return f"{score}_pctile"


def industry_code(sic):
    """Return the 2-digit SIC industry (major group): 3571 -> 35."""
    return sic // 100


def size_bucket(total_assets):
    """Return small / mid / large terciles of one industry-year's assets.

    Uses each company's average rank as a fraction of the group, so tied
    asset values always land in the same bucket and the result does not
    depend on row order. Missing assets get no bucket.
    """
    fraction = total_assets.rank(method="average", pct=True)
    bucket = pd.Series(pd.NA, index=total_assets.index, dtype="string")
    bucket[fraction <= 1 / 3] = SIZE_LABELS[0]
    bucket[(fraction > 1 / 3) & (fraction <= 2 / 3)] = SIZE_LABELS[1]
    bucket[fraction > 2 / 3] = SIZE_LABELS[2]
    return bucket


def assign_peer_groups(scored_df, min_size=None):
    """Return scored_df with peer_group, peer_group_level, peer_group_size.

    scored_df needs cik, fiscal_year, sic and total_assets, one row per
    scored company-year.
    """
    if min_size is None:
        min_size = config.MIN_PEER_GROUP_SIZE
    peers_df = scored_df.copy()
    peers_df["industry"] = industry_code(peers_df["sic"])
    peers_df["size_bucket"] = peers_df.groupby(
        ["industry", "fiscal_year"], group_keys=False
    )["total_assets"].apply(size_bucket)

    industry_keys = ["industry", "fiscal_year"]
    size_keys = industry_keys + ["size_bucket"]
    industry_count = peers_df.groupby(industry_keys)["cik"].transform("size")
    # dropna=False keeps rows without a bucket; they cannot use it anyway.
    size_count = peers_df.groupby(size_keys, dropna=False)["cik"].transform(
        "size"
    )
    use_size = peers_df["size_bucket"].notna() & (size_count >= min_size)

    industry_text = peers_df["industry"].astype(int).astype(str).str.zfill(2)
    peers_df["peer_group"] = ("SIC " + industry_text).where(
        ~use_size, "SIC " + industry_text + " " + peers_df["size_bucket"]
    )
    peers_df["peer_group"] = peers_df["peer_group"].astype("string")
    peers_df["peer_group_level"] = pd.Series(
        np.where(use_size, LEVEL_INDUSTRY_SIZE, LEVEL_INDUSTRY),
        index=peers_df.index,
        dtype="string",
    )
    peers_df["peer_group_size"] = (
        size_count.where(use_size, industry_count)
    ).astype("int64")
    # industry and size_bucket stay for add_percentile_ranks, which
    # drops them once the ranks are computed.
    return peers_df


def percentile_within(values):
    """Return 0-100 percentile ranks for one peer group's values.

    (average rank - 1) / (number of valid values - 1) * 100: the share of
    the other ranked companies with a lower value, ties counting half.
    """
    valid_count = values.notna().sum()
    if valid_count < 2:
        return pd.Series(np.nan, index=values.index)
    ranks = values.rank(method="average")
    return (ranks - 1) / (valid_count - 1) * 100


def add_percentile_ranks(peers_df):
    """Add one <score>_pctile column per score in RANKED_SCORES.

    Ranks are computed both within the industry-size group and within
    the whole industry, and each row takes the one its peer_group_level
    names. (Grouping on the peer_group label alone would be wrong: a
    fallback company labelled "SIC 35" must be ranked against all of
    industry 35 that year, not only against other fallback companies.)
    """
    ranked_df = peers_df.copy()
    use_size = ranked_df["peer_group_level"] == LEVEL_INDUSTRY_SIZE
    industry_keys = [ranked_df["industry"], ranked_df["fiscal_year"]]
    size_keys = industry_keys + [ranked_df["size_bucket"]]
    for score in RANKED_SCORES:
        values = ranked_df[score].astype("float64")
        within_industry = values.groupby(
            industry_keys, group_keys=False
        ).apply(percentile_within)
        within_size = values.groupby(
            size_keys, group_keys=False, dropna=False
        ).apply(percentile_within)
        ranked_df[percentile_column(score)] = within_size.where(
            use_size, within_industry
        )
    return ranked_df.drop(columns=["industry", "size_bucket"])
