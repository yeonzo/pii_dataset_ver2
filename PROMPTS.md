# 프롬프트와 입출력 계약 — 2026-10-05

이 문서의 프롬프트와 예시는 현재 코드로 실행해 채택된 문서 1건의 실제 요청에서 그대로 가져왔다.

- 출처: run `one_medical_questionnaire_20261005_v1`, 후보 `medical_001_c001` (의료, 문진표)
- 이 실행은 관계 수를 3개로 고정하고 관계 커버리지를 껐다. 프롬프트 문구는 기본 설정과 같고, 입력의 관계 수만 다르다.
- 생성 호출 네 가지의 시스템 프롬프트는 그 실행 그대로이며 현재 코드와 같다. 검수 프롬프트는 그 뒤 관계 판정 4번과 5번에 예외가 추가됐고, 이 문서와 예시 파일에는 현재 문구를 실었다.
- 입력의 `privacy_policy`는 실행 당시의 3.0이고, 현재 정의는 문장과 예시가 추가된 3.1이다. 출처와 요청 번호는 [provenance.json](examples/structured_prompts/provenance.json)에 있다.
- 코드나 프롬프트를 바꾼 뒤에는 `python3 -m relation_pipeline inspect --run-id <run> --candidate-id <id> --artifact prompts`로 실제 요청을 다시 확인한다.

## 호출 한눈에 보기

| 호출 | 모델 | 후보당 상한 | 출력 토큰 상한 | 입력의 핵심 | 출력의 핵심 |
| --- | --- | --- | --- | --- | --- |
| 계획 | `gpt-4o-mini` | 1회 | 8,000 | 조건, 코드가 만든 그래프 | 관계별 맥락, 장면별 사실, 사건 설정 |
| 초안 | `gpt-4o-mini` | 1회 | 12,000 | 조건, 계획, 엔티티별 작성 안내 | placeholder로 쓴 문서 전체 |
| 국소 수정 | `gpt-4o-mini` | 2회 | 6,000 | 현재 초안, 코드 검사 오류, 고칠 대상 | 고친 문장과 추가 문장 |
| 분량 추가 | `gpt-4o-mini` | 4회 | 3,000 | 구간 하나, 기존 본문, 부족한 글자 수 | 그 구간의 새 문장 |
| 독립 검수 | `gpt-5-mini` | 1회 | 16,000 | 최종 본문, 라벨을 뺀 관계 목록 | 관계 판정, 품질 등급, 필수 내용 충족 여부 |

- 응답 형식 오류나 네트워크 오류의 재시도는 문서 전체에서 1회만 허용한다. 합계는 후보당 최대 10회다.
- 생성 호출은 temperature 0.7, 검수 호출은 reasoning effort `low`다.
- 모든 호출은 OpenAI Responses API의 strict JSON Schema 출력을 쓴다. Schema는 후보의 조건에 맞춰 허용 ID와 값을 좁힌 것이라 호출마다 다르다.

예시 후보는 계획 1회, 초안 1회, 국소 수정 1회, 분량 추가 3회, 검수 1회로 모두 7회를 호출했다.

## 프롬프트 조립

생성 호출 네 가지의 시스템 프롬프트는 아래 순서로 이어 붙인다.

1. 호출별 기본 프롬프트: `[목적] → [입력] → [핵심 규칙] → [출력]`
2. 문서 타입 지침: 계획은 `[타입별 문서 설계]`, 초안·국소 수정·분량 추가는 `[타입별 완성 문서 작성]`
3. `[필수 사실의 구체성]`: 네 호출 공통
4. 도메인 지침 5개 블록: 작성 맥락, 타입별 전개 순서, 필요한 세부 사실, 구체적인 서술 예시, 일관성 확인
5. `[이번 단계의 범위]`: 호출마다 다른 한 문단

검수 호출은 기본 프롬프트에 `[타입별 완성도 독립 검수]`만 붙인다. 도메인 지침과 생성용 예시는 검수에 넣지 않는다.

모델에 주지 않는 정보는 다음과 같다.

- 생성 호출: 엔티티의 실제 값. 모델은 `<NAME:E1>` 같은 토큰만 본다.
- 검수 호출: 계획한 라벨(`target_privacy`), 관계 맥락(`context_reason`), 장면별 사실 계획, 사건 설정(`document_case`), 인물과 엔티티의 정답 연결.

## 1. 계획

[입력](examples/structured_prompts/plan_input.json) · [프롬프트](examples/structured_prompts/plan_prompt.txt) · [출력 Schema](examples/structured_prompts/plan_output_schema.json) · [실제 출력](examples/structured_prompts/plan_output.json)

코드가 만든 그래프에 모델이 맥락과 사실을 채운다. 코드는 응답을 그래프에 결합한 뒤 관계 수, 허용 관계, 인물 귀속을 다시 검사하고, 사실 항목이 제목이나 작성 지시로만 채워졌으면 응답 수정을 요구한다.

