# 현재 프롬프트·Input·Output 계약 — 2026-10-04

계획·초안·국소 수정·분량 추가는 `gpt-4o-mini`, 검수만 `gpt-5-mini`다. 기본 `generation_flow=separated_v1`은 정상 3~6회, 모든 단계가 공유하는 재시도 1회를 포함해 후보당 최대 7회다. 실제 값은 코드가 공급하고 치환한다.

| 단계 | 핵심 입력·출력 | 제한 |
| --- | --- | --- |
| 계획 | 고정 그래프·타입별 내용 → 관계 사실·장면별 `facts` 2~5개 | 1회 |
| 초안 | 확정된 계획 → 전체 본문 | 1회 |
| 국소 수정 | 길이 부족을 제외한 오류 → 완전 문장 `sentence/linked_text`; `continuations={}` | 1회 |
| 분량 추가 | 한 section·기존 본문 전체·내용 지침 → `{section_id, sentences}` | 2회 |
| 독립 검수 | 최종 본문 → 의미·privacy·품질·근거 문장 ID | 1회 |

분량 추가 프롬프트 전문과 병합 검사는 [additions.py](relation_pipeline/additions.py)에 있다. 기존 문장·지시어·근거는 보존하며, 반복·명시적 숫자 충돌·새 식별값·구조 오류가 있는 블록은 병합하지 않는다. 유효한 최종 검수에서 의미·품질이 실패하면 재작성하지 않고 탈락 사유를 남긴다. 이전 조건에 검수 정책이 없으면 현재 설정의 `sentence_ids`를 상속한다.

후속 변경의 실행 원문은 소스 및 후보별 `api/request_*.json`이 기준이다. 아래 기본 프롬프트에 공통 privacy 3.0이 들어간다. `--reference-profile` 선택 시 가상 사례/작품 또는 출처 확인 공개 약력의 맥락을 추가한다. 기본 검수 출력은 [review_evidence.py](relation_pipeline/review_evidence.py)의 안내에 따라 `evidence_quotes` 없이 `evidence_groups`를 반환하고, 코드가 정확한 원문 인용을 연결한다. 복구 입력은 [repair_feedback.py](relation_pipeline/repair_feedback.py)로 알려진 실제 값을 다시 토큰으로 바꾼다. 실험용 간단한 계획·초안 프롬프트 전문은 [prose_writer.py](relation_pipeline/prose_writer.py)에 있으며 `document_policy=legacy`에서는 사용하지 않는다. 실제 비교와 채택 결정은 [NATURALNESS_EXPERIMENT.md](NATURALNESS_EXPERIMENT.md)에 기록한다.

계획 모델은 `relation_contexts, scene_notes`만 반환한다. 코드가 확정한 인물·엔티티·관계 endpoint·privacy·값 그룹·귀속 연결은 다시 쓰지 않는다. 모든 단계에 같은 `privacy_policy`를 주며, 검수에는 계획의 정답 privacy·context_reason·인물별 정답 귀속·생성자 근거·의도한 지시어 대상을 주지 않는다.

| 호출 | Input JSON | 프롬프트 전문 | 모델 Output JSON Schema |
| --- | --- | --- | --- |
| 계획 맥락 | [Input](examples/structured_prompts/plan_input.json) | [TXT](examples/structured_prompts/plan_prompt.txt) | [Schema](examples/structured_prompts/plan_output_schema.json) |
| 완성 초안 | [Input](examples/structured_prompts/draft_input.json) | [TXT](examples/structured_prompts/draft_prompt.txt) | [Schema](examples/structured_prompts/draft_output_schema.json) |
| 기존 문서 수정 | [Input](examples/structured_prompts/repair_input.json) | [TXT](examples/structured_prompts/repair_prompt.txt) | [Schema](examples/structured_prompts/repair_output_schema.json) |
| 독립 검수 | [Input](examples/structured_prompts/review_input.json) | [TXT](examples/structured_prompts/review_prompt.txt) | [Schema](examples/structured_prompts/review_output_schema.json) |
| 값 제약만 수정 | [Input](examples/structured_prompts/plan_repair_input.json) | [TXT](examples/structured_prompts/plan_repair_prompt.txt) | [Schema](examples/structured_prompts/plan_repair_output_schema.json) |

앞 네 입력/계약은 v3 금융 실제 호출에서 추출했다. 각 출처는 [provenance.json](examples/structured_prompts/provenance.json)에 있다. 실제 요청 예시는 합격 문서를 의미하지 않는다. 값 제약 수정은 호출하지 않은 가상 오류의 출력 계약 예시다.

국소 복구는 오류 주변 본문을 전달하고 정상 근거를 보호한다. `relation_repairs`는 완전한 한 문장 `sentence` 또는 연결된 문장 `linked_text`만 허용하며 Schema가 지정 endpoint 토큰의 존재를 강제한다. 과거 조각 형식과 `continuations` 이어쓰기는 `generation_flow=legacy`에만 남겨 둔다. 코드가 문장 ID·장면·근거를 결합하므로 `relation_evidence_updates={}`다.

검수는 NAME별 실제 관찰 역할·정확한 인용을 `person_checks`에 반환한다. 실제 수정이 필요한 언어·일관성·형식 문제는 `text_issues`에 S ID·관련 R ID·이유·수정 지시로 기록한다. 추가 관계·미등록 값·모순도 실제 S ID로 복구에 전달한다. 동일 S/R의 지시를 조합마다 복제하지 않는다.

기존 원문 생성 파일 `../pii_dataset/step2_document/Document/prompts.py`는 변경하지 않았다. 이 패키지의 최초 생성 프롬프트는 [stage04_draft.py](relation_pipeline/stages/stage04_draft.py)의 `SYSTEM`이다. 아래는 기본 상수와 이전 실행 예시이며, 분리 흐름에서는 계획의 `outline`을 `facts`로 바꾸고 복구의 조각·분량 지시를 제거해 요청한다. 실제 합성된 프롬프트는 후보별 `api/request_*.json`이 기준이다. 이전 버전은 [PROMPTS_20261003.md](PROMPTS_20261003.md)와 [과거 예시](examples/structured_prompts_20261003/)에 보존했다.

## 계획 맥락

```text
[목적]
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
```

## 완성 초안

```text
[목적]
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
```

## 기존 문서 수정

```text
[목적]
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
```

## 독립 검수

```text
[목적]
실제 본문으로 관계·privacy·문서 품질을 독립 검수한다. 문서는 수정하지 않는다.

[입력]
sentences/entities/references: 본문·실제 mention·지시어 span.
relations: 정답 privacy 없는 후보. domain/subtype/format: 형식 조건. ontology: 관계 정의.

[핵심 규칙]
1. 실제 개인 귀속은 PII, 기관 공용 정보는 NON_PII다. 값의 외형·합성 여부로 판정하지 않는다. 전체 맥락에서도 귀속이 여러 해석으로 남을 때만 AMBIGUOUS로 설명한다. 다문장 연결의 필요와 언어 품질은 모호성과 구분한다.
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
```

## 값 제약만 수정

```text
[목적]
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
```
