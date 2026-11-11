"""Map each standard line item to an ordered list of us-gaap XBRL tags.

Companies choose among several tags for the same concept (for example,
revenue moved from SalesRevenueNet to RevenueFromContractWithCustomer...
when ASC 606 took effect). For each company-year we use the FIRST tag in
the list that has a value, so the order expresses our preference.

A tag is added here only with evidence that it means the same thing as the
tags already listed (see the coverage report in tag_coverage.py and
docs/methodology.md). Line items are the inputs to the CLAUDE.md
section 5 formulas plus the section 2 size floor.
"""

# Period types. "duration" items (income statement, cash flow) cover a
# fiscal year; "instant" items (balance sheet) are measured on one date.
DURATION = "duration"
INSTANT = "instant"

LINE_ITEMS = {
    # ---- Income statement (duration) -------------------------------------
    "revenue": {
        "tags": [
            "Revenues",
            "RevenueFromContractWithCustomerExcludingAssessedTax",
            "SalesRevenueNet",
            # Evidence: agrees with the tags above in 65.8% of 3,226
            # company-years where both are reported; the gap is sales and
            # excise tax included in this tag. Last, so it fills gaps only
            # (2,301 company-years).
            "RevenueFromContractWithCustomerIncludingAssessedTax",
        ],
        "period": DURATION,
        "unit": "USD",
        "used_by": "M-Score DSRI GMI SGI SGAI; F-Score 8, 9; size floor",
    },
    "cost_of_revenue": {
        "tags": [
            "CostOfRevenue",
            "CostOfGoodsAndServicesSold",
            "CostOfGoodsSold",
        ],
        "period": DURATION,
        "unit": "USD",
        "used_by": "M-Score GMI; F-Score 8",
    },
    "sga": {
        "tags": ["SellingGeneralAndAdministrativeExpense"],
        "period": DURATION,
        "unit": "USD",
        "used_by": "M-Score SGAI",
    },
    "depreciation": {
        "tags": [
            "DepreciationDepletionAndAmortization",
            "DepreciationAndAmortization",
            "Depreciation",
        ],
        "period": DURATION,
        "unit": "USD",
        "used_by": "M-Score DEPI",
    },
    "operating_income": {
        "tags": ["OperatingIncomeLoss"],
        "period": DURATION,
        "unit": "USD",
        "used_by": "Z'' X3 (EBIT proxy)",
    },
    "income_continuing_ops": {
        "tags": ["IncomeLossFromContinuingOperations"],
        "period": DURATION,
        "unit": "USD",
        "used_by": "M-Score TATA",
    },
    "net_income": {
        "tags": ["NetIncomeLoss"],
        "period": DURATION,
        "unit": "USD",
        "used_by": "F-Score 1, 3, 4; accruals; cash conversion",
    },
    # ---- Cash flow statement (duration) ----------------------------------
    "cfo": {
        "tags": [
            "NetCashProvidedByUsedInOperatingActivities",
            # Evidence: agrees in 68.3% of 9,667 company-years; it differs
            # only by discontinued operations' cash flow, which is also
            # excluded from TATA's income measure. Fills 5,965.
            "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
        ],
        "period": DURATION,
        "unit": "USD",
        "used_by": "M-Score TATA; F-Score 2, 4; accruals; cash conversion",
    },
    # ---- Balance sheet (instant) -----------------------------------------
    "receivables": {
        "tags": [
            "AccountsReceivableNetCurrent",
            # Evidence: agrees in 65.2% of 2,607 company-years; used by
            # companies whose balance sheet does not split current and
            # noncurrent. Fills 2,072.
            "AccountsReceivableNet",
        ],
        "period": INSTANT,
        "unit": "USD",
        "used_by": "M-Score DSRI",
    },
    "current_assets": {
        "tags": ["AssetsCurrent"],
        "period": INSTANT,
        "unit": "USD",
        "used_by": "M-Score AQI; Z'' X1; F-Score 6",
    },
    "ppe_net": {
        "tags": ["PropertyPlantAndEquipmentNet"],
        "period": INSTANT,
        "unit": "USD",
        "used_by": "M-Score AQI, DEPI",
    },
    "total_assets": {
        "tags": [
            "Assets",
            # Evidence: agrees in 99.9% of 64,632 company-years (assets =
            # liabilities + equity, an accounting identity). Fills 256.
            "LiabilitiesAndStockholdersEquity",
        ],
        "period": INSTANT,
        "unit": "USD",
        "used_by": "every score; size floor",
    },
    "current_liabilities": {
        "tags": ["LiabilitiesCurrent"],
        "period": INSTANT,
        "unit": "USD",
        "used_by": "M-Score LVGI; Z'' X1; F-Score 6",
    },
    "long_term_debt": {
        "tags": ["LongTermDebtNoncurrent"],
        "period": INSTANT,
        "unit": "USD",
        "used_by": "M-Score LVGI; F-Score 5",
    },
    "total_liabilities": {
        "tags": ["Liabilities"],
        "period": INSTANT,
        "unit": "USD",
        "used_by": "Z'' X4",
    },
    "retained_earnings": {
        "tags": ["RetainedEarningsAccumulatedDeficit"],
        "period": INSTANT,
        "unit": "USD",
        "used_by": "Z'' X2",
    },
    "stockholders_equity": {
        "tags": ["StockholdersEquity"],
        "period": INSTANT,
        "unit": "USD",
        "used_by": "Z'' X4",
    },
    "shares_outstanding": {
        # Counted in shares, not dollars, so this item is the one exception
        # to the USD-only rule when facts_long is built.
        "tags": ["CommonStockSharesOutstanding"],
        "period": INSTANT,
        "unit": "shares",
        "used_by": "F-Score 7",
    },
}

