"""Value-free graph seed with coverage targets and named participants."""
from __future__ import annotations
import collections
import random
from .common import StageFailure, digest, fail
from .coverage import candidate_triples
from .formats import allowed_triples
from .persons import seed_person_links, ROLE_LABELS
from .semantic_profiles import profile_for


def relation_slots(condition):
    rng = random.Random(int(digest([condition["candidate_id"],"relation_slots"])[:16],16))
    privacy = ["PII"]*condition["pii_relation_target"]+["NON_PII"]*condition["non_pii_relation_target"]
    rng.shuffle(privacy)
    slots = [{"relation_id":f"R{i+1}","target_privacy":p} for i,p in enumerate(privacy)]
    available = list(slots)
    for requirement in condition.get("coverage_requirements",[]):
        slot = next((s for s in available if s["target_privacy"] == requirement["privacy"]),None)
        if slot is None:
            fail("COVERAGE_SLOT_CAPACITY","Required relations exceed privacy slot capacity","REPLAN")
        slot["required_relation"] = requirement["relation"]
        available.remove(slot)
    return slots


CONTEXTS = {
    "CONTACT_ASSOCIATION":("개인의 실제 연락 수단으로 기재하고 사용한다","기관/부서가 공동 운영하는 공식 문의 창구로 사용한다"),
    "LOCATION_ASSOCIATION":("개인의 거주지 또는 개인 관련 장소를 연결한다","기관의 사무실/행사 장소로 안내한다"),
    "IDENTITY_ASSOCIATION":("해당 개인의 신원/인구통계 속성을 확인한다","자산의 인증수단을 확인한다"),
    "ORGANIZATIONAL_RELATION":("해당 개인의 소속/직위를 명시한다","기관의 공식 부서/직위 구성을 명시한다"),
    "EDUCATION_STATUS":("개인의 재학/전공/교육 이수 상태를 명시한다","교육기관이 운영하는 공식 전공/과정을 명시한다"),
    "FINANCIAL_ASSET_ASSOCIATION":("개인의 소유/사용 계좌 또는 카드를 지정한다","기관이 공동 관리하는 정산 계좌를 지정한다"),
    "FINANCIAL_TRANSACTION":("당사자 사이의 송금/지급/상환을 명시한다","기관의 공식 지급/정산 절차를 명시한다"),
    "PERSONAL_RELATIONSHIP":("가족/보호자 등 개인 사이의 관계를 실제로 명시한다","기관 맥락"),
    "EVENT_PARTICIPATION":("개인의 행사/프로젝트 참여 사실을 명시한다","기관/부서의 공식 행사/프로젝트 참여를 명시한다"),
    "INSURANCE_RELATION":("계약자/피보험자/수익자 등 보험 당사자의 역할을 명시한다","기관 맥락"),
    "CREDIT_AND_GUARANTEE_RELATION":("개인의 차주/보증인/신용 관계를 명시한다","기관 맥락"),
    "INFORMATION_GOVERNANCE":("개인 정보의 제출/처리/확인 주체와 대상을 명시한다","공식 자료의 제출/검토/접근 주체와 대상을 명시한다"),
    "QUALIFICATION_AND_ASSESSMENT":("개인의 역량/자격/평가 근거를 명시한다","기관 맥락")}
CONTEXTS.update({
    "BUSINESS_SERVICE_RELATION":("개인이 신청·수령하는 구체적인 유료 업무나 서비스와 상대를 명시한다","기관이 제공·수령하는 공식 서비스와 계약 상대를 명시한다"),
    "COLLABORATION_PARTNERSHIP":("개인 사이의 공동 업무/사업 목적과 협력 상대를 명시한다","기관/부서가 공동 수행하는 업무의 목적과 제휴 상대를 명시한다"),
    "CASE_AND_INCIDENT_RELATION":("계좌 피해·사고·분쟁에서 개인의 피해자/신청 당사자 역할과 관련 대상을 명시한다","기관/부서의 사고·분쟁 처리 역할과 관련 기관 또는 계좌를 명시한다"),
    "PROCEDURAL_RELATION":("해당 개인의 신청·승인 조건과 처리 의무를 명시한다","기관의 신청·승인 처리 주체와 필수 요건/대상을 명시한다"),
    "GUIDANCE_SUPPORT":("누가 개인에게 어떤 안내·지도·추천을 제공하는지 명시한다","어떤 기관/부서가 어떤 업무 안내·지원을 제공하는지 명시한다"),
    "ASSET_RELATION":("개인이 소유·사용·임대하는 자산과 권리를 명시한다","기관의 공동 관리 자산에 대한 사용·소유·이전 권리를 명시한다")})


ORG_TYPES = {"WORKPLACE","DEPARTMENT","SCHOOL"}
# DEPARTMENT is excluded: public departments receive the document institution's own value.
BRIDGE_TARGET_TYPES = {"TELEPHONE","EMAIL","ADDRESS","BANK_ACCOUNT_NUMBER"}


