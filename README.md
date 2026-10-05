# 관계 계획 기반 PII 문서 생성 파이프라인

한국어 업무 문서를 합성하고, 문서에 등장하는 엔티티 관계마다 `PII` / `NON_PII` 라벨을 붙인 데이터셋을 만드는 코드입니다.

같은 모양의 값이라도 문서 안에서 누구에게 귀속되느냐에 따라 개인정보 여부가 달라집니다.

| 문장 | 관계 | 라벨 |
| --- | --- | --- |
| 신청인이 자신의 연락처로 유선 번호를 기재했다. | 이름 → 전화번호 | `PII` |
| 고객지원 부서가 휴대폰 형식의 번호를 공동 문의 창구로 운영한다. | 기관 → 전화번호 | `NON_PII` |

이 파이프라인은 이런 관계를 먼저 그래프로 계획하고, 그 계획대로 문서를 쓴 뒤, 다른 모델이 본문만 읽고도 같은 판단에 도달한 문서만 채택합니다.

## 한눈에 보기

| 항목 | 내용 |
| --- | --- |
| 도메인 | 6개: `career_education`, `contract`, `financial`, `legal`, `medical`, `support` |
| 문서 타입 | 78개 (이력서, 임대차 계약서, 송금 신청서, 환불 요청 등) |
| 엔티티 타입 | 18개 (`NAME`, `ADDRESS`, `MOBILE_PHONE`, `RRN`, `BANK_ACCOUNT_NUMBER` 등) |
| 관계 타입 | 19개 (`CONTACT_ASSOCIATION`, `FINANCIAL_TRANSACTION` 등) |
| 생성 모델 | `gpt-4o-mini` (계획, 초안, 수정, 분량 추가) |
| 검수 모델 | `gpt-5-mini` (독립 검수) |
| 기본 목표 | 도메인당 50건, 총 300건. 19개 관계 타입이 각각 1건 이상 채택되어야 완료 |
| 의존성 | Python 3.10 이상. 외부 라이브러리 없음 |

## 설계 원칙

1. **라벨은 값이 아니라 관계로 정한다.** 전화번호처럼 보인다는 이유로 PII가 되지 않습니다. 본문에서 특정 개인에게 귀속되면 `PII`, 기관 공용 정보이면 `NON_PII`입니다. 정의 전문은 [relation_pipeline/privacy.py](relation_pipeline/privacy.py)에 있습니다.
2. **생성 모델은 실제 값을 보지 않는다.** 모델은 `<NAME:E1>` 같은 placeholder로 문서를 쓰고, 실제 이름과 번호는 코드가 persona pool에서 뽑아 나중에 치환합니다.
3. **검수 모델은 정답을 보지 않는다.** 검수 모델은 계획한 라벨을 받지 않고 본문만으로 각 관계의 성립 여부와 privacy를 판정합니다. 계획과 다르거나 판단이 모호하면 그 문서는 탈락합니다.
4. **채택된 문서만 센다.** 후보를 처리한 수가 아니라 검수와 최종 검증을 통과한 문서 수가 기준입니다.

## 파이프라인 흐름

```text
0 준비 → 1 조건 → 2 계획 → 3 값 → 4 초안 → 5 검사·수정 → 6 치환·중복 → 7 독립 검수 → 8 채택
```

| 단계 | 실행 주체 | 하는 일 |
| --- | --- | --- |
| 0 준비 | 코드 | 설정, 자원, 코드의 hash를 고정하고 도메인별 slot을 만든다 |
| 1 조건 | 코드 | slot마다 문서 타입, 주제, 관점, 목표 길이, 관계 수와 PII/NON_PII 배분, 등장 인물 역할을 정한다 |
| 2 계획 | 코드 + `gpt-4o-mini` | 코드가 엔티티와 관계 그래프를 만들고, 모델이 관계별 맥락과 구간별 구체 사실을 채운다 |
| 3 값 | 코드 | persona pool에서 엔티티별 실제 값을 뽑아 고정한다. 한 사람의 속성은 같은 persona에서 가져온다 |
| 4 초안 | `gpt-4o-mini` | placeholder로 된 완성 문서를 1회 작성한다 |
| 5 검사·수정 | 코드 + `gpt-4o-mini` | 초안을 코드로 검사한다. 오류는 해당 문장만 고치고, 부족한 분량은 한 구간씩 문장을 추가한다 |
| 6 치환·중복 | 코드 | placeholder를 실제 값으로 바꾸고, 이미 채택된 문서와 내용이 겹치면 탈락시킨다 |
| 7 독립 검수 | `gpt-5-mini` + 코드 | 본문만으로 관계 성립, 방향, 귀속, privacy, 타입별 필수 내용, 품질을 판정한다 |
| 8 채택 | 코드 | 최종 스키마로 변환하고 span과 BIO 라벨을 검증한 뒤 저장한다 |

