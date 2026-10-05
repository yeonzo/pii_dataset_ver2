"""Original-generator-inspired authoring inside stages 2/4, not a new pipeline.

The model writes substantive prose; code owns mechanical sentence identifiers.
Code-derived evidence is only a structural candidate, never a semantic label.
"""
from __future__ import annotations

import copy
import itertools
import re

from .privacy import privacy_input
from .schemas import DRAFT, obj, array, string, validate

PLAN_SYSTEM = """[작업]
실제 한국어 문서의 내용을 설계한다. 문서 종류·주제를 보고 하나의 구체적인 사건/경험/업무를 창작한다.
[내용]
story의 situation, action, outcome에는 실제로 일어난 합성 사실을 적는다. '설명한다/기술한다/강조한다'라는 작성 지침은 쓰지 않는다.
예: '오류를 개선한 경험을 서술한다' 대신 '같은 요청이 두 번 접수되어 담당자가 처리 기록을 대조했고, 중복 항목을 합친 뒤 남은 요청을 다시 확인했다'.
일반적인 업무 과정·수치·기간·판단·어려움·결과를 구체적으로 만들어도 된다. 등록되지 않은 실명·기관·식별정보·추가 소속/소유 관계만 만들지 않는다.
문서의 정보는 본문 독자에게 유용해야 한다. 기관 연락처의 중요성을 설명하며 문단을 채우지 않는다.
[고정 조건]
entities/relations의 인물·endpoint·관계·privacy는 고정이다. relation_contexts는 누가 무엇을 왜 했는지 명확한 사실로 적고 각 관계를 한 SC에 배정한다.
관계 하나마다 장면을 만들 필요는 없다. section의 목적에 맞춰 scene_notes.outline에 서로 다른 구체적 내용을 배치한다.
참고 인물은 실제 신청인과 별개다. 가상 사례/작품이면 그 구분을 내용에 넣고, 공개 인물 소개는 reference_context에서 확인한 사실만 사용한다.
[출력]
JSON: story={situation,action,outcome}, relation_contexts={R:{context_reason,scene_id}}, scene_notes={SC:{purpose,outline}}.
본문이나 실제 엔티티 값을 쓰지 않는다.
"""

DRAFT_SYSTEM = """[작업]
한국어 실무 문서의 완성 본문을 작성한다. document의 종류·화자·주제와 story의 구체적 경험/업무를 중심으로 읽히는 글을 쓴다.
[핵심]
1. sections의 각 구간을 한 번씩 작성하고 target_chars에 맞게 상황·행동·판단 이유·결과를 충분히 전개한다. 문장 수를 채우려고 반복하지 않는다.
2. 추천서는 추천인이 관찰한 행동으로 추천하는 글, 자기소개서는 본인의 경험과 직무 적합성을 설명하는 글이다. 문서 쓰는 방법을 본문에 설명하지 않는다.
3. entities의 모든 토큰을 필요한 지점에 쓰고 relations의 사실을 정확히 담는다. 같은 대상을 재언급하면 같은 토큰을 쓴다. 연락처·주소는 필요한 안내에서 간결히 다룬다.
4. 일반적인 업무 설명·수치·기간·사고 과정은 자유롭게 구체화한다. 새 실명·기관·식별값 또는 계획 밖 소속·거래·소유 관계를 만들지 않는다. 실제 값 대신 <TYPE:E번호>만 사용한다.
5. 이름 없이 경험을 설명하는 문장도 자연스럽게 쓴다. 지시어는 앞 문맥에서 대상을 알 수 있게 쓴다. 임의 REF 토큰은 쓰지 않는다. 조사는 <NAME:E1>{josa:은/는}처럼 처리한다.
6. 가상 예시·작품 인물은 본문에서 그렇게 소개한다. 공개 위키 인물은 공개 소개의 맥락으로 쓰고 확인된 약력만 사용한다. 실제 당사자의 사생활과 연결하지 않는다.
[출력]
JSON {sections:{지정된 section ID:[문장 또는 양식 한 줄,...]}}만 반환한다.
각 배열 원소는 한 문장 또는 한 줄이다. 문장 ID, 근거 ID, privacy 해설은 쓰지 않는다.
"""


def plan_request(payload, schema):
    seed=payload['seed_plan']
    condition=payload['condition']
    wire=obj(story=obj(situation=string(),action=string(),outcome=string()),**copy.deepcopy(schema['properties']))
    compact={'document':{k:condition[k] for k in ('subtype_label','topic','narrative_viewpoint','document_brief') if k in condition},
        'sections':condition['section_plan'],'entities':seed['entities'],
        'relations':[{k:r[k] for k in ('relation_id','source','target','relation','target_privacy')} for r in seed['relations']],
        'scenes':[{k:s[k] for k in ('scene_id','section_id','purpose')} for s in seed['scenes']],
        'persons':seed['persons'],'privacy_policy':payload['privacy_policy'],
        'ontology':payload['ontology'],'feedback':payload.get('feedback',[])}
    if condition.get('reference_context'):
        compact['reference_context']={k:v for k,v in condition['reference_context'].items() if k!='source'}
    return compact,wire


