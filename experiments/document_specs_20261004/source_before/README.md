# 관계 계획 기반 문서 생성 파이프라인

6개 도메인에서 기본적으로 각 50건, 총 300건의 **통제된 합성 문서**를 최종 채택하는 생성 코드입니다. 완료에는 19종 관계의 최종 채택 수가 각각 1건 이상이어야 하며, 부족한 관계를 보완하는 slot을 최대 38개 추가할 수 있습니다. 기본 수량과 관계 커버리지를 별도로 기록합니다.
검수는 `gpt-5-mini`, 계획·생성·복구는 `gpt-4o-mini`를 사용합니다.
기존 생성/증강 패키지를 실행 중 import하지 않고, 규칙과 로직을 이 패키지에 직접 구현했습니다.
기존 문서와 persona pool은 읽기 전용 자원으로 사용합니다.

Python 3.10 이상이면 외부 라이브러리 설치 없이 실행할 수 있습니다.

기본 실행 흐름은 `generation_flow: separated_v1`입니다. 계획 → 초안 → 코드 검사 → 국소 수정 최대 1회 → 분량 추가 최대 2회 → 독립 검수 순서입니다. 검수 응답 형식 오류는 공통 재시도 예산으로 바로잡고, 유효한 검수에서 의미·품질이 실패하면 사유를 기록하고 탈락시킵니다. 문서 유형별 프롬프트 선택인 `document_policy`와 별개의 설정입니다.

현재 단계별 input/output은 [PIPELINE_FLOW.md](PIPELINE_FLOW.md), 공통 privacy 정의·인물 귀속·19종 완료 조건·의미/품질 복구는 [COVERAGE_PRIVACY_PERSONS.md](COVERAGE_PRIVACY_PERSONS.md)에 있습니다. 같은 엔티티의 반복 횟수·위치나 문장 간 근거 거리는 계속 강제하지 않습니다.

2026-10-04 자연스러움 개선 실험은 [NATURALNESS_EXPERIMENT.md](NATURALNESS_EXPERIMENT.md)에 있습니다.
문서 목적 안내를 넣은 8쌍, 구체적 사실 출력·완전 문장 복구를 추가한 2쌍을 실제 API로 비교했지만 수정안에서 최종 채택된 문서는 없었습니다.
`document_policy: legacy`, `purpose_review: false`를 기본값으로 유지합니다. `purpose_v1`/`purpose_v2`와 목적 검수는 실험용 선택지이며 운영 기본 동작에 적용하지 않았습니다.

원본 생성기의 경험 소재·단순 본문 출력을 참고한 후속 `prose_v1`/`prose_v2`도 최종 합격 개선이 확인되지 않아 실험용으로만 남겼습니다. 검수자가 선택한 S ID에 코드로 정확한 원문 인용을 연결하는 `review_evidence_policy: sentence_ids`는 기본 적용했습니다. 독립 검수의 라벨·근거 ID를 코드로 바꾸지는 않습니다. 복구 입력의 알려진 실제 값은 다시 placeholder로 바꿔, 모델이 전화번호 등을 원문 토큰 대신 복사하는 오류를 방지합니다. 전체 후속 결과는 [NATURALNESS_EXPERIMENT.md](NATURALNESS_EXPERIMENT.md)에 기록합니다.

가상 사례·작품 인물과 출처가 확인된 공개 위키 약력은 선택 기능입니다. [등록 자료](assets/reference_people.json)와 [정의·지원 범위](COVERAGE_PRIVACY_PERSONS.md)를 확인하세요. 실제 신청인의 합성 이름은 계속 PII입니다. 등록 인물 선택 기능의 오프라인 통합 검증과 실제 문서의 최종 품질 합격은 구분합니다.

```bash
python3 -m relation_pipeline run --run-id reference_example_20261004 --domain career_education --subtype cover_letter --topic "가상 학생 사례를 활용한 학습 프로그램 개선" --reference-profile fictional_student --target-per-domain 1 --max-candidates 1
```

