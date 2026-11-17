"""Plain-English verdict columns: f_band and flags_raised.

CLAUDE.md section 4, "Verdict columns in `scores`". These columns only
restate the three model outputs for display; they never combine the
models into one weighted score, because no published method supports a
weighting.

- f_band: "weak" (F-Score 0-3), "middle" (4-6) or "strong" (7-9). The
  edges are config.F_SCORE_WEAK_MAX and config.F_SCORE_STRONG_MIN. A
  team display convention, not Piotroski's.
- flags_raised: how many of three checks show a warning, 0 to 3:
  m_flag True (M-Score above the cutoff), z_zone "distress", f_band
  "weak". A check without a score cannot show a warning, so it counts
  as no warning; the column is null only when NONE of the three checks
  has a score, because then "0 warnings" would claim an all-clear that
  was never tested. The dashboard should show missing_inputs beside it.
"""

import pandas as pd

import config

WEAK, MIDDLE, STRONG = "weak", "middle", "strong"


def f_band(f_scores):
    """Return 'weak', 'middle' or 'strong' per F-Score; NA if no score."""
    band = pd.Series(pd.NA, index=f_scores.index, dtype="string")
    band[f_scores <= config.F_SCORE_WEAK_MAX] = WEAK
    band[
        (f_scores > config.F_SCORE_WEAK_MAX)
        & (f_scores < config.F_SCORE_STRONG_MIN)
    ] = MIDDLE
    band[f_scores >= config.F_SCORE_STRONG_MIN] = STRONG
    # Comparisons with NA give NA, and assigning through an NA mask is
    # skipped, so rows without an F-Score stay NA.
    band[f_scores.isna()] = pd.NA
    return band


def flags_raised(m_flags, z_zones, f_bands):
    """Return the number of warnings (0-3) as nullable Int64.

    Each argument is the scores-table column of the same name. NA only
    when none of the three checks has a value.
    """
    warnings = pd.DataFrame(
        {
            "m": m_flags.fillna(False).astype(bool),
            "z": (z_zones == "distress").fillna(False).astype(bool),
            "f": (f_bands == WEAK).fillna(False).astype(bool),
        }
    )
    count = warnings.sum(axis=1).astype("Int64")
    no_check = m_flags.isna() & z_zones.isna() & f_bands.isna()
    count[no_check] = pd.NA
    return count


def add_verdicts(scores_df):
    """Return scores_df with f_band and flags_raised added."""
    verdict_df = scores_df.copy()
    verdict_df["f_band"] = f_band(verdict_df["f_score"])
    verdict_df["flags_raised"] = flags_raised(
        verdict_df["m_flag"], verdict_df["z_zone"], verdict_df["f_band"]
    )
    return verdict_df
