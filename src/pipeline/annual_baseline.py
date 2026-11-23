"""Record a fingerprint of every annual table, so later work can prove it
changed none of them.

The quarterly upgrade adds new modules and new tables only; the annual
tables must stay exactly as they are. Run this once, BEFORE any
quarterly change:

    python -m src.pipeline.annual_baseline

It writes data/logs/annual_baseline.json, and tests/test_annual_baseline.py
fails if any recorded table later differs from it.

A fingerprint describes a table's CONTENTS, not its file bytes: writing
identical data again can change a Parquet file's bytes (its metadata),
which would be a false alarm, while any changed value, row, column or
type changes the fingerprint.
"""

import datetime as dt
import hashlib
import json
import subprocess

import pandas as pd

import config

BASELINE_PATH = config.LOG_DIR / "annual_baseline.json"
# Every Parquet table in these folders is fingerprinted.
BASELINE_DIRS = [config.PROCESSED_DIR, config.SAMPLE_DIR]


def table_fingerprint(path):
    """Return {rows, columns, dtypes, sha256} for one Parquet table.

    sha256 covers the column names and types and a hash of every cell,
    row by row in the stored order (pandas' hash_pandas_object), so a
    change to any value, the row order, a column or a type changes it.
    """
    table = pd.read_parquet(path)
    digest = hashlib.sha256()
    digest.update(json.dumps(list(table.columns)).encode())
    digest.update(json.dumps([str(t) for t in table.dtypes]).encode())
    row_hashes = pd.util.hash_pandas_object(table, index=False)
    digest.update(row_hashes.to_numpy().tobytes())
    return {
        "rows": len(table),
        "columns": list(table.columns),
        "dtypes": [str(t) for t in table.dtypes],
        "sha256": digest.hexdigest(),
    }


def relative_name(path):
    """Return the path relative to the project root, with / separators."""
    return path.relative_to(config.PROJECT_ROOT).as_posix()


def build_baseline(folders=BASELINE_DIRS):
    """Return {relative path: fingerprint} for every Parquet table in the
    folders (folders that do not exist are skipped)."""
    tables = {}
    for folder in folders:
        if not folder.exists():
            continue
        for path in sorted(folder.glob("*.parquet")):
            tables[relative_name(path)] = table_fingerprint(path)
    return tables


def current_commit():
    """Return the current git commit, or "unknown" outside git."""
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            cwd=config.PROJECT_ROOT,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def main():
    """Write the baseline file; refuse to overwrite an existing one, so a
    later run cannot quietly move the baseline."""
    if BASELINE_PATH.exists():
        raise SystemExit(
            f"{BASELINE_PATH} already exists; delete it by hand only if the "
            "annual tables were deliberately rebuilt."
        )
    baseline = {
        "created": dt.datetime.now().isoformat(timespec="seconds"),
        "git_commit": current_commit(),
        "tables": build_baseline(),
    }
    BASELINE_PATH.parent.mkdir(parents=True, exist_ok=True)
    BASELINE_PATH.write_text(json.dumps(baseline, indent=2))
    for name, fingerprint in baseline["tables"].items():
        print(
            f"{name}: {fingerprint['rows']:,} rows, {fingerprint['sha256'][:12]}"
        )
    print(f"Wrote {BASELINE_PATH}")


if __name__ == "__main__":
    main()
