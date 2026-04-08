#!/usr/bin/env python3
"""Dry-run sync simulation.

Discovers opportunities from GovWin, fetches details, maps fields,
and reports what WOULD be synced — without writing to HubSpot or DynamoDB.

Requires GovWin credentials (via env vars or Secrets Manager).

Usage:
    python scripts/dry_run.py                    # Default: 5 opps
    python scripts/dry_run.py --limit 20         # Fetch up to 20
    python scripts/dry_run.py --verbose          # Show all field values
    python scripts/dry_run.py --json             # Machine-readable output
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys

# Allow imports from project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config import load_config
from src.govwin.auth import GovWinAuth
from src.govwin.client import GovWinClient
from src.sync.mapper import (
    map_contact_to_hubspot,
    map_gov_entity_to_company,
    map_opportunity_to_deal,
)

logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def _inject_env_credentials(auth: GovWinAuth) -> None:
    """Inject credentials from env vars into auth cache, bypassing Secrets Manager."""
    client_id = os.environ.get("GOVWIN_CLIENT_ID")
    if client_id:
        auth._credentials = {
            "client_id": client_id,
            "client_secret": os.environ.get("GOVWIN_CLIENT_SECRET", ""),
            "username": os.environ.get("GOVWIN_USERNAME", ""),
            "password": os.environ.get("GOVWIN_PASSWORD", ""),
        }
        logger.info("Using GovWin credentials from environment variables")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Dry-run: discover and map GovWin opportunities without syncing"
    )
    parser.add_argument(
        "--limit", type=int, default=5,
        help="Max opportunities to fetch details for (default: 5)",
    )
    parser.add_argument("--verbose", action="store_true", help="Show all mapped field values")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    config = load_config()
    auth = GovWinAuth(config)

    # Allow credentials from env vars (pre-deployment testing)
    _inject_env_credentials(auth)

    print("GovWin-HubSpot Dry Run")
    print("=" * 55)
    if config.govwin.marked_version:
        mode = f"marked (v{config.govwin.marked_version})"
    else:
        mode = "date-range search"
    print(f"Mode: {mode}")
    print(f"Opp types: {config.govwin.opp_types}")
    print(f"Fetch limit: {args.limit}")
    print()

    with GovWinClient(config, auth) as client:
        # Step 1: Discover
        print("Step 1: Discovering opportunities...")
        if config.govwin.marked_version:
            opportunities = client.get_all_marked_opportunities(
                marked_version=config.govwin.marked_version,
                opp_type=config.govwin.opp_types,
            )
        else:
            from datetime import UTC, datetime, timedelta

            lookback = datetime.now(UTC) - timedelta(days=config.sync.initial_lookback_days)
            from_date = lookback.strftime("%m/%d/%Y")
            opportunities = client.search_all_opportunities(
                opp_type=config.govwin.opp_types,
                market=config.govwin.market,
                opp_selection_date_from=from_date,
            )

        print(f"  Found {len(opportunities)} opportunities")
        if not opportunities:
            print("\n  No opportunities to sync. If using marked mode, ensure opps are")
            print("  marked for 'Web Services Download' in GovWin IQ.")
            return 0

        # Step 2: Fetch details (limited)
        to_fetch = opportunities[: args.limit]
        print(f"\nStep 2: Fetching details for {len(to_fetch)}"
              f" of {len(opportunities)} opportunities...")
        bundles = []
        for opp in to_fetch:
            if not opp.id:
                continue
            print(f"  Fetching {opp.id}: {opp.title or '(no title)'}...")
            bundle = client.get_opportunity_bundle(opp.id)
            if bundle:
                bundles.append(bundle)

        print(f"  Fetched {len(bundles)} complete bundles")
        print(f"  API calls used: {client.rate_limiter.calls_in_window}")

        # Step 3: Map to HubSpot format
        print("\nStep 3: Mapping to HubSpot format...")
        results = []
        companies_seen: set[str] = set()
        contacts_seen: set[str] = set()

        for bundle in bundles:
            deal = map_opportunity_to_deal(bundle)
            props = deal["properties"]

            # Track unique companies
            entity = bundle.opportunity.gov_entity
            company = None
            if entity and entity.id and str(entity.id) not in companies_seen:
                companies_seen.add(str(entity.id))
                company = map_gov_entity_to_company(entity)

            # Track unique contacts
            mapped_contacts = []
            for contact in bundle.contacts:
                key = contact.email or contact.contact_id or ""
                if key and key not in contacts_seen:
                    contacts_seen.add(key)
                    mapped_contacts.append(map_contact_to_hubspot(contact))

            results.append({
                "deal": props,
                "company": company["properties"] if company else None,
                "contacts": [c["properties"] for c in mapped_contacts],
                "contact_count": len(bundle.contacts),
            })

    # Step 4: Report
    if args.json:
        print(json.dumps(results, indent=2, default=str))
        return 0

    print(f"\n{'=' * 55}")
    print("DRY RUN RESULTS")
    print(f"{'=' * 55}\n")

    for i, r in enumerate(results, 1):
        d = r["deal"]
        print(f"  {i}. {d.get('dealname', '???')}")
        print(f"     GovWin ID:   {d.get('govwin_opp_id', '???')}")
        print(f"     Type:        {d.get('govwin_opp_type', '???')}")
        print(f"     Status:      {d.get('govwin_status', '???')}")
        amt = f"${int(d['amount']):,}" if d.get("amount") else "N/A"
        print(f"     Amount:      {amt}")
        print(f"     Agency:      {d.get('govwin_agency', 'N/A')}")
        print(f"     Industry:    {d.get('govwin_industry', 'N/A')}")
        naics = f"{d.get('govwin_naics_code', 'N/A')} — {d.get('govwin_primary_naics', '')}"
        print(f"     NAICS:       {naics}")
        print(f"     Close Date:  {d.get('closedate', 'N/A')}")
        print(f"     Contacts:    {r['contact_count']}")
        if d.get("govwin_iq_url"):
            print(f"     GovWin URL:  {d['govwin_iq_url']}")

        if args.verbose and r["company"]:
            c = r["company"]
            print("     --- Company ---")
            print(f"     Name:        {c.get('name', '???')}")
            print(f"     Entity ID:   {c.get('govwin_gov_entity_id', '???')}")

        if args.verbose and r["contacts"]:
            for ct in r["contacts"]:
                print("     --- Contact ---")
                print(f"     Name:        {ct.get('firstname', '')} {ct.get('lastname', '')}")
                print(f"     Email:       {ct.get('email', 'N/A')}")
                print(f"     Title:       {ct.get('jobtitle', 'N/A')}")

        print()

    # Summary
    print(f"{'=' * 55}")
    print(f"Summary: {len(results)} deals, {len(companies_seen)} companies, "
          f"{len(contacts_seen)} contacts")
    remaining = len(opportunities) - len(to_fetch)
    print(f"Remaining opportunities not fetched: {remaining}")
    calls = client.rate_limiter.calls_in_window
    print(f"API calls used: {calls} of {config.govwin.rate_limit_per_hour}/hr")
    print()
    print("This was a DRY RUN. No data was written to HubSpot or DynamoDB.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
