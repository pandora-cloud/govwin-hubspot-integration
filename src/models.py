"""Pydantic models for GovWin and HubSpot data structures."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# GovWin Models
# ---------------------------------------------------------------------------


class GovWinPaging(BaseModel):
    max: int = 10
    offset: int = 0
    sort: str = "relevancy"
    order: str = "asc"
    total_count: int = Field(0, alias="totalCount")

    model_config = {"populate_by_name": True}


class GovWinMeta(BaseModel):
    paging: GovWinPaging = Field(default_factory=GovWinPaging)


class GovWinGovEntity(BaseModel):
    id: int | None = None
    title: str | None = None
    parent_hierarchy: list[dict[str, Any]] = Field(default_factory=list, alias="parentHierarchy")

    model_config = {"populate_by_name": True, "extra": "ignore"}


class GovWinContact(BaseModel):
    contact_id: str | int | None = Field(None, alias="contactId")
    first_name: str | None = Field(None, alias="firstName")
    last_name: str | None = Field(None, alias="lastName")
    email: str | None = None
    phone: str | None = None
    title: str | None = None
    address1: str | None = None
    city: str | None = None
    state: str | None = None
    country: str | None = None
    zip: str | None = None
    gov_entity_level1: str | None = Field(None, alias="govEntityLevel1")
    gov_entity_level2: str | None = Field(None, alias="govEntityLevel2")
    modified_date: str | None = Field(None, alias="modifiedDate")

    model_config = {"populate_by_name": True, "extra": "ignore"}


class GovWinCompany(BaseModel):
    id: int | None = None
    company_profile_name: str | None = Field(None, alias="companyProfileName")
    company_url: str | None = Field(None, alias="companyURL")
    num_of_employees: str | None = Field(None, alias="numOfEmployees")
    revenue: str | None = None
    address1: str | None = None
    city: str | None = None
    state: str | None = None
    country: str | None = None
    zip_code: str | None = Field(None, alias="zipCode")

    model_config = {"populate_by_name": True, "extra": "ignore"}


class GovWinContract(BaseModel):
    contract_id: str | None = Field(None, alias="contractId")
    contract_number: str | None = Field(None, alias="contractNumber")
    award_date: str | None = Field(None, alias="awardDate")
    estimated_value: str | None = Field(None, alias="estimatedValue")
    expiration_date: str | None = Field(None, alias="expirationDate")
    company: dict[str, Any] | None = None
    incumbent: bool | None = None

    model_config = {"populate_by_name": True, "extra": "ignore"}


class GovWinNAICS(BaseModel):
    id: str | None = None
    title: str | None = None

    model_config = {"extra": "ignore"}


class GovWinLinks(BaseModel):
    web_href: dict[str, str] | str | None = Field(None, alias="webHref")
    contacts: dict[str, str] | str | None = None
    companies: dict[str, str] | str | None = None
    related_documents: dict[str, str] | str | None = Field(None, alias="relatedDocuments")

    model_config = {"populate_by_name": True, "extra": "ignore"}


class GovWinOpportunity(BaseModel):
    """Represents a GovWin opportunity with all available fields."""

    id: str | None = None
    iq_opp_id: int | None = Field(None, alias="iqOppId")
    title: str | None = None
    type: str | None = None
    status: str | None = None
    description: str | None = None
    country: str | None = None
    created_date: str | None = Field(None, alias="createdDate")
    update_date: str | None = Field(None, alias="updateDate")
    solicitation_date: dict[str, Any] | None = Field(None, alias="solicitationDate")
    solicitation_number: str | None = Field(None, alias="solicitationNumber")
    response_date: dict[str, Any] | None = Field(None, alias="responseDate")
    p_award_date_from: dict[str, Any] | None = Field(None, alias="pAwardDateFrom")
    p_award_date_to: dict[str, Any] | None = Field(None, alias="pAwardDateTo")
    opp_value: float | None = Field(None, alias="oppValue")
    opp_value_canada: float | None = Field(None, alias="oppValueCanada")
    priority: int | None = None
    primary_naics: GovWinNAICS | None = Field(None, alias="primaryNAICS")
    naics: list[GovWinNAICS] = Field(default_factory=list, alias="NAICS")
    gov_entity: GovWinGovEntity | None = Field(None, alias="govEntity")
    primary_requirement: str | None = Field(None, alias="primaryRequirement")
    procurement: str | None = None
    source_url: str | None = Field(None, alias="sourceURL")
    duration: str | None = None
    competition_types: list[dict[str, Any]] = Field(
        default_factory=list, alias="competitionTypes"
    )
    contract_types: list[dict[str, Any]] = Field(default_factory=list, alias="contractTypes")
    type_of_award: str | None = Field(None, alias="typeOfAward")
    cmmc_requirements: str | None = Field(None, alias="cmmcRequirements")
    smart_tag: list[dict[str, Any]] | str | None = Field(None, alias="smartTag")
    links: GovWinLinks | None = None

    model_config = {"populate_by_name": True, "extra": "ignore"}


class GovWinOpportunityBundle(BaseModel):
    """An opportunity with all its extended attributes fetched."""

    opportunity: GovWinOpportunity
    contacts: list[GovWinContact] = Field(default_factory=list)
    companies: list[GovWinCompany] = Field(default_factory=list)
    contracts: list[GovWinContract] = Field(default_factory=list)
    places_of_performance: list[dict[str, Any]] = Field(default_factory=list)

    model_config = {"extra": "ignore"}


# ---------------------------------------------------------------------------
# HubSpot Models
# ---------------------------------------------------------------------------


class HubSpotProperty(BaseModel):
    """Definition of a custom HubSpot property."""

    name: str
    label: str
    type: str = "string"
    field_type: str = Field("text", alias="fieldType")
    group_name: str = Field("govwin", alias="groupName")
    description: str = ""
    options: list[dict[str, str]] = Field(default_factory=list)

    model_config = {"populate_by_name": True}


class HubSpotDealProperties(BaseModel):
    """Properties for a HubSpot deal upsert."""

    dealname: str
    amount: str | None = None
    dealstage: str | None = None
    pipeline: str | None = None
    description: str | None = None
    closedate: str | None = None
    govwin_opp_id: str | None = None
    govwin_iq_opp_id: str | None = None
    govwin_opp_type: str | None = None
    govwin_status: str | None = None
    govwin_solicitation_date: str | None = None
    govwin_solicitation_number: str | None = None
    govwin_source_url: str | None = None
    govwin_iq_url: str | None = None
    govwin_duration: str | None = None
    govwin_primary_naics: str | None = None
    govwin_naics_code: str | None = None
    govwin_primary_requirement: str | None = None
    govwin_analyst_notes: str | None = None
    govwin_competition_type: str | None = None
    govwin_contract_type: str | None = None
    govwin_type_of_award: str | None = None
    govwin_country: str | None = None
    govwin_created_date: str | None = None
    govwin_update_date: str | None = None
    govwin_cmmc_requirements: str | None = None
    govwin_smart_tags: str | None = None
    govwin_agency: str | None = None
    govwin_priority: str | None = None
    govwin_market: str | None = None
    govwin_industry: str | None = None
    govwin_ace_opportunity_type: str | None = None

    model_config = {"extra": "ignore"}


class HubSpotCompanyProperties(BaseModel):
    """Properties for a HubSpot company upsert."""

    name: str
    industry: str | None = None
    govwin_gov_entity_id: str | None = None
    govwin_parent_agency: str | None = None
    govwin_entity_url: str | None = None
    govwin_entity_type: str | None = None

    model_config = {"extra": "ignore"}


class HubSpotContactProperties(BaseModel):
    """Properties for a HubSpot contact upsert."""

    email: str | None = None
    firstname: str | None = None
    lastname: str | None = None
    phone: str | None = None
    jobtitle: str | None = None
    address: str | None = None
    city: str | None = None
    state: str | None = None
    zip: str | None = None
    govwin_contact_id: str | None = None
    govwin_entity_level1: str | None = None
    govwin_entity_level2: str | None = None

    model_config = {"extra": "ignore"}


# ---------------------------------------------------------------------------
# Sync State Models
# ---------------------------------------------------------------------------


class SyncState(BaseModel):
    """Global sync state."""

    last_sync_timestamp: datetime | None = None
    total_synced: int = 0
    last_run_status: str = "never_run"