BRIDGE_FACTS = {
    "TELEPHONE":"당사자가 소속된 기관이 이 번호를 기관 대표 문의 창구로 공동 운영한다. 당사자 개인의 연락처가 아니다.",
    "EMAIL":"당사자가 소속된 기관이 이 주소를 기관 공용 접수 창구로 공동 운영한다. 당사자 개인의 메일이 아니다.",
    "ADDRESS":"당사자가 소속된 기관의 사업장·사무실이 이 주소에 있다. 당사자의 거주지가 아니다.",
    "BANK_ACCOUNT_NUMBER":"당사자가 소속된 기관이 이 계좌를 기관 명의의 정산 계좌로 쓴다. 당사자 개인의 계좌가 아니다."}


def cross_relation_fact(plan,condition,relation):
    """Fixed fact for a NON_PII relation that touches a PII entity; empty for every ordinary relation."""
    if any(r["relation_id"] == relation["relation_id"] for r in organization_bridges(plan)):
        types = {e["entity_id"]:e["entity_type"] for e in plan["entities"]}
        return BRIDGE_FACTS[types[relation["target"]]]
    from .reference_people import reference_relation_fact
    return reference_relation_fact(plan,condition,relation)


def organization_bridges(plan):
    """NON_PII relations from a participant's own organisation to public-only information."""
    labels = collections.defaultdict(set)
    for r in plan["relations"]:
        labels[r["source"]].add(r["target_privacy"])
        labels[r["target"]].add(r["target_privacy"])
    types = {e["entity_id"]:e["entity_type"] for e in plan["entities"]}
    return [r for r in plan["relations"] if r["target_privacy"] == "NON_PII" and types.get(r["source"]) in ORG_TYPES
            and "PII" in labels[r["source"]] and "PII" not in labels[r["target"]]]


def condition_triples(condition):
    """Typed edges this document may use; the same filter as the planning contract."""
    types = set(condition["allowed_personal_types"]+condition["allowed_public_types"]+["NAME"])
    return [t for t in allowed_triples(condition["domain"]) if t[0] in types and t[2] in types]


def plan_organization_bridges(condition,cfg):
    """Record the bridge count this subtype's graph can actually hold; zero leaves the graph unchanged."""
    low,high = cfg.get("organization_bridge_range",[0,0])
    if not high:
        return condition
    from .schemas import PLAN
    from .stages.stage02_plan import check_plan
    rng = random.Random(int(digest([cfg["seed"],condition["candidate_id"],"organization_bridge"])[:16],16))
    triples = condition_triples(condition)
    for want in range(rng.randint(low,high),0,-1):
        trial = {**condition,"organization_bridge_target":want}
        try:
            plan = seed_plan(trial,triples)
            check_plan({k:plan[k] for k in PLAN["properties"]},trial)
        except StageFailure:
            continue
        condition["organization_bridge_target"] = want
        break
    return condition


