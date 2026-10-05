"""One operational privacy definition shared by planning, writing and review."""
from __future__ import annotations

import copy

from .common import digest

POLICY = {
    "version":"2.0",
    "unit":"관계의 문서 내 의미·귀속으로 판정한다. 값 외형이나 엔티티 타입만으로 판정하지 않는다.",
    "PII":"문서의 특정 개인에게 식별자·연락처·주소·소속·학력·금융정보·활동 사실을 귀속하거나, 개인을 식별·연결하는 관계. 가족·보호자 등 개인 사이의 사적 관계도 포함한다.",
    "NON_PII":"실제 의미 관계이며 개인 귀속이 없는 관계. 기관이 공식적으로 공동 운영하는 문의 채널·조직 구성·정산 계좌·공동 관리 자산·기관 간 업무 관계 등이 해당한다.",
    "AMBIGUOUS":"전체 본문을 읽어도 관계의 귀속·역할을 정할 근거가 부족하거나 해석이 충돌하는 경우. 여러 문장의 근거가 필요하다는 사실만으로 AMBIGUOUS가 되지 않는다.",
    "name_policy":"실제 당사자·환자·지원자·고객·보호자·담당 대표의 이름은 개인 맥락이다. 명시된 예시 장면의 예시 인물만 별도 예시 인물로 구분할 수 있다. 예시 이름에 인구통계/식별자 속성을 임의 확장하지 않는다. 유명인 여부를 추측하지 않는다.",
    "synthetic_values":"모든 값이 합성이라는 사실은 NON_PII의 근거가 아니다. 합성 문서 안에서 실제 당사자로 쓰이면 개인 귀속으로 판단한다.",
    "examples":[
        {"text":"신청인이 자신의 연락처로 유선 번호를 기재했다.","label":"PII"},
        {"text":"고객지원 부서가 휴대폰 형식의 번호와 개인 메일처럼 보이는 주소를 공동 문의 창구로 운영한다.","label":"NON_PII"},
        {"text":"계좌를 개인의 생활비 계좌로 등록했다.","label":"PII"},
        {"text":"기관의 공동 정산 계좌로 납부를 접수한다.","label":"NON_PII"}],
    "annotation":"독립 검수에서 확정된 관계만 채택한다. 한 노드가 PII 관계에 참여하면 그 노드의 모든 실제 mention을 마스킹하며 관계별 privacy_label은 별도로 보존한다. 이는 노드 마스킹 규칙이지 모든 관계를 PII로 바꾸는 규칙이 아니다.",
}
POLICY_HASH = digest(POLICY)


def privacy_input():
    return copy.deepcopy(POLICY)