| 입력 필드 | 내용 |
| --- | --- |
| `privacy_policy` | 모든 호출이 공유하는 PII / NON_PII / AMBIGUOUS 정의 |
| `requirements` | 관계 수와 PII / NON_PII 목표 수 |
| `relation_slots` | 관계 ID별로 고정된 라벨 |
| `seed_plan` | 코드가 만든 그래프: 엔티티, 관계, 장면, 인물과 엔티티의 연결 |
| `condition` | 문서 타입, 관점, 구간 구성, 목표 길이, 문서 타입 기준(`document_spec`) |
| `ontology` | 이 문서에 쓰인 관계 타입의 정의 |
| `feedback` | 이전 응답의 오류. 첫 호출에서는 빈 배열 |

| 출력 필드 | 내용 |
| --- | --- |
| `relation_contexts` | 관계 ID별 `context_reason`과 `scene_id` |
| `scene_notes` | 장면 ID별 `purpose`와 필수 사실 항목별 `content_facts` |
| `document_case` | 사건 설정: `situation`, `scope_decisions`, `end_state` |

```text
[목적]
코드가 확정한 관계 그래프에 구체적인 업무 맥락과 장면 설명을 계획한다. 본문과 실제 엔티티 식별값은 생성하지 않는다. 비식별 사건의 날짜·금액·기간·관찰 사실은 구체값으로 계획한다.

[입력]
condition: 형식·주제·관점·인물 역할. seed_plan: 고정 인물·엔티티·관계·값 그룹.
ontology: 사용된 관계의 정의. feedback: 이전 오류. 기존 계획은 수정 맥락이다.

[핵심 규칙]
1. 그래프의 인물·역할·endpoint·관계·privacy·값 그룹은 고정이다. 다시 반환하거나 바꾸지 않는다.
2. privacy_policy에 따라 각 R의 context_reason에 해당 개인/기관의 역할, 정보 귀속, 실제 사용 목적·행위·상대를 구체적으로 쓴다. 관계명이 아니라 온톨로지의 의미를 본문에서 입증할 수 있는 맥락이어야 한다. 값의 외형을 근거로 삼지 않는다.
3. 각 R을 입력의 SC 중 하나에 배정하고, 모든 SC의 purpose/content_facts을 문서 종류·변형·주제에 맞게 쓴다. 장면 간 당사자 역할·사실·처리 흐름을 일관되게 연결한다. section ID·순서는 코드가 보존한다.
4. 서로 다른 E ID는 같은 TYPE이어도 서로 다른 대상이다. 특히 계좌·카드의 소유자, 사용 목적, 기관 정산 계좌, 거래 출처·도착지를 구분하고 하나의 사건으로 임의 통합하지 않는다. 각 R의 context_reason과 장면 개요가 서로 모순되지 않도록 한다.
5. 인물과 개인 속성의 소유자를 바꾸거나, 다른 이름·기관·식별정보·계획 밖 의미 관계를 추가하지 않는다. 같은 기관의 연락·조직 정보라도 개인 귀속과 공용 용도를 구분한다.
6. 반복 횟수·위치·mention 비율·근거 거리·표현 방식별 수량은 배정하지 않는다. 기존 계획에 feedback이 있으면 오류 맥락만 수정한다.

[출력]
JSON 필수 필드: relation_contexts, scene_notes.
relation_contexts: 모든 R ID를 키로 {context_reason, scene_id}.
scene_notes: 모든 SC ID를 키로 {purpose, content_facts}.
서술은 한국어다. 코드가 고정 그래프에 이 맥락만 결합해 최종 plan을 검사한다.
```

계획에만 붙는 문서 타입 지침:

```text
[타입별 문서 설계]
document_spec의 작성자·독자·역할·항목 순서·조건·완성 기준을 따른다. 공통 상담 서식으로 바꾸지 않는다.
document_case에 구체적 사건·조건별 적용 여부·끝 상태를 확정한다. 선택되지 않은 상황은 섞지 않는다.
scene_notes의 content_facts는 각 field_id가 요구하는 실제 합성 사실·내역을 채운다. 제목이나 작성 지시를 반환하지 않는다.
금액·날짜·기간·과목·검사수치 등 비식별 사실은 실제 같은 구체값으로 만들고 계산·선후관계를 맞춘다.
예: '피해 금액을 기재한다' 대신 '9월 3일 두 차례 이체한 18만원과 12만원의 합계 30만원을 피해액으로 신고했다'.
없음·미확인은 이유와 확인 범위를 적고, 필수 항목을 모두 '해당 없음'으로 채우지 않는다.
당사자·실명·기관·식별값은 고정 그래프를 따른다. 새 엔티티나 관계를 추가하지 않는다.
표의 행 수·문답 수가 지정되어 있으면 해당 필드에 필요한 서로 다른 내역/문답을 계획한다. 표 내역은 문장 나열로도 표현할 수 있다.
```

