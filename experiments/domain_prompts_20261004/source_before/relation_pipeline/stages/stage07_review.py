"""Input: independently reviewable text. Output: observed relations, grades, gates."""
from __future__ import annotations

import collections
import json
import re

from ..common import Issue
from ..distribution import measure
from ..evidence import observed_expression
from ..formats import ONTOLOGY
from ..schemas import REVIEW, validate
from ..privacy import privacy_input
from ..persons import ROLE_LABELS
from ..document_purpose import brief_for, REVIEW_GUIDANCE

SYSTEM = """[목적]
실제 본문으로 관계·privacy·문서 품질을 독립 검수한다. 문서는 수정하지 않는다.

[입력]
sentences/entities/references: 본문·실제 mention·지시어 span.
relations: 정답 privacy 없는 후보. domain/subtype/format: 형식 조건. ontology: 관계 정의.

[핵심 규칙]
1. privacy_policy가 공통 기준이다. 실제 당사자 귀속은 PII, 기관 공용·명시적 가상 사례/작품 설정·출처가 확인된 공개 약력 소개는 정의된 범위에서 NON_PII다. 이름이 유명하거나 위키에 있다는 이유만으로 NON_PII로 만들지 않는다. 본문의 역할·소개 맥락을 확인한다. 전체 맥락에서도 귀속이 여러 해석으로 남을 때만 AMBIGUOUS로 설명한다. 다문장 연결의 필요와 언어 품질은 모호성과 구분한다.
2. 모든 R와 실제 사용 C를 한 번씩 평가한다. 지시어의 관찰 대상은 E ID 또는 null이며, 등록된 값·역할 지시어를 미등록 entity로 다시 보고하지 않는다.
3. R별 최소 근거 대안과 정확한 부분 인용을 반환한다. 선행 대상 문장이 필요하면 포함한다. single_sentence_sufficient은 최소 근거 대안과 일치시킨다. 코드는 실제 표현 방식을 evidence_groups와 최종 문장 순서로 판정한다. S ID는 입력 그대로 쓴다. 근거 거리·방식별 목표는 없다.
4. 온톨로지에서 지원되는 추가 관계·실제 미등록 이름/조직/연락처·사실 모순을 보고한다. 일반 명사·배경 사실·단순 재언급은 오류가 아니다. 사건 장소·이행지·출장지가 거주지와 다른 것도 정상이며 값의 진위를 외부와 비교하지 않는다.

5. 품질은 다음 기준으로 별도 평가한다.
consistency: 역할·귀속·사실의 일관성. fluency: 한국어·조사의 자연스러움; 명백한 문법 오류는 하.
suitability: 문서 종류·형식·변형·관점의 적합성.
overall: consistency/suitability 상, fluency 상 또는 중이면 상; 앞의 두 항목에 중이면 최대 중; 하나라도 하이면 하.
6. 공통 privacy_policy가 판정 기준이다. person_expectation의 인물 수/역할 조건에 대해 본문에서 실제 관찰한 인물을 NAME E ID별로 보고한다. 역할은 role_vocabulary의 코드로 반환하고 입증되지 않으면 other를 쓴다. 생성자의 인물 연결 정답은 주어지지 않는다. 일반 익명 담당자는 이름 있는 주요 인물 수에 넣지 않는다.
7. 실제로 수정해야 할 언어·일관성·형식 오류는 text_issues에 해당 S ID, 관련 R ID, 이유, 구체적 수정 지시를 기록한다. 관련 R이 없으면 relation_ids=[]다. 여러 계좌·카드의 충돌은 관련된 모든 S/R을 적고 소유자·자산·거래 출처·도착지를 구분하도록 지시한다. 계획에 명시되지 않은 경우 최종 환불 대상을 임의로 고르라고 하지 않는다. 단순 취향이나 추측은 오류로 만들지 않는다. 정상 문서는 text_issues=[]다.

[출력]
Schema에 맞는 JSON만 반환한다. 필수 필드: relation_checks, reference_checks, missing_relations,
unregistered_entities, contradictions, format_adherence, quality, person_checks, text_issues. 추가 사항이 없으면 해당 배열은 []이다.
"""