`fictional_story_student`는 창작 작품 인물, `marie_curie_education`은 공개 교육 약력입니다. 모든 문서에 강제 삽입하지 않습니다. 기존 run은 고정된 과거 설정을 사용하므로 변경 사항 시험에는 새 run ID가 필요합니다.

```bash
cd /home/upsecurity00/data/members/yeonju/relation_document_pipeline
python3 -m relation_pipeline --help
```

선택적으로 `python3 -m pip install -e .`를 사용하면 `relation-docs` 명령도 사용할 수 있습니다.
설정은 `config.json`에서 조정합니다. 이미 준비된 run의 설정·자원·코드는 고정합니다.
수정한 설정이나 코드로 실행할 때는 새 run ID를 사용하세요.

## 실행

전체 실행은 각 도메인 50개 slot을 준비하고, 검사와 commit을 통과한 문서만 수량에 포함합니다.

```bash
python3 -m relation_pipeline run --run-id production_20261003
```

처음에는 후보 수를 제한해 실제 합격률과 탈락 이유를 확인할 수 있습니다.

```bash
python3 -m relation_pipeline run --run-id pilot_20261003 --domain support --target-per-domain 3 --max-candidates 3
python3 -m relation_pipeline stats --run-id pilot_20261003
python3 -m relation_pipeline resume --run-id pilot_20261003 --max-candidates 3
```

후보 3건 처리와 최종 문서 3건 채택은 다릅니다. 탈락한 slot은 계속 미완료로 남습니다.
예산·시도 상한에 도달하면 `manifest.json`은 `incomplete`이며, 수량을 채웠다고 표시하지 않습니다.

문서 종류·구성 변형·주제·관점을 직접 지정할 수 있습니다.

```bash
python3 -m relation_pipeline catalog --domain support
python3 -m relation_pipeline run --run-id selected_20261003 --domain support --subtype support_ticket --variant question_answer --topic "배송 문의와 후속 안내" --viewpoint staff_record --target-per-domain 2 --max-candidates 2
```

고정 계약서와 고정 서식에는 해당하는 고정 variant만 지정할 수 있습니다.
문서 종류나 variant가 지정한 도메인과 호환되지 않으면 API 호출 전에 오류를 반환합니다.
variant quota는 subtype이 아닌 `document_format`별 최종 채택 수량을 기준으로 맞춥니다.

API를 호출하기 전에 준비된 slot이나 선정 조건만 볼 수도 있습니다.

```bash
python3 -m relation_pipeline prepare --run-id conditions_20261003 --domain support --target-per-domain 2
python3 -m relation_pipeline resume --run-id conditions_20261003 --max-candidates 1 --stop-after-stage 1
python3 -m relation_pipeline inspect --run-id conditions_20261003 --candidate-id support_001_c001 --artifact condition
```

`--stop-after-stage 1`은 조건만 선정합니다. 2부터는 계획 API를 사용할 수 있으며, 중단한 후보는 `resume`에서 이어집니다.

## API 키와 모델 요청

환경 변수 `OPENAI_API_KEY_1`, `OPENAI_API_KEY_2` 또는 이 폴더의 `.env`에서 키를 읽습니다.
전달받은 두 키는 `.env`에 저장했으며 권한은 `600`입니다. 소스와 통계에는 키 이름만 기록합니다.
환경 변수가 `.env`보다 우선하고, 제공된 키를 요청마다 순환 사용합니다.
키 값은 소스·이벤트 로그·CSV·CLI 오류에 기록하지 않습니다.

