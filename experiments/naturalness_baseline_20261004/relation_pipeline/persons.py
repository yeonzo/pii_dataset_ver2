"""Named document participants, subtype counts and explicit ownership links."""
from __future__ import annotations

import collections
import re

from .common import Issue

# Explicit named-person counts for every document subtype in assets/catalog.json.
# Unknown subtype keys fail loudly in party_range() rather than inheriting (1,1).
_CONTRACT_SUBTYPES = (
    "lease", "rental", "construction", "loan", "investment", "shareholder",
    "escrow", "settlement", "service", "sale", "consign", "joint_venture",
    "franchise", "partnership", "agency", "distribution", "advertising",
    "maintenance", "supply", "transfer", "car_rental_short", "car_rental_long",
    "car_rental_corp", "accident_rear", "accident_intersection", "accident_parking",
    "accident_pedestrian", "accident_single", "overseas_visa", "overseas_assignment",
    "overseas_trip", "employment", "freelance", "consulting", "nda", "license",
    "it_outsourcing", "research", "data_processing",
)
_CONTRACT_THREE_PARTY = {
    "accident_rear", "accident_intersection", "accident_parking",
    "accident_pedestrian", "accident_single",
}
_LEGAL_SUBTYPES = (
    "incident_report", "legal_consultation", "complaint_filing", "damage_claim",
    "witness_statement", "police_statement", "mediation_application",
)

RANGES = {
    "career_education":{
        "resume_form":(1,1), "cover_letter":(1,1), "career_statement":(1,1),
        "job_application":(1,1), "recommendation":(2,2),
        "admission_application":(1,2), "enrollment_certificate":(1,1),
        "transcript":(1,1), "scholarship_application":(1,2), "leave_return":(1,1),
    },
    "contract":{
        subtype:((2,3) if subtype in _CONTRACT_THREE_PARTY else (2,2))
        for subtype in _CONTRACT_SUBTYPES
    },
    "financial":{
        "loan_application":(1,2), "card_application":(1,1), "account_opening":(1,1),
        "insurance_subscription":(2,3), "wire_transfer":(2,2), "fraud_report":(1,2),
    },
    "legal":{subtype:(2,3) for subtype in _LEGAL_SUBTYPES},
    "medical":{
        "registration":(1,2), "questionnaire":(1,1), "health_checkup":(1,1),
        "payment":(1,1), "insurance_claim":(1,2), "telemedicine_consult":(1,1),
        "checkup_result":(1,1), "surgery_consent":(2,2),
    },
    "support":{
        "complaint_product":(1,1), "complaint_service":(1,1), "support_ticket":(1,1),
        "refund_request":(1,1), "delivery_issue":(1,1), "as_request":(1,1),
        "billing_dispute":(1,1), "account_inquiry":(1,1),
    },
}
ROLE_LABELS = {"applicant":"신청인","student":"학생","candidate":"지원자","recommender":"추천인",
    "guardian":"보호자","guarantor":"보증인","patient":"환자","claimant":"청구인","borrower":"차주",
    "policyholder":"보험 계약자","insured":"피보험자","beneficiary":"수익자","sender":"송금인",
    "recipient":"수취인","reporter":"신고인","counterparty":"상대방","customer":"고객",
    "witness":"목격자","contract_party_1":"첫 번째 계약 당사자 또는 담당 대표",
    "contract_party_2":"두 번째 계약 당사자 또는 담당 대표","example_person":"예시 인물"}

# Named-person roles by document subtype. Unnamed clerks, issuers and institutional
# contacts are not counted as NAME entities. Repeated lists share document semantics.
CAREER_EDUCATION_ROLES = {
    "resume_form":["candidate"], "cover_letter":["candidate"],
    "career_statement":["candidate"], "job_application":["applicant"],
    "recommendation":["candidate","recommender"],
    "admission_application":["candidate","guardian"],
    "enrollment_certificate":["student"], "transcript":["student"],
    "scholarship_application":["applicant","guarantor"], "leave_return":["student"],
}
CONTRACT_ROLES = {
    subtype:["contract_party_1","contract_party_2","guarantor"]
    for subtype in _CONTRACT_SUBTYPES
}
for _subtype in _CONTRACT_THREE_PARTY:
    CONTRACT_ROLES[_subtype] = ["claimant","counterparty","witness"]

