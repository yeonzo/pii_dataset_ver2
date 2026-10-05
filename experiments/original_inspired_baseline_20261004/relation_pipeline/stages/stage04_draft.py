"""Input: condition and value-free plan. Output: one complete placeholder document."""
from __future__ import annotations

import json
import math
import re

from ..schemas import DRAFT, PATCH
from ..prompt_inputs import condition_input, plan_input
from ..privacy import privacy_input
from ..document_purpose import DRAFT_GUIDANCE, FACT_DRAFT_GUIDANCE

SYSTEM = """[목적]
계획에 맞는 완성된 한국어 문서 전체를 한 번에 작성한다.

[입력]
condition: 형식·변형·주제·관점·section·분량. plan: 엔티티·관계·장면·제약.
placeholder_map/relation_write_slots: 정확한 토큰과 관계 endpoint. feedback: 이전 오류.

[핵심 규칙]
1. 모든 필수 section을 형식·변형·관점에 맞게 작성한다. section별 target_chars와 length_target을 목표로 충분한 처리 내용과 맥락을 쓴다.
2. 실제 값은 만들지 않는다. 모든 계획 엔티티를 정확한 <TYPE:E번호>로 실제 언급하고, 모든 관계의 방향·귀속·사용 맥락을 드러낸다. 새 엔티티·관계·privacy 해설은 추가하지 않는다.
3. 재언급에는 같은 E ID를 쓴다. 반복 횟수·위치·mention 비율·근거 거리·표현 방식별 할당량은 없으며 사실 복사로 분량을 채우지 않는다.
   서로 다른 E ID는 같은 TYPE이어도 별개 대상이다. 계좌·카드에서는 소유자, 결제수단, 기관 정산 계좌, 이체 출처·도착지를 구분한다. plan의 context_reason에 없는 환불 대상·거래 방향·처리 결과를 추측하거나 여러 E를 같은 거래 대상으로 합치지 않는다.
4. 지시어는 선행 대상을 명시한 뒤 <REF:C번호>로 쓰고 refs에 등록한다. surface는 실제 역할 표현이며 placeholder를 넣지 않는다. reference는 실제 entity mention을 대체하지 않는다.
5. 산문 segment는 한 문장, 양식은 한 줄, 제목은 heading이다. 조사는 <NAME:E1>{josa:은/는}처럼 표시한다.
6. R별 최소 근거의 대안 그룹을 반환하고 무관한 문장을 제외한다. 양식 항목 사이의 귀속 연결도 명확해야 한다.
7. 공통 privacy_policy와 persons/person_entity_links의 역할·정보 귀속을 지킨다. 각 주요 인물의 역할과 개인 정보를 분명히 연결하고, 공식 기관 창구는 기관이 공동 운영하는 용도로 쓴다. 계획에 없는 실명 인물을 추가하지 않는다.

[출력]
Schema에 맞는 JSON만 반환한다. 필수 필드: draft_version, segments, refs, relation_evidence.
문장 ID는 S1..., 지시어 ID는 C1...이다. 지시어를 쓰지 않으면 refs=[]이다.
"""


def document_contract(condition: dict, plan: dict, patch=False, draft=None) -> dict:
    schema = json.loads(json.dumps(PATCH if patch else DRAFT))
    tags = [f"<{e['entity_type']}:{e['entity_id']}>" for e in plan["entities"]]
    pattern = "^(?:[^<>]|" + "|".join(re.escape(tag) for tag in tags) + r"|<REF:C[1-9][0-9]*>)*$"
    def segment(item):
        props = item["properties"]
        props["sentence_id"]["pattern"] = r"^S[1-9][0-9]*$"
        props["section_id"]["enum"] = [s["section_id"] for s in condition["section_plan"]]
        props["scene_id"]["enum"] = [s["scene_id"] for s in plan["scenes"]]
        props["text"]["pattern"] = pattern
    props = schema["properties"]
    if patch:
        segment(props["replacements"]["items"])
        segment(props["insertions"]["items"]["properties"]["segments"]["items"])
        props["insertions"]["items"]["properties"]["after_sentence_id"]["pattern"] = r"^(?:S[1-9][0-9]*|)$"
        if draft is not None:
            old_ids = [s["sentence_id"] for s in draft["segments"]]
            last_number = max((int(sid[1:]) for sid in old_ids),default=0)
            # Disjoint IDs prevent a patch from overwriting or confusing old evidence.
            new_ids = [f"S{i}" for i in range(last_number+1, last_number+129)]
            props["base_draft_version"]["enum"] = [draft["draft_version"]]
            props["replacements"]["items"]["properties"]["sentence_id"]["enum"] = old_ids
            insertion = props["insertions"]["items"]["properties"]
            insertion["after_sentence_id"]["enum"] = ["", *old_ids]
            insertion["segments"]["items"]["properties"]["sentence_id"]["enum"] = new_ids
            props["replacements"]["maxItems"] = len(old_ids)
    else:
        segment(props["segments"]["items"])
        props["segments"]["minItems"] = max(12, math.ceil(condition["length_target"]/80))
        # Bound the response array as well as tokens; this is a generation budget.
        props["segments"]["maxItems"] = max(props["segments"]["minItems"]+16, math.ceil(condition["length_target"]/30))
    refs = props["refs"]["items"]["properties"]
    refs["ref_id"]["pattern"] = r"^C[1-9][0-9]*$"
    refs["entity_id"]["enum"] = [e["entity_id"] for e in plan["entities"]]
    refs["surface"]["pattern"] = r"^[^<>\r\n]+$"
    evidence = props["relation_evidence_updates" if patch else "relation_evidence"]
    if not patch:
        evidence.update(minItems=len(plan["relations"]), maxItems=len(plan["relations"]))
    fields = evidence["items"]["properties"]
    fields["relation_id"]["enum"] = [r["relation_id"] for r in plan["relations"]]
    fields["evidence_groups"]["items"]["items"]["pattern"] = r"^S[1-9][0-9]*$"
    branches = []
    for relation in plan["relations"]:
        branch = json.loads(json.dumps(evidence["items"]))
        branch["properties"]["relation_id"]["enum"] = [relation["relation_id"]]
        group = branch["properties"]["evidence_groups"]["items"]
        group["minItems"] = 1
        branch["properties"]["evidence_groups"]["minItems"] = 1
        branches.append(branch)
    evidence["items"] = {"anyOf":branches}
    return schema


def draft_input(condition: dict, plan: dict, feedback=None) -> dict:
    placeholders = {e["entity_id"]:f"<{e['entity_type']}:{e['entity_id']}>" for e in plan["entities"]}
    slots = [{"relation_id":r["relation_id"],"source_placeholder":placeholders[r["source"]],
              "target_placeholder":placeholders[r["target"]],"relation":r["relation"],
              "scene_id":r["scene_id"], "context_reason":r["context_reason"]} for r in plan["relations"]]
    return {"privacy_policy":privacy_input(),"condition": condition_input(condition), "plan": plan_input(plan), "placeholder_map":placeholders,"relation_write_slots":slots,"feedback": feedback or []}


def generate(client, condition: dict, plan: dict, feedback=None) -> dict:
    policy = condition.get("document_policy")
    system = SYSTEM + (DRAFT_GUIDANCE if policy in {"purpose_v1","purpose_v2"} else "")
    if policy == "purpose_v2":
        system += FACT_DRAFT_GUIDANCE
    return client.request(condition["candidate_id"], 4, "draft", system,
                          draft_input(condition, plan, feedback),
                          document_contract(condition,plan))
