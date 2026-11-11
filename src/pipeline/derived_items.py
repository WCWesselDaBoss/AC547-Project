"""Calculate two line items from other reported facts when not tagged.

Both rules were adopted on evidence from the coverage report (see
docs/methodology.md). A calculated value is used ONLY when the item's own
tag is missing, and every calculated value is named in the
derived_items column so it is never mistaken for a reported figure.

Input and output are "wide" DataFrames: one row per company-year, one
column per line item (the names in tag_map.ALL_ITEMS).
"""

import pandas as pd

# Separator for the derived_items column, matching the rest of the project.
SEPARATOR = "; "


def derive_income_continuing_ops(wide_df):
    """Return (values, was_derived) for income from continuing operations.

    Rule: net income minus income from discontinued operations. A missing
    discontinued-operations line is treated as none, because companies
    must show discontinued operations as a separate income statement line
    when they have them.

    Evidence (Nov 2026 data): where both are reported, this matches the
    tagged value in 79% of company-years with discontinued operations and
    70% without. Moderate, so every use is flagged.
    """
    tagged = wide_df["income_continuing_ops"]
    calculated = wide_df["net_income"] - wide_df[
        "income_discontinued_ops"
    ].fillna(0)
    was_derived = tagged.isna() & wide_df["net_income"].notna()
    return tagged.where(~was_derived, calculated), was_derived


def derive_total_liabilities(wide_df):
    """Return (values, was_derived) for total liabilities.

    Rule: total liabilities and equity, minus equity including minority
    (noncontrolling) interests, minus temporary (mezzanine) equity. Many
    balance sheets never show a total-liabilities line, but every one
    balances, so the total can be recovered from reported facts.

    Equity falls back to parent-only equity when no minority-interest
    total is reported. Temporary equity uses the combined tag if present,
    otherwise parent plus redeemable minority interest; missing parts
    count as zero because temporary equity is shown on the balance sheet
    whenever it exists.

    Evidence: matches the tagged value in 95.6% of 50,146 company-years.
    """
    tagged = wide_df["total_liabilities"]
    equity = wide_df["equity_including_nci"].fillna(
        wide_df["stockholders_equity"]
    )
    temporary = wide_df["temporary_equity_total"].fillna(
        wide_df["temporary_equity_parent"].fillna(0)
        + wide_df["redeemable_nci"].fillna(0)
    )
    calculated = wide_df["liabilities_and_equity"] - equity - temporary
    was_derived = tagged.isna() & calculated.notna()
    return tagged.where(~was_derived, calculated), was_derived


# Item name -> function. Order does not matter; neither uses the other.
DERIVATIONS = {
    "income_continuing_ops": derive_income_continuing_ops,
    "total_liabilities": derive_total_liabilities,
}


def apply_derivations(wide_df):
    """Return a copy with gaps filled and a derived_items text column.

    derived_items lists which line items in that row were calculated
    (e.g. "total_liabilities"), or is null when every value was reported.
    """
    result = wide_df.copy()
    flags = pd.DataFrame(index=wide_df.index)
    for item, derive in DERIVATIONS.items():
        result[item], flags[item] = derive(wide_df)
    result["derived_items"] = flags.apply(
        lambda row: SEPARATOR.join(row.index[row]) or None, axis=1
    ).astype("string")
    return result
