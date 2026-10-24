"""Checks that a streamed answer reaches the browser event by event, uncompressed.

    python3 check_stream.py https://localhost

The fake API (fake_answer_stream.py) sends one delta every 0.5 s: if a proxy buffered
the response, the events would all arrive together at the end.
"""

import http.client
import ssl
import sys
import time
from urllib.parse import urlsplit

MIN_SPREAD_SECONDS = 1.5  # 5 deltas, 0.5 s apart: 2 s from first to last when unbuffered


def main(base_url: str) -> int:
    url = urlsplit(base_url)
    connection: http.client.HTTPConnection
    if url.scheme == "https":
        # Caddy's local certificate authority in CI.
        connection = http.client.HTTPSConnection(
            url.netloc, context=ssl._create_unverified_context(), timeout=30
        )
    else:
        connection = http.client.HTTPConnection(url.netloc, timeout=30)
    connection.request(
        "POST",
        "/api/ask/stream",
        body='{"repository": "o/r", "question": "How?"}',
        headers={"content-type": "application/json", "accept-encoding": "zstd, br, gzip"},
    )
    response = connection.getresponse()
    started = time.monotonic()
    arrivals: list[tuple[str, float]] = []
    while line := response.readline():
        if line.startswith(b"event: "):
            arrivals.append((line[7:].strip().decode(), time.monotonic() - started))

    names = [name for name, _ in arrivals]
    deltas = [at for name, at in arrivals if name == "delta"]
    spread = deltas[-1] - deltas[0] if deltas else 0.0
    checks = {
        "status 200": response.status == 200,
        "event stream": (response.getheader("content-type") or "").startswith("text/event-stream"),
        "not compressed": response.getheader("content-encoding") is None,
        "sources, 5 deltas, done": names == ["sources"] + ["delta"] * 5 + ["done"],
        f"deltas spread over >= {MIN_SPREAD_SECONDS} s (got {spread:.2f} s)": spread
        >= MIN_SPREAD_SECONDS,
    }
    for description, passed in checks.items():
        print(f"{'ok  ' if passed else 'FAIL'}  {description}")
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
