"""Quarterly upgrade, step 6: the quarterly tables for the committed sample.

data/sample/ lets a fresh clone run the app without data/processed/
(CLAUDE.md section 4). This module adds the quarterly tables for the SAME
companies as the annual sample, which it reads from
data/sample/companies.parquet (written by src/pipeline/sample.py, which
is not changed), so the two modes always show the same companies:

- facts_quarterly, financials_ttm and ttm_sources are copied, cut down to
  those companies, from data/processed/;
- scores_quarterly and score_drivers_quarterly are then computed FROM the
  sample tables (python -m src.scores.quarterly_scores --sample), as the
  annual sample scores are, so a fresh clone can reproduce them. Peer
  ranks on about 50 companies are illustrative only.

Run: python -m src.pipeline.quarterly_sample
"""

import pandas as pd

import config
from src.pipeline import quarterly, ttm

SAMPLE_TABLES = {
    "facts_quarterly": quarterly.FACTS_QUARTERLY_PATH,
    "financials_ttm": ttm.TTM_PATH,
    "ttm_sources": ttm.TTM_SOURCES_PATH,
}


def sample_ciks(sample_dir=config.SAMPLE_DIR):
    """Return the CIKs of the annual sample (data/sample/companies)."""
    companies = pd.read_parquet(
        sample_dir / "companies.parquet", columns=["cik"]
    )
    return sorted(companies["cik"].unique().tolist())


def cut_table(path, ciks):
    """Return one processed table cut down to the given companies, read
    with a filter so the full table is never loaded at once."""
    table = pd.read_parquet(path, filters=[("cik", "in", list(ciks))])
    return table.reset_index(drop=True)


def build_quarterly_sample(sample_dir=config.SAMPLE_DIR, tables=SAMPLE_TABLES):
    """Write the sample's quarterly tables to sample_dir; return {name:
    rows}."""
    ciks = sample_ciks(sample_dir)
    written = {}
    for name, path in tables.items():
        table = cut_table(path, ciks)
        table.to_parquet(sample_dir / f"{name}.parquet", index=False)
        written[name] = len(table)
    return written


def main():
    """Write the quarterly sample tables and print their sizes."""
    for name, rows in build_quarterly_sample().items():
        print(f"  {name}: {rows:,} rows")
    print(f"Quarterly sample tables written to {config.SAMPLE_DIR}")


if __name__ == "__main__":
    main()
