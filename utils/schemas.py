from typing import List
from pydantic import BaseModel


class TenantName(BaseModel):
    value: str
    citation: str
    amendments: List[List[str]]


class KeyFacts(BaseModel):
    tenant_name: TenantName


class PeriodDescription(BaseModel):
    value: str
    citation: str


class RentScheduleItem(BaseModel):
    period_description: PeriodDescription


class Alterations(BaseModel):
    value: str
    citation: str


class KeyClauses(BaseModel):
    alterations: Alterations


class FactSheet(BaseModel):
    key_facts: KeyFacts
    rent_schedule: List[RentScheduleItem]
    key_clauses: KeyClauses


class MoneyMapItem(BaseModel):
    clause_name: str
    explanation: str
    citation: str


class TenantObligation(BaseModel):
    description: str
    citation: str


class LandlordObligation(BaseModel):
    description: str
    citation: str


class ObligationsList(BaseModel):
    tenant_obligations: List[TenantObligation]
    landlord_obligations: List[LandlordObligation]


class AuditAndException(BaseModel):
    flag_type: str
    description: str
    suggested_next_step: str
    citation: str


class LeaseDocument(BaseModel):
    fact_sheet: FactSheet
    money_map: List[MoneyMapItem]
    obligations_list: ObligationsList
    audit_and_exceptions: List[AuditAndException]