### 단계별 입력과 출력

1~7단계의 출력은 `runs/<run-id>/candidates/<candidate-id>/`에 파일로 남습니다.

| 단계 | 입력 | 출력 |
| --- | --- | --- |
| 0 준비 | `config.json`, 문서 타입 catalog, 관계 ontology, persona pool, 명령 옵션 | `run_config.json`: 고정된 설정과 자원 hash. slot 목록과 privacy 정의 사본 |
| 1 조건 | slot의 도메인과 문서 타입, 지금까지의 채택 현황 | `condition.json`: 주제, 관점, 구간 구성, 목표 길이와 하한, 관계 수와 PII/NON_PII 목표 수, 인물 역할, 문서 타입 기준 |
| 2 계획 | `condition`, 코드가 만든 그래프, 관계 정의, privacy 정의 | `plan.json`: 엔티티(`E1…`), 관계(`R1…`)의 양 끝과 타입, 목표 라벨(`target_privacy`), 맥락(`context_reason`), 장면(`SC1…`)별 사실, 인물과 엔티티의 연결 |
| 3 값 | `plan`, persona pool | `value_map.json`: 엔티티별 실제 값과 출처 persona |
| 4 초안 | `condition`, 값이 없는 `plan`, 엔티티별 작성 안내, placeholder 목록 | `draft_versions/draft_v1.json`: 문장 목록(`segments`), 지시어(`refs`), 관계별 근거 문장(`relation_evidence`) |
| 5 검사·수정 | 초안, `plan`, `value_map` | `diagnoses/`: 오류 목록과 분량. `repairs/`, `additions/`: 수정과 추가 내역. `assembled.json`: 코드 검사를 통과한 초안 |
| 6 치환·중복 | `assembled`, `value_map`, 채택된 문서 목록, 기존 corpus | `filled.json`: 실제 문장과 엔티티 언급 위치. `diversity_check.json`: 중복 검사 결과 |
| 7 독립 검수 | `filled`의 본문과 엔티티, 라벨을 뺀 관계 목록, 형식 조건, 문서 타입 기준 | `review.json`: 모델의 판정(`review`)과 코드가 계산한 통과 여부(`checks`) |
| 8 채택 | 검수를 통과한 `filled`, `plan`, `review` | `output/<run-id>/dataset/`의 최종 문서, `audits/`의 감사 기록 |

코드 검사의 기준은 다음과 같습니다.

- **5단계**: 구간과 문장 구조, 모든 엔티티의 실제 언급, 관계 양 끝 엔티티의 근거 문장, placeholder 형식, 문장 반복, 최소 분량을 봅니다. 구조만 확인하며 관계의 의미가 맞는지는 7단계가 판정합니다.
- **6단계**: 엔티티 값을 타입으로 바꾼 본문끼리 문자 4-gram Jaccard를 계산해 0.55 이상이면 내용 중복으로 탈락시킵니다. 비교 대상은 이미 채택된 문서와 기존 corpus입니다. 구조 반복 검사는 기본 설정에서 모든 문서 타입이 고정 서식이라 적용되지 않습니다.
- **분량**: 하한은 `max(1500, 목표 길이 × 0.75)`자이며 상한은 없습니다.

### 채택 기준

7단계 검수에서 아래를 모두 만족해야 합니다. 하나라도 어긋나면 사유를 기록하고 그 후보를 탈락시킵니다.

- 계획한 모든 관계가 본문에서 성립하고, 방향과 당사자 귀속이 맞다.
- 검수 모델이 관찰한 privacy가 계획한 라벨과 같다. `AMBIGUOUS` 판정은 탈락이다.
- 계획에 없는 관계가 본문에 새로 생기지 않았다.
- 문서 타입별 필수 내용이 빠지지 않았다.
- 문서 형식과 관점이 조건과 맞고, 수정이 필요한 문장 오류가 없다.
- 종합 품질 등급이 `상`이다.

