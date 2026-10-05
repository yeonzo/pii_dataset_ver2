"""Input: condition/ontology. Output: checked graph and scenes, without mention quotas."""
from __future__ import annotations

import collections
import copy
import json
import re

from ..common import Issue, StageFailure, digest
from ..formats import ONTOLOGY, allowed_triples
from ..schemas import PLAN, obj, string, array, validate
from ..planning_seed import relation_slots, seed_plan
from ..prompt_inputs import condition_input
from ..value_constraints import value_group_issues
from ..persons import person_plan_issues
from ..privacy import privacy_input
from ..document_purpose import PLAN_GUIDANCE, FACT_PLAN_GUIDANCE

SYSTEM = """[목적]
코드가 확정한 관계 그래프에 구체적인 업무 맥락과 장면 설명을 계획한다. 본문과 실제 값은 생성하지 않는다.

[입력]
condition: 형식·주제·관점·인물 역할. seed_plan: 고정 인물·엔티티·관계·값 그룹.
ontology: 사용된 관계의 정의. feedback: 이전 오류. 기존 계획은 수정 맥락이다.

[핵심 규칙]
1. 그래프의 인물·역할·endpoint·관계·privacy·값 그룹은 고정이다. 다시 반환하거나 바꾸지 않는다.
2. privacy_policy에 따라 각 R의 context_reason에 해당 개인/기관의 역할, 정보 귀속, 실제 사용 목적·행위·상대를 구체적으로 쓴다. 관계명이 아니라 온톨로지의 의미를 본문에서 입증할 수 있는 맥락이어야 한다. 값의 외형을 근거로 삼지 않는다.
3. 각 R을 입력의 SC 중 하나에 배정하고, 모든 SC의 purpose/outline을 문서 종류·변형·주제에 맞게 쓴다. 장면 간 당사자 역할·사실·처리 흐름을 일관되게 연결한다. section ID·순서는 코드가 보존한다.
4. 서로 다른 E ID는 같은 TYPE이어도 서로 다른 대상이다. 특히 계좌·카드의 소유자, 사용 목적, 기관 정산 계좌, 거래 출처·도착지를 구분하고 하나의 사건으로 임의 통합하지 않는다. 각 R의 context_reason과 장면 개요가 서로 모순되지 않도록 한다.
5. 인물과 개인 속성의 소유자를 바꾸거나, 다른 이름·기관·식별정보·계획 밖 의미 관계를 추가하지 않는다. 같은 기관의 연락·조직 정보라도 개인 귀속과 공용 용도를 구분한다.
6. 반복 횟수·위치·mention 비율·근거 거리·표현 방식별 수량은 배정하지 않는다. 기존 계획에 feedback이 있으면 오류 맥락만 수정한다.

[출력]
JSON 필수 필드: relation_contexts, scene_notes.
relation_contexts: 모든 R ID를 키로 {context_reason, scene_id}.
scene_notes: 모든 SC ID를 키로 {purpose, outline}.
서술은 한국어다. 코드가 고정 그래프에 이 맥락만 결합해 최종 plan을 검사한다.
"""

CONSTRAINT_REPAIR_SYSTEM = """[목적]
기존 계획의 값 제약 오류만 수정한다. 그래프·장면·privacy를 다시 작성하지 않는다.

[입력]
existing_plan: 고정 엔티티·관계·장면·현재 값 제약. feedback: 충돌/공급 오류.
baseline_slot_groups: 엔티티를 서로 다른 그룹으로 두는 수정 시작점. 개인 NAME의 명확한 PII 연락/신원 속성은 코드가 자동 묶는다.

[핵심 규칙]
1. 서로 다른 같은 TYPE 노드는 같은 persona/기관 그룹으로 묶지 않는다. slot_group과 same_persona/same_organization의 전이적 합집합도 검사된다.
2. 개인 귀속을 보존한다. 기관/부서/학교 등의 별도 주체를 무리하게 한 행으로 묶지 않는다. 자동 개인 귀속 연결은 제약으로 반복 지정할 필요가 없다.
3. 오류를 만든 그룹/명시 제약을 수정하고, 무관한 유효 제약은 보존한다. occupation의 허용 값 교집합은 비어 있으면 안 된다.

[출력]
JSON: slot_groups는 모든 기존 E ID를 키로 하는 그룹 문자열 객체, slot_constraints는 수정된 제약 배열이다.
엔티티·관계·장면·본문은 반환하지 않는다. 코드가 기존 계획에 제약 변경만 적용한다.
"""

