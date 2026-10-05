"""One operational privacy definition shared by planning, writing and review."""
from __future__ import annotations

import copy

from .common import digest

POLICY = {
    "version":"3.0",
    "unit":"관계의 문서 내 의미·귀속으로 판정한다. 값 외형이나 엔티티 타입만으로 판정하지 않는다.",
    "PII":"문서의 특정 개인에게 식별자·연락처·주소·소속·학력·금융정보·활동 사실을 귀속하거나, 개인을 식별·연결하는 관계. 가족·보호자 등 개인 사이의 사적 관계도 포함한다.",
    "NON_PII":"기관 공용 정보의 의미 관계 또는 명시적 가상 사례/작품 인물의 설정 관계. 공개 위키·전기 소개로 분명히 구분된 인물의 출처로 확인한 공개 약력 관계도 이 데이터셋에서는 NON_PII로 분류한다. 공개 인물의 모든 정보가 NON_PII라는 뜻은 아니다.",
    "AMBIGUOUS":"전체 본문을 읽어도 관계의 귀속·역할을 정할 근거가 부족하거나 해석이 충돌하는 경우. 여러 문장의 근거가 필요하다는 사실만으로 AMBIGUOUS가 되지 않는다.",
    "name_policy":"actual_party: 문서의 신청인·환자·지원자·고객·담당 대표는 합성 이름이어도 PII 맥락. example_person: 본문에서 가상 예시 또는 작품 등장인물임이 명시된 설정 관계만 NON_PII. public_reference: 공개 위키·전기 소개로 서술하며 출처로 확인된 공개 약력만 NON_PII. 유명인이라는 추측이나 위키 존재만으로 판정하지 않는다. 같은 사람을 문서의 실제 계약/진료 당사자로 쓰거나 비공개 연락처·금융·신원 정보를 귀속하면 PII다. 참고 인물을 실제 당사자의 관계망과 혼동하지 않는다.",
    "scope":"공개 약력의 NON_PII는 이 데이터셋의 명시적인 운영 정의이며 법적 비개인정보 판정이 아니다. 실제 값의 합성 여부와 문서 내 역할은 구분한다.",
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
