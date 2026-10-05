"""Document purpose and reader expectations within the existing 1–8 stages.

This is a genre/content brief, not a new relation ontology or a mention quota.
Every catalog subtype has an explicit purpose; shared section roles are only
used where the documents actually share a genre.
"""
from __future__ import annotations

import copy
import re
from difflib import SequenceMatcher


# purpose, writer voice, four section functions, substantive content to develop
CAREER = {
    "resume_form": ("지원자의 학력·경력·역량을 빠르게 확인할 수 있는 이력서", "applicant_form",
        ["지원자 기본 사항", "학력과 교육", "경력과 수행 업무", "역량 및 확인 사항"],
        "기간별 수행 업무와 역량을 기재한다. 없는 학력·기관·직위를 만들어 채우지 않는다."),
    "cover_letter": ("지원자가 자신의 경험을 근거로 지원 동기와 직무 적합성을 설명하는 자기소개서", "first_person_applicant",
        ["지원 동기와 관심", "구체적인 경험과 과제", "직접 한 행동과 성과", "배운 점과 향후 기여"],
        "주제와 관련한 경험 하나를 중심으로 어려움, 본인의 선택, 실행, 결과, 배운 점을 구체화한다."),
    "career_statement": ("지원자가 담당 업무와 기여를 구체적으로 증명하는 경력기술서", "first_person_professional",
        ["업무 및 프로젝트 개요", "담당 역할과 문제", "수행 방법과 성과", "기여 및 활용 역량"],
        "프로젝트의 문제, 본인의 담당 범위, 의사결정, 실행 내용, 성과를 구분한다."),
    "job_application": ("채용 심사에 필요한 지원 사항을 기재하는 입사지원서", "applicant_form",
        ["지원자와 지원 목적", "학력 및 경력", "직무 관련 경험", "지원 의사와 확인"],
        "지원 분야와 연결되는 경험·역량을 구체화하고 제출 정보는 항목에 간결하게 둔다."),
    "recommendation": ("추천인이 직접 관찰한 사실로 지원자의 역량을 평가하고 추천하는 추천서", "first_person_recommender",
        ["추천 대상과 관찰 관계", "관찰한 과제와 행동", "성과 및 역량 평가", "추천 의사와 맺음말"],
        "추천인의 관찰 근거, 주제와 관련해 지원자가 실제로 한 행동, 그 결과와 추천 이유를 연결한다."),
    "admission_application": ("입학·편입을 희망하는 지원자의 지원 사실과 학업 계획을 기재하는 원서", "applicant_form",
        ["지원 사항", "학업 이력", "지원 동기와 학업 계획", "제출 및 확인 사항"],
        "지원 목적과 이수 경험, 학업 계획을 연결한다. 보호자는 계획에 있을 때만 별도 역할로 쓴다."),
    "enrollment_certificate": ("특정 학생의 재학 또는 졸업 사실을 확인하는 증명서", "official_record",
        ["증명 대상", "학적 사항", "증명 내용과 기준", "발급 및 확인"],
        "재학·졸업 중 증명할 상태를 일관되게 기재한다. 홍보·상담 서사를 넣지 않는다."),
    "transcript": ("학생의 이수와 성적 관련 사항을 확인하는 성적증명서", "official_record",
        ["성적 증명 대상", "이수 및 성적 사항", "평가 기준과 해석", "발급 확인"],
        "이수·평가 항목을 읽기 쉽게 조직하고 항목의 설명을 실적 이야기로 바꾸지 않는다."),
    "scholarship_application": ("신청자가 장학금 신청 사유와 관련 활동·계획을 설명하는 신청서", "applicant_form",
        ["장학금 신청 사항", "신청 사유와 활동", "학업 및 활용 계획", "제출 정보와 확인"],
        "신청 사유, 관련 경험, 학업 계획을 연결한다. 보증인 정보는 계획에 있을 때만 쓴다."),
    "leave_return": ("학생이 휴학 또는 복학 의사를 밝히고 처리에 필요한 사항을 제출하는 신청서", "applicant_form",
        ["신청 구분과 대상", "신청 사유", "학업 및 복귀 계획", "처리와 확인 사항"],
        "휴학·복학 중 신청 구분을 일관되게 유지하고 사유와 후속 계획을 구체화한다."),
}