def review_input(filled: dict, plan: dict, condition: dict) -> dict:
    payload = {
        "privacy_policy":privacy_input(),
        "person_expectation":{"actual_person_count":condition.get("n_parties",sum(e["entity_type"] == "NAME" for e in filled["entities"])),
            "count_scope":condition.get("person_count_scope","이름으로 등록된 주요 실제 인물"),
            "role_vocabulary":{**ROLE_LABELS,"other":"역할 입증 불가/다른 역할"},
            "expected_roles":[s["role"] for s in condition.get("person_slots",[])]},
        "domain": condition["domain"], "subtype": condition["subtype"], "subtype_label": condition["subtype_label"],
        "format": {"document_format":condition["document_format"],"layout_variant":condition["layout_variant"],"layout_variant_label":condition["layout_variant_label"],"narrative_viewpoint":condition["narrative_viewpoint"],"section_plan":[{k:s[k] for k in ("section_id","title","allowed_kinds")} for s in condition["section_plan"]]},
        "sentences": filled["sentences"], "entities": filled["entities"],
        "relations": [{k:r[k] for k in ("relation_id","source","target","relation")} for r in plan["relations"]],
        "references": filled["references"], "ontology": ONTOLOGY[condition["domain"]],
        "suspected_literal_entities": [],
    }
    if condition.get("purpose_review") or condition.get("document_policy") in {"purpose_v1","purpose_v2","prose_v1","prose_v2"}:
        payload["topic"] = condition["topic"]
        payload["document_expectation"] = brief_for(condition["domain"],condition["subtype"])
    from ..reference_people import PROFILES
    payload['public_biography_facts']=[{'name':p['name'],'attribute_type':p['target_type'],
        'attribute':p['target_value'],'fact':p['fact'],'source':p['source']}
        for p in PROFILES.values() if p['context_kind']=='public_reference']
    if condition.get('document_spec'):
        import copy
        payload['document_spec']=copy.deepcopy(condition['document_spec'])
        payload['document_spec'].pop('role_bindings',None)  # No planned person-to-role answers.
        payload['topic']=condition['topic']
    return payload


def validate_evidence(item: dict, sentences: dict) -> list[Issue]:
    issues = []
    quotes = collections.defaultdict(list)
    for q in item["evidence_quotes"]:
        sid, quote = q["sentence_id"], q["quote"]
        if sid not in sentences or not quote or quote not in sentences[sid]["sentence"]:
            issues.append(Issue("REVIEW_QUOTE", "Quote is not an exact nonempty substring", "RETRY_RESPONSE", sentence_id=sid))
        else:
            quotes[sid].append(quote)
    for group in item["evidence_groups"]:
        if not group or len(group) != len(set(group)):
            issues.append(Issue("REVIEW_EVIDENCE_GROUP", "Empty/duplicate evidence group", "RETRY_RESPONSE"))
        for sid in group:
            if sid not in sentences or not quotes[sid]:
                issues.append(Issue("REVIEW_EVIDENCE_QUOTE_MISSING", "Every evidence sentence needs an exact quote", "RETRY_RESPONSE", sentence_id=sid))
    return issues