Responses API의 strict JSON Schema 출력 계약을 사용합니다.
계획의 ID·허용 엔티티 타입·관계 종류·관계 배열 길이·section ID는 선정 조건에 맞게 출력 계약에서도 제한합니다.
문서 출력 계약은 허용 placeholder, reference 표면형, 비어 있지 않은 관계 근거 그룹을 검사합니다.
생성 응답의 segment 배열에는 길이 목표에서 계산한 생성 예산이 있으며, 무제한 항목 반복으로 토큰 예산을 소진하는 것을 막습니다.
복구에서는 교체용 기존 S ID와 삽입용 신규 S ID를 구분하고 기준 버전·삽입 위치도 검사합니다.
관계별 privacy slot은 조건에 맞게 섞어 배정하며, 수량을 만족하는 값 없는 그래프 예시를 계획 모델에 제공합니다.
표현 방식은 계획에서 배정하지 않고, 독립 검수의 최소 근거와 최종 문장 순서로 관찰합니다.
모델은 그래프와 업무 맥락을 계획하고, 코드가 허용 triple·장면 귀속·전체 수량을 다시 검사합니다.
본문 계약은 정확한 TYPE/ID placeholder 조합과 section/scene ID, 역할 지시어 표면형,
비어 있지 않은 근거 그룹을 제한합니다. 검수 계약도 전달한 관계·문장·지시어 ID만 사용하도록 제한합니다.
각 호출의 실제 system prompt·user 입력·출력 계약을 `candidates/<id>/api/request_XXXXX.json`에 저장합니다.
인증 헤더와 API 키는 저장하지 않습니다. `inspect --artifact prompts`로 조회할 수 있습니다.
현재 네 프롬프트는 `[목적] → [입력] → [핵심 규칙] → [출력]`으로 구조화했습니다.
모델 입력에서는 실행 ID·fingerprint·예상 privacy 그룹과 복구에 필요 없는 반복/분포 통계를 제외합니다.
실행 기록과 통계에는 전체 조건·계획·진단을 보존하며, section 분량·관계 맥락·출력 Schema·합격 기준은 유지합니다.
프롬프트 전문과 현재 입력/출력 계약은 [PROMPTS.md](PROMPTS.md)에서 확인할 수 있습니다.
`gpt-5-mini`에는 `reasoning.effort=low`를 적용하고 temperature를 전달하지 않습니다.
모델 요청 형식은 OpenAI Docs의 [Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs)와
[Reasoning models](https://developers.openai.com/api/docs/guides/reasoning)를 확인해 구현했습니다.

기본 상한은 계획 1회, 초안 1회, 국소 수정 1회, 분량 추가 2회, 독립 검수 1회입니다.
정상 경로는 3~6회이며, 네트워크·JSON·검수 근거 오류·잘못된 추가 본문에 대한 재시도는 문서 전체에서 합쳐서 1회만 허용해 절대 최대 7회입니다.
기존 계획·초안을 재사용하면 정상 최대 4회, 재시도 포함 최대 5회입니다. 후보별 `call_policy.json`과 검증 응답 캐시를 저장해 재개 시에도 예산을 유지합니다.
slot당 후보 10건, 도메인당 후보 500건이며, 기존 run의 `generation_flow`가 없거나 `legacy`이면 그 run의 기존 복구 흐름을 사용합니다.
전체 실행은 provider 요청 2,400회와 추정 비용 20 USD를 넘지 않도록 제한합니다.
타임아웃 등 사용량을 알 수 없는 요청의 비용은 보수적인 예약액을 남깁니다.
통계의 비용은 설정된 토큰 단가에 의한 추정이며 실제 청구서가 아닙니다.

## 단계별 입력과 출력

| 단계 | 모듈 | 입력 | 출력 및 주요 검사 |
| --- | --- | --- | --- |
| 0 준비 | `stage00_prepare.py` | 설정·catalog·ontology·pool·기존 corpus | 고정 설정·자원/코드 hash·slot ledger·SQLite |
| 1 조건 | `stage01_condition.py` | slot·채택 quota·선택 옵션 | `condition.json`: 형식·variant·topic·관점·길이·관계/privacy 수·자연스러운 재언급 정책 |
| 2 계획 | `stage02_plan.py` | 조건·허용 triple·이전 오류·오류가 난 기존 계획 | 그래프·장면·`context_reason`·fingerprint. 전이적 값 그룹/허용 값 충돌을 조기에 검사하고 기존 계획의 제약만 수정 |
| 3 값 | `stage03_values.py` | 계획·persona pool | 고정 value map·정합성/공급 가능성 검사 |
| 4 생성 | `stage04_draft.py` | 조건·값을 숨긴 계획 | 완성 문서 전체의 placeholder segments·refs·관계 근거 |
| 5 검사/복구 | `stage05_assemble.py` | 기존 초안·고정 계획/값·ID별 수정 대상·진단 | 오류 R별 수정 문구에 코드가 endpoint를 연결한 부분 patch·수정 후 전체 진단·복구 진척 기록·assembled 문서 |
| 6 치환/중복 | `stage06_render.py` | assembled·고정 값·registry | 실제 본문·모든 mention/reference span·내용/실제 구조 중복 검사 |
| 7 독립 검수 | `stage07_review.py` | 본문·privacy 없는 관계 후보·reference 표면/span·형식·관점 | 관찰 privacy·최소 근거/인용·지시어 대상·상중하 등급·의미/형식 통과 여부 |
| 8 채택 | `stage08_accept.py` | 검수 통과 문서·graph·registry | 기존 증강 스키마·전체 span/BIO 검증·accepted audit·manifest 갱신 |

개인 연락/신원 속성의 귀속이 한 사람으로 명확하면 이름·연락처·생년월일 등을 같은 persona에서 선택합니다.
조직·학교·사건 장소·공동 연락처 등 모든 노드를 무조건 한 persona 행으로 합치지는 않습니다.
PII/NON-PII에는 같은 pool과 formatter를 사용하며, 실제 값은 생성 모델에 보내지 않습니다.

검수 입력에는 목표 privacy, `context_reason`, 생성자의 근거 그룹, reference의 의도된 대상,
`PII_set` 또는 BIO 정답을 주지 않습니다. 형식·variant·관점은 평가를 위해 제공합니다.
검수 후 관찰 privacy로 반복·분포를 다시 계산하고 기록합니다. 반복 횟수·위치·등장 비율은 합격 조건이 아닙니다.
의미 실패를 관계 삭제나 자동 라벨 변경으로 해결하지 않습니다.

4단계 전체 초안은 최초 1회입니다. 새 계획은 장면별로 구체적 사실 2~5개를 반환하며, 관계 맥락도 작성 지시 대신 역할·귀속·행위를 확정합니다.
코드 검사에서 관계·문장 오류와 길이 부족이 함께 나오면, 국소 수정 호출에는 길이 부족을 제외해 전달합니다. `relation_repairs`는 완전한 `sentence` 또는 `linked_text`만 허용하며 과거 조각 결합 형식은 제외합니다. 이때 `continuations={}`입니다.
길이 부족은 `additions.py`의 별도 `expand` 호출로 처리합니다. 부족한 section 하나와 기존 본문 전체·타입별 사실 지침을 전달하고 `{section_id, sentences}`만 받습니다. 한 번의 신규 본문 목표는 200~1,000자이며, 문서 전체의 상한이 아닙니다.
병합 전에 빈 문장·줄바꿈·과도한 길이·식별값·문자열 중복 및 높은 유사도·명시된 숫자 필드 충돌을 검사합니다. 병합 후 구조 검사와 원문 문장·지시어·관계 근거의 완전 보존을 검사합니다. 검사 실패한 추가 본문은 병합하지 않습니다. 의미가 같은 다른 표현, 일반 서술의 사실 모순, 새 인물 등은 최종 독립 검수가 판정합니다.
`relation_pipeline/content_depth.py`는 6개 도메인 78개 타입별 실질 내용을 정의합니다. 예를 들어 문진표는 증상 변화·복약·생활 패턴, 계약서는 산출물·검수·정산 내역을 구체화합니다. 분량만 채우는 반복 안내문을 금지합니다.
분량 기준은 원본 Git의 타입별 목표 범위와 `max(1500, int(목표×0.75))` 하한을 유지하며 상한은 없습니다.
분리 전 [실제 검증 결과](experiments/additive_length_20261004/RESULTS.md)는 기존 6개 초안 중 분량 충족 3개, 최종 품질 채택 0개였습니다. [분리 흐름 검증 결과](experiments/separated_flow_20261004/RESULTS.md)는 실제 21회 호출, 분량 충족 4개, 최종 채택 0개입니다. 자동 테스트 145개가 통과했습니다. 원문 보존·호출 제한은 확인했으며 실제 합격률 개선은 아직 확인되지 않았습니다.
국소 수정과 추가 후 전체 길이·근거 연결·엔티티 존재를 검사하고, 코드 검사를 통과한 최종 본문에 독립 검수 1회를 수행합니다.
토큰 삽입과 endpoint 연결은 구조 검사이며, 관계 의미·privacy가 정확하다는 판정은 독립 검수가 담당합니다.
실제 수정 내역과 제한된 실험은 [TARGETED_REPAIR.md](TARGETED_REPAIR.md)에 기록합니다.
prose segment는 한 문장, 서식 segment는 한 줄로 검사합니다.
코드는 section을 선언된 순서로 안정 정렬합니다. 근거 거리와 표현 방식은 최종 본문 순서에서 분류합니다.
잘못된 근거 ID는 기존 한 단위에 두 endpoint가 실제 등장하는 경우에만 후보 근거로 정규화하고 이력을 남깁니다.
이는 동시 출현 확인일 뿐 의미 통과가 아닙니다. 독립 검수는 이 후보 근거를 보지 않고 관계와 최소 근거를 새로 판정합니다.
문장 간 관계의 근거를 코드가 임의로 만들지는 않습니다.

계획 중복은 엔티티 ID·배열 순서에 독립적인 실제 연결 구조 fingerprint의 반복 상한으로 검사합니다.
연속 관계 feature 유사도는 기록만 하고 탈락 기준으로 쓰지 않습니다.
본문의 엔티티 값을 타입 토큰으로 정규화한 문자 4-gram Jaccard는 초기 기준 `0.55`를 사용합니다.
이 값은 기존 기준을 가져온 것이며 새 corpus에서 보정된 임계값은 아닙니다.
실제 section 블록·segment 수/종류 패턴·길이 구간으로 구조 fingerprint를 계산합니다.
고정 형식은 구조 반복 상한에서 제외합니다.
계획에 없는 endpoint의 동시 출현은 의심 항목으로만 기록하고, 실제 신규 관계 여부는 검수 모델이 판정합니다.

## 통계와 후보 확인

```bash
python3 -m relation_pipeline stats --run-id pilot_20261003 --json
python3 -m relation_pipeline stats --run-id pilot_20261003 --domain support --json
python3 -m relation_pipeline stats --run-id pilot_20261003 --export
python3 -m relation_pipeline inspect --run-id pilot_20261003 --candidate-id support_001_c001
python3 -m relation_pipeline inspect --run-id pilot_20261003 --candidate-id support_001_c001 --artifact review
python3 -m relation_pipeline validate --run-id pilot_20261003
```

`inspect --artifact`에는 `condition`, `plan`, `values`, `draft`, `assembled`, `filled`, `review`, `diversity`, `history`, `prompts`도 있습니다.
아직 도달하지 않은 단계의 artifact를 요청하면 `ARTIFACT_NOT_READY`로 표시합니다.

통계는 후보 하나가 끝날 때마다 다시 내보냅니다. API 오류로 종료돼도 해당 시점의 통계가 남습니다.

| 파일 | 확인할 내용 |
| --- | --- |
| `statistics/summary.json` | 모든 집계·도메인별 채택/탈락·등급·분포·호출량·완료 수량 추정 |
| `statistics/stages.csv` | 단계별 실제 시도 수·고유 후보 수·최신 결과·합격률/신뢰구간·추가 합격/탈락 예상치 |
| `statistics/domains.csv` | 도메인별 slot·최종 채택·탈락·남은 수량 |
| `statistics/selections.csv` | domain·subtype·document_format·layout_variant별 후보 상태 분포 |
| `statistics/candidates.csv` | 후보별 선택 조건·topic·관점·최종 단계·탈락 이유 |
| `statistics/stage_attempts.csv` | 각 단계 재시도와 진단 metrics·탈락 이유·artifact 위치 |
| `statistics/reviews.csv` | 검수 시도별 상/중/하 등급·응답 형식 유효 여부·의미/형식 통과 여부 |
| `statistics/review_relations.csv` | 검수 버전별 관계의 계획/관찰 privacy·표현 방식·최소 근거 수·모호성 사유·본문 버전/hash |
| `statistics/repair_progress.csv` | 복구별 실제 변경 S ID·누락/근거 잔여 오류·해결/신규 오류 수·코드 검사 통과·효과 없는 복구 여부 |
| `statistics/api_calls.csv` | 모델·키 이름·실제/모의 호출 상태·토큰·비용 추정 |
| `statistics/accepted_distribution.csv` | 채택 문서의 PII/NON-PII 실제 언급 수·위치·장면·엔티티별 반복 수 |
| `statistics/events.csv` | 선정·검사·provider 오류·재개·탈락의 상세 이벤트 |

시도 수와 고유 후보 수를 구분합니다. 검수 응답 형식이 잘못돼도 읽을 수 있는 등급은 기록합니다.
단계별 최종 탈락은 `final_rejections_count`로 집계합니다. 마지막 진단이 `repair_needed`여도 복구 예산이 소진돼 탈락했다면 해당 단계의 최종 탈락 수에 포함합니다.
시도 상태와 후보의 최종 탈락은 별도 지표이므로 같은 후보가 마지막 진단과 최종 탈락 양쪽에 표시될 수 있습니다.
`reason_counts`와 `final_rejection_reasons`는 진단 항목 발생 수이며, `reason_candidate_counts`와 `final_rejection_reason_candidate_counts`는 사유별 고유 후보 수입니다. 한 후보의 여러 관계가 같은 이유로 실패해도 후보 수는 한 번만 셉니다.
아직 검수하지 않은 후보의 등급은 `미판정`입니다.
예상 수량은 실제 채택/탈락으로 끝난 후보만 이용하고 API 오류·진행 중·중단된 후보는 제외합니다.
관찰한 합격률의 Wilson 95% 구간과 남은 slot 수를 이용한 추정이며,
표본 수·slot 난이도·quota가 달라질 수 있어 최종 채택 수량을 보장하지 않습니다.
표본이 없거나 관찰 합격률이 0이면 필요한 후보 수를 임의로 만들지 않고 `null`로 표시합니다.

## 데이터의 주장 범위와 선별 편향

이 데이터는 맥락에 따른 PII/NON_PII 판단을 비교하기 위해 분포를 설계한 통제된 합성 문서입니다.
기본값은 문서당 관계 4~6개, NON_PII 관계 목표 수는 비율 구간 35~55%에서 계산해 정수로 반올림합니다. 19종의 최소 채택 수는 개별 문서가 아닌 전체 실행에서 검사합니다.
`graph_policy=scenario_v1`은 검증한 6개 subtype에서 문서 목적·인물 역할에 맞는 관계 후보와 방향을 사용합니다. 나머지 subtype은 기존 도메인 ontology 후보를 사용하며, `summary.json.dataset_design.selected_graph_profile_counts`로 적용 수를 확인할 수 있습니다. 비교 시험과 남은 범위는 [SCENARIO_GRAPH_TRIAL.md](SCENARIO_GRAPH_TRIAL.md)에 기록합니다.
PII 관계와 NON-PII-only 노드의 존재, 선택한 문서 형식·변형·길이는 계속 통제합니다.
동일 엔티티 반복 횟수·장면/문서 위치·PII mention 비율과 표현 방식별 개수는 강제하지 않습니다.
맥락상 필요한 재언급은 같은 E ID를 쓰도록 안내하고, 실제 결과를 기록합니다.
따라서 모든 엔티티가 반복되거나 PII/NON-PII가 위치별로 고르게 등장한다고 보장하지 않습니다.
자연스러운 업무 문체는 품질 목표이며, 실제 현업의 빈도·관계 밀도·비율을 재현한다는 주장은 하지 않습니다.
`summary.json.dataset_design`에는 이 분류와 설정값, 배정된 관계 수, `mention_policy=natural`, `expression_policy=observe_only`를 기록합니다.
이전 실행의 반복 통제와 표현 배정은 `legacy_configured_controls`와 `selected_expression_target_totals`로 구분해 보존합니다.
배정값과 실제 본문에서 확인한 언급 수·검수 근거 수는 별도로 집계합니다.

전체 문서의 맥락으로 정답을 확정할 수 있는 사례와, 전체를 읽어도 귀속을 확정할 수 없는 사례는 다릅니다.
인접 또는 비인접 문장의 연결이 필요한 사례도 검수자가 최소 근거를 확인하면 채택할 수 있습니다.
`AMBIGUOUS` 제외만으로 모든 채택 사례가 쉽다고 단정할 수는 없습니다.
다만 동일 검수 모델이 불확실하다고 본 경계 사례가 제외되므로, 모델의 선별 편향은 남습니다.
모델의 AMBIGUOUS 판정은 문서 자체에 정답이 없다는 증명이 아닙니다.
정답이 있는 어려운 사례를 모델이 해석하지 못해 제외했을 가능성도 남으며, 이 통계만으로 그 편향이 해소됐다고 주장하지 않습니다.
현재 기준으로 경계 사례 전체를 평가하거나 실제 분포에 대한 성능으로 일반화할 수 없습니다.
상/중/하 등급은 일관성·유창성·형식 적합성에 대한 판정이고, privacy의 확정 가능성과 별개입니다.
기존 통과 기준을 유지합니다: 일관성 상, 형식 적합성 상, 유창성 상/중, 종합 상.

`summary.json.selection_audit`에서 다음을 확인할 수 있습니다.

- `latest_ambiguous_candidates`: 후보별 최신 유효 검수에서 AMBIGUOUS가 나온 수.
- `ever_ambiguous_candidate_outcomes`: 복구 전을 포함해 한 번이라도 AMBIGUOUS가 나온 후보의 현재 상태. 복구 후 채택된 사례도 구분합니다.
- `accepted_observed_expression_counts`: 최종 채택 문서에서 독립 검수의 최소 근거로 분류한 single/adjacent/nonadjacent 관계 수. 기존 `accepted_confirmed_expression_counts`는 호환용 동일 집계입니다.
- `accepted_confirmed_multisentence_relations`: 검수자가 한 문장으로 충분하지 않다고 판정했고 최소 두 문장의 근거가 필요한 채택 관계 수.
- `latest_ambiguity_candidate_rate`: 관계별 관찰 결과가 남은 최신 유효 검수 후보 중 모호한 후보의 비율. 검수 전 탈락을 분모에 넣지 않으며, 관찰이 없으면 null입니다.

근거 수와 거리는 맥락 요구의 관찰값이며 검증된 난이도 척도는 아닙니다.
단일 문장 대안이 있으면 single, 없고 연속 근거 대안이 있으면 adjacent, 모든 대안에 실제 간격이 있으면 nonadjacent입니다.
연속된 세 문장도 adjacent이며, S ID 숫자가 아니라 최종 본문의 `sent_idx` 순서로 계산합니다.
검수자의 한 문장 충분 여부와 실제 근거 그룹이 다르면 불일치를 기록하고 표현 방식은 실제 근거 그룹에서 계산합니다.
근거 거리 변화 자체로 문서를 탈락시키거나 복구하지 않습니다.
`accepted_entity_mention_count_histogram`과 `accepted_repeated_entities_by_group`은 반복의 실제 집계입니다.
엔티티별 mention 수·장면·문서 3구간·각 등장 위치는 `accepted_distribution.csv`에 기록합니다.
모호성은 `PRIVACY_AMBIGUOUS` 사유로 기록합니다. 기본 분리 흐름에서는 최종 검수 후 탈락하며, 이전 `legacy` 흐름에서만 남은 복구 예산으로 수정·재검수합니다.
끝까지 확정되지 않은 후보는 본문·계획·검수 버전·등급·탈락 사유를 실행 기록에 보존합니다.
추가 LLM 호출로 별도 난이도 등급을 만들거나 통과 기준을 완화하지 않습니다.

## 저장과 재개

실행 기록은 `runs/<run-id>/`, 최종 채택 문서는 `output/<run-id>/dataset/<domain>/`에 저장합니다.
최종 문서는 `sentences`, `entities`, `relations`이고 문장 ID는 `<document-id>_0`부터 연속인 문자열입니다.
`PII_set`, 문자 단위 `sent_seq`와 `labelling_seq`, entity mention span, 방향 있는 관계와 privacy를 포함합니다.
PII 관계가 하나라도 연결된 엔티티의 모든 실제 mention을 마스킹합니다.
NON-PII-only 엔티티와 역할 지시어 reference는 마스킹하지 않습니다.

writer lock으로 동일 run의 동시 쓰기를 막습니다.
단계 checkpoint를 재사용하므로 재개가 합격/탈락 수나 계획 호출을 중복 집계하지 않습니다.
저장 순서는 최종 문서 → accepted audit → SQLite ledger → manifest입니다.
audit 저장 후 DB commit 전에 중단되면 재개 시 audit를 확인해 복구합니다.
최종 문서 hash나 audit가 맞지 않으면 중단하며, 검사 없이 다시 채택하지 않습니다.

## 오프라인 점검

```bash
python3 -m unittest discover -s tests -v
python3 -m relation_pipeline run --run-id offline_verified_20261003 --offline --target-per-domain 1 --max-candidates 6
python3 -m relation_pipeline validate --run-id offline_verified_20261003
```

오프라인 모드는 API를 호출하지 않는 결정적 fixture입니다.
모의 검수는 fixture의 의도된 정보를 이용하므로 실제 문서 품질·privacy 판단이나 모델 합격률 평가에 사용할 수 없습니다.
audit·고정 설정·통계에는 `mode=offline`, 키 이름에는 `OFFLINE`, 요청 상태에는 `offline_simulated`,
수량 추정에는 `offline_fixture_only=true`가 표시됩니다. 실제 생성 데이터와 섞어 사용하지 마세요.
테스트에는 전체 단계, 길이 이어쓰기, 의미 실패 탈락, 검수 응답 재시도/등급 보존,
checkpoint 재개, audit 복구, 반복 span/BIO, 최소 근거 거리, 그래프 ID 정규화와 예산 제한이 포함됩니다.

현재 프롬프트 전문·입력·출력 계약은 [PROMPTS.md](PROMPTS.md), 단계별 변환과 이전 실행 예시는 [PIPELINE_FLOW.md](PIPELINE_FLOW.md)에 있습니다.
내부 계획 계약은 schema version 2.0입니다. 최종 증강 JSON 스키마는 유지합니다.
