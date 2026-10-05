"""Value-free entity and endpoint meaning supplied to document writers."""
from __future__ import annotations

from .formats import ONTOLOGY


TYPE_MEANINGS = {
    "NAME":"자연인의 이름이다. 기관·부서·계좌·주소·번호를 NAME으로 쓰지 않는다.",
    "ADDRESS":"개인 거주지 또는 조직 소재지의 주소다. plan의 귀속 주체를 문장에 함께 쓴다.",
    "WORKPLACE":"회사·기관·사업장 이름이다. 부서명이나 사람 이름으로 쓰지 않는다.",
    "DEPARTMENT":"WORKPLACE·SCHOOL 등 조직 내부의 부서 이름이다. 기관 자체로 쓰지 않는다.",
    "POSITION":"개인이 맡은 직위·직책 또는 조직의 직제상 직위다.",
    "SCHOOL":"학교·대학·교육기관 이름이다.",
    "MAJOR":"학교가 개설한 전공·학과·교육과정 이름이다.",
    "AGE":"특정 자연인의 나이다. 사람에게 귀속해 쓴다.",
    "DATE_OF_BIRTH":"특정 자연인의 생년월일이다. 사람에게 귀속해 쓴다.",
    "MOBILE_PHONE":"휴대전화 번호다. 개인 번호인지 조직 업무용 회선인지 plan의 귀속을 따른다.",
    "TELEPHONE":"유선 전화번호다. 개인 번호인지 기관 대표·부서 문의번호인지 plan의 귀속을 따른다.",
    "EMAIL":"이메일 주소다. 개인 메일인지 조직 접수·문의 창구인지 plan의 귀속을 따른다.",
    "RRN":"특정 자연인의 주민등록번호다. 사람의 신원 확인 속성으로만 쓴다.",
    "PASSPORT_NUMBER":"특정 자연인의 여권번호다. 사람의 신원·여행 서류 속성으로만 쓴다.",
    "DRIVER_LICENSE_NUMBER":"특정 자연인의 운전면허번호다. 사람의 자격·신원 속성으로만 쓴다.",
    "VEHICLE_NUMBER":"차량의 등록번호다. 개인 또는 조직 중 plan에 정한 소유·운영 주체를 밝힌다.",
    "BANK_ACCOUNT_NUMBER":"은행 계좌번호다. 개인 계좌인지 조직 정산·환불·납입 계좌인지 plan의 소유·용도를 따른다.",
    "CARD_NUMBER":"결제 카드번호다. plan에 정한 개인·조직의 카드 소유·사용 관계를 따른다.",
}

PUBLIC_RULES = {
    "WORKPLACE":"회사·기관 이름과 문서 절차에서 맡는 역할을 쓴다.",
    "DEPARTMENT":"어느 조직 안에서 어떤 업무를 담당하는 부서인지 쓴다.",
    "SCHOOL":"학교·교육기관 이름과 문서에서의 교육 역할을 쓴다.",
    "POSITION":"공개된 직제상 직위로 쓰며 특정 개인의 사적 정보로 만들지 않는다.",
    "MAJOR":"학교가 개설한 전공·과정으로 쓴다.",
    "TELEPHONE":"기관 대표번호나 부서 문의번호임을 밝히며 사람의 개인 번호로 쓰지 않는다.",
    "MOBILE_PHONE":"조직이 운영하는 현장·업무용 회선임을 밝히며 개인 휴대전화로 쓰지 않는다.",
    "EMAIL":"조직의 접수·문의 창구임을 밝히며 특정 개인의 메일로 쓰지 않는다.",
    "ADDRESS":"조직의 사업장·사무실·캠퍼스·방문 접수처 주소임을 주체와 함께 쓴다.",
    "VEHICLE_NUMBER":"조직이 보유·운행하는 업무 차량임을 소유 주체와 함께 쓴다.",
    "BANK_ACCOUNT_NUMBER":"조직 명의의 정산·환불·납입 계좌임을 용도와 주체와 함께 쓴다.",
}


def entity_write_guide(plan: dict, domain: str) -> list[dict]:
    meanings={x["relation"]:x["meaning"] for x in ONTOLOGY[domain]}
    entities={e["entity_id"]:e for e in plan["entities"]}
    links={e["entity_id"]:[] for e in plan["entities"]}
    for link in plan.get("person_entity_links",[]):
        links.setdefault(link["entity_id"],[]).append({k:link[k] for k in ("person_id","role","link_kind","relation_ids") if k in link})
    from .planning_seed import organization_bridges
    owners={r["target"]:r["source"] for r in organization_bridges(plan)}
    guides=[]
    for entity in plan["entities"]:
        eid,typ=entity["entity_id"],entity["entity_type"]
        relations=[]
        for rel in plan["relations"]:
            if eid not in (rel["source"],rel["target"]):
                continue
            side="source" if rel["source"]==eid else "target"
            other=rel["target"] if side=="source" else rel["source"]
            relations.append({"relation_id":rel["relation_id"],"endpoint_role":side,
                "relation":rel["relation"],"relation_meaning":meanings.get(rel["relation"],""),
                "counterpart":{"entity_id":other,"placeholder":f"<{entities[other]['entity_type']}:{other}>",
                    "entity_type":entities[other]["entity_type"],"document_role":entities[other]["context_role"]},
                "required_context":rel["context_reason"],"privacy_context":rel["target_privacy"]})
        public=entity["context_role"] in {"public_office_information","public_organization_information"} or all(r["privacy_context"]=="NON_PII" for r in relations)
        rule=(PUBLIC_RULES.get(typ,TYPE_MEANINGS[typ]) if public else
              "특정 개인에게 귀속되는 값이다. 연결된 NAME 인물과 소유·제출·사용 관계를 명확히 쓰고 다른 타입의 역할어를 붙이지 않는다.")
        if eid in owners:
            org=owners[eid]
            rule+=(f" 이 값의 주체는 당사자가 소속된 기관 <{entities[org]['entity_type']}:{org}>다."
                   " 당사자 본인의 연락처·주소·계좌 항목에 넣지 않고, 그 기관을 주어로 한 문장이나 기관 안내 항목에 쓴다.")
        guides.append({"entity_id":eid,"placeholder":f"<{typ}:{eid}>","entity_type":typ,
            "type_meaning":TYPE_MEANINGS[typ],"document_role":entity["context_role"],
            "person_links":links.get(eid,[]),"write_rule":rule,
            "relations":relations})
    return guides