## 2. 초안

[입력](examples/structured_prompts/draft_input.json) · [프롬프트](examples/structured_prompts/draft_prompt.txt) · [출력 Schema](examples/structured_prompts/draft_output_schema.json) · [실제 출력](examples/structured_prompts/draft_output.json)

문서 전체를 한 번에 쓴다. 다시 쓰는 호출은 없고, 이후에는 코드 검사 결과에 따라 고치거나 덧붙이기만 한다.

| 입력 필드 | 내용 |
| --- | --- |
| `privacy_policy`, `condition` | 계획과 같음 |
| `plan` | 계획 결과. 실제 값은 없다 |
| `entity_write_guide` | 엔티티별 타입 의미, 문서 속 역할, 연결된 인물, 작성 규칙, 참여하는 관계 |
| `placeholder_map` | 엔티티 ID와 토큰의 대응. 예: `E1` → `<NAME:E1>` |
| `relation_write_slots` | 관계별 양 끝 토큰, 관계 타입, 장면, 맥락 |
| `feedback` | 이전 응답의 오류. 첫 호출에서는 빈 배열 |

| 출력 필드 | 내용 |
| --- | --- |
| `draft_version` | 초안 버전 |
| `segments` | 문장 목록: `sentence_id`, `section_id`, `scene_id`, `kind`, `text` |
| `refs` | 지시어 목록: `ref_id`, `entity_id`, `surface`, `kind` |
| `relation_evidence` | 관계별 근거 문장 묶음: `relation_id`, `evidence_groups` |

```text
[목적]
계획에 맞는 완성된 한국어 문서 전체를 한 번에 작성한다.

[입력]
condition: 형식·변형·주제·관점·section·분량. plan: 엔티티·관계·장면·제약.
entity_write_guide: 각 E의 타입 의미, 문서 역할, 개인/기관 귀속, 연결 관계와 올바른 작성법.
placeholder_map/relation_write_slots: 정확한 토큰과 관계 endpoint. feedback: 이전 오류.

[핵심 규칙]
1. 모든 필수 section을 형식·변형·관점에 맞게 작성한다. section별 target_chars와 length_target을 목표로 충분한 처리 내용과 맥락을 쓴다.
2. 실제 엔티티 식별값은 만들지 않는다. 계획에 확정된 사건의 날짜·금액·기간·관찰 사실은 구체값으로 쓴다. 모든 계획 엔티티를 정확한 <TYPE:E번호>로 실제 언급하고, 모든 관계의 방향·귀속·사용 맥락을 드러낸다. E1, E2 같은 내부 ID를 일반 문장에 직접 쓰지 않는다. 새 엔티티·관계·privacy 해설은 추가하지 않는다.
   entity_write_guide의 type_meaning·document_role·write_rule을 따른다. NAME은 사람, WORKPLACE는 기관, DEPARTMENT는 기관 안의 부서, 번호·주소·계좌는 해당 속성값이다. "주민등록번호 <NAME:E1>", "신고인 <RRN:E2>", "부서 <TELEPHONE:E3>"처럼 역할어와 타입을 바꾸지 않는다.
3. 재언급에는 같은 E ID를 쓴다. 반복 횟수·위치·mention 비율·근거 거리·표현 방식별 할당량은 없으며 사실 복사로 분량을 채우지 않는다.
   서로 다른 E ID는 같은 TYPE이어도 별개 대상이다. 계좌·카드에서는 소유자, 결제수단, 기관 정산 계좌, 이체 출처·도착지를 구분한다. plan의 context_reason에 없는 환불 대상·거래 방향·처리 결과를 추측하거나 여러 E를 같은 거래 대상으로 합치지 않는다.
4. 지시어는 선행 대상을 명시한 뒤 <REF:C번호>로 쓰고 refs에 등록한다. surface는 실제 역할 표현이며 placeholder를 넣지 않는다. reference는 실제 entity mention을 대체하지 않는다.
5. 산문 segment는 한 문장, 양식은 한 줄, 제목은 heading이다. 조사는 <NAME:E1>{josa:은/는}처럼 표시한다.
6. R별 최소 근거의 대안 그룹을 반환하고 무관한 문장을 제외한다. 양식 항목 사이의 귀속 연결도 명확해야 한다.
7. 공통 privacy_policy와 persons/person_entity_links의 역할·정보 귀속을 지킨다. 각 주요 인물의 역할과 개인 정보를 분명히 연결하고, 공식 기관 창구는 기관이 공동 운영하는 용도로 쓴다. 계획에 없는 실명 인물을 추가하지 않는다.
8. "관계를 정의한다", "관계를 명확히 한다", "관계를 설명한다", "관계를 명시한다", "관계를 나타낸다"처럼 관계 자체를 설명하지 않는다. context_reason은 의미 제약이지 본문 문구 예시가 아니므로 복사·의역하지 않는다. 문서에서 실제로 일어난 제출·연락·접수·소유·소속 사실을 직접 쓴다.
9. 같은 기관 연락처·소속·주소 또는 같은 필수 사실을 어미만 바꾸어 반복하지 않는다. 하나의 구체적인 문장이나 항목으로 충분하면 한 번만 쓴다.

[출력]
Schema에 맞는 JSON만 반환한다. 필수 필드: draft_version, segments, refs, relation_evidence.
문장 ID는 S1..., 지시어 ID는 C1...이다. 지시어를 쓰지 않으면 refs=[]이다.
```

