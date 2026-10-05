# 현재 파이프라인 — 2026-10-04

최초 완성 초안을 한 번 생성하고, 오류가 있으면 기존 문서를 수정한다. 검수만 `gpt-5-mini`, 계획 맥락·초안·수정은 `gpt-4o-mini`다. 공통 privacy 정의와 이름 있는 인물의 수·역할·정보 귀속을 사용한다. 반복 횟수·문서 내 위치·문장 간 근거 방식별 개수는 강제하지 않는다.

현재 기본 `generation_flow=separated_v1`에서는 5단계의 국소 수정(최대 1회)과 분량 추가(최대 2회)를 분리한다. 추가 호출은 한 section의 새 문장 목록만 반환하고 기존 문장·지시어·근거를 유지한다. 7단계는 최종 본문을 1회 검수하며, 의미·품질 실패는 탈락 처리한다. 모든 단계가 공유하는 응답/네트워크 재시도는 문서당 1회다. 신규 문서는 정상 3~6회·절대 최대 7회, 기존 초안 재사용은 정상 최대 4회·절대 최대 5회다. 아래의 검수 후 복구 루프와 조각 결합 설명은 과거 `legacy` 흐름에 해당하며, 현재 입출력 차이는 [PROMPTS.md](PROMPTS.md) 첫 표에 정리했다.

후속 변경: privacy 3.0은 선택한 가상 예시·작품 인물·출처 확인 공개 약력을 실제 당사자와 구분한다. 1단계에서 reference_profile을 선택하고, 2단계에서 별도 인물/관계를 연결하며, 3단계에서 등록된 값과 출처를 고정한다. 7단계는 실제 본문의 맥락을 독립 판단하고 선택한 근거 S ID만 출력한다. 코드는 원문 인용을 연결한다. 8단계 증강 JSON 형식은 유지하고 출처는 audit에 보존한다. 생성 기본값은 legacy이며, 구체적 story와 간단한 본문 출력을 쓰는 prose_v1/prose_v2는 합격 개선 미확인으로 실험용이다.

| 단계 / 실행 | Input | Output | 검사·다음 동작 |
| --- | --- | --- | --- |
| 0 준비 / 코드 | config, 6개 도메인 catalog, 19종 ontology, persona pool, 선택 옵션 | run_config, slots, privacy_policy와 hash, person_catalog, coverage_preflight, SQLite | 자원/설정 고정. 선택한 도메인에서 불가능한 관계도 명시하며 전체 요구 목록은 유지 |
| 1 조건 / 코드 | slot의 domain/subtype, 형식별 채택 현황, 최종 관계별 채택 현황 | condition: format/variant/topic/관점, section별 분량, 길이, 관계 4–6개와 NON_PII 목표, n_parties/person_slots, required_relation_types, graph_profile_applied | subtype에 맞는 인물 수·역할 및 부족한 관계 선정. 기본 NON_PII 목표 비율 35–55%. 검증한 6개 subtype은 시나리오별 관계 후보를 사용 |
| 2 관계 계획 / 코드 + 4o mini | condition, 허용 triple, 공통 정의, 코드가 만든 고정 그래프, 사용된 관계의 ontology | 모델: relation_contexts/scene_notes. 코드: 최종 plan의 entities/relations/scenes/slot_constraints/persons/person_entity_links/context_reason/fingerprint | 시나리오 프로필이 있으면 subtype·인물 역할에 맞는 관계 방향을 코드가 먼저 선택. 인물·endpoint·값 그룹은 코드가 유지. 모델은 구체적 귀속·사용 목적과 장면 설명 작성. 계획 및 조기 중복 검사, 값 공급 가능성 검사 |
| 3 값 공급 / 코드 | 검사한 plan, persona pool, 인물 귀속/값 제약 | value_map: E별 고정 value/canonical/source_uuid/constraint_group | 명확한 개인 속성은 해당 인물의 같은 persona에서 공급. 기관과 상대 인물을 무조건 하나로 합치지 않음 |
| 4 완성 초안 / 4o mini | 압축한 condition/plan, privacy_policy, placeholder_map, R별 작성 슬롯 | draft: draft_version, segments, refs, relation_evidence | 모든 section·엔티티·관계가 있는 전체 초안 1회. 실제 값 대신 정확한 TYPE:E 토큰 |
| 5 조립·수정 / 코드, 필요시 4o mini | draft, plan, value_map, 구조/길이 진단 또는 검수의 구체적 오류 | assembled, diagnosis, 필요한 경우 patch와 progress, 새 draft revision | 조사는 코드 정규화. 누락/관계 오류는 실제 문장 수정; 부족 분량은 기존 section 이어쓰기. 정상 근거 유지. 최대 2회 patch |
| 6 치환·내용/구조 중복 / 코드 | assembled, value_map, 채택 registry | filled의 실제 문장·mention/span·reference, diversity_check | 타입 토큰 정규화 본문 4-gram Jaccard 0.55, 실제 구조 fingerprint 반복 제한. 통과 후 검수 |
| 7 독립 검수 / 5 mini + 코드 | 실제 본문·mention/span·지시어, 정답 privacy 없는 R, 형식·변형·관점, 공통 정의, 인물 수·역할 vocabulary | relation_checks, reference_checks, person_checks, text_issues, 추가 관계/미등록 값/모순, format_adherence, 상중하 quality와 최소 근거/인용 | 관찰 라벨·역할·근거를 계획과 비교. 오류의 S/R ID·수정 지시를 5단계로 전달. 수정 후 같은 본문을 재검수 |
| 8 최종 채택 / 코드 | 통과한 filled/plan/review/checks, registry | 증강 document, audit, accepted_relations 집계, manifest, statistics JSON/CSV | commit 시 중복 재확인. 최종 span/BIO 검사. 기본 수량과 19종 최소 채택 수를 모두 충족해야 complete |

