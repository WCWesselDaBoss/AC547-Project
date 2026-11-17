"""Build the score_drivers table: what pushes each M-Score up.

Usage:
    python -m src.scores.drivers            # data/processed/
    python -m src.scores.drivers --sample   # data/sample/

Ranking rule (CLAUDE.md section 4, "How `score_drivers` ranks the
M-Score components"):
- contribution = coefficient x (index - 1) for the seven ratio indexes,
  where 1 means "unchanged from last year", and coefficient x TATA for
  TATA (TATA is already a level, with 0 meaning profit equals cash);
- keep the components with a positive contribution (pushing the score
  toward the warning zone), at most config.MAX_DRIVERS per company-year,
  largest first;
- attach the approved sentence from explanations.py.

Why "distance from no change": the M-Score can be rewritten as
    M = BASELINE + sum of all 8 contributions,
where BASELINE = intercept + the seven ratio coefficients (a company
whose ratios are all unchanged and whose profit equals its cash). So
the contributions add up exactly to how far M sits from that baseline,
and the drivers are the biggest parts of that distance.

Only company-years with an M-Score get drivers (all 8 indexes known).
A neutral SGAI or LVGI of 1 contributes exactly 0, so the neutral-value
rule can never create a driver.
"""

import argparse

import pandas as pd

import config
from src.scores import explanations

# Component names as shown to users, keyed by scores-table column.
COMPONENTS = {
    "dsri": "DSRI",
    "gmi": "GMI",
    "aqi": "AQI",
    "sgi": "SGI",
    "depi": "DEPI",
    "sgai": "SGAI",
    "tata": "TATA",
    "lvgi": "LVGI",
}
# TATA is a level, not a ratio of this year to last year, so its
# "no change" point is 0, not 1.
NO_CHANGE = {column: 1.0 for column in COMPONENTS}
NO_CHANGE["tata"] = 0.0

DRIVER_COLUMNS = [
    "cik",
    "fiscal_year",
    "driver_rank",
    "component",
    "component_value",
    "contribution",
    "explanation",
]
DRIVER_TYPES = {
    "cik": "int64",
    "fiscal_year": "int64",
    "driver_rank": "int64",
    "component": "string",
    "component_value": "float64",
    "contribution": "float64",
    "explanation": "string",
}


def m_score_baseline():
    """Return M when every ratio index is 1 and TATA is 0 (about -2.48).

    intercept + sum of the seven ratio coefficients. Used to show that
    M = baseline + sum of contributions.
    """
    ratio_coefficients = [
        value
        for name, value in config.BENEISH_COEFFICIENTS.items()
        if name != "tata"
    ]
    return config.BENEISH_INTERCEPT + sum(ratio_coefficients)


def contributions(scores_df):
    """Return one column per component: coefficient x (index - no change).

    Rows without an M-Score are dropped, because a ranking of a score
    that does not exist would be meaningless.
    """
    scored = scores_df[scores_df["m_score"].notna()]
    result = scored[["cik", "fiscal_year"]].copy()
    for column in COMPONENTS:
        coefficient = config.BENEISH_COEFFICIENTS[column]
        result[column] = coefficient * (scored[column] - NO_CHANGE[column])
    return result


def build_score_drivers(scores_df):
    """Return the score_drivers table (section 4 columns and types)."""
    contribution_df = contributions(scores_df)
    long_df = contribution_df.melt(
        id_vars=["cik", "fiscal_year"],
        value_vars=list(COMPONENTS),
        var_name="column",
        value_name="contribution",
    )
    long_df = long_df[
        long_df["contribution"] > config.DRIVER_MIN_CONTRIBUTION
    ].copy()
    # Ties are broken by the fixed component order, so the ranking never
    # depends on row order.
    long_df["component_order"] = long_df["column"].map(
        {column: i for i, column in enumerate(COMPONENTS)}
    )
    long_df = long_df.sort_values(
        ["cik", "fiscal_year", "contribution", "component_order"],
        ascending=[True, True, False, True],
    )
    long_df["driver_rank"] = (
        long_df.groupby(["cik", "fiscal_year"]).cumcount() + 1
    )
    long_df = long_df[long_df["driver_rank"] <= config.MAX_DRIVERS]

    values = scores_df.set_index(["cik", "fiscal_year"])
    long_df["component_value"] = [
        values.at[(cik, year), column]
        for cik, year, column in zip(
            long_df["cik"], long_df["fiscal_year"], long_df["column"]
        )
    ]
    long_df["component"] = long_df["column"].map(COMPONENTS)
    long_df["explanation"] = long_df["component"].map(explanations.explain)
    return (
        long_df[DRIVER_COLUMNS]
        .astype(DRIVER_TYPES)
        .sort_values(["cik", "fiscal_year", "driver_rank"])
        .reset_index(drop=True)
    )


def summary(scores_df, drivers_df):
    """Return (metric, count) rows for the log and the README."""
    with_m = int(scores_df["m_score"].notna().sum())
    per_year = drivers_df.groupby(["cik", "fiscal_year"]).size()
    rows = [
        ("company_years_with_m_score", with_m),
        ("company_years_with_drivers", int(len(per_year))),
        ("company_years_with_no_positive_component", with_m - len(per_year)),
        ("driver_rows", len(drivers_df)),
    ]
    rank_one = drivers_df[drivers_df["driver_rank"] == 1]
    rows += [
        (f"top_driver_{component}", int(count))
        for component, count in rank_one["component"].value_counts().items()
    ]
    return rows


def main(argv=None):
    """Build score_drivers from data/processed/ (or data/sample/)."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sample", action="store_true")
    args = parser.parse_args(argv)
    if args.sample:
        scores_path = config.SAMPLE_DIR / "scores.parquet"
        output_path = config.SAMPLE_DIR / "score_drivers.parquet"
        log_path = config.LOG_DIR / "score_drivers_sample_log.csv"
    else:
        scores_path = config.SCORES_PATH
        output_path = config.SCORE_DRIVERS_PATH
        log_path = config.LOG_DIR / "score_drivers_log.csv"

    scores_df = pd.read_parquet(scores_path)
    drivers_df = build_score_drivers(scores_df)
    drivers_df.to_parquet(output_path, index=False)
    log_df = pd.DataFrame(
        summary(scores_df, drivers_df), columns=["metric", "count"]
    )
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_df.to_csv(log_path, index=False)
    print(log_df.to_string(index=False))
    print(f"Wrote {len(drivers_df)} rows to {output_path}")


if __name__ == "__main__":
    main()
