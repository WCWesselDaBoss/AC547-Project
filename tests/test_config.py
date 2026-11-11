"""Sanity checks on config.py so a typo cannot silently change the universe."""

import config


def test_year_range_matches_spec():
    """FY2012 start and a range that runs forward in time."""
    assert config.FIRST_FISCAL_YEAR == 2012
    assert config.LAST_FISCAL_YEAR >= config.FIRST_FISCAL_YEAR


def test_size_floor_is_100_million():
    """The floor is $100M in nominal dollars, not $100K or $100B."""
    assert config.SIZE_FLOOR_USD == 100_000_000


def test_excluded_sic_range():
    """SIC 6000-6799 is excluded, and it covers blank-check shells (6770)."""
    assert config.EXCLUDED_SIC_MIN == 6000
    assert config.EXCLUDED_SIC_MAX == 6799
    assert config.EXCLUDED_SIC_MIN <= 6770 <= config.EXCLUDED_SIC_MAX


def test_annual_period_window_includes_52_and_53_week_years():
    """364-day and 371-day fiscal years must both count as annual."""
    assert config.MIN_ANNUAL_PERIOD_DAYS <= 364
    assert config.MAX_ANNUAL_PERIOD_DAYS >= 371


def test_sec_rate_limit_below_ten_per_second():
    """SEC allows at most 10 requests per second."""
    assert 0 < config.SEC_MAX_REQUESTS_PER_SECOND < 10


def test_placeholder_user_agent_is_detected():
    """The downloader must be able to tell the placeholder from a real one."""
    assert config.user_agent_is_placeholder(config.SEC_USER_AGENT_PLACEHOLDER)
    assert not config.user_agent_is_placeholder("Team X a.student@ua.edu")


def test_data_dirs_live_inside_project():
    """Paths are anchored to the repo, not the current working directory."""
    for path in (config.RAW_DIR, config.PROCESSED_DIR, config.SAMPLE_DIR):
        assert config.PROJECT_ROOT in path.parents


def test_fiscal_year_compustat_convention():
    """Jan-May year ends map to the prior year; June-Dec to the same year."""
    from datetime import date

    assert config.fiscal_year_from_period_end(date(2025, 12, 31)) == 2025
    assert config.fiscal_year_from_period_end(date(2026, 1, 31)) == 2025
    assert config.fiscal_year_from_period_end(date(2026, 5, 31)) == 2025
    assert config.fiscal_year_from_period_end(date(2026, 6, 30)) == 2026
