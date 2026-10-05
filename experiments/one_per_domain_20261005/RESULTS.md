# 도메인별 채택 문서 생성 결과

- 실행일: 2026-10-05 (Asia/Seoul)
- 결과: 6개 도메인 모두 1개씩 채택
- 설정: 문서당 관계 3개, 기존 품질·개인정보·관계 검증 기준 유지
- 재검증: `relation_pipeline validate` 기준 6개 문서 모두 통과

| 도메인 | 문서 타입 | 채택 후보 | 해당 성공 실행 내 탈락 수 | 문장 | 엔티티 | 관계 | PII 언급 | 문서 |
|---|---|---:|---:|---:|---:|---:|---:|---|
| 고객지원 | refund_request | support_001_c015 | 14 | 54 | 5 | 3 | 2 | [JSON](../../output/one_support_20261005_v1/dataset/support/one_support_20261005_v1_support_001.json) |
| 금융 | fraud_report | financial_001_c005 | 4 | 37 | 5 | 3 | 2 | [JSON](../../output/one_financial_20261005_v1/dataset/financial/one_financial_20261005_v1_financial_001.json) |
| 의료 | questionnaire | medical_001_c001 | 0 | 45 | 6 | 3 | 2 | [JSON](../../output/one_medical_questionnaire_20261005_v1/dataset/medical/one_medical_questionnaire_20261005_v1_medical_001.json) |
| 계약 | service | contract_001_c009 | 8 | 53 | 5 | 3 | 2 | [JSON](../../output/one_contract_20261005_v1/dataset/contract/one_contract_20261005_v1_contract_001.json) |
| 법률 | legal_consultation | legal_001_c010 | 9 | 31 | 6 | 3 | 2 | [JSON](../../output/one_legal_consultation_20261005_v1/dataset/legal/one_legal_consultation_20261005_v1_legal_001.json) |
| 경력·교육 | resume_form | career_education_001_c012 | 11 | 35 | 5 | 3 | 2 | [JSON](../../output/one_career_resume_20261005_v1/dataset/career_education/one_career_resume_20261005_v1_career_education_001.json) |

## 검증 명령

각 실행에 대해 아래 명령을 수행했고 모두 종료 코드 0 및 `passed: true`를 반환했다.

```bash
.venv/bin/python -m relation_pipeline validate --run-id <run_id>
```

성공 실행의 후보 집계는 채택 6개, 탈락 46개다. 문서 타입 전환 전에 소진한 실패 실행은 이 집계에서 제외했다.
