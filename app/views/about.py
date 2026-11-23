"""About page: what the tool does, where the data comes from, its limits.

Every number on this page is either read from config.py (rules and
cutoffs) or computed from the loaded tables (app/about_view.py), so the
page is always true for the data on screen. Citations and known
differences from the papers come from docs/methodology.md, where the
team checked each one against the source paper.
"""

import streamlit as st

import config
from app import about_quarterly, about_view, basis, company_view, data
from app import labels

st.title("About and limitations")
st.markdown(labels.APP_TAGLINE)
st.caption(labels.SCOPE_NOTE)

source, _ = data.resolve_data_source()
summary = about_view.data_summary(data.scores(), data.financials_filings())

# ---- The data on screen -----------------------------------------------------
st.subheader("The data on screen")
st.markdown(labels.data_source_note(source, summary["companies"]))
st.markdown(
    f"{summary['companies']:,} companies and {summary['company_years']:,} "
    f"scored company-years, fiscal years {summary['first_year']} to "
    f"{summary['last_year']}. The latest 10-K included was filed on "
    f"{company_view.long_date(summary['latest_filing'])}."
)

# ---- What each score measures -----------------------------------------------
st.subheader("What each score measures")
st.markdown(f"""
- **{labels.COLUMN_LABELS['m_score']}.** {labels.SCORE_HELP['m_score']}
  A warning appears when the score is above
  {config.BENEISH_FLAG_CUTOFF}, the cutoff Beneish (1999) reports for
  investors' relative error costs. Source: Beneish, M. D. (1999), The
  detection of earnings manipulation, *Financial Analysts Journal*
  55(5), 24-36. The screener's alternative of
  {config.BENEISH_ALTERNATE_CUTOFF} is widely used by practitioners but
  does not appear in the paper.
- **{labels.COLUMN_LABELS['z_score']}.** {labels.SCORE_HELP['z_score']}
  Below {config.ALTMAN_Z2_DISTRESS_BELOW:.2f} is the distress zone,
  above {config.ALTMAN_Z2_SAFE_ABOVE:.2f} is safe. Source for the
  coefficients: Altman, E. I. (2000), Predicting financial distress of
  companies: revisiting the Z-Score and ZETA models (NYU Stern working
  paper). The zone cutoffs are widely attributed to Altman, Hartzell and
  Peck (1995); the team has not yet confirmed them in a primary source.
- **{labels.COLUMN_LABELS['f_score']}.** {labels.SCORE_HELP['f_score']}
  Shown as weak ({config.F_SCORE_WEAK_MAX} or fewer), middle or strong
  ({config.F_SCORE_STRONG_MIN} or more); these bands are the team's
  display convention, not Piotroski's. Source: Piotroski, J. D. (2000),
  Value investing: the use of historical financial statement information
  to separate winners from losers, *Journal of Accounting Research* 38
  (Supplement), 1-41.
- **{labels.COLUMN_LABELS['accruals_ratio']}.**
  {labels.SCORE_HELP['accruals_ratio']}
- **{labels.COLUMN_LABELS['cash_conversion']}.**
  {labels.SCORE_HELP['cash_conversion']}

The three checks are never combined into one weighted score, because no
published method supports a weighting. "Checks raising concerns" simply
counts how many of the three show a warning.
""")

# ---- Where the data comes from ----------------------------------------------
st.subheader("Where the data comes from")
bulk_files = ", ".join(f"`{name}`" for name in config.SEC_BULK_FILES)
forms = " and ".join(config.ANNUAL_FORMS)
floor = labels.format_money(config.SIZE_FLOOR_USD, decimals=0)
st.markdown(f"""
- **Source:** the SEC's EDGAR bulk XBRL files ({bulk_files}). Every
  number is a value the company tagged in its own {forms} filing.
- **Numbers as first reported:** each score uses the value from the
  earliest 10-K that reported it, because that is what investors saw at
  the time. Later restatements are kept and shown in the trace panel.
- **Companies included:** US GAAP {forms} filers, including companies
  later delisted. Banks, insurers, REITs and shell companies (SIC
  {config.EXCLUDED_SIC_MIN} to {config.EXCLUDED_SIC_MAX}) and companies
  with no industry code are left out.
- **Size floor:** a company-year is scored only if revenue or total
  assets is at least {floor}, tested separately in each year.
- **Years:** fiscal years {config.FIRST_FISCAL_YEAR} to
  {config.LAST_FISCAL_YEAR}; {config.FIRST_FISCAL_YEAR - 1} is used only
  as the prior year for {config.FIRST_FISCAL_YEAR}.
- **No estimates:** a score is left blank when an input is missing,
  except the neutral substitutions listed under limitations.
""")

