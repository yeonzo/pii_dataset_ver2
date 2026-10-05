"""Materialize verbatim quotes from reviewer-selected IDs, without changing IDs.

No candidate evidence, intended privacy or intended reference target is used.
This removes a redundant copying task, not the independent semantic judgement.
"""
import copy
from .common import fail


def id_only_schema(schema):
    result=copy.deepcopy(schema)
    def visit(node):
        if not isinstance(node,dict):
            return
        if 'evidence_quotes' in node.get('properties',{}):
            del node['properties']['evidence_quotes']
            node['required'].remove('evidence_quotes')
        for value in node.values():
            if isinstance(value,dict):
                visit(value)
            elif isinstance(value,list):
                for item in value:
                    visit(item)
    visit(result)
    return result


def materialize_quotes(response, filled):
    result=copy.deepcopy(response)
    sentences={s['sentence_id']:s['sentence'] for s in filled['sentences']}
    items=[*result['relation_checks'],*result['reference_checks'],*result['missing_relations'],
           *result['person_checks']['observed_persons']]
    for item in items:
        ids=list(dict.fromkeys(sid for group in item['evidence_groups'] for sid in group))
        if any(sid not in sentences for sid in ids):
            fail('REVIEW_UNKNOWN_EVIDENCE','Reviewer selected an unknown sentence ID','RETRY_RESPONSE')
        item['evidence_quotes']=[{'sentence_id':sid,'quote':sentences[sid]} for sid in ids]
    return result


GUIDANCE = """
[근거 출력]
evidence_quotes는 출력하지 않는다. 독립적으로 선택한 evidence_groups의 원문 인용은 코드가 해당 문장 그대로 연결한다.
각 안쪽 배열은 그 자체로 충분한 최소 근거 묶음이다. S1의 이름과 S2의 속성을 함께 읽어야 하면 [["S1","S2"]]이다.
[["S1"],["S2"]]는 각 문장 단독으로 관계 전체를 입증하는 두 대안일 때만 쓴다.
각 관계 근거 묶음에 source와 target의 실제 언급 또는 그 지시어의 선행 연결을 포함한다. 각 인물 근거에는 그 이름이 실제 등장하는 문장을 포함한다.
관계가 본문에 없으면 extractable=false로 보고한다. 인용을 맞추기 위해 의미를 있다고 판단하지 않는다.
"""
