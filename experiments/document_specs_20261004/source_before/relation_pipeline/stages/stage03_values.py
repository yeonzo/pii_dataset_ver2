"""Input: checked plan and pool. Output: frozen, entity-keyed value map."""
from __future__ import annotations

import random

from ..common import digest, fail
from ..renderer import address, canonical, missing, value_error
from ..value_constraints import value_groups, value_group_issues
from ..common import StageFailure


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
    return result