def draft_request(condition, plan):
    placeholders={e['entity_id']:f"<{e['entity_type']}:{e['entity_id']}>" for e in plan['entities']}
    pattern='^(?:[^<>]|'+'|'.join(re.escape(p) for p in placeholders.values())+')+$'
    schema=obj(sections=obj(**{s['section_id']:{**array({'type':'string','pattern':pattern}),
        'minItems':1,'maxItems':80} for s in condition['section_plan']}))
    from .content_depth import content_depth
    # No target-derived minimum sentence count; rendered length gate remains.
    payload={'document':{k:condition[k] for k in ('subtype_label','topic','narrative_viewpoint','length_target','min_chars','document_brief') if k in condition},
        'story':plan.get('document_story',{}),'sections':condition['section_plan'],
        'scene_content':[{k:s[k] for k in ('section_id','outline')} for s in plan['scenes']],
        'entities':[{'token':placeholders[e['entity_id']],'role':e['context_role']} for e in plan['entities']],
        'relations':[{'source':placeholders[r['source']],'target':placeholders[r['target']],
                      'meaning':r['context_reason'],'privacy':r['target_privacy']} for r in plan['relations']],
        'persons':plan.get('persons',[]),'privacy_policy':privacy_input()}
    payload['content_depth'] = content_depth(condition)
    if condition.get('reference_context'):
        payload['reference_context']={k:v for k,v in condition['reference_context'].items() if k!='source'}
    if condition.get('document_policy')=='prose_v2':
        from .repair_tasks import relation_repair_schema
        # Reuse the provider-tested complete-sentence contract. The previous
        # lookahead-pattern probe returned zero-token incomplete responses.
        sections={}
        for section in condition['section_plan']:
            sid=section['section_id']
            scene=next(s['scene_id'] for s in plan['scenes'] if s['section_id']==sid)
            facts={}
            for relation in plan['relations']:
                if relation['scene_id']!=scene:
                    continue
                unit=relation_repair_schema(placeholders[relation['source']],placeholders[relation['target']])
                unit['anyOf']=unit['anyOf'][:2]
                facts[relation['relation_id']]=unit
            sections[sid]=obj(relation_facts=obj(**facts),context={'type':'string','pattern':pattern})
        schema=obj(sections=obj(**sections))
        payload['section_relation_ids']={sid:list(node['properties']['relation_facts']['properties']) for sid,node in sections.items()}
    return payload,schema


def decode_prose(response, condition, plan, schema):
    validate(response,schema)
    scene_by_section={s['section_id']:s['scene_id'] for s in plan['scenes']}
    segments=[]
    for section in condition['section_plan']:
        kinds=section['allowed_kinds']
        content=response['sections'][section['section_id']]
        if isinstance(content,dict):
            fragments=[]
            for unit in content['relation_facts'].values():
                fragments.extend([unit['text']] if unit['form']=='sentence' else [unit['source_text'],*unit['bridge_sentences'],unit['target_text']])
            content=[*fragments,content['context']]
        for text in ([content] if isinstance(content,str) else content):
            kind=('question' if text.rstrip().endswith(('?','？')) else 'answer') if 'question' in kinds else ('prose' if 'prose' in kinds else kinds[0])
            segments.append({'sentence_id':f'S{len(segments)+1}','section_id':section['section_id'],
                'scene_id':scene_by_section[section['section_id']],'kind':kind,'text':text})
    mentions={e['entity_id']:[i for i,s in enumerate(segments) if f"<{e['entity_type']}:{e['entity_id']}>" in s['text']] for e in plan['entities']}
    evidence=[]
    for relation in plan['relations']:
        a,b=mentions[relation['source']],mentions[relation['target']]
        common=sorted(set(a)&set(b))
        groups=[[segments[i]['sentence_id']] for i in common]
        if not groups and a and b:
            # Mechanical witness of endpoint occurrence only. Stage 7 does not
            # receive this guess, and must independently justify the relation.
            i,j=min(itertools.product(a,b),key=lambda ij:(
                sum(segments[k]['scene_id']!=relation['scene_id'] for k in ij),abs(ij[0]-ij[1]),ij))
            groups=[[segments[k]['sentence_id'] for k in sorted({i,j})]]
        evidence.append({'relation_id':relation['relation_id'],'evidence_groups':groups})
    draft={'draft_version':1,'segments':segments,'refs':[],'relation_evidence':evidence}
    validate(draft,DRAFT)
    return draft