def check_review(review: dict, filled: dict, plan: dict, condition: dict, draft: dict) -> dict:
    from ..document_specs import review_schema,check_review_spec
    validate(review, review_schema(REVIEW,condition))
    response_issues, semantic_issues = [], []
    if condition.get('document_spec'):
        response_issues,semantic_issues=check_review_spec(review,condition,filled)
    sentences = {s["sentence_id"]:s for s in filled["sentences"]}
    relations = {r["relation_id"]:r for r in plan["relations"]}
    used_refs = {ref["ref_id"] for ref in filled["references"]}
    intended_refs = {r["ref_id"]:r["entity_id"] for r in draft["refs"]}
    observed_refs = {r["ref_id"]:r for r in review["reference_checks"]}
    entity_ids = {e["entity_id"] for e in filled["entities"]}
    if collections.Counter(c["relation_id"] for c in review["relation_checks"]) != collections.Counter(relations.keys()):
        response_issues.append(Issue("REVIEW_RELATION_COVERAGE", "Each candidate R ID must be checked once", "RETRY_RESPONSE"))
    if collections.Counter(c["ref_id"] for c in review["reference_checks"]) != collections.Counter(used_refs):
        response_issues.append(Issue("REVIEW_REFERENCE_COVERAGE", "Each used C ID must be checked once", "RETRY_RESPONSE"))
    for item in review["relation_checks"]+review["reference_checks"]+review["missing_relations"]:
        response_issues.extend(validate_evidence(item,sentences))
    for item in review["missing_relations"]:
        if not item["evidence_groups"]:
            response_issues.append(Issue("REVIEW_EXTRA_EVIDENCE","A supported extra relation needs actual evidence","RETRY_RESPONSE"))
    named = {e["entity_id"]:e for e in filled["entities"] if e["entity_type"] == "NAME"}
    persons = review["person_checks"]["observed_persons"]
    if collections.Counter(p["name_entity_id"] for p in persons) != collections.Counter(named.keys()):
        response_issues.append(Issue("REVIEW_PERSON_COVERAGE","Each actual NAME mention needs one observed person","RETRY_RESPONSE"))
    observed_count = sum(p["context_kind"] == "actual_party" for p in persons)
    if not any(e["entity_type"] == "NAME" for e in review["unregistered_entities"]) and review["person_checks"]["actual_person_count"] != observed_count:
        response_issues.append(Issue("REVIEW_PERSON_COUNT","Observed person count disagrees with person records","RETRY_RESPONSE"))
    if review["person_checks"]["actual_person_count"] != condition.get("n_parties",observed_count):
        semantic_issues.append(Issue("PERSON_COUNT_MEANING",review["person_checks"]["reason"],"REWRITE_SCENE"))
    planned_people = {p["name_entity_id"]:p for p in plan.get("persons",[])}
    for p in persons:
        response_issues.extend(validate_evidence(p,sentences))
        eid = p["name_entity_id"]
        appearance = {m["sentence_id"] for m in named.get(eid,{}).get("mentions",[])}
        if not p["evidence_groups"] or any(not(set(g)&appearance) for g in p["evidence_groups"]):
            response_issues.append(Issue("REVIEW_PERSON_EVIDENCE","Person evidence needs an actual name mention","RETRY_RESPONSE",entity_id=eid))
        expected = planned_people.get(eid)
        if expected and (p["role"] != expected["role"] or p["context_kind"] != expected["context_kind"]):
            semantic_issues.append(Issue("PERSON_ROLE_MEANING",f"Observed role/kind {p['role']}/{p['context_kind']} differs from planned {expected['role']}/{expected['context_kind']}","REWRITE_SCENE",entity_id=eid))
    for c in review["reference_checks"]:
        if c["observed_entity_id"] is not None and c["observed_entity_id"] not in entity_ids:
            response_issues.append(Issue("REVIEW_REFERENCE_ENTITY", "Unregistered observed E ID", "RETRY_RESPONSE"))
        if not c["unambiguous"] or c["observed_entity_id"] != intended_refs.get(c["ref_id"]):
            semantic_issues.append(Issue("REFERENCE_MEANING", c["reason"], "REWRITE_SCENE"))
        if c["unambiguous"] and not c["evidence_groups"]:
            response_issues.append(Issue("REVIEW_REFERENCE_EVIDENCE", "An unambiguous reference needs minimum evidence", "RETRY_RESPONSE"))
        if c["unambiguous"] and c["observed_entity_id"] in entity_ids:
            ref_sids = {ref["sentence_id"] for ref in filled["references"] if ref["ref_id"] == c["ref_id"]}
            entity_sids = {m["sentence_id"] for e in filled["entities"] if e["entity_id"] == c["observed_entity_id"] for m in e["mentions"]}
            for group in c["evidence_groups"]:
                if not (set(group) & ref_sids and set(group) & entity_sids):
                    response_issues.append(Issue("REVIEW_REFERENCE_CONNECTION", "Reference evidence must include the reference and an actual target mention", "RETRY_RESPONSE"))
    entity_appearances = collections.defaultdict(set)
    for e in filled["entities"]:
        for m in e["mentions"]:
            entity_appearances[m["sentence_id"]].add(e["entity_id"])
    for ref in filled["references"]:
        observed = observed_refs.get(ref["ref_id"],{}).get("observed_entity_id")
        if observed:
            entity_appearances[ref["sentence_id"]].add(observed)
    expressions = []
    for c in review["relation_checks"]:
        r = relations.get(c["relation_id"])
        if r is None:
            continue
        if c["observed_privacy"] == "AMBIGUOUS":
            semantic_issues.append(Issue("PRIVACY_AMBIGUOUS", c["reason"], "REWRITE_SCENE", relation_id=r["relation_id"]))
        if not c["extractable"] or not c["direction_supported"] or not c["coreference_unambiguous"] or c["observed_privacy"] not in (r["target_privacy"], "AMBIGUOUS"):
            semantic_issues.append(Issue("RELATION_MEANING", c["reason"], "REWRITE_SCENE", relation_id=r["relation_id"]))
        groups = c["evidence_groups"]
        if c["extractable"] and not groups:
            response_issues.append(Issue("REVIEW_MISSING_EVIDENCE", "Extractable relation needs evidence", "RETRY_RESPONSE", relation_id=r["relation_id"]))
        usable = [g for g in groups if g and all(sid in sentences for sid in g)]
        endpoints_valid = True
        for group in usable:
            covered = set().union(*(entity_appearances[sid] for sid in group))
            if not {r["source"],r["target"]} <= covered:
                endpoints_valid = False
                if condition.get('review_evidence_policy')=='sentence_ids':
                    response_issues.append(Issue("REVIEW_ENDPOINT_EVIDENCE", "Selected evidence group needs both endpoints and antecedents; correct the review response", "RETRY_RESPONSE", relation_id=r["relation_id"]))
                else:
                    semantic_issues.append(Issue("REVIEW_ENDPOINT_EVIDENCE", "Minimum evidence lacks endpoint/reference connection", "REWRITE_SCENE", relation_id=r["relation_id"]))
        singles = any(len(g)==1 for g in usable)
        # This boolean duplicates evidence_groups and is occasionally inconsistent
        # in model output. Keep the disagreement in the audit, but use the concrete
        # cited groups to derive observed expression mode instead of spending a
        # second reviewer call to restate a code-derivable fact.
        claim_consistent = not c["extractable"] or c["single_sentence_sufficient"] == singles
        observed = observed_expression(groups, {sid:s["sent_idx"] for sid,s in sentences.items()})
        evidence_valid = bool(usable) and endpoints_valid and not validate_evidence(c,sentences)
        expressions.append({"relation_id":r["relation_id"], **observed, "evidence_valid":evidence_valid,
            "reviewer_single_sentence_claim":c["single_sentence_sufficient"],
            "single_sentence_claim_consistent":claim_consistent,"observed_groups":groups})
    if review["missing_relations"]:
        for extra in review["missing_relations"]:
            message = f"계획 밖 관계 {extra['source']}->{extra['target']} {extra['relation']} ({extra['observed_privacy']}). 이 근거를 만들지 않도록 해당 문맥을 수정한다."
            for sid in list(dict.fromkeys(sid for group in extra["evidence_groups"] for sid in group)) or [""]:
                semantic_issues.append(Issue("UNPLANNED_RELATIONS",message,"REWRITE_SCENE",sentence_id=sid))
    if review["unregistered_entities"]:
        for extra in review["unregistered_entities"]:
            semantic_issues.append(Issue("UNREGISTERED_ENTITIES",f"미등록 {extra['entity_type']} {extra['form']}: {extra['reason']}","REWRITE_SCENE",sentence_id=extra["sentence_id"]))
    if review["contradictions"]:
        for c in review["contradictions"]:
            for sid in c["sentence_ids"] or [""]:
                if sid and sid not in sentences:
                    response_issues.append(Issue("REVIEW_TEXT_TARGET","Unknown contradiction sentence","RETRY_RESPONSE",sentence_id=sid))
                else:
                    semantic_issues.append(Issue("CONTRADICTIONS",c["reason"],"REWRITE_SCENE",sentence_id=sid))
    for finding in review["text_issues"]:
        if not finding["sentence_ids"] or any(sid not in sentences for sid in finding["sentence_ids"]) or any(rid not in relations for rid in finding["relation_ids"]):
            response_issues.append(Issue("REVIEW_TEXT_TARGET","Text correction needs known S IDs and known R IDs","RETRY_RESPONSE"))
            continue
        code = {"fluency":"TEXT_FLUENCY","consistency":"TEXT_CONSISTENCY","format":"TEXT_FORMAT"}[finding["kind"]]
        for sid in finding["sentence_ids"]:
            matches = [rid for rid in finding["relation_ids"] if any(sid in g for item in review["relation_checks"] if item["relation_id"] == rid for g in item["evidence_groups"])]
            rid = matches[0] if len(matches) == 1 else ""
            semantic_issues.append(Issue(code,finding["reason"]+" 수정: "+finding["fix_instruction"],"REWRITE_SCENE",sentence_id=sid,relation_id=rid))
    fmt = review["format_adherence"]
    format_ok = all(fmt[k] for k in ("document_format_supported","layout_variant_supported","viewpoint_supported","section_roles_supported"))
    if not format_ok:
        semantic_issues.append(Issue("FORMAT_MEANING", fmt["reason"], "REWRITE_SCENE"))
    q = review["quality"]
    quality_ok = q["overall"] == "상" and q["scores"]["consistency"] == "상" and q["scores"]["suitability"] == "상" and q["scores"]["fluency"] in ("상","중")
    if not quality_ok:
        # A low grade without a repairable target otherwise turns into an
        # unfocused rewrite of every scene. Require the reviewer to point to
        # the failed dimension before spending a generation call on repair.
        finding_kinds = {item["kind"] for item in review["text_issues"]}
        actionable_codes = {item.code for item in semantic_issues}
        actionable = {
            "consistency": ("consistency" in finding_kinds or bool(review["contradictions"]) or bool(actionable_codes & {
                "PRIVACY_AMBIGUOUS", "RELATION_MEANING", "REVIEW_ENDPOINT_EVIDENCE", "REFERENCE_MEANING",
                "PERSON_COUNT_MEANING", "PERSON_ROLE_MEANING", "UNPLANNED_RELATIONS", "UNREGISTERED_ENTITIES",
                "CONTRADICTIONS", "REFERENCE_MEANING"})),
            "fluency": "fluency" in finding_kinds,
            "suitability": "format" in finding_kinds or not format_ok or bool(actionable_codes & {"FORMAT_MEANING", "TEXT_FORMAT", "DOCUMENT_SPEC_INCOMPLETE"}),
        }
        missing_targets = []
        if q["scores"]["consistency"] != "상" and not actionable["consistency"]:
            missing_targets.append("consistency")
        if q["scores"]["fluency"] == "하" and not actionable["fluency"]:
            missing_targets.append("fluency")
        if q["scores"]["suitability"] != "상" and not actionable["suitability"]:
            missing_targets.append("suitability")
        if q["overall"] != "상" and not any(actionable.values()):
            missing_targets.append("overall")
        if missing_targets:
            response_issues.append(Issue("REVIEW_QUALITY_TARGET",
                "Low quality grade needs concrete sentence/relation IDs and a correction instruction for: " + ", ".join(missing_targets),
                "RETRY_RESPONSE"))
        semantic_issues.append(Issue("QUALITY_GRADE", q["reason"], "REPAIR"))
    distribution, distribution_issues = measure(filled,plan,condition)
    # Accepted observed labels equal the frozen plan; derive from observed labels when complete.
    observed = {c["relation_id"]:c["observed_privacy"] for c in review["relation_checks"]}
    if set(observed) == set(relations) and all(v in ("PII","NON_PII") for v in observed.values()):
        observed_plan = {**plan,"relations":[{**r,"target_privacy":observed[r["relation_id"]]} for r in plan["relations"]]}
        distribution, distribution_issues = measure(filled,observed_plan,condition)
    semantic_issues.extend(distribution_issues)
    return {"response_valid":not response_issues,"semantic_passed":not semantic_issues,"format_passed":format_ok,"quality_passed":quality_ok,"expression_checks":expressions,"person_checks":review["person_checks"],"distribution":distribution,"issues":[i.json() for i in response_issues+semantic_issues],"passed":not response_issues and not semantic_issues}


