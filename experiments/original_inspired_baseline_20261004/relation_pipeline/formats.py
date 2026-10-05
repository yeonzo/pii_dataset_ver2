"""Small coupled layout catalog; subtype labels/lengths live in local assets."""
from __future__ import annotations

from .common import ROOT, read_json

CATALOG = read_json(ROOT / "assets/catalog.json")
ONTOLOGY = read_json(ROOT / "assets/ontology.json")

VARIANTS = {
    "chronological": ("시간순 상담 경과", [("background", "접수 배경", ["prose"], .18), ("initial", "초기 확인", ["prose", "key_value"], .25), ("progress", "상담 경과", ["prose", "list_item"], .37), ("followup", "결과와 후속 일정", ["prose"], .20)]),
    "question_answer": ("문답식 기록", [("background", "상담 개요", ["prose", "key_value"], .15), ("questions", "상담 문답", ["question", "answer"], .45), ("summary", "확인 사항", ["prose", "list_item"], .25), ("followup", "후속 안내", ["prose"], .15)]),
    "topical": ("항목별 요약", [("overview", "핵심 요약", ["prose", "key_value"], .20), ("facts", "확인한 사실", ["prose", "list_item"], .30), ("actions", "업무 처리", ["prose", "numbered_list"], .30), ("followup", "남은 사항", ["prose", "list_item"], .20)]),
    "problem_action_result": ("문제–조치–결과", [("background", "상담 배경", ["prose"], .15), ("problem", "확인된 문제", ["prose", "key_value"], .30), ("action", "처리 내용", ["prose", "numbered_list"], .35), ("result", "처리 결과와 후속 조치", ["prose"], .20)]),
    "handoff": ("담당자 인계 메모", [("status", "현재 상황", ["prose", "key_value"], .25), ("completed", "완료한 조치", ["prose", "list_item"], .30), ("pending", "인계할 사항", ["prose", "list_item"], .30), ("next", "다음 담당자의 확인 사항", ["prose", "numbered_list"], .15)]),
    "request_resolution": ("신청 내용과 처리 결과", [("request", "신청 내용", ["prose", "key_value"], .25), ("verification", "확인 과정", ["prose"], .30), ("resolution", "처리 결과", ["prose", "list_item"], .30), ("notice", "안내 사항", ["prose"], .15)]),
    "narrative": ("자유 서술형 업무 기록", [("opening", "사건의 시작", ["prose"], .20), ("development", "진행 과정", ["prose"], .35), ("response", "대응과 확인", ["prose"], .30), ("ending", "마무리", ["prose"], .15)]),
    "fixed_contract": ("조항형 계약서", [("parties", "당사자와 계약 목적", ["prose", "key_value"], .20), ("terms", "계약 조건", ["prose", "numbered_list"], .30), ("duties", "의무와 이행 절차", ["prose", "numbered_list"], .30), ("closing", "통지와 계약 확인", ["prose", "key_value"], .20)]),
    "fixed_form": ("항목형 서식", [("overview", "작성 목적", ["prose", "key_value"], .15), ("details", "기재 사항", ["key_value", "prose"], .35), ("procedure", "확인과 처리 절차", ["prose", "numbered_list"], .35), ("notice", "안내 및 확인", ["prose", "key_value"], .15)]),
}


def format_for(domain: str, subtype: str) -> tuple[str, bool, list[str]]:
    if domain == "contract":
        return "contract", True, ["fixed_contract"]
    if domain == "financial" or subtype in {"resume_form", "job_application", "admission_application", "enrollment_certificate", "transcript", "scholarship_application", "leave_return", "registration", "questionnaire", "health_checkup", "payment", "insurance_claim", "surgery_consent", "complaint_filing", "damage_claim", "mediation_application"}:
        return "form", True, ["fixed_form"]
    if subtype in {"cover_letter", "career_statement", "recommendation"}:
        return "career_narrative", False, ["chronological", "topical", "problem_action_result", "narrative"]
    if subtype in {"incident_report", "witness_statement", "police_statement", "checkup_result"}:
        return "case_record", False, ["chronological", "topical", "problem_action_result", "narrative", "handoff"]
    return "consultation_record", False, [k for k in VARIANTS if not k.startswith("fixed_")]


