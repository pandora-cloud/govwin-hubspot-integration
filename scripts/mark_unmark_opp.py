"""Mark or unmark a GovWin opportunity for Web Services Download via the WSAPI.

Per the Deltek WSAPI Quick Reference (March 2025), the marking endpoints are:
    GET /neo-ws/opportunities/{OppID}?setMark=2.2
    GET /neo-ws/opportunities/{OppID}?clearMark=2.2

Usage:
    python scripts/mark_unmark_opp.py mark   OPP123 BID456 FBO789
    python scripts/mark_unmark_opp.py unmark OPP123 BID456 FBO789
"""

from __future__ import annotations

import os
import sys

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


def main() -> int:
    if len(sys.argv) < 3 or sys.argv[1] not in {"mark", "unmark"}:
        print(__doc__)
        return 1

    action = sys.argv[1]
    opp_ids = sys.argv[2:]
    param = "setMark" if action == "mark" else "clearMark"
    token = _token()

    for opp_id in opp_ids:
        r = httpx.get(
            f"https://services.govwin.com/neo-ws/opportunities/{opp_id}",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            params={param: "2.2"},
            timeout=30,
        )
        if r.status_code == 200:
            print(f"  {action}ed {opp_id}: HTTP 200")
        else:
            print(f"  {action} FAILED for {opp_id}: HTTP {r.status_code} — {r.text[:200]}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