PURPOSES = {
    "contract": {
        "lease":"부동산 임대의 대상·대금·인도·반환 조건을 합의한다",
        "rental":"물품 대여의 사용·관리·반환 조건을 합의한다",
        "construction":"공사 범위·대금·검수·하자 처리 의무를 정한다",
        "loan":"금전 대여·상환과 당사자 의무를 정한다",
        "investment":"투자 내용·집행 조건·권리와 책임을 정한다",
        "shareholder":"주주의 권리·의결·지분 관련 합의를 정한다",
        "escrow":"예치와 지급·반환 조건 및 확인 절차를 정한다",
        "settlement":"합의 대상과 지급·정산·의무 완료 조건을 정한다",
        "service":"용역의 범위·산출물·대금·검수·변경 절차를 합의한다",
        "sale":"매매 목적물·대금·인도·하자 처리 조건을 정한다",
        "consign":"위탁 업무의 범위·보고·책임과 정산을 정한다",
        "joint_venture":"공동 투자·운영·배분과 의사결정 조건을 정한다",
        "franchise":"가맹 운영·지원·비용·계약 종료 조건을 정한다",
        "partnership":"동업자의 출자·업무 분담·손익 배분을 정한다",
        "agency":"대리점 업무·권한·수수료·거래 조건을 정한다",
        "distribution":"유통·판매의 공급·인도·정산·반품 조건을 정한다",
        "advertising":"광고 제작·집행 범위·승인·성과물·대금을 정한다",
        "maintenance":"유지보수 대상·점검·장애 대응·검수 조건을 정한다",
        "supply":"원자재 규격·수량·납기·검수·대금 조건을 정한다",
        "transfer":"양도 대상·인수·대금·권리 이전 조건을 정한다",
        "car_rental_short":"단기 차량 대여·운행·반납·사고 처리 조건을 정한다",
        "car_rental_long":"장기 차량 이용·관리·납부·중도 종료 조건을 정한다",
        "car_rental_corp":"법인 차량 사용·운행 책임·관리·반납 조건을 정한다",
        "accident_rear":"추돌 경위와 합의·지급·이행 확인 사항을 정한다",
        "accident_intersection":"교차로 충돌의 합의 대상과 이행 조건을 정한다",
        "accident_parking":"주차장 접촉사고의 손해·합의·처리 사항을 정한다",
        "accident_pedestrian":"보행자 사고의 합의 범위와 후속 이행 사항을 정한다",
        "accident_single":"단독사고 경위와 자기부담금 확인·처리를 기록한다",
        "overseas_visa":"비자 신청의 목적과 제출·확인 사항을 기록한다",
        "overseas_assignment":"해외파견의 업무·기간·지원·당사자 의무를 정한다",
        "overseas_trip":"해외출장의 목적·업무·일정·보고 계획을 신청한다",
        "employment":"업무·근로 조건·보수·당사자 의무를 합의한다",
        "freelance":"독립 용역의 업무·산출물·대금·검수 조건을 정한다",
        "consulting":"자문 범위·수행 방법·산출물·대금과 책임을 정한다",
        "nda":"비밀정보의 범위·이용 목적·보호·반환 의무를 정한다",
        "license":"이용 허락의 범위·제한·대가·유지 조건을 정한다",
        "it_outsourcing":"IT 업무·납품·검수·변경·운영 책임을 정한다",
        "research":"공동 연구의 목표·분담·성과·권리 조건을 정한다",
        "data_processing":"처리위탁의 목적·범위·보호·반환·감독 의무를 정한다",
    },
    "financial": {
        "loan_application":"대출 목적·상환 계획과 심사에 필요한 정보를 신청한다",
        "card_application":"카드 신청 의사와 이용·결제 관련 확인 사항을 기재한다",
        "account_opening":"계좌 개설 목적과 신청·확인 사항을 기재한다",
        "insurance_subscription":"보험 신청 목적과 계약자·피보험자·수익자 역할을 기재한다",
        "wire_transfer":"송금 목적·출처·수취·확인 절차를 기재한다",
        "fraud_report":"피해 경위·확인한 사실·조치와 요청 사항을 신고한다",
    },
    "legal": {
        "incident_report":"관찰한 사건 경위·행동·결과를 순서 있게 기록한다",
        "legal_consultation":"상담 쟁점·확인한 사실·설명과 후속 과제를 기록한다",
        "complaint_filing":"신고 취지·구체적 행위·근거와 조사 요청을 기재한다",
        "damage_claim":"손해 발생 경위·피해 내용·근거와 청구 취지를 기재한다",
        "witness_statement":"직접 목격한 사실과 추정·전해 들은 내용을 구분하여 진술한다",
        "police_statement":"진술인의 경험·사건 경위·확인 사항을 진술한다",
        "mediation_application":"분쟁 경위·쟁점·기존 협의와 원하는 조정안을 신청한다",
    },
    "medical": {
        "registration":"진료를 원하는 이유와 접수에 필요한 사항을 기록한다",
        "questionnaire":"증상·경과·관련 생활 상태와 확인 사항을 문진한다",
        "health_checkup":"검진 목적·관련 상태·확인 항목을 문진한다",
        "payment":"수납 목적·내역·결제와 확인 사항을 기록한다",
        "insurance_claim":"의료비 청구의 사유·관련 내역·서류와 수령 절차를 기록한다",
        "telemedicine_consult":"상담 이유·증상 경과·확인 내용과 후속 안내를 기록한다",
        "checkup_result":"검진 항목·관찰 결과·해석 범위와 후속 확인 사항을 통보한다",
        "surgery_consent":"동의 대상·설명 내용·질문과 동의 확인 사항을 기록한다",
    },
    "support": {
        "complaint_product":"상품의 구체적 문제·확인 과정과 고객이 원하는 처리를 기록한다",
        "complaint_service":"서비스 이용 문제·응대·확인과 조치 계획을 기록한다",
        "support_ticket":"문의 증상·재현·확인·처리와 다음 단계를 기록한다",
        "refund_request":"환불 사유·확인 근거·처리 결정과 후속 안내를 기록한다",
        "delivery_issue":"배송 문제·조회 및 확인·처리와 안내를 기록한다",
        "as_request":"고장 증상·점검·수리 접수와 인계 사항을 기록한다",
        "billing_dispute":"청구 이의 사유·대조 근거·판단과 처리 결과를 기록한다",
        "account_inquiry":"계정 문의의 증상·본인 확인·처리와 후속 안내를 기록한다",
    },
}


