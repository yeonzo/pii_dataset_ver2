"""One-section additions; unchanged originals, small responses, no LLM fact checker."""
import math
import re

from .call_policy import validated_request
from .common import fail
from .content_depth import content_depth
from .schemas import obj, string, array, validate
from .stages.stage05_assemble import LITERALS, apply_patch, diagnose

SYSTEM = '''[목적]
확정된 문서에서 지정 항목에 들어갈 새 내용만 추가한다.
[규칙]
1. section과 scene_facts에 맞춰 facts_to_develop 중 아직 설명하지 않은 내용을 골라 target_new_chars 정도로 작성한다.
2. 기존 본문 전체를 읽고 날짜·금액·인물·처리 상태와의 모순, 같은 뜻의 재진술, 일반 안내문 반복을 피한다. 새 엔티티·관계·식별값·placeholder는 만들지 않는다.
3. 기존 문장은 반환하지 않는다. 새로운 문장만 sentences에 쓰며 각 원소는 완전한 문장 또는 해당 양식의 한 줄이다. 문장 조각·빈 문자열·줄바꿈을 넣지 않는다.
4. 계획에서 허용하는 비식별 업무 경위·확인 결과·판단 근거를 구체화한다. 이미 확정된 값이나 사건을 바꾸지 않는다.
[출력]
{"section_id":"지정 ID","sentences":["추가할 문장", "추가할 문장"]} JSON만 반환한다.
'''


def normalized(text):
    text=re.sub(r'<[^>]+>|\{josa:[^}]+\}', '', text)
    return re.sub(r'\s+','',text)


def near_duplicate(a,b):
    if a==b:
        return True
    if min(len(a),len(b))<30:
        return False
    aa={a[i:i+4] for i in range(len(a)-3)}
    bb={b[i:i+4] for i in range(len(b)-3)}
    return len(aa&bb)/max(1,len(aa|bb))>=.82


def numeric_fields(text):
    pairs=re.findall(r'([가-힣]{2,12})\s*[:：]\s*([0-9][0-9,./-]*\s*(?:원|개|명|일|개월|년|%))',text)
    return {k:re.sub(r'[,\s]','',v) for k,v in pairs}


def build_request(draft,condition,plan,diagnosis,remaining):
    deficits=diagnosis['metrics'].get('section_shortages',{})
    section=max(condition['section_plan'],key=lambda s:deficits.get(s['section_id'],0))
    scene=next(s for s in plan['scenes'] if s['section_id']==section['section_id'])
    # This caps only one addition's size, not total document length.
    target=min(1000,max(200,math.ceil(diagnosis['metrics']['shortage_chars']/max(1,remaining))+100))
    schema=obj(section_id=string([section['section_id']]),
               sentences={**array(string()),'minItems':2,'maxItems':18})
    payload={'document_type':condition['subtype_label'],'section':section,
             'scene_facts':scene['outline'],'facts_to_develop':content_depth(condition)['facts_to_develop'],
             'target_new_chars':target,'original_minimum':condition['min_chars'],
             'current_chars':diagnosis['metrics']['rendered_chars'],
             'existing_segments':draft['segments']}
    if condition.get('document_spec'):
        payload['document_spec']=condition['document_spec']
        payload['document_case']=plan.get('document_case',{})
        payload['facts_to_develop']=[f['requirement'] for f in section['fact_fields']]
    return payload,schema,section,scene