### 호출 상한

문서 하나(후보 1건)에 쓰는 모델 호출 수는 코드로 제한합니다.

| 호출 | 상한 |
| --- | --- |
| 계획 | 1회 |
| 초안 | 1회 |
| 국소 수정 | 2회 |
| 분량 추가 | 4회 |
| 독립 검수 | 1회 |
| 응답 형식·네트워크 오류 재시도 | 문서 전체에서 1회 |

합계는 후보당 최대 10회입니다. 실행 전체는 요청 2,400회와 추정 비용 20 USD를 넘지 않도록 막습니다. 값은 [config.json](config.json)에서 조정합니다.

## 프롬프트 요약

모델 호출은 다섯 종류입니다. 모두 OpenAI Responses API의 strict JSON Schema 출력을 씁니다. 시스템 프롬프트는 `[목적] → [입력] → [핵심 규칙] → [출력]` 구조이고, 여기에 문서 타입 기준과 도메인별 작성 지침이 붙습니다.

| 호출 | 모델 | 모델이 받는 것 | 모델이 돌려주는 것 |
| --- | --- | --- | --- |
| 계획 | `gpt-4o-mini` | 조건, 코드가 확정한 그래프, 관계 정의 | 관계별 맥락(`relation_contexts`), 장면별 구체 사실(`scene_notes`), 문서의 사건 설정(`document_case`) |
| 초안 | `gpt-4o-mini` | 조건, 계획, 엔티티별 작성 안내, placeholder 목록 | 문장 목록(`segments`), 지시어(`refs`), 관계별 근거 문장(`relation_evidence`) |
| 국소 수정 | `gpt-4o-mini` | 현재 초안, 진단된 오류, 고칠 대상(`repair_tasks`) | 교체할 문장, 삽입할 문장, 오류 관계를 다시 쓴 문장(`relation_repairs`) |
| 분량 추가 | `gpt-4o-mini` | 구간 하나, 기존 본문 전체, 아직 쓰지 않은 사실, 부족한 글자 수 | 그 구간에 넣을 새 문장(`sentences`) |
| 독립 검수 | `gpt-5-mini` | 최종 본문, 라벨을 뺀 관계 목록, 형식 조건, 문서 타입 기준 | 관계별 판정(`relation_checks`), 계획 밖 관계(`unplanned_relations`), 형식과 품질 판정, 고칠 문장(`text_issues`), 필수 내용 충족 여부(`spec_checks`) |

생성 호출은 temperature 0.7, 검수 호출은 reasoning effort `low`로 보냅니다.

### 프롬프트별 핵심 규칙

**계획**

- 인물, 엔티티, 관계, 라벨로 이루어진 그래프는 고정이며 모델이 바꾸지 않는다.
- 관계마다 누가 어떤 목적으로 그 정보를 쓰는지 구체적인 맥락을 쓴다. 값의 모양을 근거로 삼지 않는다.
- 날짜, 금액, 기간 같은 비식별 사실은 구체적인 값으로 정한다. 이름이나 번호 같은 엔티티 값은 만들지 않는다.

**초안**

- 모든 구간을 쓰고 모든 엔티티를 `<TYPE:E번호>` 토큰으로 언급한다. 예: `신청인 <NAME:E1>{josa:의} 개인 연락처는 <MOBILE_PHONE:E2>이다.`
- 관계의 방향과 귀속을 문서 속 사실로 드러낸다. "관계를 명시한다" 같은 해설 문장은 쓰지 않는다.
- 같은 사실을 어미만 바꿔 반복해 분량을 채우지 않는다.
- 계획에 없는 인물, 엔티티, 관계를 추가하지 않는다.

**국소 수정**

- 진단된 오류만 고치고 정상 문장과 근거는 그대로 둔다.
- 오류가 난 관계는 양 끝 엔티티 토큰이 모두 들어간 완전한 문장으로 다시 쓴다.
- 분량은 이 호출에서 다루지 않는다.

**분량 추가**

- 지정된 구간 하나에 새 문장만 추가한다. 기존 문장은 돌려주지 않는다.
- 기존 본문의 날짜, 금액, 인물, 처리 상태와 어긋나지 않게 쓰고 같은 뜻을 다시 말하지 않는다.
- 새 엔티티, 관계, 식별값은 만들지 않는다.

**독립 검수**