# ---- Components used only by derivations (see derived_items.py) ----------
# They become financials_annual columns too, so every derived value can be
# traced to the reported facts it was calculated from.
COMPONENT_ITEMS = {
    "income_discontinued_ops": {
        "tags": [
            # Attributable to the parent first, to match NetIncomeLoss.
            "IncomeLossFromDiscontinuedOperationsNetOfTaxAttributableToReportingEntity",
            "IncomeLossFromDiscontinuedOperationsNetOfTax",
        ],
        "period": DURATION,
        "unit": "USD",
        "used_by": "derive income_continuing_ops",
    },
    "liabilities_and_equity": {
        "tags": ["LiabilitiesAndStockholdersEquity"],
        "period": INSTANT,
        "unit": "USD",
        "used_by": "derive total_liabilities",
    },
    "equity_including_nci": {
        "tags": [
            "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"
        ],
        "period": INSTANT,
        "unit": "USD",
        "used_by": "derive total_liabilities",
    },
    "temporary_equity_total": {
        "tags": [
            "TemporaryEquityCarryingAmountIncludingPortionAttributableToNoncontrollingInterests"
        ],
        "period": INSTANT,
        "unit": "USD",
        "used_by": "derive total_liabilities",
    },
    "temporary_equity_parent": {
        "tags": ["TemporaryEquityCarryingAmountAttributableToParent"],
        "period": INSTANT,
        "unit": "USD",
        "used_by": "derive total_liabilities",
    },
    "redeemable_nci": {
        "tags": ["RedeemableNoncontrollingInterestEquityCarryingAmount"],
        "period": INSTANT,
        "unit": "USD",
        "used_by": "derive total_liabilities",
    },
}

# Every item that gets a column, in output order.
ALL_ITEMS = {**LINE_ITEMS, **COMPONENT_ITEMS}

# Name patterns used ONLY to find candidate tags for the coverage report.
# A tag matching a pattern is not used for anything until it has been
# reviewed and moved into LINE_ITEMS above.
CANDIDATE_PATTERNS = {
    "revenue": r"Revenue|Sales",
    "cost_of_revenue": r"^Cost",
    "sga": r"GeneralAndAdministrative|SellingAndMarketing|Selling",
    "depreciation": r"Depreciation|Amortization",
    "operating_income": r"OperatingIncome|IncomeLossFromContinuingOperations",
    "income_continuing_ops": r"ContinuingOperations|NetIncomeLoss|ProfitLoss",
    "net_income": r"NetIncomeLoss|ProfitLoss",
    "cfo": r"OperatingActivities",
    "receivables": r"Receivable",
    "current_assets": r"AssetsCurrent",
    "ppe_net": r"PropertyPlantAndEquipment",
    "total_assets": r"^Assets|LiabilitiesAndStockholdersEquity",
    "current_liabilities": r"LiabilitiesCurrent",
    "long_term_debt": r"LongTermDebt|Notes|Borrowings|SeniorDebt",
    "total_liabilities": r"^Liabilities",
    "retained_earnings": r"RetainedEarnings|AccumulatedDeficit",
    "stockholders_equity": r"StockholdersEquity|PartnersCapital|MembersEquity",
    "shares_outstanding": r"SharesOutstanding|SharesIssued",
}

# Extra name patterns collected so derivations can be tested against real
# data (discontinued operations, temporary/redeemable equity). Like the
# candidate patterns, they change nothing until reviewed.
SUPPORT_PATTERNS = {
    "discontinued_ops": r"DiscontinuedOperation",
    "temporary_equity": r"TemporaryEquity|RedeemableNoncontrollingInterest",
}


def all_mapped_tags():
    """Return the set of every tag used by any line item."""
    return {tag for item in ALL_ITEMS.values() for tag in item["tags"]}


def pick_first_tag(available_tags, line_item, tag_order=None):
    """Return the first tag in the line item's list that is available.

    tag_order overrides the map's order (see company_tag_order). Returns
    None if no mapped tag is available, which means the line item is
    missing for that company-year (never estimated).
    """
    for tag in tag_order or ALL_ITEMS[line_item]["tags"]:
        if tag in available_tags:
            return tag
    return None


def company_tag_order(years_reported_by_tag, line_item):
    """Return the mapped tags in the order one company should use them.

    years_reported_by_tag maps tag -> number of fiscal years the company
    reports it. The tag the company uses in the most years comes first;
    ties keep the map's order. Why: the scores compare year t with t-1, so
    switching tags between years (for example, depreciation-and-
    amortization one year, depreciation only the next) can move a ratio
    with no change in the business. Using each company's most consistent
    tag keeps its own years comparable; other tags fill only real gaps.
    """
    map_order = ALL_ITEMS[line_item]["tags"]
    return sorted(
        map_order,
        key=lambda tag: (
            -years_reported_by_tag.get(tag, 0),
            map_order.index(tag),
        ),
    )