def brief_for(domain, subtype):
    if domain == "career_education":
        goal, voice, sections, substance = CAREER[subtype]
    else:
        goal = PURPOSES[domain][subtype]
        voice = "official_record" if domain in {"contract", "financial"} else "staff_record"
        if domain == "contract":
            sections = ["당사자와 목적", "업무 범위와 조건", "이행·확인 절차", "책임과 마무리"]
            substance = "목적물·수행 범위·의무·확인·변경 조건을 실제 조항으로 쓴다. 법조문 번호나 법적 효력을 지어내지 않는다."
        elif domain == "financial":
            sections = ["신청·신고 목적", "사실과 관련 내역", "확인 및 요청 사항", "처리와 후속 안내"]
            substance = "신청 사유나 사건 경위와 처리 목적을 구체화한다. 계획된 자산의 소유·출처·도착지를 바꾸지 않는다."
        elif domain == "medical":
            sections = ["접수·작성 목적", "경과 및 확인 항목", "설명과 처리 내용", "확인 및 후속 사항"]
            substance = "접수 사유·증상 경과·확인 질문·행정 처리를 구체화한다. 근거 없는 확정 진단·치료 결과를 만들지 않는다."
        elif domain == "legal":
            sections = ["사건과 작성 취지", "구체적인 경위", "쟁점과 확인 근거", "요청과 후속 사항"]
            substance = "사건 전후의 행동·쟁점·당사자의 요청을 구체화한다. 관찰과 주장을 구분하고 허위 법조문을 만들지 않는다."
        else:
            sections = ["문의와 문제", "확인한 내용", "처리와 판단 이유", "결과 및 후속 안내"]
            substance = "문제의 구체적인 모습·확인 방법·조치의 이유·결과를 연결한다. 미확인 사항은 미확인으로 남긴다."
    return {"goal":goal, "writer_voice":voice, "section_functions":sections,
            "substantive_content":substance,
            "entity_usage":"이름·기관·연락처는 사실을 전달하는 데 필요할 때 쓴다. 엔티티 없는 업무·경험 설명도 충분히 쓸 수 있다.",
            "supporting_information":"공용 연락처·주소 등은 자연스러운 안내·머리말·말미에 간결히 묶고 본문 주제로 확대하지 않는다.",
            "avoid":["문서가 작성되었다는 설명으로 실제 문서를 대신하기", "동일 사실을 바꿔 말하며 분량 채우기", "정보가 중요하다는 추상적 해설", "PII·NON_PII 판정이나 데이터 생성 과정의 해설"]}


