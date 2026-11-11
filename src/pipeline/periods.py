"""Period checks shared by the tag coverage report and facts_long."""

from datetime import date

import config


def to_date(text):
    """Return a date from SEC's 'YYYY-MM-DD' text, or None if missing."""
    if not text:
        return None
    return date.fromisoformat(text)


def period_days(start, end):
    """Return the length of a reporting period in days, counting both ends.

    A fiscal year from 2025-01-01 to 2025-12-31 is 365 days. Counting both
    ends matches how filers describe a year and keeps 52/53-week years
    (364 or 371 days) inside the 350-380 window.
    """
    return (end - start).days + 1


def is_annual_duration(start, end):
    """Return True if a flow period covers roughly one full year.

    This drops quarterly and year-to-date values that 10-Ks also contain,
    which would otherwise be mistaken for annual totals.
    """
    days = period_days(start, end)
    return (
        config.MIN_ANNUAL_PERIOD_DAYS <= days <= config.MAX_ANNUAL_PERIOD_DAYS
    )
