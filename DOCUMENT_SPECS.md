# 타입별 문서 작성 계약

정의 버전: `type_specs_v1`. 원본 Git 기준: `deaa2f6403a22253c9ebc70fe9ead5563d5257bd`.

실행 정의는 `relation_pipeline/spec_definitions.py`, 상황 선택·프롬프트·검수 연결은 `relation_pipeline/document_specs.py`에 있다. 이 문서는 실행 정의에서 자동 생성했다.

공통 규칙 → 도메인 지침 → subtype 전용 항목·화자 → 선택 상황 → 항목별 확정 사실 순서로 요청을 구성한다. 필수 사실은 계획의 `content_facts`에 채우고, 독립 검수는 실제 본문의 근거 문장으로 `spec_checks`를 판정한다.

[도메인별 생성 프롬프트 전문](DOMAIN_PROMPTS.md)은 작성 맥락·타입별 전개 순서·세부 사실·서술 예시·일관성 확인으로 구성한다. 문장 나열과 목록을 허용하며 표 모양이 아닌 실제 필수 내용으로 검수한다.

분량은 원본 subtype 범위와 `max(1500, int(length_target * .75))` 하한을 유지하며 전체 상한은 두지 않는다. 부족한 분량은 원문을 보존한 추가 방식으로 처리한다. 새로운 LLM 호출 단계는 추가하지 않는다.

각 정의는 합성 문서의 작성·평가 기준이다. 아래 내용이 실제 법률·의료·금융 서식의 적법성이나 임상적 타당성을 보증하지 않는다.

| 도메인 | 타입 수 | 전체 정의 |
| --- | ---: | --- |
| career_education | 10 | [career_education.md](docs/document_specs/career_education.md) |
| contract | 39 | [contract.md](docs/document_specs/contract.md) |
| financial | 6 | [financial.md](docs/document_specs/financial.md) |
| legal | 7 | [legal.md](docs/document_specs/legal.md) |
| medical | 8 | [medical.md](docs/document_specs/medical.md) |
| support | 8 | [support.md](docs/document_specs/support.md) |

## 적용 경로

1. 조건 선정: 타입별 작성자·독자·역할·전용 항목을 고정하고 상황을 선택한다. 명시적인 `--topic`은 유지하며 `--scenario`로 지원되는 상황을 지정할 수 있다.
2. 계획: 하나의 사건과 조건별 적용 여부·종료 상태를 확정하고 항목마다 필수 사실을 채운다. 작성 지시만 들어간 사실은 초안 생성 전에 거부한다.
3. 초안·국소 수정: 동일한 정의와 확정 사실을 사용한다. 원문 전체 재생성 없이 오류 부분만 수정한다.
4. 분량 추가: 선택한 항목의 필수 사실과 확정 상황 안에서 새 내용만 추가한다.
5. 독립 검수: 생성자의 사실 계획·정답 역할 연결은 제공하지 않는다. 공통 작성 요구와 본문만으로 각 완성 기준을 확인하고 실제 근거 문장 ID를 남긴다. 제목만 있거나 정보가 빠졌으면 탈락한다.

## 실행

```bash
python -m relation_pipeline catalog --specs --domain medical
python -m relation_pipeline run --run-id specs_NEW_ID --domain support --subtype refund_request --scenario subscription --max-candidates 1 --target-per-domain 1
```

기본 설정은 `spec_policy: type_specs_v1`이다. 전용 형식의 variant는 `type_spec`이며 기존 범용 variant를 지정하려면 별도 설정의 `spec_policy: legacy`를 사용한다. 이전 run에 이 키가 없으면 기존 경로를 유지한다. `resume` 도메인은 포함하지 않는다.

재생성: `python -m experiments.export_document_specs`. 전체 기계 판독 정의: [catalog.json](docs/document_specs/catalog.json).
