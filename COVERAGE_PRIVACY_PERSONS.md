# privacy 정의, 인물 귀속, 관계 커버리지 — 2026-10-05

## privacy 정의

정의는 [relation_pipeline/privacy.py](relation_pipeline/privacy.py)에 하나만 있고(버전 3.1), 계획·초안·국소 수정·검수 호출에 같은 내용을 `privacy_policy`로 넣는다. 실행할 때 `runs/<run-id>/privacy_policy.json`에 정의와 hash를 남긴다.

| 라벨 | 기준 |
| --- | --- |
| `PII` | 특정 개인에게 식별자, 연락처, 주소, 소속, 학력, 금융정보, 활동 사실을 귀속하거나 개인을 식별·연결하는 관계. 개인 사이의 사적 관계도 포함한다 |
| `NON_PII` | 기관 공용 정보의 관계. 본문에서 가상 사례나 작품 인물이라고 밝힌 설정 관계와, 출처를 확인한 공개 약력 관계도 여기에 넣는다 |
| `AMBIGUOUS` | 본문 전체를 읽어도 귀속이나 역할을 정할 근거가 부족하거나 해석이 충돌한다. 채택하지 않는다 |

- 라벨은 관계 단위로 붙인다. 값의 모양이나 엔티티 타입만으로 정하지 않는다.
- 값이 모두 합성이라는 사실은 `NON_PII`의 근거가 아니다. 문서 속 신청인, 환자, 고객의 이름은 합성이어도 개인 맥락이다.
- 여러 문장을 이어 읽어야 관계가 드러난다는 이유만으로 `AMBIGUOUS`가 되지 않는다.
- 마스킹은 엔티티 단위다. PII 관계에 하나라도 참여한 엔티티는 모든 언급을 마스킹하고, 관계별 라벨은 그대로 보존한다.

## 인물 귀속

문서 타입마다 이름이 있는 주요 인물의 수와 역할이 정해져 있다. 이름 없는 일반 담당자는 세지 않는다.

| 문서 타입 | 인물 수 | 역할 |
| --- | --- | --- |
| 환불 요청 처리 기록 (`refund_request`) | 1 | `customer` |
| 송금·이체 신청서 (`wire_transfer`) | 2 | `sender`, `recipient` |
| 입원·수술 동의서 (`surgery_consent`) | 2 | `patient`, `guardian` |
| 추천서 (`recommendation`) | 2 | `candidate`, `recommender` |

78개 타입 전체는 `python3 -m relation_pipeline catalog`의 `person_count_range`와 `person_roles`에서 볼 수 있다.

계획에는 인물과 엔티티의 연결이 들어간다. 아래는 문진표 예시다.

```json
{
  "persons": [
    {"person_id": "P1", "name_entity_id": "E1", "role": "patient", "context_kind": "actual_party"}
  ],
  "person_entity_links": [
    {"person_id": "P1", "entity_id": "E1", "link_kind": "identity", "relation_ids": ["R1"]},
    {"person_id": "P1", "entity_id": "E2", "link_kind": "personal_attribute", "relation_ids": ["R1"]}
  ]
}
```

- 인물, 관계의 양 끝, 값 묶음은 코드가 정한다. 모델은 이 연결을 다시 쓰지 않는다.
- 한 사람의 개인 속성(이름, 생년월일, 연락처 등)은 같은 persona에서 값을 가져온다. 기관과 다른 인물을 한 persona로 묶지 않는다.
- 검수 모델에는 이 연결을 주지 않는다.
- 같은 엔티티를 몇 번, 어디에 쓰는지는 강제하지 않는다.

### 참고 인물

실제 당사자 외에 참고 인물 1명을 넣을 수 있다. 기본 설정(`reference_person_rate: 0.1`)에서는 해당 문서 타입에 확률 0.1로 등록된 인물 중 하나를 무작위로 넣고, `--reference-profile`로 직접 지정할 수도 있다. 관계 자리가 모자란 문서에는 넣지 않는다. 관계 커버리지용 필수 관계가 배정된 문서가 그런 경우다.

- 등록된 프로필은 3개다: 교재의 가상 학생(`fictional_student`), 창작 작품의 등장인물(`fictional_story_student`), 출처를 확인한 공개 교육 약력(`marie_curie_education`). 자료는 [assets/reference_people.json](assets/reference_people.json)에 있다.
- 경력·교육 도메인의 6개 타입(자기소개서, 경력기술서, 입사지원서, 추천서, 입학·편입 원서, 장학금 신청서)에서만 쓸 수 있다.
- 본문에서 가상 사례나 공개 소개임이 드러나야 `NON_PII`다. 같은 사람을 문서의 실제 당사자로 쓰거나 사적인 연락처, 금융정보를 붙이면 `PII`다.
- 기본 설정(`reference_link_policy: party_link_v1`)에서는 실제 당사자가 참고 인물을 인용하는 관계가 하나 더 들어간다. 아래 "한쪽만 마스킹되는 관계"에 설명한다.

## 한쪽만 마스킹되는 관계

PII 엔티티와 NON_PII 엔티티를 잇는 `NON_PII` 관계다. 기존 데이터셋에 있는 모양을 따랐다. 이 관계가 없는 문서에서는 사람 쪽(PII 관계)과 기관 쪽(NON_PII 관계)이 엔티티를 공유하지 않는다.

| 설정과 기본값 | 관계 | 마스킹 |
| --- | --- | --- |
| `organization_bridge_range: [0, 2]` | 당사자의 소속 기관 → 그 기관의 공용 정보 | 기관은 마스킹, 공용 정보는 비마스킹 |
| `reference_person_rate: 0.1`, `reference_link_policy: party_link_v1` | 실제 당사자의 이름 → 참고 인물의 이름 | 당사자는 마스킹, 참고 인물은 비마스킹 |

