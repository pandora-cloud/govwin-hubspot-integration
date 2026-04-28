"""Look up a single GovWin opportunity by its global ID and print what the API returns."""

from __future__ import annotations

import json
import os
import sys

import httpx


def _token() -> str:
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


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: python scripts/check_opp.py <OPP_ID> [<OPP_ID> ...]")
        return 1

    token = _token()
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}

    for opp_id in sys.argv[1:]:
        print(f"\n=== {opp_id} ===")
        r = httpx.get(
            f"https://services.govwin.com/neo-ws/opportunities/{opp_id}",
            headers=headers,
            timeout=30,
        )
        print(f"HTTP {r.status_code}")
        if r.status_code != 200:
            print(r.text[:500])
            continue

        data = r.json()
        opps = data.get("opportunities", [])
        if not opps:
            print("(no opportunity returned in body)")
            continue

        opp = opps[0]
        print(json.dumps(
            {
                "id": opp.get("id"),
                "iqOppId": opp.get("iqOppId"),
                "title": opp.get("title"),
                "status": opp.get("status"),
                "type": opp.get("type"),
                "updateDate": opp.get("updateDate"),
                "createdDate": opp.get("createdDate"),
                "govEntity": opp.get("govEntity"),
                "solicitationNumber": opp.get("solicitationNumber"),
                "marked": opp.get("marked"),
            },
            indent=2,
            default=str,
        ))

    return 0


if __name__ == "__main__":
    sys.exit(main())