ROLE_IDS = {
    "career_education":CAREER_EDUCATION_ROLES,
    "contract":CONTRACT_ROLES,
    "financial":{
        "loan_application":["borrower","guarantor"],
        "card_application":["applicant"], "account_opening":["applicant"],
        "insurance_subscription":["policyholder","insured","beneficiary"],
        "wire_transfer":["sender","recipient"], "fraud_report":["reporter","counterparty"],
    },
    "legal":{
        "incident_report":["reporter","counterparty","witness"],
        "legal_consultation":["applicant","counterparty","witness"],
        "complaint_filing":["reporter","counterparty","witness"],
        "damage_claim":["claimant","counterparty","witness"],
        "witness_statement":["witness","reporter","counterparty"],
        "police_statement":["reporter","counterparty","witness"],
        "mediation_application":["applicant","counterparty","witness"],
    },
    "medical":{
        "registration":["patient","guardian"], "questionnaire":["patient"],
        "health_checkup":["patient"], "payment":["patient"],
        "insurance_claim":["insured","claimant"], "telemedicine_consult":["patient"],
        "checkup_result":["patient"], "surgery_consent":["patient","guardian"],
    },
    "support":{
        "complaint_product":["customer"], "complaint_service":["customer"],
        "support_ticket":["customer"], "refund_request":["customer"],
        "delivery_issue":["customer"], "as_request":["customer"],
        "billing_dispute":["customer"], "account_inquiry":["customer"],
    },
}


def party_range(domain,subtype):
    try:
        return RANGES[domain][subtype]
    except KeyError as exc:
        raise ValueError(f"Missing named-person range for {domain}/{subtype}") from exc


def role_ids(domain,subtype):
    try:
        return list(ROLE_IDS[domain][subtype])
    except KeyError as exc:
        raise ValueError(f"Missing named-person roles for {domain}/{subtype}") from exc


def select_people(domain,subtype,rng,minimum=1):
    lo,hi = party_range(domain,subtype)
    if minimum > hi:
        raise ValueError("Required relation exceeds subtype person capacity")
    n = rng.randint(max(lo,minimum),hi)
    slots = [{"person_id":f"P{i+1}","name_entity_id":f"E{i+1}","role":role,"role_label":ROLE_LABELS[role]}
             for i,role in enumerate(role_ids(domain,subtype)[:n])]
    return {"n_parties":n,"person_count_range":[lo,hi],"person_slots":slots,
            "person_count_scope":"문서에 이름 엔티티로 등록되는 주요 실제 인물 수. 이름 없는 일반 담당자 역할은 제외한다.",
            "max_example_persons":0}


def seed_person_links(plan,condition):
    """Build explicit seed ownership from named graph endpoints, without values."""
    slots = condition.get("person_slots") or [{"person_id":f"P{i+1}","name_entity_id":e["entity_id"],"role":"applicant"}
          for i,e in enumerate(e for e in plan["entities"] if e["entity_type"] == "NAME")]
    people = [{"person_id":s["person_id"],"name_entity_id":s["name_entity_id"],"role":s["role"],"context_kind":"actual_party"} for s in slots]
    types = {e["entity_id"]:e["entity_type"] for e in plan["entities"]}
    links = {}
    personal = {"AGE","DATE_OF_BIRTH","RRN","PASSPORT_NUMBER","DRIVER_LICENSE_NUMBER","MOBILE_PHONE","TELEPHONE","EMAIL","BANK_ACCOUNT_NUMBER","CARD_NUMBER","ADDRESS"}
    for p in people:
        name = p["name_entity_id"]
        incident = [r for r in plan["relations"] if name in (r["source"],r["target"])]
        links[p["person_id"],name] = {"person_id":p["person_id"],"entity_id":name,"role":p["role"],"link_kind":"identity","relation_ids":[r["relation_id"] for r in incident]}
        for r in incident:
            other = r["target"] if r["source"] == name else r["source"]
            key = p["person_id"],other
            if key not in links:
                links[key] = {"person_id":p["person_id"],"entity_id":other,"role":r["relation"],
                    "link_kind":"related_context" if types.get(other) == "NAME" or types.get(other) not in personal else "personal_attribute","relation_ids":[]}
            links[key]["relation_ids"].append(r["relation_id"])
    return people,list(links.values())


