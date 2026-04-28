"""Discover the full GovWin status vocabulary from live data.

Iterates over a broad federal opportunity search (no opp-type filter,
sorted by recency) across multiple pages and collects every unique
status string encountered, plus a tally of how often each appears.
"""

from __future__ import annotations

import collections
import os

import httpx


def _token() -> str:
    r = httpx.post(
        "https://services.govwin.com/neo-ws/oauth/token",
        data={
            "client_id": os.environ["GOVWIN_CLIENT_ID"],
            "client_secret": os.environ["GOVWIN_CLIENT_SECRET"],
            "grant_type": "password",
            "username": os.environ["GOVWIN_USERNAME"],
            "password": os.environ["GOVWIN_PASSWORD"],
            "scope": "read",
        },
        timeout=30,
    )
    r.raise_for_status()
    return r.json()["access_token"]


def main() -> None:
    token = _token()
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    counter: collections.Counter[str] = collections.Counter()
    by_type: dict[str, collections.Counter[str]] = collections.defaultdict(collections.Counter)

    # Sample federal + SLED so the SLED-only statuses (e.g. lead-stage)
    # surface alongside federal statuses (e.g. Source Selection).
    for market in ("Federal", "SLED"):
        for offset in range(0, 500, 100):
            r = httpx.get(
                "https://services.govwin.com/neo-ws/opportunities",
                headers=headers,
                params={
                    "max": 100,
                    "offset": offset,
                    "sort": "updatedDate",
                    "order": "desc",
                    "oppCategory": "2",
                    "market": market,
                },
                timeout=60,
            )
            r.raise_for_status()
            opps = r.json().get("opportunities", [])
            if not opps:
                break
            for opp in opps:
                status = (opp.get("status") or "").strip() or "(empty)"
                type_ = (opp.get("type") or "?").strip()
                counter[status] += 1
                by_type[type_][status] += 1

    print("\n=== Unique status values seen across the most-recent 500 federal opps ===\n")
    for status, n in counter.most_common():
        print(f"  {n:4d}  {status}")

    print("\n=== Statuses by opportunity type ===\n")
    for type_, c in sorted(by_type.items()):
        print(f"\n{type_}:")
        for status, n in c.most_common():
            print(f"  {n:4d}  {status}")


if __name__ == "__main__":
    main()
