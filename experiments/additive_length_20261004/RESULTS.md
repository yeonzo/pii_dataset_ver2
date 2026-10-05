# 지정 프로젝트의 분량 추가 방식 반영 및 실제 검증

대상: `/home/upsecurity00/data/members/yeonju/relation_document_pipeline`.
6개 도메인만 사용하며 기존 초안과 계획·치환 값을 재사용했다. 새 계획·초안 API 호출은 0회다.

## 반영 내용

- 원본 Git의 78개 타입별 목표 범위와 `max(1500, int(목표×0.75))` 하한 유지. 상한 추가 없음.
- `content_depth.py`: 78개 타입에 구체적으로 더 쓸 사실·경위·계산·확인 근거를 정의.
- `condition.content_depth`: 공통 작성 지침과 타입별 내용을 전달. 추가 글자수는 기존 `continuation_targets`에서 배분.
- 분량만 부족하면 `length_mode=append_only`: 기존 문장, refs, 관계 근거를 바꾸는 출력 채널을 스키마에서 차단.
- patch 적용에서도 교체·refs 변경·근거 변경·빈 추가·기존 segment의 정확한 복사를 거절. 새 본문만 기존 section에 삽입.
- 보충 시 전체 원문을 전달. 다른 오류가 함께 있으면 그 부분은 국소 수정하고 분량은 continuations로 추가.

## 검증 결과

오프라인 테스트 **128개 통과**. 이 중 신규 4개는 78개 타입 대응, 원문 보존, 재작성/복사 차단, 전체 원문과 부족 분량 전달을 확인한다.
타입별 목표 길이 범위 78개 모두 원본 Git `deaa2f6`의 값과 대조해 일치했다.

실제 API는 GPT-4o-mini 보충·수정 10회, GPT-5-mini 심사 10회로 총 20회 호출했다.
**최종 채택 0/6, 최종 분량 충족 3/6.** 금융은 원래 분량을 충족했고, 의료와 계약이 보충 후 새로 하한을 충족했다.
아래 숫자는 이 프로젝트의 실제 PII 치환 후 `rendered_chars`다. 모든 링크는 탈락 문서이며 통과 문서로 사용할 수 없다.

| 도메인 | 타입·최종 탈락 원문 | 보충 전 → 최종 글자수 | 하한 | 최종 탈락 사유 |
|---|---|---:|---:|---|
| support | [환불 요청 처리 기록](../../runs/additive_length_20261004_v1/candidates/support_001_c001/final_document.txt) | 1090 → 1090 | 1500 | 보충 응답 출력 한도 초과 |
| financial | [명의도용·보이스피싱 신고서](../../runs/additive_length_20261004_v1/candidates/financial_001_c001/final_document.txt) | 2686 → 3162 | 1558 | 관계 의미·근거·자연스러움 실패 |
| legal | [분쟁 조정 신청서](../../runs/additive_length_20261004_v1/candidates/legal_001_c001/final_document.txt) | 1007 → 1809 | 1848 | 하한 39자 부족; 후속 보충 응답 출력 한도 초과 |
| medical | [진료 접수서](../../runs/additive_length_20261004_v1/candidates/medical_001_c001/final_document.txt) | 696 → 2805 | 1533 | 관계 의미·일관성·형식·인용 근거 실패 |
| contract | [용역계약서](../../runs/additive_length_20261004_v1/candidates/contract_001_c001/final_document.txt) | 1557 → 2451 | 1658 | 일관성·관계 근거·인용 근거 실패 |
| career_education | [추천서](../../runs/additive_length_20261004_v1/candidates/career_education_001_c001/final_document.txt) | 231 → 231 | 1500 | 보충 응답 출력 한도 초과 |

경력·교육 초안은 코드 진단상 분량만 부족했다. 그러나 보충 API가 10,000 출력 토큰 한도에서 incomplete로 종료하여 완성된 추가 응답을 받지 못했다.
따라서 원문 보존은 회귀 테스트로 확인했으며, 이 표본의 실제 API에서 append_only 성공을 확인했다고 주장하지 않는다.
코드 통과나 분량 충족을 최종 품질 합격으로 간주하지 않았다. 6개 기존 초안을 재사용한 소규모 검증이므로 전체 타입의 품질 개선율은 알 수 없다.

## 실행 기록

- [시도별 결과·탈락 사유·원문 해시·호출 내역](../../runs/additive_length_20261004_v1/additive_length_report.json)
- [고정 실행 설정](../../runs/additive_length_20261004_v1/run_config.json)
- `runs/additive_length_20261004_v1/candidates/*/repairs/`: 타입별 보충 요청, patch와 전후 분량
- `draft_versions/`: 기존 및 수정 버전. 원본 실험 디렉터리는 변경하지 않음.
- `source_before/`: 이번 변경 전 대상 프로젝트 소스 사본

재실행은 새 run ID로 `python -B -m experiments.verify_additive_length --run-id <새ID>`를 사용한다.
최대 후보 6개, 후보당 복구 2회, 전체 공급자 요청 36회와 설정상 비용 예산 1달러로 제한한다.