VALUE_REPAIR_CODES = {"VALUE_GROUP_TYPE_CONFLICT","SAME_PERSONA_DUPLICATE_TYPE","VALUE_ALLOWED_CONFLICT","POOL_NO_FEASIBLE_ROW","POOL_DISTINCT_VALUE"}


def constraint_repair_input(condition, feedback, existing_plan):
    groups = {e["entity_id"]:e["entity_id"] for e in existing_plan["entities"]}
    constraints = copy.deepcopy(PLAN["properties"]["slot_constraints"])
    constraints["items"]["properties"]["entity_ids"]["items"]["enum"] = list(groups)
    schema = obj(slot_groups=obj(**{eid:string([*groups,""]) for eid in groups}),slot_constraints=constraints)
    payload = {"privacy_policy":privacy_input(),"domain":condition["domain"],"existing_plan":{k:copy.deepcopy(existing_plan[k]) for k in PLAN["properties"]},
               "feedback":feedback,"baseline_slot_groups":groups}
    return payload,schema


def privacy_groups(plan: dict) -> dict[str, str]:
    incident = collections.defaultdict(list)
    for r in plan["relations"]:
        incident[r["source"]].append(r["target_privacy"])
        incident[r["target"]].append(r["target_privacy"])
    return {e["entity_id"]: "PII" if "PII" in incident[e["entity_id"]] else "NON_PII" for e in plan["entities"] if incident[e["entity_id"]]}