## 3. 국소 수정

[입력](examples/structured_prompts/repair_input.json) · [프롬프트](examples/structured_prompts/repair_prompt.txt) · [출력 Schema](examples/structured_prompts/repair_output_schema.json) · [실제 출력](examples/structured_prompts/repair_output.json)

5단계 코드 검사에서 분량 부족 외의 오류가 나왔을 때만 호출한다. 코드는 응답을 초안에 적용한 뒤 전체를 다시 검사하고, 고치려던 오류가 실제로 해결됐는지 기록한다.

| 입력 필드 | 내용 |
| --- | --- |
| `draft`, `draft_scope` | 오류와 관련된 부분만 담은 현재 초안과 그 사실을 알리는 안내 |
| `diagnosis` | 코드 검사의 오류 목록(`issues`)과 측정값(`metrics`) |
| `repair_tasks` | 빠진 엔티티, 고칠 관계와 양 끝 토큰, 고쳐도 되는 문장 ID, 보호할 문장 ID, 완료 조건 |
| `new_sentence_id_start` | 새 문장에 쓸 ID의 시작값 |
| `privacy_policy`, `condition`, `plan`, `entity_write_guide` | 초안과 같음 |

| 출력 필드 | 내용 |
| --- | --- |
| `relation_repairs` | 오류 관계별 수정 문장. `sentence` 또는 `linked_text` 형식 |
| `replacements` | 문장 ID별 교체 내용. 그대로 둘 문장은 `null` |
| `insertions` | 지정한 문장 뒤에 넣을 새 문장 |
| `refs` | 추가하거나 바꾼 지시어 |
| `base_draft_version` | 수정 대상 초안의 버전 |
| `relation_evidence_updates`, `continuations` | 항상 빈 객체. 근거 연결은 코드가 하고 분량은 별도 호출이 맡는다 |

```text
[목적]
초안의 진단 오류를 추가·이어쓰기·국소 교체로 한 번에 복구한다.

[입력]
draft: 현재 초안. condition/plan: 문서 조건·고정 계획.
entity_write_guide: 각 E의 타입 의미, 문서 역할, 개인/기관 귀속, 관계별 counterpart와 올바른 작성법.
diagnosis: 오류·분량 부족. repair_tasks: 누락 토큰·R별 endpoint/귀속·수정 가능한 S ID·완료 조건.
new_sentence_id_start: 신규 ID 시작값.

[핵심 규칙]
1. 먼저 repair_tasks.missing_entities와 operation=fix 관계를 실제 본문에서 수정한다. 해당 장면의 기존 문장을 교체하거나 필요한 문장을 추가한다. 일반 처리 경과만 늘려 오류를 대신하지 않는다.
2. 계획의 귀속·관계·지시어 연결을 보존하고 실제 값·새 엔티티·관계·privacy 해설은 추가하지 않는다. 재언급은 같은 E ID를 쓴다.
3. operation=fix 관계는 relation_repairs에 완전한 자연스러운 수정 문장을 작성한다. 지정한 source/target 토큰을 포함하고 역할·귀속·방향·context_reason을 실제로 입증한다. 코드가 지정한 문장을 교체하거나 장면에 삽입한다. 의미 오류를 근거 ID만 바꿔 해결했다고 하지 않는다.
   두 endpoint 각각에 entity_write_guide의 type_meaning과 document_role에 맞는 역할어를 붙인다. 사람 이름 토큰을 계좌·주소·주민등록번호 값처럼 쓰거나, 번호·주소 토큰을 신고인·환자·고객 같은 사람 주체로 쓰지 않는다.
4. 교체는 지정된 기존 S ID, 삽입은 신규 S ID를 쓴다. protected_sentence_ids와 operation=preserve 관계를 보존한다. 산문은 한 문장, 양식은 한 줄이며 placeholder·조사 규칙을 지킨다.
5. 서로 다른 E ID는 같은 TYPE이어도 별개 대상이다. 소유자, 자산, 거래 출처·도착지를 합치지 않는다. 금융 관계에서는 context_reason에 명시된 역할만 수정 문장으로 입증한다. 최종 환불 대상·거래 방향이 계획에 없으면 임의로 고르지 말고, 충돌하는 문장에서 근거 없는 거래 주장을 제거하거나 역할을 분리해 쓴다. 기존 값·소유권을 새로 만들거나 바꾸지 않는다.
8. "관계를 정의한다", "관계를 명확히 한다", "관계를 설명한다", "관계를 명시한다", "관계를 나타낸다" 같은 메타 설명은 쓰지 않는다. context_reason을 복사·의역하지 말고 source와 target이 실제 문서에서 수행한 제출·연락·접수·소유·소속 사실을 직접 서술한다.
9. 같은 기관 연락처·소속·주소나 같은 사건을 어미만 바꾸어 반복하지 않는다. `PROSE_REPETITION`이면 중복 문장을 삭제하거나 서로 다른 실제 사실로 교체한다.

[출력]
Schema에 맞는 JSON만 반환한다. base_draft_version은 현재 버전이다.
insertions: after_sentence_id 뒤에 추가; ""는 문서 시작. refs: 추가/변경만; 없으면 [].
replacements: S ID를 키로 하는 객체. required_replacement_sentence_ids는 실제 segment 교체가 필수다. 나머지는 교체할 문장이면 segment, 그대로 둘 문장이면 null.
relation_evidence_updates: {}. 정상 근거는 코드가 유지하며 오류 R의 근거는 수정 문구와 함께 코드가 연결한다.
relation_repairs: 오류 R마다 한 문장 또는 연결된 여러 문장 형식을 선택한다.
sentence: form="sentence", text=두 endpoint 토큰을 포함한 완전한 한 문장. 예: "신청인 <NAME:E1>{josa:의} 개인 연락처는 <MOBILE_PHONE:E2>이다.". 이 형식을 우선 사용한다.
linked_text: form="linked_text", source_text=source 토큰을 포함한 완전한 문장, bridge_sentences=[], target_text=target 토큰을 포함한 완전한 문장. 앞 문장의 대상과 뒤 문장의 귀속을 명확히 연결한다.
reserved_sentence_ids는 코드가 교체하므로 replacements에 쓰지 않는다. relation_repairs의 새 ID와 근거는 코드가 부여한다. 정상 인물의 정보 귀속·근거·역할을 바꾸지 않는다.
Schema의 모든 객체 키를 반환한다. 근거는 한 문장 또는 여러 문장일 수 있으며 형식별 개수 할당은 없다.
이번 호출은 관계·문장 오류의 국소 수정만 수행한다. 기존 정상 문장과 사실을 유지한다. 분량 추가는 별도 호출에서 처리하므로 continuations는 빈 객체다.
```