### 소속 기관의 공용 정보

```text
NAME ──PII──▶ WORKPLACE ──NON_PII──▶ TELEPHONE
```

- source는 개인 관계로 당사자에게 귀속된 `WORKPLACE`, `DEPARTMENT`, `SCHOOL`이다. 새 기관을 만들지 않고 그 엔티티를 다시 쓴다.
- target은 `TELEPHONE`, `EMAIL`, `ADDRESS`, `BANK_ACCOUNT_NUMBER` 중 하나다.
- 기관 이름은 당사자의 persona에서, 공용 정보는 다른 행에서 값을 가져온다. 기관의 대표번호가 당사자의 개인 번호와 같아지지 않는다.
- `organization_bridge_range`는 문서당 개수의 범위다. 당사자의 기관 정보가 없는 문서 타입이나 관계 수가 모자란 문서에서는 1단계가 개수를 줄이거나 0으로 둔다. 확정된 개수는 `condition.json`의 `organization_bridge_target`에 남고, 계획 검사가 그 개수를 확인한다.
- 만들 수 있는 문서 타입은 경력·교육 10개 전부, 계약 39개 중 34개, 금융 6개 중 2개, 의료 8개 중 2개다. 법률과 고객지원에는 없다.

### 당사자가 인용하는 참고 인물

```text
NAME(당사자) ──NON_PII──▶ NAME(참고 인물) ──NON_PII──▶ SCHOOL
```

- 참고 인물이 가상 예시 인물이면 `GUIDANCE_SUPPORT`, 공개 인물이면 `INFORMATION_GOVERNANCE` 관계를 쓴다.
- 이 관계에 한해 "실제 당사자의 이름에는 NON_PII 관계를 붙이지 않는다"는 계획 검사를 통과시킨다. 다른 관계 타입이나 `PII` 라벨로 바꾸면 거부된다.
- 당사자의 이름은 다른 PII 관계가 있으므로 그대로 마스킹된다.
- 검수 프롬프트에는 이 관계를 `NON_PII`로 판정하는 예외가 들어 있다. 예외는 이 관계 하나에만 적용되고, 같은 당사자의 다른 관계는 그대로 `PII`로 판정한다.

두 관계는 NON_PII 관계 자리를 하나씩 쓴다. 자리가 모자라면 소속 기관 관계가 먼저 빠진다.

계획 요청에는 이 관계들의 확정 사실을 비우지 않고 넣는다. 예를 들어 소속 기관의 전화는 "당사자가 소속된 기관이 이 번호를 기관 대표 문의 창구로 공동 운영한다"로 들어간다. 작성 안내에는 공용 정보를 당사자 본인의 연락처, 주소, 계좌 항목에 쓰지 않는다는 규칙이 붙는다.

실제 API 시험 결과는 [EXPERIMENTS.md](EXPERIMENTS.md#5-한쪽만-마스킹되는-관계-2026-10-05)에 있다. 가상 예시 인물 관계가 들어간 문서 1건이 채택됐고, 소속 기관 관계와 공개 인물 관계가 들어간 문서는 아직 채택되지 않았다.

끄려면 `organization_bridge_range`를 `[0, 0]`, `reference_person_rate`를 `0`으로 둔다.

## 관계 커버리지

[assets/ontology.json](assets/ontology.json)에 있는 관계 타입 19개가 대상이다.

- 세는 것은 8단계에서 채택된 문서의 `relations` 행이다. 계획이나 초안에 나온 것은 세지 않는다.
- 기본 요구는 타입마다 1건 이상이다. 타입마다 PII와 NON_PII가 각각 있어야 하는 것은 아니다.
- `manifest.json`의 `complete`는 도메인별 수량(`quota_complete`)과 커버리지(`coverage_complete`)가 모두 충족될 때 참이다.

부족한 타입을 채우는 방법은 두 가지다.

1. 1단계에서 아직 채택되지 않은 타입 중 그 문서 타입에 넣을 수 있는 것을 문서당 최대 1개 지정한다.
2. 기본 slot을 모두 처리한 뒤에도 빠진 타입이 있으면 그 타입을 지정한 보충 slot을 최대 38개 만든다. 보충 문서도 같은 검수를 통과해야 한다.

일부 도메인만 골라 실행해도 19개 요구는 줄어들지 않는다. 선택한 도메인에서 만들 수 없는 타입은 `coverage_preflight.json`의 `unreachable_types`에 기록되고, 그 실행은 `incomplete`로 남는다. `relation_coverage.enabled`를 `false`로 두면 커버리지 요구 없이 수량만으로 완료를 판단한다.

### 관계 후보

6개 문서 타입(추천서, 용역계약서, 명의도용·보이스피싱 신고서, 분쟁 조정 신청서, 진료 접수서, 환불 요청 처리 기록)에는 문서 목적과 인물 역할에 맞는 관계 후보를 따로 정의해 두었다. 나머지 72개 타입은 도메인 공통 후보를 쓴다. 어느 쪽이 적용됐는지는 `condition.json`의 `graph_profile_applied`에 남는다.

## 통계 파일

| 파일 | 내용 |
| --- | --- |
| `statistics/relation_coverage.csv` | 관계 타입별 채택 수 |
| `statistics/accepted_relations.csv` | 채택 문서의 관계 행 |
| `statistics/persons.csv` | 계획한 인물과 역할 |