- 관계마다 성립 여부, 방향, 귀속, 관찰한 라벨(`observed_privacy`)을 판정한다.
- 특정 개인에게 정보를 귀속하거나 그 개인을 식별·연결하면 `PII`, 그렇지 않으면 `NON_PII`, 본문으로 확정할 수 없으면 `AMBIGUOUS`다.
- 후보에 없는 관계가 본문에 성립하면 보고한다.
- 일관성, 유창성, 적합성과 종합 등급을 상·중·하로 매긴다. 표현만 바꾼 반복이나 관계를 해설하는 문장이 있으면 `상`을 주지 않는다.

검수 모델에는 계획한 라벨(`target_privacy`), 관계 맥락(`context_reason`), 생성 모델이 받은 사실 계획을 전달하지 않습니다.

### 전문을 보는 곳

- 실제로 전송된 프롬프트와 입력은 후보별 `api/request_*.json`에 저장되며 `inspect --artifact prompts`로 볼 수 있습니다.
- 프롬프트 원문은 `stages/stage02_plan.py`, `stages/stage04_draft.py`, `stages/stage05_assemble.py`, `additions.py`, `stages/stage07_review.py`에 있습니다.
- [PROMPTS.md](PROMPTS.md)에 다섯 호출의 프롬프트 전문과 입출력 필드가, [PIPELINE_FLOW.md](PIPELINE_FLOW.md)에 채택된 문서 1건의 단계별 결과가 있습니다.
- [examples/structured_prompts/](examples/structured_prompts/)에 그 문서의 호출별 입력, 프롬프트, 출력 Schema, 실제 출력 파일이 있습니다.

## 한쪽만 마스킹되는 관계

PII 엔티티와 NON_PII 엔티티를 잇는 `NON_PII` 관계입니다. 기존 데이터셋에 있는 모양을 따랐고, 기본 설정에서 문서마다 무작위로 들어갑니다.

```text
NAME ──PII──▶ WORKPLACE ──NON_PII──▶ TELEPHONE          소속 기관의 공용 정보
NAME ──NON_PII──▶ NAME(참고 인물) ──NON_PII──▶ SCHOOL    당사자가 인용하는 참고 인물
```

| 관계 | 마스킹 | 기본 설정 |
| --- | --- | --- |
| 당사자의 소속 기관 → 그 기관의 공용 전화, 메일, 주소, 계좌 | 기관은 마스킹, 공용 정보는 비마스킹 | 문서마다 0~2개를 무작위로 넣는다 |
| 실제 당사자의 이름 → 예시·공개 인물의 이름 | 당사자는 마스킹, 참고 인물은 비마스킹 | 해당 문서 타입에 확률 0.1로 참고 인물을 넣는다 |

- **소속 기관 관계**는 당사자의 직장이나 학교 정보가 있는 문서 타입에서만 생깁니다. 경력·교육 10개 전부, 계약 39개 중 34개, 금융 6개 중 2개, 의료 8개 중 2개이며 법률과 고객지원에는 없습니다.
- **이름 관계**는 경력·교육의 6개 타입(자기소개서, 경력기술서, 입사지원서, 추천서, 입학·편입 원서, 장학금 신청서)에서만 생깁니다. 참고 인물은 등록된 3명 중 무작위로 고르며, `--reference-profile`로 직접 지정할 수도 있습니다.
- 두 관계는 NON_PII 관계 자리를 씁니다. 자리가 모자란 문서에서는 개수를 줄이거나 넣지 않습니다. 관계 커버리지를 채우려고 필수 관계가 배정된 문서가 대표적이라, 실행 초반에는 참고 인물이 덜 들어갑니다.
- 참고 인물의 확률을 낮게 둔 것은 등록된 인물이 3명뿐이기 때문입니다. 도메인당 50건을 만들면 참고 인물이 들어가는 문서는 3건 안팎이라 같은 이름이 여러 문서에 반복되지 않습니다.
- 기본 설정으로 78개 타입을 5건씩 계획해 보면 390건 중 154건에 이 관계가 하나 이상 들어갑니다. 대부분 소속 기관 관계입니다.
- 끄려면 `organization_bridge_range`를 `[0, 0]`, `reference_person_rate`를 `0`으로 둡니다.

[config_cross_relation_smoke.json](config_cross_relation_smoke.json)은 소속 기관 관계를 문서마다 1개로 고정하고 관계 수를 3개로 줄인 시험용 설정입니다.

