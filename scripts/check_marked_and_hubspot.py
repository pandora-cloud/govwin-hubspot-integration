"""Print the current marked-for-sync list from GovWin and check HubSpot for a deal by govwin_id."""

from __future__ import annotations

import json
import os
import sys

import httpx


def _govwin_token() -> str:
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


def list_marked() -> list[dict]:
    token = _govwin_token()
    r = httpx.get(
        "https://services.govwin.com/neo-ws/opportunities",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        params={"markedVersion": "2.2", "max": 100, "offset": 0},
        timeout=60,
    )
    r.raise_for_status()
    return r.json().get("opportunities", [])


def hubspot_deal_by_govwin_id(govwin_id: str) -> dict | None:
    token = os.environ["HUBSPOT_PRIVATE_APP_TOKEN"]
    r = httpx.post(
        "https://api.hubapi.com/crm/v3/objects/deals/search",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={
            "filterGroups": [
                {
                    "filters": [
                        {
                            "propertyName": "govwin_id",
                            "operator": "EQ",
                            "value": govwin_id,
                        }
                    ]
                }
            ],
            "properties": [
                "dealname",
                "dealstage",
                "amount",
                "govwin_id",
                "govwin_opp_id",
                "govwin_status",
                "govwin_opp_type",
                "govwin_update_date",
                "govwin_agency",
            ],
            "limit": 5,
        },
        timeout=30,
    )
    r.raise_for_status()
    results = r.json().get("results", [])
    return results[0] if results else None


def main() -> int:
    print("=== GovWin: currently marked for Web Services Download (markedVersion=2.2) ===\n")
    marked = list_marked()
    if not marked:
        print("(nothing currently marked)")
    else:
        for opp in marked:
            print(
                f"- {opp.get('id')} (#{opp.get('iqOppId')}) — "
                f"{(opp.get('title') or '')[:80]} [{opp.get('status')}]"
            )

    if len(sys.argv) > 1:
        for opp_id in sys.argv[1:]:
            print(f"\n=== HubSpot: search for govwin_id={opp_id} ===")
            deal = hubspot_deal_by_govwin_id(opp_id)
            if not deal:
                print("(no deal found with this govwin_id)")
                continue
            print(json.dumps({
                "hubspot_deal_id": deal.get("id"),
                "properties": deal.get("properties"),
            }, indent=2, default=str))

    return 0


if __name__ == "__main__":
    sys.exit(main())
