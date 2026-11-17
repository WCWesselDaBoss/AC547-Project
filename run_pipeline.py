"""Rebuild every processed table from raw data with one command.

Usage:
    python run_pipeline.py                  # download, then build all
    python run_pipeline.py --skip-download  # build from data/raw only
    python run_pipeline.py --sample-only    # rebuild data/sample/ only
    python run_pipeline.py --scores-only    # rebuild scores + returns only

Stages run in dependency order; each one reads the previous one's output
from data/processed/ (CLAUDE.md section 4), so any stage can also be run
alone with "python -m src.pipeline.<module>".
"""

import argparse
import time

from src.pipeline import companies, download, facts, financials
from src.pipeline import prices, sample
from src.scores import build_scores, drivers, returns


def run_stage(name, function, *args, **kwargs):
    """Run one stage, printing its name and how long it took."""
    print(f"\n=== {name}")
    started = time.monotonic()
    function(*args, **kwargs)
    print(f"=== {name} done in {time.monotonic() - started:.0f}s")


def parse_args(argv=None):
    """Return the command-line options."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--skip-download",
        action="store_true",
        help="use files already in data/raw; contact neither SEC nor Yahoo",
    )
    parser.add_argument(
        "--sample-only",
        action="store_true",
        help="only rebuild data/sample/ from data/processed/",
    )
    parser.add_argument(
        "--scores-only",
        action="store_true",
        help="only rebuild scores and returns from existing Phase 1 tables",
    )
    return parser.parse_args(argv)


def main(argv=None):
    """Run each pipeline stage in order."""
    args = parse_args(argv)
    if not (args.sample_only or args.scores_only):
        if not args.skip_download:
            run_stage("1. Download SEC bulk files", download.download_all)
        run_stage("2. companies", companies.main)
        run_stage("3. facts_long", facts.main)
        run_stage("4. financials_annual", financials.main)
        run_stage("5. prices", prices.main, download=not args.skip_download)
    if not args.sample_only:
        run_stage("6. scores", build_scores.main, [])
        # The M-Score components pushing each score up, with their
        # approved plain-English sentences (CLAUDE.md section 4).
        run_stage("7. score drivers", drivers.main, [])
        # Stretch goal (section 7): 12-month returns after each 10-K.
        run_stage("8. returns", returns.main, [])
    if not args.scores_only:
        run_stage("9. sample", sample.main)
    # Scores for the sample are computed from the sample's own tables, so
    # a fresh clone's app shows numbers it can reproduce (peer ranks on
    # 50 companies are illustrative only, CLAUDE.md section 4).
    run_stage("10. sample scores", build_scores.main, ["--sample"])
    run_stage("11. sample score drivers", drivers.main, ["--sample"])
    run_stage("12. sample returns", returns.main, ["--sample"])


if __name__ == "__main__":
    main()