def apply_purpose(condition, cfg):
    if cfg.get("document_policy", "legacy") not in {"purpose_v1", "purpose_v2", "prose_v1"}:
        return condition
    scope = cfg.get("purpose_subtypes")
    if scope and condition["domain"]+"/"+condition["subtype"] not in scope:
        return condition
    brief = brief_for(condition["domain"],condition["subtype"])
    condition["document_policy"] = cfg["document_policy"]
    condition["document_brief"] = copy.deepcopy(brief)
    if not cfg.get("selection",{}).get("viewpoint"):
        condition["narrative_viewpoint"] = brief["writer_voice"]
    if condition["domain"] == "career_education":
        labels = {"chronological":"경험의 시간순 서술", "topical":"핵심 항목별 구성",
                  "problem_action_result":"문제·행동·성과 중심 구성", "narrative":"연결된 자유 서술"}
        condition["layout_variant_label"] = labels.get(condition["layout_variant"],condition["layout_variant_label"])
    # IDs/kinds/weights/ordering are preserved; titles express this genre's purpose.
    for section,title in zip(condition["section_plan"],brief["section_functions"]):
        section["title"] = title
    return condition


PLAN_GUIDANCE = """
[문서 목적 구체화]
condition.document_brief를 바탕으로 독자가 실제로 읽을 문서의 사건·경험·업무를 계획한다.
scene_notes.outline은 생성 지시문이 아니라 구체적인 합성 사실 메모다. 각 장면이 새로 전달할 사실·행동·판단·결과를 2~4개 적는다.
주제는 제목에만 넣지 말고 실제 문제·선택·실행·성과에 반영한다. 수치·기간·과정·익명 역할 같은 일반 업무 사실은 설계해도 된다.
새로운 실명·기관·식별값 또는 등록된 endpoint 사이의 계획 밖 온톨로지 관계는 만들지 않는다. 이 제한은 업무 사실·경험 설명을 금지하지 않는다.
각 관계의 context_reason도 '명시한다/연결한다'라는 지시가 아니라 누가 무엇을 왜 했는지에 대한 사실을 적는다.
연락처·주소는 보조 정보가 필요한 장면에 함께 배치한다. 한 관계마다 별도 문단을 배정하거나 모든 장면을 개인정보로 채우지 않는다.
"""

DRAFT_GUIDANCE = """
[독자가 읽을 문서]
condition.document_brief의 목적과 화자에 맞는 실제 문서를 쓴다. 추천서는 추천인의 추천문, 자기소개서는 지원자의 자기소개다.
계획된 주제·장면의 구체적 사실을 충분히 전개한다. 상황→선택·행동→결과·평가가 연결되어야 하며 말만 바꾼 반복은 전개가 아니다.
기관 연락처·주소·학교 이름은 문서의 필요 지점에 자연스럽게 넣고, 이미 전달한 사실을 분량 때문에 반복하지 않는다.
문장마다 placeholder가 있을 필요는 없다. 엔티티 없는 문제 설명·판단 근거·업무 과정·관찰 결과로 본문을 전개해도 된다.
계획 밖 엔티티·관계 금지는 일반적인 업무 설명 금지가 아니다. 계획과 모순되지 않는 비식별 배경과 구체적 행동을 쓸 수 있다.
1인칭의 '저'나 주요 인물의 역할 지시어가 관계 근거로 쓰이면 해당 E의 REF로 등록한다. 메타 설명이나 privacy 해설을 쓰지 않는다.
"""