def judge(client, filled: dict, plan: dict, condition: dict, feedback=None, draft=None) -> dict:
    payload = review_input(filled,plan,condition)
    if feedback:
        payload["response_contract_feedback"] = feedback
    from ..document_specs import review_schema,REVIEW_GUIDANCE as SPEC_REVIEW_GUIDANCE
    schema = review_schema(REVIEW,condition,list(filled['sentence_id_to_index']))
    props = schema["properties"]
    sentence_ids = list(filled["sentence_id_to_index"])
    sentence_pattern = "^(?:" + "|".join(re.escape(sid) for sid in sentence_ids) + ")$"
    relation_ids = [r["relation_id"] for r in plan["relations"]]
    reference_ids = sorted({r["ref_id"] for r in filled["references"]})
    entity_ids = [e["entity_id"] for e in filled["entities"]]
    props["relation_checks"].update(minItems=len(relation_ids),maxItems=len(relation_ids))
    props["relation_checks"]["items"]["properties"]["relation_id"]["enum"] = relation_ids
    props["reference_checks"].update(minItems=len(reference_ids),maxItems=len(reference_ids))
    if reference_ids:
        props["reference_checks"]["items"]["properties"]["ref_id"]["enum"] = reference_ids
    props["reference_checks"]["items"]["properties"]["observed_entity_id"]["enum"] = [*entity_ids,None]
    for collection in ("relation_checks","reference_checks","missing_relations"):
        item = props[collection]["items"]["properties"]
        item["evidence_groups"]["items"]["items"]["pattern"] = sentence_pattern
        item["evidence_quotes"]["items"]["properties"]["sentence_id"]["pattern"] = sentence_pattern
    for field in ("source","target"):
        props["missing_relations"]["items"]["properties"][field]["enum"] = entity_ids
    props["unregistered_entities"]["items"]["properties"]["sentence_id"]["pattern"] = sentence_pattern
    props["contradictions"]["items"]["properties"]["sentence_ids"]["items"]["pattern"] = sentence_pattern
    findings = props["text_issues"]["items"]["properties"]
    findings["sentence_ids"].update(minItems=1)
    findings["sentence_ids"]["items"]["pattern"] = sentence_pattern
    findings["relation_ids"]["items"]["enum"] = relation_ids
    persons = props["person_checks"]["properties"]["observed_persons"]
    names = [e["entity_id"] for e in filled["entities"] if e["entity_type"] == "NAME"]
    persons.update(minItems=len(names),maxItems=len(names))
    pp = persons["items"]["properties"]
    if names:
        pp["name_entity_id"]["enum"] = names
    pp["role"]["enum"] = [*ROLE_LABELS,"other"]
    pp["evidence_groups"]["items"]["items"]["pattern"] = sentence_pattern
    pp["evidence_quotes"]["items"]["properties"]["sentence_id"]["pattern"] = sentence_pattern
    system = SYSTEM + (REVIEW_GUIDANCE if condition.get("purpose_review") or condition.get("document_policy") in {"purpose_v1","purpose_v2","prose_v1","prose_v2"} else "")
    if condition.get('document_spec'):
        system+='\n'+SPEC_REVIEW_GUIDANCE
    if condition.get('review_evidence_policy')=='sentence_ids':
        from ..review_evidence import id_only_schema,materialize_quotes,GUIDANCE
        schema=id_only_schema(schema)
        system=system.replace('R별 최소 근거 대안과 정확한 부분 인용을 반환한다.','R별 최소 근거 문장 ID 묶음을 반환한다.')+GUIDANCE
    from ..call_policy import validated_request
    def validate_response(raw):
        review=materialize_quotes(raw,filled) if condition.get('review_evidence_policy')=='sentence_ids' else raw
        if condition.get('generation_flow')=='separated_v1':
            checks=check_review(review,filled,plan,condition,draft)
            if not checks['response_valid']:
                from ..common import StageFailure, Issue
                exc=StageFailure([Issue(**i) for i in checks['issues'] if i['action']=='RETRY_RESPONSE'])
                exc.review_response=review
                raise exc
        return review
    return validated_request(client,condition['candidate_id'],7,'review',system,payload,schema,validate_response)