# ---- Traceability -----------------------------------------------------------
st.subheader("How to check any number")
st.markdown("""
On a company page, the **🔎 Trace to the 10-K** button under each verdict
(or the **Trace to SEC filing** tab) shows the formula, the stored
result, the Python function that computed it, and every input with its
XBRL tag, filing date, accession number and a link to the filing on
EDGAR. Where a stock price is available, the company page and each case
study also chart it, with a marker on the date each 10-K became public
colored by how many warnings that 10-K raised. All calculations live in
the project's `src/` folder and are covered by automated tests and an
Excel tie-out against the 10-Ks
(`verification/`); this app only displays finished results.
""")

# ---- Limitations ------------------------------------------------------------
st.subheader("Limitations")
scores_df = data.scores()
st.markdown(
    "**Coverage.** Many companies do not tag every input the models "
    "need, so some scores are blank. On the data on screen:"
)
st.dataframe(
    about_view.coverage_table(scores_df), hide_index=True, width="stretch"
)
st.markdown(
    "**Neutral substitutions.** Where the method allows, a missing input "
    "is set to neutral instead of leaving the score blank:"
)
st.dataframe(
    about_view.neutral_substitution_table(scores_df),
    hide_index=True,
    width="stretch",
)
st.markdown("""
**Differences from the original papers.**
- The coefficients were estimated on 1980s and 1990s samples and were
  not re-estimated on this data, so scores rank companies; they are not
  calibrated probabilities.
- Total accruals (TATA) use the cash-flow form, (income from continuing
  operations minus operating cash flow) / total assets; Beneish (1999)
  used a balance-sheet form.
- The Z''-Score uses operating income in place of EBIT, and book equity,
  so large share buybacks (which shrink book equity) can lower it for
  financially strong companies.
- Income from continuing operations and total liabilities are sometimes
  calculated from other reported facts when not tagged; the trace panel
  labels every such value.

**What the checks cannot do.**
- They flag warning signs in reported numbers. They do not predict stock
  returns or prove fraud, and a company with no warnings can still have
  problems: see the case studies, which show misses and companies the
  radar could not score.
- Disclosure problems that do not change the reported numbers (for
  example, what a company says about the drivers of its growth) are
  largely invisible to these models.
- Peer rankings compare a company only with the companies in this data
  set; on the sample they are illustrative.
- Links to EDGAR need an internet connection; everything else works
  offline.

Full details: `docs/methodology.md`.
""")

# ---- Quarterly (TTM) scores -------------------------------------------------
# Shown only when the data on screen has the quarterly tables.
if data.quarterly_available():
    st.subheader("Quarterly (TTM) scores")
    st.warning(basis.QUARTERLY_NOTE, icon=":material/warning:")
    quarterly_df = data.scores_quarterly()
    quarterly = about_quarterly.quarterly_summary(quarterly_df)
    latest_end = company_view.long_date(quarterly["latest_quarter_end"])
    latest_available = company_view.long_date(quarterly["latest_available"])
    st.markdown(f"""
Switch **Scores** in the sidebar to **Quarterly (TTM)** to see the same
three checks every quarter. Each flow (revenue, net income, cash flow...)
is the trailing twelve months: the sum of the four most recent quarters
from 10-Q and 10-K filings, as first reported. Balance sheet items are
quarter-end values. "Last year" means the same quarter one year earlier,
and peers are companies at the same fiscal quarter. On the price chart,
diamonds mark each quarterly score on the day its latest input was filed.

On the data on screen: {quarterly['companies']:,} companies and
{quarterly['company_quarters']:,} scored company-quarters; the latest
quarter ends {latest_end}, and the latest quarterly score became
available on {latest_available}.

- **{basis.NOT_ENOUGH_DATA}.** Every flow needs four complete quarters,
  this year and last, so quarterly scores are missing more often than
  annual ones (coverage below).
- **Unaudited, and not backtested.** 10-Q figures are reviewed, not
  audited, and the warning rates in the backtests apply to annual
  scores only.
- **As first reported.** A quarter later restated or reclassified stays
  as first reported. A reported 3-month value is replaced only for two
  tagging errors: a fourth-quarter value equal to the full year, and a
  value with the opposite sign of the year-to-date figures.
- **New shares (F-Score test 7)** in the first three quarters compares
  with the share count at the last fiscal year end, from the same 10-Q,
  so the window is 3, 6 or 9 months instead of 12.
- **Changes of fiscal year end:** quarters between two year ends that
  are not a year apart are left out rather than guessed.
""")
    st.dataframe(
        about_quarterly.quarterly_coverage_table(quarterly_df),
        hide_index=True,
        width="stretch",
    )

# ---- Keeping it current -----------------------------------------------------
st.subheader("Keeping the data current")
st.markdown(
    "After each 10-K season, rerun `python run_pipeline.py` to download "
    "the latest SEC files and rebuild every table (add `--quarterly` for "
    "the quarterly scores, which can be refreshed after every 10-Q "
    "season). The app picks up the new tables the next time it starts."
)
