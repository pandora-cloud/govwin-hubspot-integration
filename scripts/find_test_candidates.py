"""Find one or two unmarked candidate opportunities of each type for the smoke test.

Usage: load .env first, then `python scripts/find_test_candidates.py`.

Hits the GovWin WSAPI directly (no AWS, no HubSpot) and prints a small markdown
list of candidates per type so the BD lead can pick which to mark for the
end-to-end sync test. Read-only.
"""

from __future__ import annotations

import os
import sys

import httpx

OPP_TYPES = ["OPP", "BID", "TNS", "FBO", "OPN", "TOP"]
PER_TYPE = 3


def _token() -> str:
    """Get a GovWin access token via password grant from env vars."""
    response = httpx.post(
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
    response.raise_for_status()
    return response.json()["access_token"]


def _search(token: str, opp_type: str, limit: int) -> list[dict]:
    """Search for the most-recently-updated opps of a given type."""
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    params = {
        "max": limit,
        "offset": 0,
        "sort": "updatedDate",
        "order": "desc",
        "oppCategory": "2",  # Federal opportunities
        "oppType": opp_type,
    }
    response = httpx.get(
        "https://services.govwin.com/neo-ws/opportunities",
        headers=headers,
        params=params,
        timeout=60,
    )
    response.raise_for_status()
    return response.json().get("opportunities", [])


def main() -> int:
    token = _token()
    print("# GovWin Smoke-Test Candidates\n")
    print(
        "Pick one from each section, mark it in GovWin "
        "(Add to Web Services Download), then trigger a sync.\n"
    )

    for opp_type in OPP_TYPES:
        print(f"## {opp_type} type\n")
        try:
            opps = _search(token, opp_type, PER_TYPE)
        except httpx.HTTPStatusError as e:
            print(f"_(GovWin returned {e.response.status_code} for {opp_type})_\n")
            continue

        if not opps:
            print(f"_(no current {opp_type} opps returned)_\n")
            continue

        for opp in opps:
            opp_id = opp.get("id", "?")
            iq_id = opp.get("iqOppId", "?")
            title = (opp.get("title") or "")[:80]
            status = opp.get("status") or "?"
            agency = (opp.get("govEntity") or {}).get("title", "?")
            value = opp.get("oppValue")
            value_str = f"${int(value):,}K" if value else "TBD"
            print(
                f"- **{opp_id}** (#{iq_id}) — {title}\n"
                f"  - Agency: {agency}\n"
                f"  - Status: {status} · Value: {value_str}"
            )
        print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