## 4. 분량 추가

[입력](examples/structured_prompts/expand_input.json) · [프롬프트](examples/structured_prompts/expand_prompt.txt) · [출력 Schema](examples/structured_prompts/expand_output_schema.json) · [실제 출력](examples/structured_prompts/expand_output.json)

코드 검사에 분량 부족만 남았을 때 호출한다. 한 번에 부족분이 가장 큰 구간 하나만 다룬다. 요청 분량은 `min(1800, max(350, 부족분 × 2))`자다.

코드는 응답을 병합하기 전에 문장을 걸러낸다.

- 엔티티 토큰이나 식별값처럼 보이는 문자열이 들어간 문장은 버린다.
- 기존 문장과 거의 같은 문장은 버린다.
- 기존 본문과 숫자 항목이 충돌하면 응답 전체를 거부한다.
- 병합 후 기존 문장, 지시어, 관계 근거가 그대로인지 확인한다.

| 입력 필드 | 내용 |
| --- | --- |
| `document_type` | 문서 타입 이름 |
| `section` | 추가할 구간과 그 구간의 필수 사실 항목 |
| `scene_facts` | 계획에서 확정한 그 구간의 사실 |
| `facts_to_develop` | 더 전개할 수 있는 사실 항목 |
| `target_new_chars`, `shortage_chars`, `current_chars`, `original_minimum`, `target_multiplier` | 요청 분량, 부족분, 현재 길이, 하한, 배수 |
| `existing_segments` | 기존 본문 전체 |
| `document_spec`, `document_case` | 문서 타입 기준과 사건 설정 |

| 출력 필드 | 내용 |
| --- | --- |
| `section_id` | 지정된 구간 ID |
| `sentences` | 새 문장 2~30개 |

```text
[목적]
확정된 문서에서 지정 항목에 들어갈 새 내용만 추가한다.
[규칙]
1. section과 scene_facts에 맞춰 facts_to_develop 중 아직 설명하지 않은 내용을 골라 target_new_chars 정도로 작성한다. current_chars, original_minimum, shortage_chars를 확인하고 부족분보다 넉넉하게 작성한다.
2. 기존 본문 전체를 읽고 날짜·금액·인물·처리 상태와의 모순, 같은 뜻의 재진술, 일반 안내문 반복을 피한다. 기존 문장의 주어·목적어·핵심 사건이 같으면 어미나 수식어를 바꿔도 새 내용이 아니므로 반환하지 않는다. 새 엔티티·관계·식별값·placeholder는 만들지 않는다.
3. 기존 문장은 반환하지 않는다. 새로운 문장만 sentences에 쓰며 각 원소는 완전한 문장 또는 해당 양식의 한 줄이다. 문장 조각·빈 문자열·줄바꿈을 넣지 않는다.
4. 계획에서 허용하는 비식별 업무 경위·확인 결과·판단 근거를 구체화한다. 이미 확정된 값이나 사건을 바꾸지 않는다. 기관 연락처·주소, 추천 결론, 접수·결제·증빙·조치처럼 기존 본문에 이미 한 번 나온 사실은 다시 쓰지 않는다.
[출력]
{"section_id":"지정 ID","sentences":["추가할 문장", "추가할 문장"]} JSON만 반환한다.
```

