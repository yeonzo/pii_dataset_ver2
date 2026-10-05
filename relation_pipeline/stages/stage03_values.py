"""Input: checked plan and pool. Output: frozen, entity-keyed value map."""
from __future__ import annotations

import random

from ..common import digest, fail
from ..renderer import address, canonical, missing, value_error
from ..value_constraints import value_groups, value_group_issues
from ..common import StageFailure


DOMAIN_ROLE_VALUES = {
    "career_education": {
        "WORKPLACE": ["가온인재개발원", "한별교육연구원"],
        "DEPARTMENT": ["교육운영팀", "인재개발팀"],
    },
    "contract": {
        "WORKPLACE": ["누리계약관리센터", "다온서비스관리원"],
        "DEPARTMENT": ["계약관리팀", "정산관리팀"],
    },
    "financial": {
        "WORKPLACE": ["한빛은행", "가온저축은행"],
        "DEPARTMENT": ["금융사고접수팀", "이상거래조사팀"],
    },
    "legal": {
        "WORKPLACE": ["새봄분쟁조정센터", "가온법률지원센터"],
        "DEPARTMENT": ["조정접수과", "사건관리팀"],
    },
    "medical": {
        "WORKPLACE": ["가온의료원", "새봄종합병원"],
        "DEPARTMENT": ["원무과", "진료접수팀"],
    },
    "support": {
        "WORKPLACE": ["다온고객지원센터", "누리서비스센터"],
        "DEPARTMENT": ["환불정산팀", "고객상담팀"],
    },
}


def apply_domain_role_values(result: dict, entities: dict, condition: dict) -> None:
    """Give public organization roles a value that fits the document domain."""
    choices = DOMAIN_ROLE_VALUES.get(condition.get("domain", ""), {})
    serial = int(digest([condition["candidate_id"], "domain-role-values"])[:8], 16)
    offsets = {}
    for eid, entity in entities.items():
        typ = entity["entity_type"]
        values = choices.get(typ)
        if not values or entity.get("context_role") in {"personal_context", "personal_attribute"}:
            continue
        offset = offsets.get(typ, 0)
        value = values[(serial + offset) % len(values)]
        offsets[typ] = offset + 1
        result[eid].update(value=value, canonical_form=canonical(value, typ),
                           render_style="domain_role_surface",
                           source_uuid=f"domain-role:{condition.get('domain','')}:{typ}")


def select_values(plan: dict, condition: dict, rows: list[dict]) -> dict:
    entities = {e["entity_id"]: e for e in plan["entities"]}
    conflicts = value_group_issues(plan)
    if conflicts:
        raise StageFailure(conflicts)
    groups = value_groups(plan)
    rng = random.Random(int(digest([condition["candidate_id"], "values"])[:16], 16))
    result, used = {}, set()
    from ..reference_people import fixed_reference_values
    fixed = fixed_reference_values(plan,condition)
    for eid,item in fixed.items():
        value=item['value']
        error=value_error(entities[eid]['entity_type'],value)
        if error:
            fail('REFERENCE_VALUE',error,'REPLAN')
        result[eid]={'value':value,'canonical_form':canonical(value,entities[eid]['entity_type']),
                     'render_style':'frozen_reference_surface','source_uuid':'reference:'+condition['reference_profile'],
                     'constraint_group':next(g for g,ids in groups.items() if eid in ids),
                     'provenance':item['provenance']}
        used.add((entities[eid]['entity_type'],result[eid]['canonical_form']))
    unique_types = {"NAME", "EMAIL", "MOBILE_PHONE", "TELEPHONE", "RRN", "PASSPORT_NUMBER", "DRIVER_LICENSE_NUMBER", "BANK_ACCOUNT_NUMBER", "CARD_NUMBER", "VEHICLE_NUMBER", "WORKPLACE", "DEPARTMENT", "SCHOOL"}
    for group, ids in groups.items():
        if set(ids)&set(fixed):
            if not set(ids)<=set(fixed):
                fail('REFERENCE_VALUE_GROUP','Reference facts cannot share a value group with actual parties','REPLAN')
            continue
        types = [entities[eid]["entity_type"] for eid in ids]
        candidates = []
        for row in rows:
            if any(missing(row.get(t)) for t in types):
                continue
            okay = True
            for c in plan["slot_constraints"]:
                if c["kind"] == "occupation" and set(ids) & set(c["entity_ids"]):
                    field = c["field"] or "occupation"
                    if not c["allowed_values"] or str(row.get(field, "")) not in c["allowed_values"]:
                        okay = False
            if okay:
                candidates.append(row)
        rng.shuffle(candidates)
        selected = None
        for row in candidates:
            mapping = {}
            for eid in ids:
                type_ = entities[eid]["entity_type"]
                value = address(row[type_], rng) if type_ == "ADDRESS" else str(row[type_]).strip()
                canon = canonical(value, type_)
                if value_error(type_, value) or (type_ in unique_types and (type_, canon) in used):
                    break
                mapping[eid] = {"value": value, "canonical_form": canon, "render_style": "frozen_pool_surface", "source_uuid": row.get("uuid", ""), "constraint_group": group}
            if len(mapping) == len(ids):
                selected = mapping
                break
        if selected is None:
            fail("POOL_NO_FEASIBLE_ROW", f"No usable row for types {types}; no silent fallback")
        result.update(selected)
        used.update((entities[eid]["entity_type"], selected[eid]["canonical_form"]) for eid in ids)
    for c in plan["slot_constraints"]:
        if c["kind"] == "distinct_value":
            forms = [result[eid]["canonical_form"] for eid in c["entity_ids"]]
            if len(forms) != len(set(forms)):
                fail("POOL_DISTINCT_VALUE", c["constraint_id"])
    apply_domain_role_values(result, entities, condition)
    return result
