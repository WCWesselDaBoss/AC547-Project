"""Tests for src/pipeline/download.py. No test touches the internet."""

import json

import pytest

from src.pipeline import download


class FakeResponse:
    """Stand-in for requests.Response with just the parts we use."""

    def __init__(self, status_code, body=b""):
        """Store a status code and a body to stream back."""
        self.status_code = status_code
        self.body = body

    def iter_content(self, chunk_size):
        """Yield the body in chunks, like a streamed download."""
        for start in range(0, len(self.body), chunk_size):
            yield self.body[start : start + chunk_size]

    def raise_for_status(self):
        """Raise for 4xx/5xx codes, like requests does."""
        if self.status_code >= 400:
            raise download.requests.HTTPError(str(self.status_code))

    def close(self):
        """Nothing to release in a fake response."""


class FakeSession:
    """Returns pre-set responses in order and counts the calls."""

    def __init__(self, responses):
        """Queue up the responses to hand back."""
        self.responses = list(responses)
        self.calls = 0

    def get(self, url, stream, timeout):
        """Return the next queued response."""
        self.calls += 1
        return self.responses.pop(0)


class NoWaitLimiter:
    """Rate limiter that never sleeps, so tests run instantly."""

    def wait(self):
        """Do nothing."""


def test_rate_limiter_spaces_requests():
    """Two back-to-back requests at 8/s must be 0.125 s apart."""
    fake_time = [100.0]
    slept = []

    def fake_sleep(seconds):
        slept.append(seconds)
        fake_time[0] += seconds

    limiter = download.RateLimiter(
        8, clock=lambda: fake_time[0], sleep=fake_sleep
    )
    limiter.wait()  # first request never waits
    limiter.wait()  # second request immediately after must wait
    assert slept == [pytest.approx(0.125)]


def test_rate_limiter_no_wait_when_gap_is_long():
    """If enough time already passed, the limiter does not sleep."""
    fake_time = [100.0]
    slept = []
    limiter = download.RateLimiter(
        8, clock=lambda: fake_time[0], sleep=slept.append
    )
    limiter.wait()
    fake_time[0] += 1.0
    limiter.wait()
    assert slept == []


def test_placeholder_user_agent_is_refused():
    """build_session must not contact SEC with the placeholder."""
    with pytest.raises(ValueError):
        download.build_session(download.config.SEC_USER_AGENT_PLACEHOLDER)


def test_session_sends_user_agent():
    """A real User-Agent is attached to every request."""
    session = download.build_session("Team X a.student@ua.edu")
    assert session.headers["User-Agent"] == "Team X a.student@ua.edu"


def test_download_writes_file_and_leaves_no_part(tmp_path):
    """A successful download lands at dest_path with no .part leftover."""
    dest = tmp_path / "file.bin"
    session = FakeSession([FakeResponse(200, b"abc" * 1000)])
    status = download.download_file(
        "https://x", dest, session, NoWaitLimiter()
    )
    assert status == "downloaded"
    assert dest.read_bytes() == b"abc" * 1000
    assert not (tmp_path / "file.bin.part").exists()


def test_existing_file_is_skipped(tmp_path):
    """An existing, non-empty file is not downloaded again."""
    dest = tmp_path / "file.bin"
    dest.write_bytes(b"already here")
    session = FakeSession([])
    status = download.download_file(
        "https://x", dest, session, NoWaitLimiter()
    )
    assert status == "skipped"
    assert session.calls == 0


def test_force_redownloads_existing_file(tmp_path):
    """force=True replaces an existing file."""
    dest = tmp_path / "file.bin"
    dest.write_bytes(b"old")
    session = FakeSession([FakeResponse(200, b"new")])
    download.download_file(
        "https://x", dest, session, NoWaitLimiter(), force=True
    )
    assert dest.read_bytes() == b"new"