def seed_plan(condition,triples):
    rng = random.Random(int(digest([condition["candidate_id"],"graph_seed"])[:16],16))
    profile = profile_for(condition)
    n = condition.get("n_parties",1)
    people = condition.get("person_slots") or [{"person_id":f"P{i+1}","name_entity_id":f"E{i+1}","role":"applicant"} for i in range(n)]
    entities = [{"entity_id":s["name_entity_id"],"entity_type":"NAME","context_role":s["role"],"slot_group":s["person_id"]} for s in people]
    lookup = {(e["entity_type"],e["slot_group"]):e["entity_id"] for e in entities}
    kinds = {e["entity_id"]:e["entity_type"] for e in entities}
    def entity(typ,group,role):
        key = typ,group
        if key not in lookup:
            eid = f"E{len(entities)+1}"
            lookup[key] = eid
            entities.append({"entity_id":eid,"entity_type":typ,"context_role":role,"slot_group":group})
            kinds[eid] = typ
        return lookup[key]
    allowed = {tuple(t) for t in triples}
    options = {p:[t for t in candidate_triples(condition,p) if tuple(t) in allowed] for p in ("PII","NON_PII")}
    if profile is None:
        for choices in options.values():
            rng.shuffle(choices)
    if not all(options.values()):
        fail("SEED_GRAPH_CAPACITY","No feasible personal/public graph for this subtype","REPLAN")
    relations,covered,used,used_relation_types = {},set(),set(),set()
    slots = relation_slots(condition)
    want = condition.get("organization_bridge_target",0)
    # A bridge reuses an organisation that a personal relation already attributes to a
    # participant, so personal slots are built first when bridges are requested.
    order = sorted(range(len(slots)),key=lambda i:slots[i]["target_privacy"] != "PII") if want else list(range(len(slots)))
    personal_orgs,bridges = {},0
    for position,index in enumerate(order):
        slot = slots[index]
        privacy = slot["target_privacy"]
        choices = [t for t in options[privacy] if not slot.get("required_relation") or t[1] == slot["required_relation"]]
        if profile is not None and not slot.get("required_relation"):
            reserved = {slots[i]["required_relation"] for i in order[position+1:] if slots[i].get("required_relation")}
            choices.sort(key=lambda t:(t[1] in reserved,t[1] in used_relation_types))
        unmentioned = [s for s in people if s["name_entity_id"] not in covered]
        remaining_pii = sum(slots[i]["target_privacy"] == "PII" for i in order[position:])
        if privacy == "PII" and len(unmentioned)>1 and remaining_pii <= len(unmentioned):
            pairs = [t for t in choices if t[2] == "NAME"]
            if pairs:
                choices = pairs
        elif want and not slot.get("required_relation"):
            if privacy == "PII" and not personal_orgs:
                choices = sorted(choices,key=lambda t:t[2] not in ORG_TYPES)
            elif privacy == "NON_PII" and bridges < want:
                choices = sorted(choices,key=lambda t:not (t[0] in personal_orgs.values() and t[2] in BRIDGE_TARGET_TYPES))
        selected = None
        for st,relation,tt in choices:
            if privacy == "PII":
                p = unmentioned[0] if unmentioned else people[0] if profile else people[index%n]
                if profile and tt != "NAME":
                    owner_role = profile.get("attribute_owners",{}).get(relation)
                    p = next((person for person in people if person["role"] == owner_role),p)
                source = p["name_entity_id"]
                if tt == "NAME":
                    pair = profile["person_pairs"].get(relation) if profile else None
                    if pair:
                        by_role = {person["role"]:person for person in people}
                        if pair[0] not in by_role or pair[1] not in by_role:
                            continue
                        p = by_role[pair[0]]
                        source = p["name_entity_id"]
                        target = by_role[pair[1]]["name_entity_id"]
                    else:
                        other = next((s for s in unmentioned if s["name_entity_id"] != source),None) or next((s for s in people if s["name_entity_id"] != source),None)
                        if other is None:
                            continue
                        target = other["name_entity_id"]
                else:
                    target = entity(tt,p["person_id"],"personal_attribute" if tt not in {"WORKPLACE","DEPARTMENT","SCHOOL","MAJOR","POSITION"} else "personal_context")
                subject = ROLE_LABELS.get(p["role"],p["role"])
            else:
                org = next((eid for eid,typ in personal_orgs.items() if typ == st),None) if bridges < want and tt in BRIDGE_TARGET_TYPES else None
                if org is not None:
                    # The target gets its own value group: it is the organisation's line, not the participant's.
                    source = org
                    target = entity(tt,f"org_{org}","public_office_information")
                    subject = "당사자의 소속 기관"
                else:
                    group = "office_main" if profile else f"office_{index%2+1}"
                    source = entity(st,group,profile["public_role"] if profile else "public_office")
                    target = entity(tt,group if tt != st else f"office_target_{index+1}","public_office_information")
                    subject = profile["public_role"] if profile else "기관/부서"
            if source != target and (source,relation,target) not in used and (profile is None or (target,relation,source) not in used):
                selected = source,relation,target,subject
                break
        if selected is None:
            fail("SEED_GRAPH_CAPACITY","Cannot supply distinct edges within participant/type constraints","REPLAN")
        source,relation,target,subject = selected
        if privacy == "PII" and kinds[target] in ORG_TYPES:
            personal_orgs[target] = kinds[target]
        bridges += privacy == "NON_PII" and source in personal_orgs
        used.add((source,relation,target))
        used_relation_types.add(relation)
        covered.update(e for e in (source,target) if e in {s["name_entity_id"] for s in people})
        meaning = CONTEXTS.get(relation,("개인의 구체적 행위/역할과 상대를 연결한다","기관의 공식 업무에서 구체적 행위/역할과 상대를 연결한다"))[privacy == "NON_PII"]
        relations[index] = {"relation_id":slot["relation_id"],"target_privacy":privacy,"source":source,"target":target,
            "relation":relation,"scene_id":f"SC{index%len(condition['section_plan'])+1}","context_reason":subject+": "+meaning}
    relations = [relations[index] for index in range(len(slots))]
    if len(covered) != n:
        fail("SEED_PERSON_CAPACITY","Every participant needs an incident personal relation","REPLAN")
    # Avoid orphan nodes from unsuccessfully attempted duplicate candidate edges.
    incident = {eid for r in relations for eid in (r["source"],r["target"])}
    entities = [e for e in entities if e["entity_id"] in incident]
    plan = {"plan_version":1,"entities":entities,"relations":relations,"slot_constraints":[],
        "scenes":[{"scene_id":f"SC{i+1}","section_id":section["section_id"],"order":i,"purpose":section["title"],
            "relation_ids":[r["relation_id"] for r in relations if r["scene_id"] == f"SC{i+1}"],
            "outline":"인물의 역할·정보 귀속과 기관의 공식 업무를 구분해 주제에 맞게 서술한다"} for i,section in enumerate(condition["section_plan"])]}
    from .reference_people import add_reference_graph
    add_reference_graph(plan,condition)
    plan["persons"],plan["person_entity_links"] = seed_person_links(plan,condition)
    return plan