```bash
python3 -m relation_pipeline run --config config_cross_relation_smoke.json --run-id bridge_01 --domain career_education --subtype resume_form --max-candidates 10
python3 -m relation_pipeline run --config config_cross_relation_smoke.json --run-id name_01 --domain career_education --subtype cover_letter --reference-profile marie_curie_education --max-candidates 10
```

규칙과 값 공급 방식은 [COVERAGE_PRIVACY_PERSONS.md](COVERAGE_PRIVACY_PERSONS.md#한쪽만-마스킹되는-관계)에, 실제 API 시험 결과는 [EXPERIMENTS.md](EXPERIMENTS.md#5-한쪽만-마스킹되는-관계-2026-10-05)에 있습니다.

## 준비

### 1. 외부 데이터

저장소에 포함되지 않은 파일 두 개가 필요합니다. [config.json](config.json)의 경로는 설정 파일이 있는 폴더를 기준으로 한 상대 경로이며, 둘 다 저장소 폴더의 바로 옆에 둡니다.

| 설정 키 | 기본 경로 | 내용 | 없으면 |
| --- | --- | --- | --- |
| `pool_path` | `../pii_dataset_release/non_pii_augmentation/data/persona/pii_dataset_2026.json` | persona pool. JSON 배열이며 각 행에 18개 엔티티 타입의 값이 모두 있어야 한다 | 실행 불가 |
| `reference_dataset` | `../reference_dataset/dataset.zip` | 기존 문서 corpus의 zip. 새 문서가 기존 문서와 겹치는지 검사하는 데 쓴다 | `null`로 두면 이 검사를 건너뛴다 |

```text
<작업 폴더>/
├── relation_document_pipeline/     이 저장소
├── pii_dataset_release/            persona pool이 들어 있는 저장소
└── reference_dataset/dataset.zip   기존 문서 corpus
```

다른 위치에 두었다면 두 경로를 바꿉니다. 절대 경로도 쓸 수 있습니다.

### 2. API 키

환경 변수 또는 저장소 루트의 `.env`에서 `OPENAI_API_KEY_1`, `OPENAI_API_KEY_2`, `OPENAI_API_KEY`를 읽습니다. 환경 변수가 우선이며, 키가 여러 개면 요청마다 번갈아 씁니다.

```bash
cp .env.example .env
chmod 600 .env   # 권한이 600이 아니면 실행을 거부한다
```

`.env`는 `.gitignore`에 들어 있습니다. 키 값은 로그, 통계, 오류 메시지에 기록하지 않습니다.

### 3. 설치

설치 없이 바로 실행할 수 있습니다. `relation-docs` 명령이 필요하면 `python3 -m pip install -e .`를 실행합니다.

## 사용법

### 처음 실행

API를 쓰지 않는 오프라인 모드로 전체 단계가 동작하는지 먼저 확인합니다.

```bash
python3 -m unittest discover -s tests
python3 -m relation_pipeline run --run-id offline_check --offline --target-per-domain 1 --max-candidates 6
python3 -m relation_pipeline validate --run-id offline_check
```

오프라인 모드는 정해진 모의 응답을 쓰는 동작 점검용입니다. 그 결과물은 문서 품질이나 합격률의 근거가 되지 않으므로 실제 생성 데이터와 섞지 않습니다.

### 실제 생성

적은 수로 먼저 돌려 합격률과 탈락 사유를 확인합니다.

```bash
# 고객지원 도메인에서 3건을 목표로, 후보는 3건까지만 처리
python3 -m relation_pipeline run --run-id pilot_01 --domain support --target-per-domain 3 --max-candidates 3

# 결과 확인
python3 -m relation_pipeline stats --run-id pilot_01

# 이어서 실행
python3 -m relation_pipeline resume --run-id pilot_01 --max-candidates 3

# 전체 실행 (6개 도메인 × 50건)
python3 -m relation_pipeline run --run-id production_01
```

후보 3건을 처리했다고 문서 3건이 채택되는 것은 아닙니다. 탈락한 slot은 미완료로 남고, 예산이나 시도 상한에 걸리면 `manifest.json`의 상태는 `incomplete`입니다.

### 명령

| 명령 | 용도 |
| --- | --- |
| `catalog` | 도메인별 문서 타입 목록. `--specs`를 붙이면 타입별 작성 기준까지 출력 |
| `prepare` | API 호출 없이 slot과 설정만 준비 |
| `run` | 새 실행을 준비하고 생성 |
| `resume` | 중단된 실행을 이어서 진행 |
| `stats` | 단계별 수량, 등급, 탈락 사유, 호출량. `--json`, `--export` 지원 |
| `inspect` | 후보 하나의 조건, 계획, 본문, 검수 결과, 실제 프롬프트 확인 |
| `validate` | 채택된 문서의 hash, span, BIO, 관계를 다시 검증 |

`run`과 `prepare`의 주요 옵션입니다.

| 옵션 | 설명 |
| --- | --- |
| `--run-id` | 실행 이름. 영문, 숫자, `_`, `-`만 사용 |
| `--domain` | 도메인 선택. 여러 번 지정 가능 |
| `--target-per-domain` | 도메인당 채택 목표 수 |
| `--max-candidates` | 이번 호출에서 처리할 후보 수 |
| `--subtype`, `--scenario`, `--topic`, `--viewpoint` | 문서 타입, 상황, 주제, 관점을 직접 지정 |
| `--stop-after-stage N` | N단계까지만 진행하고 멈춤 |
| `--offline` | API 없이 모의 응답으로 실행 |

문서 타입을 지정해 한 건만 만들어 보는 예시입니다.

```bash
python3 -m relation_pipeline catalog --domain support
python3 -m relation_pipeline run --run-id refund_01 --domain support --subtype refund_request --scenario subscription --target-per-domain 1 --max-candidates 5
python3 -m relation_pipeline inspect --run-id refund_01 --candidate-id support_001_c001 --artifact review
```

### run ID와 재현성

실행을 준비하는 순간 설정, 자원 파일, 파이프라인 코드의 hash가 그 run에 고정됩니다. 이후 코드나 설정을 바꾸면 같은 run ID로는 `resume`할 수 없으므로 새 run ID를 써야 합니다.

## 출력

채택된 문서는 `output/<run-id>/dataset/<domain>/<document-id>.json`에 저장됩니다. 루트 키는 `sentences`, `entities`, `relations`입니다. 아래는 구조를 보여 주기 위해 값을 바꾸고 줄인 예시입니다.

```json
{
  "sentences": [
    {
      "sent_idx": "refund_01_support_001_18",
      "sentence": "고객 홍길동은 자신의 카드 번호 1234-5678-9012-3456과 관련하여 환불을 요청하였다.",
      "PII_set": [
        {"form": "홍길동", "label": "NAME", "begin": 3, "end": 6, "id": 0},
        {"form": "1234-5678-9012-3456", "label": "CARD_NUMBER", "begin": 18, "end": 37, "id": 1}
      ],
      "sent_seq": ["고", "객", " ", "홍", "길", "동", "..."],
      "labelling_seq": ["O", "O", "O", "B-NAME", "I-NAME", "I-NAME", "..."]
    }
  ],
  "entities": [
    {
      "entity_id": "E1", "entity_type": "NAME", "canonical_form": "홍길동",
      "mentions": [{"form": "홍길동", "begin": 3, "end": 6, "sent_idx": "refund_01_support_001_18"}]
    }
  ],
  "relations": [
    {"entity": "E1", "entity_type": "NAME", "target_entity": "E2", "target_entity_type": "CARD_NUMBER",
     "relation": "FINANCIAL_ASSET_ASSOCIATION", "privacy_label": "PII"},
    {"entity": "E3", "entity_type": "WORKPLACE", "target_entity": "E4", "target_entity_type": "TELEPHONE",
     "relation": "CONTACT_ASSOCIATION", "privacy_label": "NON_PII"}
  ]
}
```

- `PII_set`과 `labelling_seq`는 문자 단위 마스킹 정답입니다.
- PII 관계에 하나라도 참여한 엔티티는 문서 안의 모든 언급을 마스킹합니다.
- NON_PII 관계에만 참여한 엔티티는 마스킹하지 않습니다.
- 관계별 `privacy_label`은 마스킹과 별도로 보존합니다.

### 실행 기록

`runs/<run-id>/`에 실행 과정 전체가 남습니다. `runs/`와 `output/`은 `.gitignore`에 들어 있습니다.

```text
runs/<run-id>/
├── run_config.json        고정된 설정과 자원 hash
├── manifest.json          완료 여부, 채택 문서 목록, 관계 커버리지
├── statistics.sqlite3     slot, 후보, 단계 시도, API 호출, 검수 기록
├── statistics/            summary.json과 CSV 통계
├── audits/                채택 문서별 감사 기록
└── candidates/<candidate-id>/
    ├── condition.json, plan.json, value_map.json
    ├── draft_versions/, repairs/, additions/
    ├── assembled.json, filled.json, review.json
    └── api/               실제 요청과 응답 (인증 헤더 제외)
```

통계는 후보 하나가 끝날 때마다 갱신됩니다. 먼저 볼 파일은 다음과 같습니다.

| 파일 | 내용 |
| --- | --- |
| `statistics/summary.json` | 전체 집계. 도메인별 채택과 탈락, 등급, 호출량 |
| `statistics/candidates.csv` | 후보별 조건, 최종 단계, 탈락 사유 |
| `statistics/stages.csv` | 단계별 시도 수와 합격률 |
| `statistics/reviews.csv` | 검수별 품질 등급과 통과 여부 |
| `statistics/api_calls.csv` | 모델, 토큰, 추정 비용 |

비용은 `config.json`의 토큰 단가로 계산한 추정값이며 실제 청구액이 아닙니다.

## 주요 설정

[config.json](config.json)에서 자주 바꾸는 값입니다.

| 키 | 기본값 | 의미 |
| --- | --- | --- |
| `target_per_domain` | 50 | 도메인당 채택 목표 수 |
| `relation_count_range` | [4, 6] | 문서당 관계 수 |
| `non_pii_relation_fraction_range` | [0.35, 0.55] | 관계 중 NON_PII의 비율 |
| `relation_coverage.enabled` | true | 19개 관계 타입을 각각 1건 이상 채택해야 완료로 볼지 여부 |
| `organization_bridge_range` | [0, 2] | 문서당 "소속 기관 → 공용 정보" 관계 수의 범위. 범위 안에서 무작위로 정한다 |
| `reference_person_rate` | 0.1 | 해당 문서 타입에 참고 인물을 넣을 확률. 등록된 인물이 3명뿐이라 낮게 둔다 |
| `reference_link_policy` | "party_link_v1" | 참고 인물이 있으면 당사자가 그 인물을 인용하는 관계를 넣는다. `none`이면 넣지 않는다 |
| `max_candidates_per_slot` | 10 | slot 하나에서 시도할 후보 수 |
| `run_request_budget` | 2400 | 실행 전체의 API 요청 상한 |
| `run_cost_budget_usd` | 20.0 | 실행 전체의 추정 비용 상한 |
| `content_jaccard_threshold` | 0.55 | 이 값 이상으로 기존 문서와 겹치면 탈락 |
| `seed` | 1729 | slot 배정과 조건 선택의 난수 seed |

모델은 `gpt-4o-mini`와 `gpt-5-mini`로 고정되어 있으며 다른 값을 넣으면 준비 단계에서 오류가 납니다. `config_*_smoke.json`은 실험용 설정이며 `--config`로 지정해 씁니다.

## 코드 구조

```text
relation_pipeline/
├── cli.py                  명령 진입점
├── runner.py               단계 실행, checkpoint, 재개
├── stages/stage00~08_*.py  단계별 구현
├── client.py               OpenAI Responses API 호출, 키 순환, 예산
├── call_policy.py          후보별 호출 상한과 재시도
├── schemas.py              모델 출력 JSON Schema
├── privacy.py              PII / NON_PII / AMBIGUOUS 정의
├── planning_seed.py        엔티티와 관계 그래프 생성
├── reference_people.py     가상 예시 인물과 공개 인물
├── spec_definitions.py     78개 문서 타입의 작성 기준
├── domain_prompts.py       도메인별 생성 지침
├── persons.py              문서 타입별 등장 인물과 정보 귀속
├── coverage.py             19개 관계 타입의 채택 현황
├── dedup.py                내용·구조 중복 검사
├── renderer.py             값 치환, 조사 처리, span 계산
├── validation.py           최종 문서 검증
├── statistics.py, store.py 통계와 SQLite 기록
└── offline.py              오프라인 모의 응답
assets/        문서 타입 catalog, 관계 ontology, 등록 참고 인물
tests/         단위·통합 테스트
experiments/   비교 실험 스크립트와 결과
examples/      호출별 입력, 프롬프트, 출력 예시
docs/          문서 타입별 작성 기준
```

## 현재 검증 상태

2026-10-05 기준입니다.

- 테스트 200개가 모두 통과합니다.
- 실제 API로는 도메인마다 문서 1건씩 채택되는 것을 확인했습니다. 이 실행은 기본 설정과 달리 관계 수를 3개로 고정하고 관계 커버리지 요구를 껐습니다. 6건을 채택하는 데 후보 52건, API 호출 257회, 추정 비용 약 0.61 USD가 들었고, 도메인별로 필요한 후보 수는 1건에서 15건까지 차이가 났습니다.
- 기본 설정(관계 4~6개, 관계 커버리지 포함, 도메인당 50건)으로 전체를 완료한 실행은 아직 없습니다. 이 설정에서의 합격률과 비용은 확인되지 않았습니다.
- 한쪽만 마스킹되는 관계는 실제 API로 후보 175건을 시험했습니다. 가상 예시 인물을 인용하는 문서 1건이 채택됐습니다. 소속 기관 관계는 검수 모델이 33건 중 30건에서 계획대로 `NON_PII`로 판정했지만, 그 관계가 들어간 문서는 문장 중복 등 품질 기준에 걸려 아직 채택되지 않았습니다.
- 공개 인물을 인용하는 관계는 처음에 검수 모델이 모두 `PII`로 판정했습니다. 검수 프롬프트에 예외를 넣은 뒤 같은 문서 7건을 다시 검수하니 7건 모두 `NON_PII`로 판정했습니다. 이 예외를 넣은 상태로 문서를 새로 생성해 채택까지 확인하지는 않았습니다.

## 데이터의 한계

- **분포는 설계한 값입니다.** 문서당 관계 수, NON_PII 비율, 도메인별 문서 수는 `config.json`으로 정합니다. 실제 업무 문서의 통계에 맞춘 것이 아닙니다.
- **PII 쪽과 NON_PII 쪽을 잇는 관계는 일부 문서에만 있습니다.** 당사자의 기관 정보가 없는 문서 타입(법률, 고객지원 등)에서는 PII 관계가 사람의 이름에서만 뻗고 NON_PII 관계는 별도의 기관 엔티티끼리만 이어집니다.
- **라벨은 모델 하나가 확인한 것입니다.** 채택된 문서는 `gpt-5-mini`가 본문에서 계획과 같은 라벨로 판정한 문서뿐이며, 사람이 라벨을 확인하는 단계는 없습니다.
- **검수 모델이 판단하지 못한 사례는 빠집니다.** 현재 흐름의 실제 실행에서 검수까지 간 후보 103건 가운데 9건에는 `AMBIGUOUS`로 판정된 관계가, 22건에는 본문에서 성립하지 않는다고 판정된 관계가 있었고 모두 탈락했습니다. 이 선별이 채택 문서를 어느 쪽으로 치우치게 하는지는 측정하지 않았습니다.
- **`PII`와 `NON_PII`는 이 데이터셋의 운영 정의입니다.** [relation_pipeline/privacy.py](relation_pipeline/privacy.py)의 기준을 따른 라벨이며 법적인 개인정보 판정이 아닙니다.
- **문서 타입별 작성 기준은 합성 문서용입니다.** 실제 법률, 의료, 금융 서식의 적법성이나 임상적 타당성을 보증하지 않습니다.

## 상세 문서

| 문서 | 내용 |
| --- | --- |
| [PIPELINE_FLOW.md](PIPELINE_FLOW.md) | 후보 한 건의 진행, 탈락 지점, 채택된 문서 1건의 단계별 예시 |
| [PROMPTS.md](PROMPTS.md) | 다섯 호출의 프롬프트 전문과 입출력 필드 |
| [COVERAGE_PRIVACY_PERSONS.md](COVERAGE_PRIVACY_PERSONS.md) | privacy 정의, 인물 귀속, 관계 커버리지 |
| [DOCUMENT_SPECS.md](DOCUMENT_SPECS.md) | 78개 문서 타입의 작성 기준 (코드에서 자동 생성) |
| [DOMAIN_PROMPTS.md](DOMAIN_PROMPTS.md) | 도메인별 생성 지침 (코드에서 자동 생성) |
| [EXPERIMENTS.md](EXPERIMENTS.md) | 기본 설정을 정한 비교 실험의 결과와 결론 |
