"""Plain-English sentences for the M-Score drivers (score_drivers table).

One fixed sentence per M-Score component, approved by the team on
2026-11-17. The dashboard only displays these sentences and never
writes its own (CLAUDE.md section 4), so every explanation a user sees
is reviewed text that traces to this file.

Each sentence describes the direction that pushes the M-Score toward
the warning zone, because score_drivers keeps only positive
contributions:
- DSRI, GMI, AQI, SGI, DEPI have positive coefficients, so they drive
  the score when the index is above 1 (the ratio rose).
- SGAI and LVGI have NEGATIVE coefficients in Beneish (1999), so they
  drive the score when the index is BELOW 1 (the ratio fell). Their
  coefficients were not statistically significant in Beneish's Table 3
  (t = -0.71 and -1.22), which is why their sentences call them weak
  patterns rather than warning signs.
- TATA drives the score when it is above 0 (profit above cash).
"""

COMPONENT_SENTENCES = {
    "DSRI": (
        "Money owed to the company by customers grew faster than its "
        "sales, which can mean some sales were recorded before "
        "customers actually paid for them."
    ),
    "GMI": (
        "The company kept less of each sales dollar after paying the "
        "direct cost of what it sold than it did a year earlier, and "
        "shrinking margins can pressure managers to make results look "
        "better."
    ),
    "AQI": (
        "A larger share of the company's assets is now in hard-to-value "
        "items such as intangibles or deferred costs, which can mean "
        "some spending is being recorded as an asset instead of an "
        "expense."
    ),
    "SGI": (
        "Sales grew compared with last year; growth is not a problem in "
        "itself, but fast-growing companies face pressure to keep the "
        "pace, and the model treats growth as a risk factor."
    ),
    "DEPI": (
        "The company is spreading the cost of its buildings and "
        "equipment over a longer time than last year, which lowers "
        "yearly expenses and raises reported profit without any change "
        "in the business."
    ),
    "SGAI": (
        "Selling and overhead costs fell as a share of sales; in the "
        "1999 model this slightly raises the score, but it is a weak "
        "statistical pattern from the original study, not a warning "
        "sign by itself."
    ),
    "TATA": (
        "Reported profit was higher than the cash the business actually "
        "brought in, so more of the profit depends on accounting "
        "estimates rather than money received."
    ),
    "LVGI": (
        "The company's debts fell relative to its total assets; in the "
        "1999 model this slightly raises the score, but like the "
        "overhead measure it is a weak statistical pattern, not a "
        "warning sign by itself."
    ),
}


def explain(component):
    """Return the approved sentence for an M-Score component, e.g. 'DSRI'.

    Raises KeyError for an unknown component, so a typo can never show
    an empty or invented explanation on the dashboard.
    """
    return COMPONENT_SENTENCES[component]
