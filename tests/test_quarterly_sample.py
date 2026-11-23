"""Tests for the quarterly sample (src/pipeline/quarterly_sample.py)."""

import pandas as pd

from src.pipeline import quarterly_sample


def test_quarterly_sample_keeps_the_annual_sample_companies(tmp_path):
    """The quarterly tables are cut to the companies listed in the
    sample's companies table (CIKs 1 and 3), not the others (2)."""
    sample_dir = tmp_path / "sample"
    sample_dir.mkdir()
    pd.DataFrame({"cik": [1, 3]}).to_parquet(
        sample_dir / "companies.parquet", index=False
    )
    processed = {}
    for name in ["facts_quarterly", "financials_ttm", "ttm_sources"]:
        path = tmp_path / f"{name}.parquet"
        pd.DataFrame(
            {"cik": [1, 2, 3, 3], "value": [1.0, 2.0, 3.0, 4.0]}
        ).to_parquet(path, index=False)
        processed[name] = path
    written = quarterly_sample.build_quarterly_sample(sample_dir, processed)
    assert written == {name: 3 for name in processed}
    table = pd.read_parquet(sample_dir / "financials_ttm.parquet")
    assert table["cik"].tolist() == [1, 3, 3]
