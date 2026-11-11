"""Build the companies table (CLAUDE.md section 4).

One row per company with XBRL data: cik, name, sic, sic_description,
ticker, is_excluded and exclusion_reason. Excluded companies are kept and
labeled, never deleted, so every exclusion can be counted (section 6).

Run on its own with:
    python -m src.pipeline.companies
"""

import json
import zipfile

import pandas as pd

import config

# Exclusion reason labels. They are written into the table and the log, so
# they are spelled out rather than coded as numbers.
REASON_FINANCIAL_SIC = "financial_sic_6000_6799"
REASON_SIC_MISSING = "sic_missing"
REASON_NO_10K = "no_10k_filings"

# Separator when a company has more than one exclusion reason. Keeping all
# reasons (not just the first) means each rule's count is complete.
REASON_SEPARATOR = "; "


def cik_from_member_name(member_name):
    """Return the integer CIK from a bulk-file name like CIK0000320193.json."""
    return int(member_name[3:13])


def submissions_member_name(cik):
    """Return the submissions file name for a CIK (zero-padded to 10)."""
    return f"CIK{cik:010d}.json"


def list_companyfacts_ciks(companyfacts_zip):
    """Return the sorted CIKs that have a file in companyfacts.zip.

    Only the ZIP's table of contents is read, not the 19.5 GB of facts.
    """
    with zipfile.ZipFile(companyfacts_zip) as archive:
        return sorted(
            cik_from_member_name(name)
            for name in archive.namelist()
            if name.startswith("CIK") and name.endswith(".json")
        )


def parse_sic(raw_sic):
    """Return the SIC code as an int, or None if blank or not numeric."""
    if raw_sic is None:
        return None
    text = str(raw_sic).strip()
    return int(text) if text.isdigit() else None


def is_financial_sic(sic):
    """Return True if the SIC code is in the excluded 6000-6799 range."""
    if sic is None:
        return False
    return config.EXCLUDED_SIC_MIN <= sic <= config.EXCLUDED_SIC_MAX


def pick_ticker(tickers):
    """Return the first ticker SEC lists, or None if there are none.

    Delisted companies usually have no ticker in SEC's data. We leave them
    blank rather than guess, because a wrong ticker would attach another
    company's prices (CLAUDE.md section 6, No silent fixes).
    """
    if not tickers:
        return None
    return tickers[0]


def has_annual_report(forms):
    """Return True if any form in the list is a 10-K or 10-K/A."""
    return any(form in config.ANNUAL_FORMS for form in forms)


def filed_annual_report(submission, archive):
    """Return True if the company ever filed a 10-K or 10-K/A.

    SEC keeps only about the latest 1,000 filings in "recent"; older ones
    sit in overflow files. A long-lived company whose recent filings are
    all 8-Ks and Form 4s would be wrongly excluded without the overflow
    check, so we read those files whenever "recent" has no 10-K.
    """
    filings = submission.get("filings", {})
    if has_annual_report(filings.get("recent", {}).get("form", [])):
        return True
    for overflow in filings.get("files", []):
        older = json.loads(archive.read(overflow["name"]))
        if has_annual_report(older.get("form", [])):
            return True
    return False


def exclusion_reasons(sic, filed_10k):
    """Return the list of exclusion reasons for one company (empty = keep)."""
    reasons = []
    if sic is None:
        reasons.append(REASON_SIC_MISSING)
    elif is_financial_sic(sic):
        reasons.append(REASON_FINANCIAL_SIC)
    if not filed_10k:
        reasons.append(REASON_NO_10K)
    return reasons


def build_company_row(cik, submission, archive):
    """Return one companies-table row (a dict) from a submissions record."""
    sic = parse_sic(submission.get("sic"))
    reasons = exclusion_reasons(sic, filed_annual_report(submission, archive))
    return {
        "cik": cik,
        "name": submission.get("name"),
        "sic": sic,
        # Blank descriptions become null so "missing" has one meaning.
        "sic_description": submission.get("sicDescription") or None,
        "ticker": pick_ticker(submission.get("tickers")),
        "is_excluded": bool(reasons),
        "exclusion_reason": REASON_SEPARATOR.join(reasons) or None,
        # Helper for the log only; dropped before the table is saved
        # because it is not in the section 4 contract.
        "_ticker_count": len(submission.get("tickers") or []),
    }


def build_companies(companyfacts_zip, submissions_zip):
    """Return (companies DataFrame, ticker-count Series) for every CIK.

    The universe is every company with an XBRL companyfacts file. Each one
    is looked up in submissions.zip for its name, SIC and filing history.
    """
    rows = []
    with zipfile.ZipFile(submissions_zip) as archive:
        available = set(archive.namelist())
        for cik in list_companyfacts_ciks(companyfacts_zip):
            member = submissions_member_name(cik)
            if member not in available:
                # Never happened on the Nov 2026 download, but if SEC adds
                # a company to one file before the other we must not crash
                # or silently skip it: it is kept and labeled.
                rows.append(
                    {
                        "cik": cik,
                        "name": None,
                        "sic": None,
                        "sic_description": None,
                        "ticker": None,
                        "is_excluded": True,
                        "exclusion_reason": "no_submissions_record",
                        "_ticker_count": 0,
                    }
                )
                continue
            submission = json.loads(archive.read(member))
            rows.append(build_company_row(cik, submission, archive))

    companies_df = pd.DataFrame(rows)
    ticker_counts = companies_df.pop("_ticker_count")
    companies_df = companies_df.astype(
        {
            "cik": "int64",
            # Nullable integer: blank SIC stays <NA> instead of becoming a
            # float like 3571.0.
            "sic": "Int64",
            "name": "string",
            "sic_description": "string",
            "ticker": "string",
            "is_excluded": "bool",
            "exclusion_reason": "string",
        }
    )
    return companies_df, ticker_counts


def summarize_exclusions(companies_df, ticker_counts):
    """Return a DataFrame of counts for the exclusion log and README.

    A company with two reasons is counted under each, so reason counts can
    add up to more than the excluded total; the total row is exact.
    """
    reason_counts = (
        companies_df["exclusion_reason"]
        .dropna()
        .str.split(REASON_SEPARATOR)
        .explode()
        .value_counts()
    )
    summary_rows = [
        ("companies_with_xbrl_facts", len(companies_df)),
        ("excluded_total", int(companies_df["is_excluded"].sum())),
        ("included_total", int((~companies_df["is_excluded"]).sum())),
    ]
    summary_rows += [
        (f"reason:{reason}", int(count))
        for reason, count in reason_counts.items()
    ]
    included = ~companies_df["is_excluded"]
    summary_rows += [
        (
            "included_without_ticker",
            int(companies_df.loc[included, "ticker"].isna().sum()),
        ),
        (
            "included_with_multiple_tickers",
            int((ticker_counts[included] > 1).sum()),
        ),
    ]
    return pd.DataFrame(summary_rows, columns=["measure", "count"])


def main():
    """Build the companies table and its exclusion log from data/raw/."""
    companies_df, ticker_counts = build_companies(
        config.COMPANYFACTS_ZIP, config.SUBMISSIONS_ZIP
    )
    config.PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    companies_df.to_parquet(config.COMPANIES_PATH, index=False)
    summary_df = summarize_exclusions(companies_df, ticker_counts)
    summary_df.to_csv(config.COMPANIES_EXCLUSION_LOG, index=False)
    print(summary_df.to_string(index=False))


if __name__ == "__main__":
    main()
