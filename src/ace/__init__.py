"""AWS Partner Central (ACE) Selling API integration.

Replaces the SaaSify ACE Connector with direct calls to
``partnercentral-selling`` (region us-east-1, IAM SigV4 auth). The submission
flow is three calls: ``CreateOpportunity`` -> ``AssociateOpportunity`` ->
``StartEngagementFromOpportunityTask``.
"""

from src.ace.client import ACEAPIError, ACEClient
from src.ace.mapper import map_hubspot_deal_to_ace_create_payload
from src.ace.rate_limiter import ACERateLimiter

__all__ = [
    "ACEAPIError",
    "ACEClient",
    "ACERateLimiter",
    "map_hubspot_deal_to_ace_create_payload",
]
