"""Small, explicit relation vocabularies for document scenarios under evaluation.

The domain ontology says which typed edges are legal. These profiles narrow that
set to edges that can naturally be explained in a particular document subtype.
Unlisted subtypes continue to use the domain ontology until they are profiled.
"""
from __future__ import annotations


# Tuples are (source type, relation, target type), in preferred selection order.
PROFILES = {
    ("career_education", "recommendation"): {
        "PII": [
            ("NAME", "GUIDANCE_SUPPORT", "NAME"),
            ("NAME", "EDUCATION_STATUS", "SCHOOL"),
            ("NAME", "QUALIFICATION_AND_ASSESSMENT", "MAJOR"),
            ("NAME", "ORGANIZATIONAL_RELATION", "WORKPLACE"),
            ("NAME", "CONTACT_ASSOCIATION", "EMAIL"),
            ("NAME", "EDUCATION_STATUS", "MAJOR"),
            ("NAME", "ORGANIZATIONAL_RELATION", "POSITION"),
            ("NAME", "CONTACT_ASSOCIATION", "MOBILE_PHONE"),
            ("NAME", "QUALIFICATION_AND_ASSESSMENT", "SCHOOL"),
        ],
        "NON_PII": [
            ("SCHOOL", "EDUCATION_STATUS", "MAJOR"),
            ("SCHOOL", "CONTACT_ASSOCIATION", "TELEPHONE"),
            ("SCHOOL", "CONTACT_ASSOCIATION", "EMAIL"),
            ("SCHOOL", "LOCATION_ASSOCIATION", "ADDRESS"),
            ("WORKPLACE", "ORGANIZATIONAL_RELATION", "DEPARTMENT"),
            ("WORKPLACE", "CONTACT_ASSOCIATION", "TELEPHONE"),
            ("WORKPLACE", "CONTACT_ASSOCIATION", "EMAIL"),
        ],
        "public_role": "추천서 수신 기관의 공식 정보",
        "person_pairs": {"GUIDANCE_SUPPORT": ("recommender", "candidate")},
    },
    ("contract", "service"): {
        "PII": [
            ("NAME", "BUSINESS_SERVICE_RELATION", "NAME"),
            ("NAME", "FINANCIAL_TRANSACTION", "NAME"),
            ("NAME", "CONTACT_ASSOCIATION", "EMAIL"),
            ("NAME", "FINANCIAL_ASSET_ASSOCIATION", "BANK_ACCOUNT_NUMBER"),
            ("NAME", "ORGANIZATIONAL_RELATION", "WORKPLACE"),
            ("NAME", "CONTACT_ASSOCIATION", "MOBILE_PHONE"),
            ("NAME", "IDENTITY_ASSOCIATION", "DATE_OF_BIRTH"),
            ("NAME", "LOCATION_ASSOCIATION", "ADDRESS"),
        ],
        "NON_PII": [
            ("WORKPLACE", "ORGANIZATIONAL_RELATION", "DEPARTMENT"),
            ("WORKPLACE", "CONTACT_ASSOCIATION", "TELEPHONE"),
            ("WORKPLACE", "LOCATION_ASSOCIATION", "ADDRESS"),
            ("WORKPLACE", "CONTACT_ASSOCIATION", "EMAIL"),
            ("DEPARTMENT", "CONTACT_ASSOCIATION", "TELEPHONE"),
            ("WORKPLACE", "FINANCIAL_ASSET_ASSOCIATION", "BANK_ACCOUNT_NUMBER"),
        ],
        "public_role": "계약 관련 기관의 공식 정보",
        "person_pairs": {
            "BUSINESS_SERVICE_RELATION": ("contract_party_2", "contract_party_1"),
            "FINANCIAL_TRANSACTION": ("contract_party_1", "contract_party_2"),
        },
        "attribute_owners": {"FINANCIAL_ASSET_ASSOCIATION": "contract_party_2"},
    },
    ("financial", "fraud_report"): {
        "PII": [
            ("NAME", "CASE_AND_INCIDENT_RELATION", "NAME"),
            ("NAME", "FINANCIAL_TRANSACTION", "NAME"),
            ("NAME", "FINANCIAL_ASSET_ASSOCIATION", "BANK_ACCOUNT_NUMBER"),
            ("NAME", "CONTACT_ASSOCIATION", "MOBILE_PHONE"),
            ("NAME", "IDENTITY_ASSOCIATION", "RRN"),
            ("NAME", "FINANCIAL_ASSET_ASSOCIATION", "CARD_NUMBER"),
            ("NAME", "LOCATION_ASSOCIATION", "ADDRESS"),
            ("NAME", "INFORMATION_GOVERNANCE", "RRN"),
        ],
        "NON_PII": [
            ("WORKPLACE", "ORGANIZATIONAL_RELATION", "DEPARTMENT"),
            ("WORKPLACE", "CONTACT_ASSOCIATION", "TELEPHONE"),
            ("WORKPLACE", "CONTACT_ASSOCIATION", "EMAIL"),
            ("WORKPLACE", "LOCATION_ASSOCIATION", "ADDRESS"),
            ("DEPARTMENT", "CONTACT_ASSOCIATION", "TELEPHONE"),
            ("WORKPLACE", "PROCEDURAL_RELATION", "DEPARTMENT"),
        ],
        "public_role": "신고 접수 기관의 공식 정보",
        "person_pairs": {
            "CASE_AND_INCIDENT_RELATION": ("reporter", "counterparty"),
            "FINANCIAL_TRANSACTION": ("reporter", "counterparty"),
        },
    },
    ("legal", "mediation_application"): {
        "PII": [
            ("NAME", "CASE_AND_INCIDENT_RELATION", "NAME"),
            ("NAME", "CONTACT_ASSOCIATION", "MOBILE_PHONE"),
            ("NAME", "LOCATION_ASSOCIATION", "ADDRESS"),
            ("NAME", "IDENTITY_ASSOCIATION", "DATE_OF_BIRTH"),
            ("NAME", "FINANCIAL_ASSET_ASSOCIATION", "BANK_ACCOUNT_NUMBER"),
            ("NAME", "CONTACT_ASSOCIATION", "TELEPHONE"),
        ],
        "NON_PII": [
            ("WORKPLACE", "ORGANIZATIONAL_RELATION", "DEPARTMENT"),
            ("WORKPLACE", "CONTACT_ASSOCIATION", "TELEPHONE"),
            ("WORKPLACE", "LOCATION_ASSOCIATION", "ADDRESS"),
            ("WORKPLACE", "CONTACT_ASSOCIATION", "EMAIL"),
            ("DEPARTMENT", "CONTACT_ASSOCIATION", "TELEPHONE"),
            ("WORKPLACE", "PROCEDURAL_RELATION", "DEPARTMENT"),
        ],
        "public_role": "조정 접수 기관의 공식 정보",
        "person_pairs": {"CASE_AND_INCIDENT_RELATION": ("applicant", "counterparty")},
    },
    ("medical", "registration"): {
        "PII": [
            ("NAME", "IDENTITY_ASSOCIATION", "DATE_OF_BIRTH"),
            ("NAME", "CONTACT_ASSOCIATION", "MOBILE_PHONE"),
            ("NAME", "LOCATION_ASSOCIATION", "ADDRESS"),
            ("NAME", "IDENTITY_ASSOCIATION", "RRN"),
            ("NAME", "CONTACT_ASSOCIATION", "TELEPHONE"),
            ("NAME", "INFORMATION_GOVERNANCE", "RRN"),
        ],
        "NON_PII": [
            ("WORKPLACE", "ORGANIZATIONAL_RELATION", "DEPARTMENT"),
            ("WORKPLACE", "CONTACT_ASSOCIATION", "TELEPHONE"),
            ("WORKPLACE", "LOCATION_ASSOCIATION", "ADDRESS"),
            ("WORKPLACE", "CONTACT_ASSOCIATION", "EMAIL"),
            ("DEPARTMENT", "CONTACT_ASSOCIATION", "TELEPHONE"),
            ("WORKPLACE", "PROCEDURAL_RELATION", "DEPARTMENT"),
        ],
        "public_role": "진료 접수 기관의 공식 정보",
        "person_pairs": {},
    },
    ("support", "refund_request"): {
        "PII": [
            ("NAME", "FINANCIAL_ASSET_ASSOCIATION", "CARD_NUMBER"),
            ("NAME", "CONTACT_ASSOCIATION", "EMAIL"),
            ("NAME", "CONTACT_ASSOCIATION", "MOBILE_PHONE"),
            ("NAME", "FINANCIAL_ASSET_ASSOCIATION", "BANK_ACCOUNT_NUMBER"),
            ("NAME", "FINANCIAL_TRANSACTION", "CARD_NUMBER"),
            ("NAME", "FINANCIAL_TRANSACTION", "BANK_ACCOUNT_NUMBER"),
            ("NAME", "LOCATION_ASSOCIATION", "ADDRESS"),
        ],
        "NON_PII": [
            ("WORKPLACE", "CONTACT_ASSOCIATION", "TELEPHONE"),
            ("WORKPLACE", "CONTACT_ASSOCIATION", "EMAIL"),
            ("WORKPLACE", "LOCATION_ASSOCIATION", "ADDRESS"),
            ("DEPARTMENT", "CONTACT_ASSOCIATION", "TELEPHONE"),
            ("WORKPLACE", "FINANCIAL_ASSET_ASSOCIATION", "BANK_ACCOUNT_NUMBER"),
        ],
        "public_role": "환불 처리 기관의 공식 정보",
        "person_pairs": {},
    },
}


def profile_for(condition: dict) -> dict | None:
    if condition.get("graph_policy") != "scenario_v1":
        return None
    return PROFILES.get((condition["domain"], condition.get("subtype")))