def sections_for(variant: str, target: int) -> list[dict]:
    sections = [{"section_id": sid, "title": title, "allowed_kinds": kinds, "target_chars": round(target * weight), "required": True} for sid, title, kinds, weight in VARIANTS[variant][1]]
    sections[-1]["target_chars"] += target - sum(s["target_chars"] for s in sections)
    return sections


# Explicit endpoint policy. This is a conservative policy, not an assertion that
# every combination below is meaningful in every scene; independent review decides.
ORG = {"WORKPLACE", "DEPARTMENT", "SCHOOL"}
ACTOR = {"NAME"} | ORG
CONTACT = {"EMAIL", "MOBILE_PHONE", "TELEPHONE"}
IDENTITY = {"AGE", "DATE_OF_BIRTH", "RRN", "PASSPORT_NUMBER", "DRIVER_LICENSE_NUMBER"}
MONEY = {"BANK_ACCOUNT_NUMBER", "CARD_NUMBER"}
PAIRS = {
    "CONTACT_ASSOCIATION": [(ACTOR, CONTACT)],
    "LOCATION_ASSOCIATION": [(ACTOR, {"ADDRESS"})],
    "IDENTITY_ASSOCIATION": [({"NAME"}, IDENTITY), ({"VEHICLE_NUMBER"}, {"DRIVER_LICENSE_NUMBER"})],
    "ORGANIZATIONAL_RELATION": [({"NAME"}, ORG | {"POSITION"}), ({"WORKPLACE", "DEPARTMENT"}, {"DEPARTMENT", "POSITION"})],
    "EDUCATION_STATUS": [({"NAME"}, {"SCHOOL", "MAJOR"}), ({"SCHOOL"}, {"MAJOR"})],
    "FINANCIAL_ASSET_ASSOCIATION": [(ACTOR, MONEY)],
    "FINANCIAL_TRANSACTION": [(ACTOR, MONEY), ({"NAME"}, {"NAME"})],
    "ASSET_RELATION": [(ACTOR, {"VEHICLE_NUMBER", "ADDRESS"})],
    "PERSONAL_RELATIONSHIP": [({"NAME"}, {"NAME"})],
    "BUSINESS_SERVICE_RELATION": [(ACTOR, ACTOR)],
    "COLLABORATION_PARTNERSHIP": [(ACTOR, ACTOR)],
    "GUIDANCE_SUPPORT": [(ACTOR, ACTOR)],
    "CREDIT_AND_GUARANTEE_RELATION": [({"NAME"}, {"NAME", "WORKPLACE", "BANK_ACCOUNT_NUMBER"})],
    "INSURANCE_RELATION": [({"NAME"}, {"NAME", "WORKPLACE", "BANK_ACCOUNT_NUMBER"})],
    "QUALIFICATION_AND_ASSESSMENT": [({"NAME"}, {"SCHOOL", "MAJOR", "POSITION", "WORKPLACE"})],
    "INFORMATION_GOVERNANCE": [(ACTOR, CONTACT | IDENTITY | MONEY | {"ADDRESS", "VEHICLE_NUMBER"})],
    "PROCEDURAL_RELATION": [(ACTOR, ACTOR | {"POSITION"})],
    "CASE_AND_INCIDENT_RELATION": [(ACTOR, ACTOR | {"VEHICLE_NUMBER", "BANK_ACCOUNT_NUMBER"})],
    "EVENT_PARTICIPATION": [(ACTOR, ORG)],
}


def allowed_triples(domain: str) -> list[list[str]]:
    return sorted([s, item["relation"], t] for item in ONTOLOGY[domain] for sources, targets in PAIRS.get(item["relation"], []) for s in sources for t in targets if not (s == t and s not in ACTOR))


def format_catalog() -> dict:
    return {key: {"label": label, "sections": sections_for(key, 2000)} for key, (label, _) in VARIANTS.items()}
