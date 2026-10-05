"""One definition of persona/organization grouping for planning and value selection."""
from __future__ import annotations

import collections

from .common import Issue, StageFailure


def value_groups(plan: dict) -> dict[str, list[str]]:
    entities = {e["entity_id"]:e for e in plan["entities"]}
    parent = {eid:eid for eid in entities}
    def find(eid):
        while parent[eid] != eid:
            parent[eid] = parent[parent[eid]]
            eid = parent[eid]
        return eid
    def union(ids):
        if not ids or any(eid not in entities for eid in ids):
            raise StageFailure([Issue("CONSTRAINT_ENDPOINT", f"Invalid constraint entities: {ids}", "REPAIR_PLAN")])
        for eid in ids[1:]:
            parent[find(eid)] = find(ids[0])
    implicit = collections.defaultdict(list)
    for eid,e in entities.items():
        if e["slot_group"]:
            implicit[e["slot_group"]].append(eid)
    for ids in implicit.values():
        union(ids)
    for c in plan["slot_constraints"]:
        if c["kind"] in {"same_persona","same_organization"}:
            union(c["entity_ids"])
    personal = {"AGE","DATE_OF_BIRTH","RRN","PASSPORT_NUMBER","DRIVER_LICENSE_NUMBER","MOBILE_PHONE","TELEPHONE","EMAIL"}
    owners = collections.defaultdict(set)
    for r in plan["relations"]:
        if (r["source"] in entities and r["target"] in entities and r["target_privacy"] == "PII"
                and entities[r["source"]]["entity_type"] == "NAME" and entities[r["target"]]["entity_type"] in personal):
            owners[r["target"]].add(r["source"])
    for target,names in owners.items():
        if len(names) == 1:
            union([next(iter(names)),target])
    people = {p["person_id"]:p["name_entity_id"] for p in plan.get("persons",[])}
    explicit = collections.defaultdict(set)
    for link in plan.get("person_entity_links",[]):
        if link["link_kind"] == "personal_attribute" and link["person_id"] in people and link["entity_id"] in entities:
            explicit[link["entity_id"]].add(people[link["person_id"]])
    for eid,names in explicit.items():
        if len(names) == 1:
            union([next(iter(names)),eid])
    groups = collections.defaultdict(list)
    for eid in entities:
        groups[find(eid)].append(eid)
    return dict(groups)


def value_group_issues(plan: dict) -> list[Issue]:
    entities = {e["entity_id"]:e for e in plan["entities"]}
    issues = []
    try:
        groups = value_groups(plan)
    except StageFailure as exc:
        return exc.issues
    for group,ids in groups.items():
        allowed_by_field = collections.defaultdict(list)
        for c in plan["slot_constraints"]:
            if c["kind"] == "occupation" and set(c["entity_ids"]) & set(ids):
                allowed_by_field[c["field"] or "occupation"].append(c)
        for field,constraints in allowed_by_field.items():
            common = set(constraints[0]["allowed_values"])
            for constraint in constraints[1:]:
                common &= set(constraint["allowed_values"])
            if not common:
                issues.append(Issue("VALUE_ALLOWED_CONFLICT",
                    f"Group {group}: mutually incompatible/empty allowed values for {field}; "
                    f"constraints={[c['constraint_id'] for c in constraints]}. Correct only the value constraints.",
                    "REPAIR_PLAN",entity_id=ids[0]))
        by_type = collections.defaultdict(list)
        for eid in ids:
            by_type[entities[eid]["entity_type"]].append(eid)
        for typ,duplicates in by_type.items():
            if len(duplicates) < 2:
                continue
            constraints = [c["constraint_id"] for c in plan["slot_constraints"]
                           if c["kind"] in {"same_persona","same_organization"} and set(c["entity_ids"]) & set(ids)]
            slots = sorted({entities[eid]["slot_group"] for eid in ids if entities[eid]["slot_group"]})
            issues.append(Issue("VALUE_GROUP_TYPE_CONFLICT",
                f"Group {group}: {typ} occurs at {duplicates}; slot_groups={slots}, constraints={constraints}. "
                "Correct slot_group/slot_constraints according to the intended owners; preserve all entities and relations.",
                "REPAIR_PLAN",entity_id=duplicates[0]))
    return issues