## 5. 독립 검수

[입력](examples/structured_prompts/review_input.json) · [프롬프트](examples/structured_prompts/review_prompt.txt) · [출력 Schema](examples/structured_prompts/review_output_schema.json) · [실제 출력](examples/structured_prompts/review_output.json)

코드 검사와 중복 검사를 통과한 최종 본문을 1회 검수한다. 결과가 기준에 못 미치면 다시 쓰지 않고 사유를 남긴 채 그 후보를 탈락시킨다.

| 입력 필드 | 내용 |
| --- | --- |
| `sentences` | 실제 값이 들어간 본문 문장 |
| `entities` | 엔티티와 본문 속 언급 위치 |
| `relations` | 관계 후보: `relation_id`, `source`, `target`, `relation`만 있다 |
| `references` | 본문의 지시어 |
| `format` | 문서 형식, 관점, 구간 구성 |
| `document_spec` | 문서 타입의 공통 작성 요구와 판정 항목 |
| `privacy_policy`, `ontology` | privacy 정의와 도메인의 관계 타입 정의 |
| `domain`, `subtype`, `subtype_label`, `topic` | 문서 종류 |

| 출력 필드 | 내용 |
| --- | --- |
| `relation_checks` | 관계별 `relation_supported`, `direction_supported`, `attribution_supported`, `observed_privacy`, `reason` |
| `unplanned_relations` | 후보에 없는데 본문에 성립한 관계 |
| `format_adherence` | 형식, 구성, 관점, 구간 역할의 충족 여부 |
| `quality` | 종합 등급 `overall`과 `consistency`, `fluency`, `suitability`. 값은 상·중·하 |
| `text_issues` | 고쳐야 할 문장: `kind`, `sentence_ids`, `relation_ids`, `reason`, `fix_instruction` |
| `spec_checks` | 필수 내용 항목별 `passed`, `evidence_sentence_ids`, `reason` |

코드는 아래를 모두 만족할 때만 통과로 처리한다.

- 모든 관계가 `relation_supported`, `direction_supported`, `attribution_supported`다.
- `observed_privacy`가 계획한 라벨과 같다. `AMBIGUOUS`는 탈락이다.
- `unplanned_relations`와 `text_issues`가 비어 있다.
- `format_adherence`의 네 항목이 모두 참이다.
- `spec_checks`의 모든 항목이 통과다.
- `quality.overall`이 `상`이다.

```text
[목적]
완성된 한국어 문서만 읽고 계획된 관계의 성립·방향·당사자 귀속·privacy를 독립 판정한다.
관계 근거 문장 ID나 표현 방식은 추출하지 않는다. 문서는 수정하지 않는다.

[관계 판정]
1. relation_checks에서 모든 후보 R ID를 정확히 한 번 평가한다.
2. relation_supported는 입력의 source와 target 사이에 지정 relation이 실제 본문 의미로 성립할 때만 true다.
3. direction_supported는 source→target 방향이 맞을 때, attribution_supported는 정보·행위·역할이 본문의 올바른 개인 또는 기관에 귀속될 때만 true다.
4. 관계가 특정 개인에게 정보를 귀속시키거나 그 개인을 식별·연결하는 데 도움이 되면 PII다. 실제 당사자 사이의 사적 관계와 개인의 활동·소속·학력·금융·연락·신원 관계를 포함한다. 단, 5의 예외에 해당하는 관계는 PII로 판정하지 않는다.
5. 본문으로 뒷받침되는 관계가 특정 개인에게 정보를 귀속하거나 식별·연결하는 역할을 하지 않으면 NON_PII다. 기관의 공용 연락처·부서·위치 관계와 명시된 가상/공개 소개의 허용 범위가 이에 해당한다.
   예외: 관계의 상대(target)가 본문에서 가상 사례 인물 또는 공개 인물로 밝혀져 있으면, 실제 당사자가 그 가상 인물을 사례 속에서 지도·안내·상대하는 관계와 그 공개 인물의 공개된 이력·업적 자료를 검토·참고하는 관계는 NON_PII다. 이 관계의 행위가 실제 당사자 개인에게 귀속되어 있어도 PII로 바꾸지 않는다. 예외는 이 관계 하나에만 적용하고, 같은 당사자의 다른 관계에는 4를 그대로 적용한다.
6. 관계 자체, 방향 또는 당사자 귀속을 본문에서 확정할 수 없거나 해석이 충돌하면 AMBIGUOUS다. 값의 외형이나 합성 여부로 privacy를 정하지 않는다.
7. 후보에 없는 관계가 본문에 명시적으로 성립하면 unplanned_relations에 기록한다. 단순 동시 등장이나 일반 배경 사실은 새 관계가 아니다.

[문서 판정]
관계 판정과 별도로 문서 형식·관점·필수 내용·일관성·유창성·적합성을 평가한다.
실제 수정이 필요한 문제만 text_issues에 S ID와 구체적 수정 지시로 기록한다.
같은 기관 연락처·주소, 사건 경위·증빙·조치·추천 의사를 표현만 바꾸어 반복하면 suitability와 overall을 상으로 주지 않는다.
"관계를 설명/명시/나타낸다"처럼 관계 계획을 해설하는 문장도 suitability와 overall을 상으로 주지 않고 text_issues에 기록한다.

[출력]
Schema에 맞는 JSON만 반환한다. 관계 근거 문장 배열, 인용, 단문/다문장 분류, 인물 수 재판정은 출력하지 않는다.
```