def merge_response(response,draft,condition,plan,values,diagnosis,section,scene,target):
    validate(response,obj(section_id=string([section['section_id']]),
                          sentences={**array(string()),'minItems':2,'maxItems':18}))
    sentences=response['sentences']
    old=[normalized(s['text']) for s in draft['segments']]
    fields=numeric_fields('\n'.join(s['text'] for s in draft['segments']))
    for text in sentences:
        if not text.strip() or len(text)>250 or '\n' in text or '\r' in text:
            fail('ADDITION_TEXT','Use nonempty single-line complete sentences of at most 250 characters','RETRY_RESPONSE')
        if '<' in text or '>' in text or any(p.search(text) for p in LITERALS):
            fail('ADDITION_IDENTIFIER','Do not introduce entity tokens or literal identifiers','RETRY_RESPONSE')
        key=normalized(text)
        if any(near_duplicate(key,previous) for previous in old):
            fail('ADDITION_REPEAT','New sentence repeats existing or newly added content','RETRY_RESPONSE')
        old.append(key)
        for label,value in numeric_fields(text).items():
            if label in fields and fields[label]!=value:
                fail('ADDITION_FACT_CONFLICT','A numeric field contradicts an existing value','RETRY_RESPONSE')
            fields[label]=value
    chars=sum(map(len,sentences))
    if chars<max(80,int(target*.75)) or chars>target+300:
        fail('ADDITION_SIZE',f'Addition has {chars} characters; requested approximately {target}','RETRY_RESPONSE')
    anchor=next((s['sentence_id'] for s in reversed(draft['segments']) if s['scene_id']==scene['scene_id']),None)
    if anchor is None:
        fail('ADDITION_SCENE','Repair missing scenes before adding length','STOP_CANDIDATE')
    serial=max(int(s['sentence_id'][1:]) for s in draft['segments'])+1
    kind=next((k for k in ('prose','answer','list_item','key_value','numbered_list') if k in section['allowed_kinds']),section['allowed_kinds'][0])
    def added_kind(text):
        if section.get('mode')=='qa':return 'question' if text.rstrip().endswith('?') else 'answer'
        if section.get('mode') in ('fields','table'):return 'key_value'
        return kind
    patch={'base_draft_version':draft['draft_version'],'replacements':[],'refs':[],
           'relation_evidence_updates':[], 'insertions':[{'after_sentence_id':anchor,'segments':[
                {'sentence_id':f'S{serial+i}','section_id':section['section_id'],
                 'scene_id':scene['scene_id'],'kind':added_kind(text),'text':text} for i,text in enumerate(sentences)]}]}
    merged=apply_patch(draft,patch,diagnosis)
    checks,_=diagnose(merged,condition,plan,values)
    errors=[i for i in checks['issues'] if i['code']!='LENGTH_SHORTAGE']
    if errors:
        fail('ADDITION_INVALID','Added block failed code checks: '+','.join(sorted({i['code'] for i in errors})),'RETRY_RESPONSE')
    result=checks['normalized_draft']
    ids={s['sentence_id'] for s in draft['segments']}
    if [s for s in result['segments'] if s['sentence_id'] in ids]!=draft['segments']:
        fail('ADDITION_CHANGED_ORIGINAL','Original sentences must be preserved exactly','RETRY_RESPONSE')
    if result['refs']!=draft['refs'] or result['relation_evidence']!=draft['relation_evidence']:
        fail('ADDITION_CHANGED_EVIDENCE','Original references and evidence must be preserved','RETRY_RESPONSE')
    return {'draft':result,'patch':patch,'checks':{k:v for k,v in checks.items() if k!='normalized_draft'},
            'original_segments_unchanged':True,'added_chars':chars}


def expand(client,draft,condition,plan,values,diagnosis,remaining):
    payload,schema,section,scene=build_request(draft,condition,plan,diagnosis,remaining)
    system=SYSTEM
    if condition.get('document_spec'):
        from .document_specs import WRITE_GUIDANCE
        system+='\n'+WRITE_GUIDANCE+'\n이번 응답에는 지정 section의 새 문장만 반환한다. 기존 본문과 사실·화자를 유지하며 다른 section을 작성하지 않는다.\n'
    return validated_request(client,condition['candidate_id'],5,'expand',system,payload,schema,
        lambda response:merge_response(response,draft,condition,plan,values,diagnosis,section,scene,payload['target_new_chars']))