def test_retries_after_429_then_succeeds(tmp_path):
    """A 429 'slow down' is retried after a back-off wait."""
    dest = tmp_path / "file.bin"
    session = FakeSession([FakeResponse(429), FakeResponse(200, b"ok")])
    waits = []
    status = download.download_file(
        "https://x",
        dest,
        session,
        NoWaitLimiter(),
        backoff_seconds=10,
        sleep=waits.append,
    )
    assert status == "downloaded"
    assert session.calls == 2
    assert waits == [10]


def test_gives_up_after_max_retries(tmp_path):
    """Repeated 503s end in a clear error, not an endless loop."""
    dest = tmp_path / "file.bin"
    session = FakeSession([FakeResponse(503)] * 3)
    with pytest.raises(RuntimeError):
        download.download_file(
            "https://x",
            dest,
            session,
            NoWaitLimiter(),
            max_retries=2,
            sleep=lambda s: None,
        )
    assert not dest.exists()


def test_404_is_not_retried(tmp_path):
    """A 404 means a wrong URL; retrying would not help."""
    dest = tmp_path / "file.bin"
    session = FakeSession([FakeResponse(404)])
    with pytest.raises(download.requests.HTTPError):
        download.download_file("https://x", dest, session, NoWaitLimiter())
    assert session.calls == 1


def test_download_all_writes_manifest(tmp_path):
    """Downloaded files get a manifest entry with url, size and hash."""
    files = {"a.json": "https://x/a.json"}
    session = FakeSession([FakeResponse(200, b"{}")])
    manifest_path = tmp_path / "manifest.json"
    results = download.download_all(
        files=files,
        raw_dir=tmp_path,
        manifest_path=manifest_path,
        session=session,
    )
    assert results == {"a.json": "downloaded"}
    entry = json.loads(manifest_path.read_text())["a.json"]
    assert entry["url"] == "https://x/a.json"
    assert entry["bytes"] == 2
    assert len(entry["sha256"]) == 64


class DroppingResponse(FakeResponse):
    """Response whose stream is cut off partway, like a connection reset."""

    def iter_content(self, chunk_size):
        """Yield one chunk, then fail the way requests does mid-stream."""
        yield b"partial"
        raise download.requests.exceptions.ChunkedEncodingError("reset")


def make_zip_bytes(tmp_path):
    """Return the bytes of a small valid ZIP holding one JSON member."""
    import zipfile

    zip_path = tmp_path / "source.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("CIK0000000001.json", "{}")
    return zip_path.read_bytes()


def test_connection_drop_mid_stream_is_retried(tmp_path):
    """A connection reset during the body is retried from scratch."""
    dest = tmp_path / "file.bin"
    session = FakeSession(
        [DroppingResponse(200), FakeResponse(200, b"complete")]
    )
    status = download.download_file(
        "https://x", dest, session, NoWaitLimiter(), sleep=lambda s: None
    )
    assert status == "downloaded"
    assert dest.read_bytes() == b"complete"
    assert not (tmp_path / "file.bin.part").exists()


def test_truncated_zip_is_rejected(tmp_path):
    """A ZIP cut short fails the integrity check and is never saved."""
    dest = tmp_path / "data.zip"
    truncated = make_zip_bytes(tmp_path)[:-10]
    session = FakeSession([FakeResponse(200, truncated)] * 2)
    with pytest.raises(RuntimeError, match="integrity"):
        download.download_file(
            "https://x",
            dest,
            session,
            NoWaitLimiter(),
            max_retries=1,
            sleep=lambda s: None,
        )
    assert not dest.exists()
    assert not (tmp_path / "data.zip.part").exists()


def test_valid_zip_is_accepted(tmp_path):
    """A complete ZIP passes the check and is saved."""
    dest = tmp_path / "data.zip"
    session = FakeSession([FakeResponse(200, make_zip_bytes(tmp_path))])
    status = download.download_file(
        "https://x", dest, session, NoWaitLimiter()
    )
    assert status == "downloaded"