FACT_PLAN_GUIDANCE = """
[사실 메모 출력 계약]
이번 출력에서 scene_notes는 {purpose, facts}다. outline 필드는 반환하지 않는다.
facts는 각 장면에서 실제로 전달할 서로 다른 합성 사실 2~5개다. 글쓰기 지시·소제목·'중요하다'는 평가만으로 채우지 않는다.
예: '개선 활동을 구체적으로 설명한다'는 사실이 아니다. '같은 문의를 두 번 분류하는 절차 때문에 회신이 지연되었고, 담당자는 분류 항목을 합친 뒤 미처리 건을 매일 대조했다'처럼 설계한다.
주제에서 구체적인 어려움, 선택의 이유, 실제 행동, 관찰한 변화 또는 남은 한계를 정하고 장면 간 이어지게 한다. 성과를 쓰면 무엇을 어떻게 확인했는지도 정한다.
계약·신청 양식은 실제 업무 범위·조건·요청·확인 사항을 사실로 정한다. '서비스의 세부 사항' 같은 미완성 항목으로 대신하지 않는다.
등록 인물의 활동은 그 인물의 역할 코드로 서술하고, 기관 공용 정보는 문서의 보조 정보가 필요한 장면에 배정한다.
seed의 빈 scene_id와 relation_ids는 미배정 표시다. 모든 R을 자연스러운 SC에 한 번씩 배정하며 한 장면에 여러 관계 또는 관계 없이 내용만 있을 수 있다.
context_reason에는 실제 정보 귀속·용도·행위를 적는다. 근거 없는 조직 간 서비스 제공을 단순 연락·제출과 혼동하지 않는다.
"""

FACT_DRAFT_GUIDANCE = """
[사실 메모를 본문으로 전개]
scenes.outline의 사실을 문서 화자의 말로 구체화한다. 업무 상황, 선택 이유, 수행 순서, 확인한 결과를 서로 다른 문장으로 전개한다.
한 사실을 바꿔 말하며 target_chars를 채우지 않는다. 프로젝트라면 문제 발견→검토한 대안→선택→실행 중 조정→결과 확인→남은 한계를 설명할 수 있다.
첫머리에서 화자의 역할과 이름을 일치시킨다. 추천인 자신과 추천 대상 지원자를 혼동하지 않는다.
관계 복구는 sentence 또는 linked_text의 완전한 문장으로 쓴다. endpoint의 순서는 한국어 의미에 맞게 정한다.
"""

REVIEW_GUIDANCE = """
[문서 목적·자연스러움 검수]
topic과 document_expectation은 독자가 원하는 문서의 기준이다. 엔티티·관계를 모두 담았어도 문서 목적을 이루지 못하면 suitability는 상이 아니다.
추천서는 관찰 근거·역량 평가·추천 의사, 자기소개서는 본인의 경험·행동·배운 점·지원 동기가 실제 본문에 있어야 한다.
주제와 관련한 구체적 과정이 없이 '중요하다/필수다/포함된다'만 반복하거나, 연락처·주소 설명이 본문을 지배하면 suitability를 중 또는 하로 평가한다.
같은 사실을 여러 문장으로 바꿔 말한 것도 의미 반복이다. 지시어/이름의 자연스러운 재언급 자체와 구분한다.
개선이 필요한 문장은 text_issues(kind=format)에 정확한 S ID와 구체적 수정 지시를 남긴다. 추가 온톨로지 관계의 근거가 없는 일반 업무 설명은 오류로 만들지 않는다.
"""


def prose_metrics(draft):
    """Diagnostic observations, never mandatory entity-density or repeat targets."""
    texts = [s["text"] for s in draft.get("segments",[]) if s.get("kind") != "heading"]
    normalized = [re.sub(r"\s+", "", re.sub(r"\{josa:[^}]+\}", "", re.sub(r"<([A-Z_]+):[EC]\d+>",r"<\1>",s))) for s in texts]
    redundant = []
    for i,text in enumerate(normalized):
        if len(text) >= 24 and any(SequenceMatcher(None,text,earlier,autojunk=False).ratio() >= .82 for earlier in normalized[:i] if len(earlier)>=24):
            redundant.append(i)
    return {"sentence_count":len(texts), "near_duplicate_sentences":len(redundant),
            "near_duplicate_share":round(len(redundant)/max(len(texts),1),4),
            "entity_free_sentence_share":round(sum(not re.search(r"<[A-Z_]+:E\d+>",s) for s in texts)/max(len(texts),1),4),
            "basis":"Placeholder type normalization; SequenceMatcher >= .82; diagnostic only, not semantic proof or an acceptance gate."}
