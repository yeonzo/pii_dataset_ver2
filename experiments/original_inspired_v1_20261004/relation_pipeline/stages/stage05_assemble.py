"""Input: full draft/plan/frozen values. Output: diagnostics and repaired assembly."""
from __future__ import annotations

import collections
import copy
import itertools
import re

from ..common import Issue, StageFailure, fail
from ..distribution import measure
from ..renderer import PLACEHOLDER, REF_PATTERN, TOKEN, normalize, render
from ..schemas import DRAFT, PATCH, validate
from ..prompt_inputs import condition_input, diagnosis_input, plan_input
from ..repair_tasks import actual_entities, build_tasks, collapse_exact_boilerplate, decode_patch, repair_contract, split_prose_sentences
from ..privacy import privacy_input
from ..document_purpose import DRAFT_GUIDANCE, FACT_DRAFT_GUIDANCE, prose_metrics

LITERALS = [re.compile(r"[A-Za-z0-9_.+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), re.compile(r"(?<!\d)(?:010|011|016|017|018|019)[- ]?\d{3,4}[- ]?\d{4}(?!\d)"), re.compile(r"(?<!\d)\d{6}-[1-8]\d{6}(?!\d)"), re.compile(r"(?<!\d)0(?:2|[3-6]\d)[- ]\d{3,4}[- ]\d{4}(?!\d)")]
REPAIR_SYSTEM = """[목적]
초안의 진단 오류를 추가·이어쓰기·국소 교체로 한 번에 복구한다.

[입력]
draft: 현재 초안. condition/plan: 문서 조건·고정 계획.
diagnosis: 오류·분량 부족. repair_tasks: 누락 토큰·R별 endpoint/귀속·수정 가능한 S ID·완료 조건.
new_sentence_id_start: 신규 ID 시작값.

[핵심 규칙]
1. 먼저 repair_tasks.missing_entities와 operation=fix 관계를 실제 본문에서 수정한다. 해당 장면의 기존 문장을 교체하거나 필요한 문장을 추가한다. 일반 처리 경과만 늘려 오류를 대신하지 않는다.
2. 계획의 귀속·관계·지시어 연결을 보존하고 실제 값·새 엔티티·관계·privacy 해설은 추가하지 않는다. 재언급은 같은 E ID를 쓴다.
3. operation=fix 관계는 relation_repairs에 완전한 자연스러운 수정 문장을 작성한다. 지정한 source/target 토큰을 포함하고 역할·귀속·방향·context_reason을 실제로 입증한다. 코드가 지정한 문장을 교체하거나 장면에 삽입한다. 의미 오류를 근거 ID만 바꿔 해결했다고 하지 않는다.
4. 교체는 지정된 기존 S ID, 삽입은 신규 S ID를 쓴다. protected_sentence_ids와 operation=preserve 관계를 보존한다. 산문은 한 문장, 양식은 한 줄이며 placeholder·조사 규칙을 지킨다.
5. 서로 다른 E ID는 같은 TYPE이어도 별개 대상이다. 소유자, 자산, 거래 출처·도착지를 합치지 않는다. 금융 관계에서는 context_reason에 명시된 역할만 수정 문장으로 입증한다. 최종 환불 대상·거래 방향이 계획에 없으면 임의로 고르지 말고, 충돌하는 문장에서 근거 없는 거래 주장을 제거하거나 역할을 분리해 쓴다. 기존 값·소유권을 새로 만들거나 바꾸지 않는다.
6. 관계·엔티티 수정과 함께 continuations의 지정 section을 최소 신규 문자 수 이상 이어 쓴다. 사건 설명·처리 이유·확인 절차를 보충하되, 근거 없는 사실을 추가하거나 기존 사실을 복사해 분량을 채우지 않는다. 반복·위치·mention 비율·근거 거리·표현 방식별 개수는 복구 목표가 아니다.

[출력]
Schema에 맞는 JSON만 반환한다. base_draft_version은 현재 버전이다.
insertions: after_sentence_id 뒤에 추가; ""는 문서 시작. refs: 추가/변경만; 없으면 [].
replacements: S ID를 키로 하는 객체. required_replacement_sentence_ids는 실제 segment 교체가 필수다. 나머지는 교체할 문장이면 segment, 그대로 둘 문장이면 null.
relation_evidence_updates: {}. 정상 근거는 코드가 유지하며 오류 R의 근거는 수정 문구와 함께 코드가 연결한다.
relation_repairs: 오류 R마다 한 문장 또는 연결된 여러 문장 형식을 선택한다.
sentence: form="sentence", text=두 endpoint 토큰을 포함한 완전한 한 문장. 예: "신청인 <NAME:E1>{josa:의} 개인 연락처는 <MOBILE_PHONE:E2>이다.". 이 형식을 우선 사용한다.
linked_text: form="linked_text", source_text=source 토큰을 포함한 완전한 문장, bridge_sentences=[], target_text=target 토큰을 포함한 완전한 문장. 앞 문장의 대상과 뒤 문장의 귀속을 명확히 연결한다.
아래 조각 형식도 과거 출력 호환을 위해 지원하지만 새 수정에는 완전한 문장을 우선한다.
one_sentence: before_source + [source] + between_entities + [target] + after_target. 예: "", "의 개인 연락처는 ", "이다.".
linked_sentences: source_before + [source] + source_after; bridge_sentences; target_before + [target] + target_after. 앞 문장의 대상과 뒤 문장의 관계가 분명해야 한다. 각 조각 조합은 한 문장이다.
연결형 개인 연락처 예: source_before="", source_after="{josa:은/는} 개인 연락처를 접수 때 제출했다.", bridge_sentences=[], target_before="해당 신청인이 제출한 개인 연락처는 ", target_after="이다.".
source/target 앞부분에는 마침표를 넣지 않는다. 뒷부분에는 해당 엔티티에 이어지는 술어와 종결 부호를 넣는다. 공용 관계는 해당 기관·부서가 주체인 공용 용도와 귀속을 명시한다.
reserved_sentence_ids는 코드가 교체하므로 replacements에 쓰지 않는다. relation_repairs의 새 ID와 근거는 코드가 부여한다. 정상 인물의 정보 귀속·근거·역할을 바꾸지 않는다.
continuations: 지정된 SC ID별 이어쓰기 본문 문자열. minimum_new_chars는 공백 포함 문자 수이며 각 구간의 최소 길이를 반드시 충족한다. 토큰·ID는 코드가 연결한다.
Schema의 모든 객체 키를 반환한다. 근거는 한 문장 또는 여러 문장일 수 있으며 형식별 개수 할당은 없다.
"""


def evidence_issues(groups: list[list[str]], segments: list[dict], endpoints: tuple[str,str], refs: dict) -> list[str]:
    positions = {s["sentence_id"]: i for i,s in enumerate(segments)}
    appearances = {}
    for seg in segments:
        ids = {eid for _,eid in PLACEHOLDER.findall(seg["text"])}
        ids |= {refs[rid]["entity_id"] for rid in REF_PATTERN.findall(seg["text"]) if rid in refs}
        appearances[seg["sentence_id"]] = ids
    valid_groups = []
    for group in groups:
        if not group or len(group) != len(set(group)) or any(sid not in positions for sid in group):
            return ["invalid evidence IDs"]
        covered = set().union(*(appearances[sid] for sid in group))
        if not set(endpoints) <= covered:
            return ["evidence endpoints not structurally connected"]
        # This is a structural condition only. Full semantic minimality is judged later.
        valid_groups.append(group)
    if not valid_groups:
        return ["missing evidence group"]
    return []


def diagnose(draft: dict, condition: dict, plan: dict, values: dict) -> tuple[dict, dict | None]:
    validate(draft, DRAFT)
    result = copy.deepcopy(draft)
    for seg in result["segments"]:
        seg["text"] = normalize(seg["text"])
    result,sentence_splits = split_prose_sentences(result)
    result,duplicate_merges = collapse_exact_boilerplate(result)
    section_order = {s["section_id"]:i for i,s in enumerate(condition["section_plan"])}
    original_order = [s["sentence_id"] for s in result["segments"]]
    result["segments"].sort(key=lambda s:section_order.get(s["section_id"],len(section_order)))
    order_normalized = original_order != [s["sentence_id"] for s in result["segments"]]
    issues = []
    suspected_pairs = []
    segments = result["segments"]
    if not segments:
        return {"issues": [Issue("EMPTY_DOCUMENT", "Add the planned sections to the empty draft", "REPAIR").json()],
                "metrics": {},"normalized_draft":result,"protected_adjacent_groups":[],"sentence_splits":sentence_splits}, None
    ids = [s["sentence_id"] for s in segments]
    if len(ids) != len(set(ids)) or any(not re.fullmatch(r"S[1-9][0-9]*", sid) for sid in ids):
        issues.append(Issue("DRAFT_SENTENCE_ID", "Repair IDs while preserving sentence text", "REPAIR"))
    entity_types = {e["entity_id"]: e["entity_type"] for e in plan["entities"]}
    scenes = {s["scene_id"]: s for s in plan["scenes"]}
    sections = {s["section_id"]: s for s in condition["section_plan"]}
    refs = {r["ref_id"]: r for r in result["refs"]}
    if len(refs) != len(result["refs"]) or any(not re.fullmatch(r"C[1-9][0-9]*", rid) for rid in refs):
        issues.append(Issue("REFERENCE_ID", "Invalid/duplicate C ID"))
    for ref in refs.values():
        if ref["entity_id"] not in entity_types or not ref["surface"].strip() or re.search(r"[<>]", ref["surface"]):
            issues.append(Issue("REFERENCE_TARGET", ref["ref_id"]))
        if ref["surface"] in {v["value"] for v in values.values()}:
            issues.append(Issue("REFERENCE_ACTUAL_VALUE", "Full actual entity values must be real mentions"))
    seen_sections = []
    evidence = {e["relation_id"]: e["evidence_groups"] for e in result["relation_evidence"]}
    evidence_ids_invalid = len(evidence) != len(result["relation_evidence"])
    structural_evidence_repairs = []
    for relation in plan["relations"]:
        rid = relation["relation_id"]
        if not evidence_issues(evidence.get(rid,[]), segments, (relation["source"],relation["target"]),refs):
            continue
        candidates = []
        for seg in segments:
            appearances = {eid for _,eid in PLACEHOLDER.findall(seg["text"])}
            appearances |= {refs[ref]["entity_id"] for ref in REF_PATTERN.findall(seg["text"]) if ref in refs}
            if {relation["source"],relation["target"]} <= appearances:
                candidates.append([seg["sentence_id"]])
        if candidates:
            structural_evidence_repairs.append({"relation_id":rid,"previous_groups":evidence.get(rid,[]),"candidate_groups":candidates,
                                               "semantic_verification":"independent_review_still_required"})
            evidence[rid] = candidates
    if structural_evidence_repairs:
        result["relation_evidence"] = [{"relation_id":rid,"evidence_groups":groups} for rid,groups in evidence.items()]
    rids = {r["relation_id"] for r in plan["relations"]}
    planned_pairs = {frozenset((r["source"],r["target"])) for r in plan["relations"]}
    if evidence_ids_invalid or set(evidence)-rids:
        issues.append(Issue("EVIDENCE_ID", "Duplicate or unregistered R ID"))
    for seg in segments:
        sid = seg["sentence_id"]
        if seg["section_id"] not in sections or seg["scene_id"] not in scenes or (seg["scene_id"] in scenes and scenes[seg["scene_id"]]["section_id"] != seg["section_id"]):
            issues.append(Issue("SEGMENT_SCENE_SECTION", "Invalid scene/section", sentence_id=sid))
            continue
        if not seen_sections or seen_sections[-1] != seg["section_id"]:
            seen_sections.append(seg["section_id"])
        if seg["kind"] not in sections[seg["section_id"]]["allowed_kinds"] + ["heading"]:
            issues.append(Issue("SEGMENT_KIND", "Kind incompatible with section", sentence_id=sid))
        for tag in re.findall(r"<[^>]*>", seg["text"]):
            if not PLACEHOLDER.fullmatch(tag) and not REF_PATTERN.fullmatch(tag):
                issues.append(Issue("UNKNOWN_TAG", tag, sentence_id=sid))
        for typ,eid in PLACEHOLDER.findall(seg["text"]):
            if entity_types.get(eid) != typ:
                issues.append(Issue("PLACEHOLDER_TYPE_ID", f"{typ}:{eid}", sentence_id=sid))
        for rid in REF_PATTERN.findall(seg["text"]):
            if rid not in refs:
                issues.append(Issue("MISSING_REFERENCE", rid, sentence_id=sid))
        appearances = {eid for _,eid in PLACEHOLDER.findall(seg["text"]) if eid in entity_types}
        appearances |= {refs[rid]["entity_id"] for rid in REF_PATTERN.findall(seg["text"]) if rid in refs and refs[rid]["entity_id"] in entity_types}
        for source,target in itertools.combinations(sorted(appearances),2):
            if frozenset((source,target)) not in planned_pairs:
                suspected_pairs.append({"sentence_id":sid,"entity_a":source,"entity_b":target,
                                        "status":"cooccurrence_only_not_a_semantic_relation_decision"})
        for match in TOKEN.finditer(seg["text"]):
            if match.group("josa"):
                from ..renderer import JOSA_PAIRS
                if match.group("josa") not in JOSA_PAIRS:
                    issues.append(Issue("JOSA_MARKER", match.group("josa"), sentence_id=sid))
        if any(pattern.search(seg["text"]) for pattern in LITERALS):
            issues.append(Issue("LITERAL_IDENTIFIER", "Identifier must be a placeholder", sentence_id=sid))
        if not seg["text"].strip():
            issues.append(Issue("EMPTY_SEGMENT", "Segment is empty", sentence_id=sid))
        if "\n" in seg["text"] or "\r" in seg["text"]:
            issues.append(Issue("MULTILINE_SEGMENT", "Each segment must be one sentence or one form line", sentence_id=sid))
        if seg["kind"] == "prose" and re.search(r"(?<!\d)[.!?。！？]+[\"'”’)]*\s+(?=[가-힣A-Za-z<])", seg["text"]):
            issues.append(Issue("PROSE_MULTIPLE_SENTENCES", "Split prose into one sentence per segment and update evidence IDs", sentence_id=sid))
    missing_sections = set(sections)-set(seen_sections)
    for section in missing_sections:
        issues.append(Issue("MISSING_SECTION", "Add planned section", section_id=section))
    order = {key:i for i,key in enumerate(sections)}
    if any(order.get(a,-1)>order.get(b,-1) for a,b in zip(seen_sections,seen_sections[1:])):
        issues.append(Issue("SECTION_ORDER", "Correct the existing section blocks", "REPAIR"))
    for scene in set(scenes)-{s["scene_id"] for s in segments}:
        issues.append(Issue("MISSING_SCENE", scene))
    for relation in plan["relations"]:
        errs = evidence_issues(evidence.get(relation["relation_id"], []), segments, (relation["source"], relation["target"]), refs)
        for error in errs:
            issues.append(Issue("RELATION_EVIDENCE", error, "REWRITE_SCENE", relation_id=relation["relation_id"]))
    for eid in sorted(set(entity_types)-actual_entities(result,plan)):
        issues.append(Issue("MISSING_ENTITY_MENTION","Entity has no actual typed placeholder mention",entity_id=eid))
    if condition["layout_variant"] == "question_answer":
        kinds = [s["kind"] for s in segments]
        if not ("question" in kinds and "answer" in kinds):
            issues.append(Issue("QUESTION_ANSWER_LAYOUT", "Question and answer units are required"))
    filled = None
    metrics = {}
    blocking = {"DRAFT_SENTENCE_ID", "REFERENCE_TARGET", "REFERENCE_ID", "SEGMENT_SCENE_SECTION", "UNKNOWN_TAG", "PLACEHOLDER_TYPE_ID", "MISSING_REFERENCE", "JOSA_MARKER"}
    if not any(i.code in blocking for i in issues):
        try:
            filled = render(result, plan, values)
            distribution, distribution_issues = measure(filled, plan, condition)
            issues.extend(i for i in distribution_issues if i.code != "MISSING_ENTITY_MENTION")
            lengths = collections.Counter()
            for sentence in filled["sentences"]:
                lengths[sentence["section_id"]] += len(sentence["sentence"])
            shortage = max(0, condition["min_chars"]-filled["rendered_chars"])
            if shortage:
                issues.append(Issue("LENGTH_SHORTAGE", f"Continue existing document by at least {shortage} rendered characters"))
            metrics = {"rendered_chars": filled["rendered_chars"], "min_chars": condition["min_chars"], "shortage_chars": shortage, "section_chars": dict(lengths), "section_shortages": {sid:max(0,s["target_chars"]-lengths[sid]) for sid,s in sections.items()}, "sentence_chars":{s["sentence_id"]:len(s["sentence"]) for s in filled["sentences"]}, "distribution": distribution}
        except StageFailure as exc:
            issues.extend(exc.issues)
    metrics["prose_observations"] = prose_metrics(result)
    return {"issues": [i.json() for i in issues], "metrics": metrics, "section_order_normalized":order_normalized,"sentence_splits":sentence_splits,"duplicate_sentence_merges":duplicate_merges,
            "structural_evidence_repairs":structural_evidence_repairs,"suspected_unplanned_endpoint_pairs":suspected_pairs,
            "protected_adjacent_groups": [], "normalized_draft": result}, filled


def apply_patch(draft: dict, patch: dict, diagnosis: dict) -> dict:
    validate(patch, PATCH)
    if patch["base_draft_version"] != draft["draft_version"]:
        fail("PATCH_BASE_VERSION", "Patch targets a stale draft", "STOP_CANDIDATE")
    result = copy.deepcopy(draft)
    old_ids = {s["sentence_id"] for s in result["segments"]}
    replacements = {s["sentence_id"]: s for s in patch["replacements"]}
    if len(replacements) != len(patch["replacements"]) or set(replacements)-old_ids:
        fail("PATCH_REPLACEMENT_ID", "Replacement must preserve an existing S ID", "STOP_CANDIDATE")
    insertions = collections.defaultdict(list)
    new_ids = set()
    positions = {segment["sentence_id"]: i for i,segment in enumerate(result["segments"])}
    blocked_after = set()
    for group in diagnosis.get("protected_adjacent_groups", []):
        ordered = sorted((sid for sid in group if sid in positions), key=positions.get)
        blocked_after.update(a for a,b in zip(ordered,ordered[1:]) if positions[b]-positions[a] == 1)
    for items, field in [(patch["refs"], "ref_id"), (patch["relation_evidence_updates"], "relation_id")]:
        identifiers = [item[field] for item in items]
        if len(identifiers) != len(set(identifiers)):
            fail("PATCH_DUPLICATE_UPDATE", f"Duplicate {field} in patch", "STOP_CANDIDATE")
    for insertion in patch["insertions"]:
        anchor = insertion["after_sentence_id"]
        if anchor and anchor not in old_ids:
            fail("PATCH_ANCHOR", anchor, "STOP_CANDIDATE")
        if anchor in blocked_after:
            fail("PATCH_PROTECTED_GAP", anchor, "STOP_CANDIDATE")
        for segment in insertion["segments"]:
            sid = segment["sentence_id"]
            if sid in old_ids or sid in new_ids:
                fail("PATCH_NEW_ID", sid, "STOP_CANDIDATE")
            new_ids.add(sid)
        insertions[anchor].extend(insertion["segments"])
    segments = list(insertions[""])
    for segment in result["segments"]:
        segments.append(replacements.get(segment["sentence_id"],segment))
        segments.extend(insertions[segment["sentence_id"]])
    result["segments"] = segments
    refs = {r["ref_id"]:r for r in result["refs"]}
    refs.update({r["ref_id"]:r for r in patch["refs"]})
    used_refs = {rid for segment in segments for rid in REF_PATTERN.findall(segment["text"])}
    result["refs"] = [r for rid,r in refs.items() if rid in used_refs]
    evidence = {e["relation_id"]:e for e in result["relation_evidence"]}
    evidence.update({e["relation_id"]:e for e in patch["relation_evidence_updates"]})
    result["relation_evidence"] = list(evidence.values())
    result["draft_version"] += 1
    validate(result, DRAFT)
    return result


def repair_input(draft: dict, condition: dict, plan: dict, diagnosis: dict) -> dict:
    old_ids = [s["sentence_id"] for s in draft["segments"]]
    first_new = max((int(sid[1:]) for sid in old_ids),default=0)+1
    tasks = build_tasks(draft,condition,plan,diagnosis)
    relevant = set(tasks["editable_sentence_ids"])|set(tasks["reserved_sentence_ids"])
    fixed = [r for r in tasks["relations"] if r["operation"] == "fix"]
    for s in draft["segments"]:
        if any(s["scene_id"] == r["scene_id"] and any(t in s["text"] for t in (r["source_placeholder"],r["target_placeholder"])) for r in fixed):
            relevant.add(s["sentence_id"])
    for t in tasks["continuation_targets"]:
        relevant.update(s["sentence_id"] for s in [s for s in draft["segments"] if s["scene_id"] == t["scene_id"]][-2:])
    positions = {s["sentence_id"]:i for i,s in enumerate(draft["segments"])}
    context = set(relevant)
    for sid in relevant:
        index = positions.get(sid)
        if index is not None:
            context.update(s["sentence_id"] for s in draft["segments"][max(0,index-1):index+2] if s["scene_id"] == draft["segments"][index]["scene_id"])
    view = {**draft,"segments":[s for s in draft["segments"] if s["sentence_id"] in context]}
    return {"privacy_policy":privacy_input(),"draft": view,"draft_scope":"Only repair-relevant context is shown; all omitted text remains intact.", "condition": condition_input(condition), "plan": plan_input(plan),
               "new_sentence_id_start": f"S{first_new}",
               "diagnosis": diagnosis_input(diagnosis),"repair_tasks":tasks}


def repair(client, draft: dict, condition: dict, plan: dict, diagnosis: dict) -> dict:
    payload = repair_input(draft, condition, plan, diagnosis)
    schema = repair_contract(draft,condition,plan,payload["repair_tasks"])
    policy = condition.get("document_policy")
    system = REPAIR_SYSTEM + (DRAFT_GUIDANCE if policy in {"purpose_v1","purpose_v2","prose_v1"} else "")
    if policy in {"purpose_v2","prose_v1"}:
        system += FACT_DRAFT_GUIDANCE
    if policy=='prose_v1':
        start=system.index('아래 조각 형식도')
        end=system.index('reserved_sentence_ids는',start)
        system=system[:start]+system[end:]
        system+='\n분량 보완은 plan.document_story의 구체적인 업무를 전개한다. 일반 비식별 업무 사실을 보충해도 된다. 작성법·중요성 해설·같은 사실의 반복은 쓰지 않는다.\n'
    response = client.request(condition["candidate_id"], 5, "repair", system, payload, schema)
    return decode_patch(response,schema,draft,condition,plan,payload["repair_tasks"])
