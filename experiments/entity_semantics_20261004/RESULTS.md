# Entity 의미 계약 보강 결과 — 2026-10-04

기존 증강 프롬프트의 `how_to_write_it` 방식을 현재 관계 계획 파이프라인에 맞게 확장했다. 초안과 국소 수정 입력에 `entity_write_guide`를 추가해 18개 Entity Type의 의미, 각 E의 문서 역할, 개인/기관 귀속, 작성 규칙, 연결된 counterpart와 관계 의미·필수 맥락을 전달한다. 고정 인명이나 실제 슬롯값은 넣지 않는다.

분리 흐름의 관계 복구는 source와 target이 함께 있는 완전한 한 문장만 허용한다. 코드 검사는 `신고인 <BANK_ACCOUNT_NUMBER>`, `주민등록번호 <NAME>`, `주소 <NAME>`, `부서 <TELEPHONE>` 같은 역할어·타입 역전을 `ENTITY_TYPE_CONTEXT`로 거절한다. 전각 placeholder도 ASCII typed placeholder로 정규화한다.

보강 전 형식상 채택됐던 금융 문서 두 건을 수동 감사했다. 한 건은 전각 placeholder 6개가 치환되지 않았고, 다른 한 건은 타입·역할 역전 8건이 있었다. 두 문서는 후보 폴더에 감사용으로 격리하고 최종 dataset 및 accepted 집계에서 제거했다.

보강 후 `entity_semantics_financial_20261004_v1`에서 금융 후보 3건을 실행했다. 최종 채택은 0/3이다.

| 후보 | 탈락 사유 | 해석 |
| --- | --- | --- |
| 1 | `ADDITION_IDENTIFIER` | 분량 추가 응답이 새 엔티티 토큰/식별값을 만들었다. |
| 2 | `ENTITY_TYPE_CONTEXT` | `신고인 <WORKPLACE:E2>` 역할 역전을 새 코드 검사가 차단했다. |
| 3 | `ADDITION_SIZE` | 목표 약 822자에 268자만 생성했다. |

세 후보 모두 계획·초안까지 통과했지만 5단계에서 탈락했으며 검수·채택까지 간 문서는 없다. 의미 계약이 오류를 숨겨 통과시키는 대신 타입 역전을 생성 단계에서 차단하는 것은 확인했다. 자동 테스트 173건이 통과했다.
