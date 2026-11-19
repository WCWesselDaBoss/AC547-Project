"""Public float from each 10-K's cover page, for the backtest's value tilt.

dei:EntityPublicFloat is the market value of the shares held by
non-insiders on the last business day of the company's second fiscal
quarter, reported on the cover of every 10-K. It is a point-in-time
market value that is known when the 10-K is filed, which makes it a
usable denominator for book-to-market. Adjusted closing prices are not,
because they are scaled for splits and dividends that happen later.

The value is read directly from the SEC bulk file data/raw/companyfacts.zip
(downloaded by Phase 1) rather than from facts_long, which keeps only
the mapped financial-statement line items; no Phase 1 table changes.
Each value keeps its accession number, so it traces to the filing.
The extract is cached in data/interim/public_float.parquet.
"""

import json
import zipfile

import pandas as pd

import config

PUBLIC_FLOAT_PATH = config.INTERIM_DIR / "public_float.parquet"
FLOAT_COLUMNS = ["cik", "accession", "period_end", "public_float"]
TEN_K_FORMS = ("10-K", "10-K/A")


def float_rows(company_facts, cik):
    """Return the public-float facts in one company's companyfacts JSON:
    one row per 10-K fact in US dollars (cik, accession, period_end,
    public_float)."""
    facts = company_facts.get("facts", {}).get("dei", {})
    units = facts.get("EntityPublicFloat", {}).get("units", {})
    rows = [
        (cik, fact["accn"], fact["end"], float(fact["val"]))
        for fact in units.get("USD", [])
        if fact.get("form") in TEN_K_FORMS
    ]
    frame = pd.DataFrame(rows, columns=FLOAT_COLUMNS)
    frame["period_end"] = pd.to_datetime(frame["period_end"])
    return frame


def extract_public_float(zip_path, ciks):
    """Return every 10-K public-float fact for the given companies."""
    frames = []
    with zipfile.ZipFile(zip_path) as archive:
        names = set(archive.namelist())
        for cik in ciks:
            name = f"CIK{int(cik):010d}.json"
            if name in names:
                frames.append(
                    float_rows(json.loads(archive.read(name)), int(cik))
                )
    floats = pd.concat(frames, ignore_index=True)
    return floats.astype(
        {
            "cik": "int64",
            "accession": "string",
            "period_end": "datetime64[ns]",
            "public_float": "float64",
        }
    )


def float_per_filing(floats_df):
    """Return one public float per (cik, accession).

    A 10-K occasionally repeats an earlier year's float; the value with
    the latest period_end is the one that filing reports for itself.
    Several values on that same date (one per share class) are added
    together, because the float is the value of all non-insider shares.
    """
    latest_end = floats_df.groupby(["cik", "accession"])[
        "period_end"
    ].transform("max")
    current = floats_df[floats_df["period_end"] == latest_end]
    current = current.drop_duplicates()
    return (
        current.groupby(["cik", "accession", "period_end"], as_index=False)[
            "public_float"
        ]
        .sum()
        .rename(columns={"period_end": "float_date"})
    )


def load_public_float(ciks, refresh=False):
    """Return float_per_filing for the given companies, from the cache
    unless refresh is True or the cache is missing."""
    if PUBLIC_FLOAT_PATH.exists() and not refresh:
        return float_per_filing(pd.read_parquet(PUBLIC_FLOAT_PATH))
    floats = extract_public_float(config.COMPANYFACTS_ZIP, ciks)
    config.INTERIM_DIR.mkdir(parents=True, exist_ok=True)
    floats.to_parquet(PUBLIC_FLOAT_PATH, index=False)
    return float_per_filing(floats)