def person_plan_issues(plan,condition):
    issues = []
    people = {p["person_id"]:p for p in plan["persons"]}
    entities = {e["entity_id"]:e for e in plan["entities"]}
    relations = {r["relation_id"]:r for r in plan["relations"]}
    names = [p["name_entity_id"] for p in plan["persons"]]
    if len(people) != len(plan["persons"]) or any(not re.fullmatch(r"P[1-9][0-9]*",p) for p in people) or len(names) != len(set(names)):
        issues.append(Issue("PERSON_ID","Persons and NAME identities must be unique","REPLAN"))
    if set(names) != {eid for eid,e in entities.items() if e["entity_type"] == "NAME"}:
        issues.append(Issue("PERSON_NAME_COVERAGE","Every registered NAME needs exactly one person","REPLAN"))
    actual = [p for p in people.values() if p["context_kind"] == "actual_party"]
    if len(actual) != condition.get("n_parties",len(actual)):
        issues.append(Issue("PERSON_COUNT","Actual named person count differs from the condition","REPLAN"))
    if len(people)-len(actual) > condition.get("max_example_persons",0):
        issues.append(Issue("EXAMPLE_PERSON_COUNT","Example person count exceeds the condition","REPLAN"))
    for expected in condition.get("person_slots",[]):
        got = people.get(expected["person_id"],{})
        if any(got.get(k) != expected[k] for k in ("person_id","name_entity_id","role")) or got.get("context_kind") != "actual_party":
            issues.append(Issue("PERSON_ROLE_PLAN","Keep assigned person ID, name ID and role","REPLAN",entity_id=expected["name_entity_id"]))
    seen,identity = set(),collections.Counter()
    linked = collections.defaultdict(set)
    for link in plan["person_entity_links"]:
        pid,eid = link["person_id"],link["entity_id"]
        person = people.get(pid)
        key = pid,eid
        if key in seen or not person or eid not in entities or not link["role"].strip():
            issues.append(Issue("PERSON_ENTITY_LINK","Invalid/duplicate person–entity link","REPLAN",entity_id=eid))
            continue
        seen.add(key)
        if link["link_kind"] == "identity":
            identity[pid] += 1
            if eid != person["name_entity_id"]:
                issues.append(Issue("PERSON_IDENTITY_LINK","Identity link must target this person's NAME","REPLAN",entity_id=eid))
        elif entities[eid]["entity_type"] == "NAME" and link["link_kind"] == "personal_attribute":
            issues.append(Issue("PERSON_OWNERSHIP","Another person is related context, not an owned attribute","REPLAN",entity_id=eid))
        for rid in link["relation_ids"]:
            relation = relations.get(rid)
            if not relation or eid not in (relation["source"],relation["target"]):
                issues.append(Issue("PERSON_LINK_RELATION","Link must cite a relation incident to this entity","REPLAN",entity_id=eid,relation_id=rid))
            else:
                linked[pid,rid].add(eid)
                if link["link_kind"] == "personal_attribute" and (relation["target_privacy"] != "PII" or
                        any(entities.get(x,{}).get("entity_type") == "NAME" for x in (relation["source"],relation["target"])) and person["name_entity_id"] not in (relation["source"],relation["target"])):
                    issues.append(Issue("PERSON_OWNERSHIP","An owned attribute needs this person's personal relation, not another person's/public relation","REPLAN",entity_id=eid,relation_id=rid))
    if any(identity[p] != 1 for p in people):
        issues.append(Issue("PERSON_IDENTITY_COVERAGE","Every person needs one identity link","REPLAN"))
    for p in actual:
        incident = [r for r in relations.values() if p["name_entity_id"] in (r["source"],r["target"])]
        if not any(r["target_privacy"] == "PII" for r in incident):
            issues.append(Issue("PERSON_PII_CONTEXT","An actual named party needs a personal relationship context","REPLAN",entity_id=p["name_entity_id"]))
        for r in incident:
            if r["target_privacy"] == "NON_PII":
                issues.append(Issue("NAME_CONTEXT_POLICY","Actual named parties cannot be attributed NON_PII relationships","REPLAN",relation_id=r["relation_id"]))
            if r["target_privacy"] == "PII" and linked[p["person_id"],r["relation_id"]] != {r["source"],r["target"]}:
                issues.append(Issue("PERSON_RELATION_LINK","Personal relationships need links for both endpoints relative to the named party","REPLAN",relation_id=r["relation_id"]))
    return issues
