"""Download SEC bulk files into data/raw/.

Run on its own with:
    python -m src.pipeline.download          # skip files already present
    python -m src.pipeline.download --force  # re-download everything

The ZIPs are kept zipped. Later steps read members straight out of the
archive, which avoids unpacking several hundred thousand small JSON files.
"""

import argparse
import hashlib
import json
import time
from datetime import datetime, timezone

import requests

import config

# Status codes worth retrying: 429 means SEC wants us to slow down, and
# 5xx means a temporary server problem. Anything else (404, 403) is a real
# error that retrying will not fix.
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}

# Read and write in 1 MB pieces so a multi-GB file never sits in memory.
CHUNK_BYTES = 1024 * 1024


class RateLimiter:
    """Space out requests so we never exceed a max requests-per-second.

    The clock and sleep functions are parameters so tests can use a fake
    clock instead of really waiting.
    """

    def __init__(self, max_per_second, clock=time.monotonic, sleep=time.sleep):
        """Store the minimum gap between requests and the time functions."""
        self.min_interval = 1.0 / max_per_second
        self.clock = clock
        self.sleep = sleep
        self.last_request_time = None

    def wait(self):
        """Sleep just long enough to respect the minimum gap, then record."""
        now = self.clock()
        if self.last_request_time is not None:
            elapsed = now - self.last_request_time
            if elapsed < self.min_interval:
                self.sleep(self.min_interval - elapsed)
                now = self.clock()
        self.last_request_time = now


def build_session(user_agent=config.SEC_USER_AGENT):
    """Return a requests Session with the headers SEC asks for.

    Raises ValueError if the User-Agent is still the placeholder, because
    SEC asks every requester to identify themselves with a contact email.
    """
    if config.user_agent_is_placeholder(user_agent):
        raise ValueError(
            "Set the SEC_USER_AGENT environment variable to your team name "
            "and school email before downloading (see config.py)."
        )
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": user_agent,
            # SEC's sample headers ask for compressed transfer.
            "Accept-Encoding": "gzip, deflate",
        }
    )
    return session


def sha256_of_file(path):
    """Return the SHA-256 hex digest of a file, read in chunks."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_file(
    url,
    dest_path,
    session,
    limiter,
    force=False,
    max_retries=config.SEC_MAX_RETRIES,
    backoff_seconds=config.SEC_RETRY_BACKOFF_SECONDS,
    sleep=time.sleep,
):
    """Download one URL to dest_path and return "skipped" or "downloaded".

    The file is written to a ".part" name and renamed only after the whole
    body arrives, so an interrupted download never looks complete and the
    skip-if-present check stays trustworthy.
    """
    if dest_path.exists() and dest_path.stat().st_size > 0 and not force:
        return "skipped"

    dest_path.parent.mkdir(parents=True, exist_ok=True)
    part_path = dest_path.with_name(dest_path.name + ".part")

    for attempt in range(max_retries + 1):
        limiter.wait()
        response = session.get(url, stream=True, timeout=60)
        if response.status_code in RETRYABLE_STATUS_CODES:
            response.close()
            if attempt == max_retries:
                break
            # Wait longer after each failure (10s, 20s, 30s) to give SEC
            # room, instead of hammering it with immediate retries.
            sleep(backoff_seconds * (attempt + 1))
            continue
        # Non-retryable errors (403, 404) stop here with a clear message.
        response.raise_for_status()
        with open(part_path, "wb") as handle:
            for chunk in response.iter_content(chunk_size=CHUNK_BYTES):
                handle.write(chunk)
        response.close()
        part_path.replace(dest_path)
        return "downloaded"

    raise RuntimeError(
        f"Gave up on {url} after {max_retries + 1} attempts "
        f"(last status {response.status_code})."
    )


def update_manifest(manifest_path, file_name, url, file_path):
    """Record url, download time, size and hash for one downloaded file."""
    manifest = {}
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
    manifest[file_name] = {
        "url": url,
        "downloaded_at_utc": datetime.now(timezone.utc).isoformat(),
        "bytes": file_path.stat().st_size,
        "sha256": sha256_of_file(file_path),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2))


def download_all(
    force=False,
    files=config.SEC_BULK_FILES,
    raw_dir=config.RAW_DIR,
    manifest_path=config.DOWNLOAD_MANIFEST,
    session=None,
):
    """Download every SEC bulk file and return {file_name: status}."""
    if session is None:
        session = build_session()
    limiter = RateLimiter(config.SEC_MAX_REQUESTS_PER_SECOND)
    results = {}
    for file_name, url in files.items():
        dest_path = raw_dir / file_name
        status = download_file(url, dest_path, session, limiter, force)
        if status == "downloaded":
            update_manifest(manifest_path, file_name, url, dest_path)
        results[file_name] = status
        print(f"{file_name}: {status}")
    return results


def main():
    """Parse command-line options and run the downloads."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--force",
        action="store_true",
        help="re-download files even if they already exist",
    )
    args = parser.parse_args()
    download_all(force=args.force)


if __name__ == "__main__":
    main()