def check_plan(plan: dict, condition: dict) -> None:
    validate(plan, PLAN)
    issues = []
    entities = {e["entity_id"]: e for e in plan["entities"]}
    relations = {r["relation_id"]: r for r in plan["relations"]}
    scenes = {s["scene_id"]: s for s in plan["scenes"]}
    for items, field, pattern in [(plan["entities"], "entity_id", r"E[1-9][0-9]*"), (plan["relations"], "relation_id", r"R[1-9][0-9]*"), (plan["scenes"], "scene_id", r"SC[1-9][0-9]*")]:
        ids = [i[field] for i in items]
        if len(ids) != len(set(ids)) or any(not re.fullmatch(pattern, x) for x in ids):
            issues.append(Issue("PLAN_ID", f"Invalid/duplicate {field}", "REPLAN"))
    triples = {tuple(x) for x in allowed_triples(condition["domain"])}
    allowed_types = set(condition["allowed_personal_types"] + condition["allowed_public_types"] + ["NAME"])
    for e in plan["entities"]:
        if e["entity_type"] not in allowed_types:
            issues.append(Issue("PLAN_TYPE_POLICY", "Type unavailable for selected subtype", "REPLAN", entity_id=e["entity_id"]))
    seen = set()
    for r in plan["relations"]:
        source, target = entities.get(r["source"]), entities.get(r["target"])
        if not source or not target or r["source"] == r["target"]:
            issues.append(Issue("PLAN_ENDPOINT", "Missing endpoint or self edge", "REPLAN", relation_id=r["relation_id"]))
            continue
        triple = (source["entity_type"], r["relation"], target["entity_type"])
        if triple not in triples:
            issues.append(Issue("PLAN_TRIPLE", str(triple), "REPLAN", relation_id=r["relation_id"]))
        key = (r["source"], r["relation"], r["target"])
        if key in seen:
            issues.append(Issue("PLAN_DUPLICATE_EDGE", str(key), "REPLAN", relation_id=r["relation_id"]))
        seen.add(key)
        if r["scene_id"] not in scenes or not r["context_reason"].strip():
            issues.append(Issue("PLAN_SCENE_CONTEXT", "Missing scene/context_reason", "REPLAN", relation_id=r["relation_id"]))
        if source["entity_type"] == "NAME" and r["target_privacy"] == "NON_PII":
            person = next((p for p in plan['persons'] if p['name_entity_id']==r['source']),{})
            if person.get('context_kind') not in {'example_person','public_reference'}:
                issues.append(Issue("NAME_CONTEXT_POLICY", "Actual personal NAME attribution cannot be NON_PII", "REPLAN", relation_id=r["relation_id"]))
            if target["entity_type"] in {"AGE", "DATE_OF_BIRTH", "RRN", "PASSPORT_NUMBER", "DRIVER_LICENSE_NUMBER"}:
                issues.append(Issue("FICTIONAL_ATTRIBUTE_POLICY", "Unconfirmed fictional demographic/identifier extension", "REPLAN", relation_id=r["relation_id"]))
    groups = privacy_groups(plan)
    if len(groups) != len(entities):
        issues.append(Issue("ISOLATED_ENTITY", "Every entity must have at least one incident edge", "REPLAN"))
    if sum(g == "NON_PII" for g in groups.values()) < condition["non_pii_only_min"]:
        issues.append(Issue("NON_PII_ONLY_COUNT", "Not enough non-PII-only nodes", "REPLAN"))
    if len(relations) != condition["relation_count"]:
        issues.append(Issue("RELATION_COUNT", "Exact relation count differs", "REPLAN"))
    for privacy, key in [("PII", "pii_relation_target"), ("NON_PII", "non_pii_relation_target")]:
        if sum(r["target_privacy"] == privacy for r in plan["relations"]) != condition[key]:
            issues.append(Issue("PRIVACY_RELATION_COUNT", privacy, "REPLAN"))
    sections = {s["section_id"] for s in condition["section_plan"]}
    if sections != {s["section_id"] for s in plan["scenes"]} or len({s["order"] for s in plan["scenes"]}) != len(scenes):
        issues.append(Issue("SCENE_SECTION", "Missing sections or duplicate scene order", "REPLAN"))
    assigned = []
    for scene in plan["scenes"]:
        assigned.extend(scene["relation_ids"])
        for rid in scene["relation_ids"]:
            if rid not in relations or relations[rid]["scene_id"] != scene["scene_id"]:
                issues.append(Issue("SCENE_RELATION", rid, "REPLAN"))
    if collections.Counter(assigned) != collections.Counter(relations.keys()):
        issues.append(Issue("SCENE_COVERAGE", "Every relation needs one owner scene", "REPLAN"))
    for c in plan["slot_constraints"]:
        if any(eid not in entities for eid in c["entity_ids"]):
            issues.append(Issue("CONSTRAINT_ENDPOINT", c["constraint_id"], "REPLAN"))
        elif c["kind"] == "same_persona" and len({entities[eid]["entity_type"] for eid in c["entity_ids"]}) != len(c["entity_ids"]):
            issues.append(Issue("SAME_PERSONA_DUPLICATE_TYPE", c["constraint_id"], "REPLAN"))
    if not any(i.code in {"PLAN_ID","PLAN_ENDPOINT","CONSTRAINT_ENDPOINT"} for i in issues):
        issues.extend(value_group_issues(plan))
        issues.extend(person_plan_issues(plan,condition))
    for relation in set(condition.get("required_relation_types",[]))-{r["relation"] for r in plan["relations"]}:
        issues.append(Issue("REQUIRED_RELATION_MISSING",relation,"REPLAN"))
    if issues:
        raise StageFailure(issues)