5단계의 endpoint 동시 출현 검사는 구조 검사다. 실제 관계 의미는 7단계가 판정한다. 계획 유사도는 정확한 fingerprint의 반복 상한을 사용하며 연속 점수는 기록한다. 내용·구조 중복은 검수 호출 전에 검사한다.

## 짧은 인물 귀속 예시

금융 `wire_transfer` 조건은 이름 있는 인물 2명이다. `P1/E1=sender`, `P2/E2=recipient`를 계획하고 각자의 NAME·개인 계좌·관련 기관을 연결한다. 예컨대 R1의 E3이 송금인의 계좌라면 모델은 다음처럼 문서를 쓸 수 있다.

```text
송금인 <NAME:E1>{josa:은/는} 출금 계좌로 <BANK_ACCOUNT_NUMBER:E3>{josa:을/를} 지정했다.
수취인 <NAME:E2>{josa:의} 입금 계좌는 <BANK_ACCOUNT_NUMBER:E4>이다.
<WORKPLACE:E5>{josa:은/는} <EMAIL:E6>{josa:을/를} 부서 직원이 공동 운영하는 문의 창구로 안내했다.
```

첫 두 관계는 개인 귀속이므로 PII이고 기관 공용 메일 관계는 NON_PII다. 이것은 정의 설명용 일부 문장으로 완성 계획이나 실제 합격 데이터가 아니다. 본문은 자연스럽게 다시 언급할 수 있으며 반복 개수·위치는 조건에 없다.

검수는 계획의 정답 귀속 연결을 받지 않고 E별 관찰 역할과 R별 관찰 privacy를 보고한다. `E3을 수취인 계좌라고 설명했다`면 S/R ID와 수정 지시를 반환하고 해당 부분을 수정한다. 단순 누락 보충과 관계 의미 수정은 별도로 검사한다.

## 최종 Output

최종 document의 루트는 기존 증강 형태 `sentences, entities, relations`다. 실제 문장과 모든 entity mention, PII 마스킹·BIO, 관계의 source/target·privacy_label을 저장한다. 인물 연결 계획·독립 관찰·정의 hash·19종 커버리지는 plan/audit/statistics에 둔다.

완료는 최종 채택 기준이다. 1단계 배정이나 7단계 응답만으로 관계 채택 수를 늘리지 않는다. 기본 slot 처리 후 부족한 관계에는 보충 slot을 만들며, 예산이나 상한 때문에 남은 관계가 있으면 manifest는 incomplete와 missing_types를 유지한다.

## 통과 기준과 호출 상한

관계가 추출되고 방향·지시어·privacy·인물 역할이 일치하며, 정확한 인용과 최소 근거가 있어야 한다. 해결되지 않은 AMBIGUOUS, 계획 밖 관계, 미등록 엔티티, 사실 모순, 실제 수정이 필요한 text_issues는 복구 대상으로 보낸다.

품질은 overall/consistency/suitability가 상, fluency가 상 또는 중이어야 한다. 응답 형식 오류는 검수 응답 재시도, 본문 의미 오류는 본문 patch 후 재검수다. 정상 경로 3회, 최초 초안 1회와 최대 2회 수정, 후보당 요청 상한 7회다. 시도·후보·실행 전체 예산은 config에 있으며 상한 이후 탈락 이유와 등급을 보존한다.

현재 프롬프트 입력·전문·명확한 출력 Schema는 [PROMPTS.md](PROMPTS.md), 19종/인물/정의와 조회 방법은 [COVERAGE_PRIVACY_PERSONS.md](COVERAGE_PRIVACY_PERSONS.md)에서 확인한다. 과거 데이터 흐름과 시험은 [PIPELINE_FLOW_20261003.md](PIPELINE_FLOW_20261003.md)에 보존했다.