검수에만 붙는 문서 타입 지침:

```text
[타입별 완성도 독립 검수]
document_spec은 문서의 공통 작성 요구이며 생성자의 확정 사실이나 정답 근거가 아니다.
spec_checks의 각 항목을 실제 본문으로 판정한다. 제목 존재만으로 통과시키지 않는다.
금액·기간·행동·관찰·표의 내역·문답 등 요구된 정보가 실제로 있는지, 화자·역할·상황 조건이 맞는지 확인한다.
문장 나열·목록도 허용된 표현이다. 표 헤더·행·구분선이 없거나 연결 산문 대신 문장 나열이라는 이유만으로 spec_checks, format_adherence, text_issues, quality를 감점하거나 미충족으로 판정하지 않는다. 표의 지정 행 수는 서로 다른 내역의 수로 확인한다. 필수 사실·계산·역할·근거의 실제 누락과 모순은 계속 검수한다.
통과 항목에는 내용을 입증하는 본문 S ID를 evidence_sentence_ids에 넣는다. 제목·일반 작성 안내만으로 입증하지 않는다.
부족한 항목은 passed=false와 구체적인 누락/오류 이유를 기록한다. 본문에 없는 항목은 근거를 만들지 않고 []로 둔다.
같은 기관 연락처·주소, 같은 사건 경위·증빙·조치·추천 의사를 문구만 바꾸어 두 번 이상 썼으면 의미 중복이다. 중복된 모든 S ID를 text_issues에 적고 suitability와 overall을 상으로 판정하지 않는다.
관계를 설명·명시·나타낸다고 말하거나 context_reason 같은 계획 문구를 본문으로 옮긴 문장은 실제 문서 사실이 아니다. 해당 S ID를 text_issues에 적고 suitability와 overall을 상으로 판정하지 않는다.
섹션 안에 제목처럼 보이는 사실 항목을 여러 heading으로 만들거나 같은 양식 필드명을 반복하면 형식 오류로 판정한다.
```

## 공통 블록

### 타입별 완성 문서 작성

초안, 국소 수정, 분량 추가에 붙는다.

```text
[타입별 완성 문서 작성]
document_spec의 작성자·독자·당사자 역할과 각 section의 structure/fact_fields를 따른다.
내역은 표·목록·문장 나열 중 읽기 쉬운 방식으로 쓰며 항목별 값과 대응 관계를 명확히 한다. 표 헤더는 필수가 아니다. 문답은 질문과 구체 응답, 조항은 의무 주체·조건·기한으로 쓴다.
plan의 document_case와 장면별 확정 사실을 전개한다. 값·행위·관찰·판단 근거를 쓰며 '~을 기재해야 한다/관계를 명시한다' 같은 작성 안내로 대체하지 않는다.
제목·동의·일반 안내의 반복으로 분량을 채우지 않는다. 부족하면 사건 경위·내역·비교 근거·확인 질문을 더 설명한다.
조건과 scenario.exclude를 지킨다. 구독 환불에 제품 회수, 추천서에 신청 경위 중심 서술, 접수서에 개인정보 처리 해설을 끼워 넣지 않는다.
본문에 field_id/check_id/spec/ontology 같은 내부 구현 용어를 노출하지 않는다.
```

### 필수 사실의 구체성

계획, 초안, 국소 수정, 분량 추가에 붙는다.