def plan_fingerprint(plan: dict) -> str:
    roles = {e["entity_id"]: (e["entity_type"], e["context_role"].strip().lower()) for e in plan["entities"]}
    scene_positions = {s["scene_id"]: (s["section_id"], i) for i, s in enumerate(sorted(plan["scenes"], key=lambda x: x["order"]))}
    edges = [(r["source"], r["target"], (r["relation"], scene_positions[r["scene_id"]], r["target_privacy"])) for r in plan["relations"]]
    neighbors = collections.defaultdict(set)
    for source,target,_ in edges:
        neighbors[source].add(target)
        neighbors[target].add(source)
    unseen = set(roles)
    components = []
    while unseen:
        frontier = [next(iter(unseen))]
        component = set()
        while frontier:
            vertex = frontier.pop()
            if vertex in component:
                continue
            component.add(vertex)
            frontier.extend(neighbors[vertex]-component)
        unseen -= component
        local_edges = [(s,t,label) for s,t,label in edges if s in component]
        initial = collections.defaultdict(list)
        for vertex in component:
            initial[roles[vertex]].append(vertex)

        def refine(partition):
            while True:
                colors = {vertex:i for i,cell in enumerate(partition) for vertex in cell}
                updated = []
                for cell in partition:
                    buckets = collections.defaultdict(list)
                    for vertex in cell:
                        outgoing = tuple(sorted((label,colors[t]) for s,t,label in local_edges if s == vertex))
                        incoming = tuple(sorted((label,colors[s]) for s,t,label in local_edges if t == vertex))
                        buckets[(outgoing,incoming)].append(vertex)
                    updated.extend(buckets[key] for key in sorted(buckets))
                if len(updated) == len(partition):
                    return updated
                partition = updated

        def canonical(partition):
            partition = refine(partition)
            unresolved = [(len(cell),i) for i,cell in enumerate(partition) if len(cell)>1]
            if not unresolved:
                order = [cell[0] for cell in partition]
                indices = {vertex:i for i,vertex in enumerate(order)}
                encoded = {"nodes":[roles[vertex] for vertex in order],
                           "edges":sorted((indices[s],indices[t],label) for s,t,label in local_edges)}
                return json.dumps(encoded, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            _, cell_index = min(unresolved)
            cell = partition[cell_index]
            results, equivalent_twins = [], set()
            for vertex in cell:
                # Identical directed neighbors are exact twins; one branch suffices.
                twin = (tuple(sorted((t,label) for s,t,label in local_edges if s == vertex)),
                        tuple(sorted((s,label) for s,t,label in local_edges if t == vertex)))
                if twin in equivalent_twins:
                    continue
                equivalent_twins.add(twin)
                split = partition[:cell_index] + [[vertex], [v for v in cell if v != vertex]] + partition[cell_index+1:]
                results.append(canonical(split))
            return min(results)

        components.append(canonical([initial[key] for key in sorted(initial)]))
    return digest({"components":sorted(components),
                   "scenes":[(s["section_id"],i) for i,s in enumerate(sorted(plan["scenes"], key=lambda s:s["order"]))]})


def attach_plan_metadata(plan: dict) -> dict:
    return {**plan, "expected_privacy_groups": privacy_groups(plan), "plan_fingerprint": plan_fingerprint(plan)}


def planning_contract(condition: dict) -> tuple[dict, list[list[str]]]:
    # Serialization also removes shared TEXT schema aliases before specialization.
    schema = json.loads(json.dumps(PLAN))
    types = sorted(set(condition["allowed_personal_types"] + condition["allowed_public_types"] + ["NAME"]))
    triples = [triple for triple in allowed_triples(condition["domain"]) if triple[0] in types and triple[2] in types]
    relation_count = condition["relation_count"]
    extra_capacity=2 if condition.get('reference_profile') else 0
    entity_ids = [f"E{i}" for i in range(1,2*relation_count+extra_capacity+1)]
    relation_ids = [f"R{i}" for i in range(1,relation_count+1)]
    scene_ids = [f"SC{i}" for i in range(1,max(len(condition["section_plan"]),2*relation_count)+1)]
    props = schema["properties"]
    props["entities"]["items"]["properties"]["entity_id"]["enum"] = entity_ids
    props["entities"]["items"]["properties"]["entity_type"]["enum"] = types
    props["relations"].update(minItems=relation_count,maxItems=relation_count)
    relations = props["relations"]["items"]["properties"]
    for field in ("source","target"):
        relations[field]["enum"] = entity_ids
    relations["relation_id"]["enum"] = relation_ids
    relations["relation"]["enum"] = sorted({t[1] for t in triples})
    relations["scene_id"]["enum"] = scene_ids
    branches = []
    for slot in relation_slots(condition):
        branch = json.loads(json.dumps(props["relations"]["items"]))
        for field in ("relation_id","target_privacy"):
            branch["properties"][field]["enum"] = [slot[field]]
        if slot.get("required_relation"):
            branch["properties"]["relation"]["enum"] = [slot["required_relation"]]
        for field in ("source","target"):
            branch["properties"][field].pop("enum", None)
            branch["properties"][field]["pattern"] = "^(?:" + "|".join(entity_ids) + ")$"
        branches.append(branch)
    props["relations"]["items"] = {"anyOf":branches}
    props["scenes"]["minItems"] = len(condition["section_plan"])
    scenes = props["scenes"]["items"]["properties"]
    scenes["scene_id"]["enum"] = scene_ids
    scenes["section_id"]["enum"] = [s["section_id"] for s in condition["section_plan"]]
    scenes["relation_ids"]["items"]["enum"] = relation_ids
    props["slot_constraints"]["items"]["properties"]["entity_ids"]["items"]["enum"] = entity_ids
    n = condition.get("n_parties",1)
    people = condition.get("person_slots",[])
    nmax=n+condition.get("max_example_persons",0)+condition.get('max_public_reference_persons',0)
    props["persons"].update(minItems=n,maxItems=nmax)
    for field,values in (("person_id",[f"P{i}" for i in range(1,n+1)]),("name_entity_id",entity_ids)):
        props["persons"]["items"]["properties"][field]["enum"] = values
    if people:
        props["persons"]["items"] = {"anyOf":[{**copy.deepcopy(props["persons"]["items"]),"properties":{
            "person_id":string([p["person_id"]]),"name_entity_id":string([p["name_entity_id"]]),"role":string([p["role"]]),"context_kind":string(["actual_party"])}} for p in people]}
        if condition.get('reference_profile'):
            from ..reference_people import extra_people
            for p in extra_people(seed_plan(condition,triples),condition):
                props['persons']['items']['anyOf'].append(obj(**{k:string([v]) for k,v in p.items()}))
    links = props["person_entity_links"]["items"]["properties"]
    links["person_id"]["enum"] = [f"P{i}" for i in range(1,nmax+1)]
    links["entity_id"]["enum"] = entity_ids
    links["relation_ids"]["items"]["enum"] = relation_ids
    return schema, triples


def planning_input(condition: dict, feedback=None, existing_plan=None) -> tuple[dict, dict]:
    _, triples = planning_contract(condition)
    requirements = {"total_relations":condition["relation_count"],"pii_relations":condition["pii_relation_target"],
                    "non_pii_relations":condition["non_pii_relation_target"],
                    "non_pii_only_nodes_min":condition["non_pii_only_min"]}
    seed = seed_plan(condition,triples)
    seed = {k:seed[k] for k in PLAN["properties"]}
    check_plan(seed,condition)
    if condition.get("document_policy") in {"purpose_v1", "purpose_v2", "prose_v1", "prose_v2"} or condition.get('generation_flow')=='separated_v1':
        # The old seed contained generic writing instructions which the model
        # copied as facts. Keep the graph, and let the existing plan call fill
        # actual content instead of echoing those instructions.
        for relation in seed["relations"]:
            relation["context_reason"] = ""
        for scene in seed["scenes"]:
            scene["outline"] = ""
    factual = condition.get("document_policy") == "purpose_v2" or condition.get('generation_flow')=='separated_v1'
    if factual or condition.get('document_policy') in {'prose_v1','prose_v2'}:
        for relation in seed["relations"]:
            relation["scene_id"] = ""
        for scene in seed["scenes"]:
            scene["relation_ids"] = []
    scenes = [s["scene_id"] for s in seed["scenes"]]
    schema = obj(relation_contexts=obj(**{r["relation_id"]:obj(context_reason=string(),scene_id=string(scenes)) for r in seed["relations"]}),
        scene_notes=obj(**{s["scene_id"]:obj(purpose=string(),outline=string()) for s in seed["scenes"]}))
    if factual:
        schema["properties"]["scene_notes"] = obj(**{s["scene_id"]:obj(purpose=string(),facts={**array(string()),"minItems":2,"maxItems":5}) for s in seed["scenes"]})
    used = {r["relation"] for r in seed["relations"]}
    payload = {"privacy_policy":privacy_input(),"requirements":requirements,"relation_slots":relation_slots(condition),"seed_plan":seed,
               "condition": condition_input(condition, planning=True), "ontology": [r for r in ONTOLOGY[condition["domain"]] if r["relation"] in used], "feedback": feedback or []}
    if existing_plan is not None:
        payload["existing_plan"] = {k:existing_plan[k] for k in PLAN["properties"]}
    return payload, schema


def make_plan(client, condition: dict, feedback=None, existing_plan=None) -> dict:
    if existing_plan is not None and feedback and all(i["code"] in VALUE_REPAIR_CODES for i in feedback):
        payload,schema = constraint_repair_input(condition,feedback,existing_plan)
        plan = {k:copy.deepcopy(existing_plan[k]) for k in PLAN["properties"]}
        try:
            patch = client.request(condition["candidate_id"],2,"plan",CONSTRAINT_REPAIR_SYSTEM,payload,schema)
            validate(patch,schema)
            for entity in plan["entities"]:
                entity["slot_group"] = patch["slot_groups"][entity["entity_id"]]
            plan["slot_constraints"] = patch["slot_constraints"]
            check_plan(plan,condition)
        except StageFailure as exc:
            exc.plan_attempt = plan
            raise
        if 'document_story' in existing_plan:
            plan['document_story']=copy.deepcopy(existing_plan['document_story'])
        return attach_plan_metadata(plan)
    payload, schema = planning_input(condition, feedback, existing_plan)
    policy = condition.get("document_policy")
    system = SYSTEM + (PLAN_GUIDANCE if policy in {"purpose_v1","purpose_v2"} else "")
    if policy == "purpose_v2" or condition.get('generation_flow')=='separated_v1':
        system = system.replace("scene_notes: 모든 SC ID를 키로 {purpose, outline}.", "scene_notes: 모든 SC ID를 키로 {purpose, facts}. facts는 구체적 사실 문자열 배열이다.")
        system += FACT_PLAN_GUIDANCE
        system+='\ncontext_reason은 작성 지시가 아닌 합성 사건의 확정된 사실이다. 예: E1은 채무자이고 E2는 E1의 대출 채무를 보증한다. 각 장면의 facts에는 구체적 경위·수치·판단 근거를 2~5개 기록하며 서로 다른 정보를 담는다.\n'
    request_payload=payload
    if policy in {'prose_v1','prose_v2'}:
        from ..prose_writer import PLAN_SYSTEM, plan_request
        system=PLAN_SYSTEM
        request_payload,schema=plan_request(payload,schema)
        if condition.get('generation_flow')=='separated_v1':
            system=system.replace('scene_notes.outline','scene_notes.facts').replace('{purpose,outline}','{purpose,facts}')
            system+=FACT_PLAN_GUIDANCE
            system+='\n각 장면 facts는 확정된 사건 사실 2~5개다. context_reason에 작성 지시 대신 당사자 역할·귀속·행위를 확정한다.\n'
    response = client.request(condition["candidate_id"], 2, "plan", system, request_payload, schema)
    validate(response,schema)
    plan = copy.deepcopy(payload["seed_plan"])
    for r in plan["relations"]:
        r.update(response["relation_contexts"][r["relation_id"]])
    for scene in plan["scenes"]:
        note = response["scene_notes"][scene["scene_id"]]
        scene.update({"purpose":note["purpose"],"outline":"\n".join(note["facts"])} if 'facts' in note else note)
        scene["relation_ids"] = [r["relation_id"] for r in plan["relations"] if r["scene_id"] == scene["scene_id"]]
    try:
        check_plan(plan, condition)
    except StageFailure as exc:
        exc.plan_attempt = plan
        raise
    if 'story' in response:
        plan['document_story']=response['story']
    return attach_plan_metadata(plan)