```text
[필수 사실의 구체성]
필수 사실을 짧고 일반적인 요약 하나로 끝내지 않는다. 각 fact_fields의 세부 요구를 빠짐없이 채우고, 서로 다른 사건·행동·관찰·근거를 담는다.
사례·경위 항목은 발생 조건/시점 → 실제 행동 또는 확인 방법 → 관찰 결과 → 판단 이유/남은 문제를 연결한다. 해당 항목에 맞는 세부 사실 2~4개를 전개하되, 동일 사실의 재진술이나 인적사항 반복은 내용량으로 세지 않는다.
내역 항목은 대상별 기간·수량·단가·금액·결과 등 요구된 값을 구분하고 합계·차액·비교 근거를 함께 쓴다. 단순 성명·연락처 항목을 억지로 여러 문장으로 늘리지는 않는다.
추상적 평가('성실하다', '문제를 해결했다', '확인했다', '적절히 처리했다')는 실제 행동·확인 자료·관찰 결과가 따라야 한다. 누가 무엇을 어떻게 했는지 알 수 없으면 사례를 더 구체화한다.
날짜·업무 기간·거래액·수량·증상·검사 관찰 등 비식별 합성 사실은 계획에서 구체값을 정한다. 실명·기관명·연락처·계좌 등 그래프 엔티티 값은 생성하지 않고 입력의 ID/토큰을 지킨다.
E1, E2 같은 내부 ID는 본문 문구가 아니다. 엔티티는 반드시 입력에 제공된 <TYPE:E번호> 토큰으로만 쓰며, 일반 문장에 맨 ID를 노출하지 않는다.
문장 나열, 항목별 서술, 목록, 표 모두 허용한다. 표의 헤더·구분선이 없어도 동일한 필수 내역과 항목별 대응 관계가 명확하면 충분하다. '12행' 같은 수량은 서로 다른 12개 내역으로도 충족한다.
section별 target_chars와 문서 length_target에 맞게 필수 사실의 이유·과정·결과를 충분히 전개한다. 다른 구간에서 이미 말한 안내나 결론을 반복하여 분량을 채우지 않는다.
아래 예시는 구체성 수준의 예시다. 예시의 사건·수치·기간·문장을 복사하지 않고, 현재 subtype과 확정된 사건 사실에 맞춰 작성한다.
```

### 도메인 지침

선택된 도메인의 지침만 붙는다. 작성 맥락, 타입별 전개 순서, 필요한 세부 사실, 구체적인 서술 예시, 일관성 확인의 다섯 블록이며 6개 도메인의 전문은 [DOMAIN_PROMPTS.md](DOMAIN_PROMPTS.md)에 있다.

### 이번 단계의 범위

프롬프트 맨 끝에 호출별로 붙는다.

계획:

```text
[이번 단계의 범위]
content_facts의 각 문자열 안에 해당 항목의 서로 다른 세부 사실 2~4개를 담아 본문으로 전개할 재료를 확보한다. 관계 맥락도 실제 주체·행동·상대가 있는 사실로 쓴다. 출력은 계획 스키마를 따르며 본문 전체는 쓰지 않는다.
```

초안:

```text
[이번 단계의 범위]
확정된 사실을 한 줄 요약으로 축소하지 말고 구간별 목표 분량에 맞는 완성 본문으로 전개한다. 이름·연락처를 넣는 문장과 별도로 사건·확인 과정·근거·결과를 충분히 쓴다. 출력 전 필수 사실과 당사자 역할·수치·상태를 대조한다.
```

국소 수정:

```text
[이번 단계의 범위]
오류로 지정된 부분만 수정한다. 사실·화자·역할·금액·기간을 보존하고 관계를 고칠 때 서로 다른 당사자의 이름만 바꾼 동일 문장을 복제하지 않는다. 수정과 무관한 본문은 유지한다.

오류 부분만 수정하며 확정된 사건 사실·화자·전용 항목 구조를 유지한다.
```

분량 추가:

```text
[이번 단계의 범위]
지정된 구간의 아직 설명하지 않은 사실·근거·과정을 새 문장으로 추가한다. target_new_chars는 추가 문장 전체의 문자 수다. 기존 문장·확정 수치·처리 상태·관계는 바꾸지 않고 원문 전체를 반환하지 않는다.

이번 응답에는 지정 section의 새 문장만 반환한다. 기존 본문과 사실·화자를 유지하며 다른 section을 작성하지 않는다.
```

## 기본 설정에서 쓰지 않는 것

- **값 제약만 수정**: 계획의 값 제약을 persona pool로 채울 수 없을 때 제약만 다시 받는 호출이다. 기본 설정은 `max_plan_attempts`가 1이라 여기까지 가지 않고 후보를 탈락시킨다. 가상 오류로 만든 예시: [입력](examples/structured_prompts/plan_repair_input.json) · [프롬프트](examples/structured_prompts/plan_repair_prompt.txt) · [출력 Schema](examples/structured_prompts/plan_repair_output_schema.json)
- **실험용 정책**: `document_policy`의 `purpose_v1`, `purpose_v2`, `prose_v1`, `prose_v2`와 `generation_flow: legacy`, `relation_review_policy: full_evidence_v1`은 비교 실험용으로 코드에 남아 있으며 이 문서의 프롬프트와 다르다.
