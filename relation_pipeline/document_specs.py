"""Shared subtype contract for condition, planning, writing, additions and review."""
import copy
import json
import re

from .common import Issue, digest, fail
from .formats import CATALOG
from .schemas import BOOL, array, obj, string
from .spec_definitions import ROWS

VERSION = 'type_specs_v1'
UPSTREAM = CATALOG['upstream_commit']
MODES = {
    'fields': ('항목명: 확정된 값 또는 상태', ['heading','key_value','prose']),
    'table': ('항목별 내역과 대응 관계가 명확한 표·목록·문장 나열; 표 헤더는 필수가 아님', ['heading','key_value','list_item','numbered_list','prose']),
    'qa': ('질문과 구체적인 응답을 짝지어 작성', ['heading','question','answer','prose']),
    'clauses': ('제N조(제목) 및 의무·조건·기한을 담은 조항', ['heading','prose','numbered_list']),
    'steps': ('번호별 실행 순서와 그 단계의 확인 결과', ['heading','numbered_list','prose']),
    'narrative': ('지정 화자의 연결된 서술; 사건·행동·근거·결과', ['heading','prose']),
}

# Situations are selected before the plan. They constrain, not merely decorate, facts.
SCENARIOS = {
    'refund_request': [
        ('subscription', '구독 해지 후 재청구', ['구독','해지','재청구'],
         ['해지 요청·완료 시각과 이후 청구','이용 이력·취소 요청·환불 산정'],
         ['실물 상품 배송·수령','제품 회수·외관 검수']),
        ('goods', '실물 상품 반품 환불', ['상품','제품','반품'],
         ['구매·수령과 반품 사유','회수·검수 상태와 비용·환불액 산정'],
         ['구독 해지','정기결제 시스템의 재청구']),
        ('service_cancel', '예약 서비스 취소 환불', ['예약','서비스','취소'],
         ['예약일·취소 시점·제공 여부','취소 조건·공제액·환불액'],
         ['제품 배송·회수·검수','정기 구독 해지']),
    ],
    'leave_return': [
        ('leave','휴학 신청',['휴학'],['중단 기간·사유·복귀 준비'],['이번 학기 복학 승인 완료']),
        ('return','복학 신청',['복학'],['복귀 학기·수강·등록 준비'],['이번 학기 신규 휴학 신청']),
    ],
    'recommendation': [
        ('employment','직무 역량 추천',['직무','채용','업무','프로젝트'],['업무 관찰 관계·기간','두 업무 사례의 행동·성과'],['추천 요청 사실만으로 구성한 경위서']),
        ('academic','학업·연구 역량 추천',['학업','연구','입학'],['학습·연구 관찰 관계·기간','두 학업 사례의 행동·결과'],['근거 없는 취업 실적']),
    ],
    'registration': [
        ('initial','초진 접수',['초진','첫 방문'],['증상 시작·변화·기존 자료 유무'],['이 기관의 이전 진료 결과를 전제로 한 서술']),
        ('followup','재진 접수',['재진','다시 방문'],['지난 방문 이후 변화·자료 인계'],['초진이라는 동시 기재']),
    ],
}

DOMAIN_GUIDANCE = {
    'contract': '합의 문서는 당사자별 의무·조건·기한·대가·확인 방법을 조항으로 쓴다. 사고 확인서와 해외 신청서는 지정된 기록/신청 형식을 따른다. 법적 효력 선언을 반복해 분량을 채우지 않는다.',
    'support': '실제 상담 기록으로 접수·고객 요구·증빙·담당자 확인·처리 상태를 구분한다. 고객의 주장과 검증 결과를 섞지 않는다. 담당자의 일반 업무 설명을 반복하지 않는다.',
    'legal': '작성자의 직접 경험·상대방 주장·증거·추정을 구분한다. 일시별 경위와 쟁점별 근거를 작성하고 법조문·책임·승소를 임의 확정하지 않는다.',
    'medical': '접수·문진·결과·청구·동의의 용도를 구분한다. 증상·응답·관찰·검사·행정 상태를 구체적으로 쓰되 해당 문서의 확인 범위를 넘어 진단·처방·치료 성공을 창작하지 않는다.',
    'financial': '신청 조건·거래 내역·금액 계산·증빙·처리 상태를 구분한다. 소유자·출금 주체·수취인·지급 대상은 서로 다를 수 있다. 서식 작성 요령으로 본문을 대체하지 않는다.',
    'career_education': '자기소개·경력·추천은 지정된 작성자의 실제 사례와 평가를 중심으로 쓴다. 학사 증명·신청은 기준일·학적·내역을 항목과 표로 작성한다. 모든 종류를 상담 기록으로 바꾸지 않는다.',
}


def definitions():
    result={}
    for domain,rows in ROWS.items():
        for row in rows.strip().splitlines():
            subtype,audience,roles,voice,layout,scope,completion=row.split('|')
            writer,reader=audience.split('>')
            sections=[]
            clause=0
            for i,block in enumerate(layout.split(' / '),1):
                header,facts=block.split(':',1)
                title,mode=header.split('@')
                if mode=='clauses':
                    clause+=1
                    title=f'제{clause}조({title})'
                fields=[{'field_id':f'F{j}', 'requirement':fact} for j,fact in enumerate(facts.split(';'),1)]
                sections.append({'section_id':f'spec_{i}','title':title,'mode':mode,
                                 'structure':MODES[mode][0],'fact_fields':fields})
            key=(domain,subtype)
            if key in result:raise ValueError(f'Duplicate subtype {key}')
            result[key]={'version':VERSION,'domain':domain,'subtype':subtype,
                'label':CATALOG['domains'][domain][subtype]['label'],
                'writer':writer,'reader':reader,'participant_roles':roles.split(';'),'voice':voice,
                'sections':sections,'conditional_rules':[scope], 'completion_criterion':completion,
                'domain_guidance':DOMAIN_GUIDANCE[domain]}
    expected={(d,s) for d,subtypes in CATALOG['domains'].items() for s in subtypes}
    if set(result)!=expected:raise ValueError(f'Spec coverage mismatch: {expected-set(result)} / {set(result)-expected}')
    return result


DEFINITIONS=definitions()

# Safe attribute relations are shared; business/event relations follow the document purpose.
RELATION_GROUPS = [
    ('resume_form cover_letter career_statement job_application recommendation admission_application enrollment_certificate transcript',
     'EDUCATION_STATUS QUALIFICATION_AND_ASSESSMENT GUIDANCE_SUPPORT EVENT_PARTICIPATION PERSONAL_RELATIONSHIP'),
    ('scholarship_application', 'EDUCATION_STATUS QUALIFICATION_AND_ASSESSMENT FINANCIAL_ASSET_ASSOCIATION FINANCIAL_TRANSACTION CREDIT_AND_GUARANTEE_RELATION'),
    ('leave_return', 'EDUCATION_STATUS PROCEDURAL_RELATION GUIDANCE_SUPPORT'),
    ('registration questionnaire health_checkup telemedicine_consult checkup_result surgery_consent',
     'BUSINESS_SERVICE_RELATION PROCEDURAL_RELATION GUIDANCE_SUPPORT PERSONAL_RELATIONSHIP INFORMATION_GOVERNANCE'),
    ('payment', 'FINANCIAL_TRANSACTION FINANCIAL_ASSET_ASSOCIATION BUSINESS_SERVICE_RELATION'),
    ('insurance_claim insurance_subscription', 'INSURANCE_RELATION FINANCIAL_TRANSACTION FINANCIAL_ASSET_ASSOCIATION PERSONAL_RELATIONSHIP'),
    ('loan loan_application', 'CREDIT_AND_GUARANTEE_RELATION FINANCIAL_TRANSACTION FINANCIAL_ASSET_ASSOCIATION'),
    ('card_application account_opening wire_transfer', 'FINANCIAL_TRANSACTION FINANCIAL_ASSET_ASSOCIATION PROCEDURAL_RELATION'),
    ('fraud_report incident_report complaint_filing damage_claim witness_statement police_statement mediation_application accident_rear accident_intersection accident_parking accident_pedestrian accident_single',
     'CASE_AND_INCIDENT_RELATION ASSET_RELATION FINANCIAL_TRANSACTION FINANCIAL_ASSET_ASSOCIATION PROCEDURAL_RELATION'),
    ('legal_consultation', 'CASE_AND_INCIDENT_RELATION GUIDANCE_SUPPORT PROCEDURAL_RELATION'),
    ('complaint_product complaint_service support_ticket refund_request delivery_issue as_request billing_dispute account_inquiry',
     'BUSINESS_SERVICE_RELATION FINANCIAL_TRANSACTION FINANCIAL_ASSET_ASSOCIATION PROCEDURAL_RELATION GUIDANCE_SUPPORT INFORMATION_GOVERNANCE'),
    ('lease rental sale transfer car_rental_short car_rental_long car_rental_corp',
     'ASSET_RELATION BUSINESS_SERVICE_RELATION FINANCIAL_TRANSACTION FINANCIAL_ASSET_ASSOCIATION INSURANCE_RELATION'),
    ('construction service consign agency distribution advertising maintenance supply freelance consulting it_outsourcing',
     'BUSINESS_SERVICE_RELATION FINANCIAL_TRANSACTION FINANCIAL_ASSET_ASSOCIATION PROCEDURAL_RELATION'),
    ('investment shareholder joint_venture partnership research',
     'COLLABORATION_PARTNERSHIP FINANCIAL_TRANSACTION FINANCIAL_ASSET_ASSOCIATION EVENT_PARTICIPATION PROCEDURAL_RELATION'),
    ('escrow settlement', 'FINANCIAL_TRANSACTION FINANCIAL_ASSET_ASSOCIATION PROCEDURAL_RELATION'),
    ('franchise license', 'BUSINESS_SERVICE_RELATION FINANCIAL_TRANSACTION FINANCIAL_ASSET_ASSOCIATION GUIDANCE_SUPPORT'),
    ('employment', 'BUSINESS_SERVICE_RELATION FINANCIAL_TRANSACTION FINANCIAL_ASSET_ASSOCIATION PROCEDURAL_RELATION'),
    ('nda data_processing', 'INFORMATION_GOVERNANCE BUSINESS_SERVICE_RELATION PROCEDURAL_RELATION'),
    ('overseas_visa overseas_assignment overseas_trip', 'PROCEDURAL_RELATION EVENT_PARTICIPATION BUSINESS_SERVICE_RELATION GUIDANCE_SUPPORT'),
]
RELATION_TYPES={s:set(relations.split())|{'CONTACT_ASSOCIATION','LOCATION_ASSOCIATION','IDENTITY_ASSOCIATION','ORGANIZATIONAL_RELATION'}
                for subtypes,relations in RELATION_GROUPS for s in subtypes.split()}
assert set(RELATION_TYPES)=={s for _,s in DEFINITIONS}


def compatible_relation(condition,source,relation,target):
    if condition.get('spec_policy')!=VERSION:return True
    if relation not in RELATION_TYPES[condition['subtype']]:return False
    # A person's contact details are not by themselves an information-processing duty.
    if relation=='INFORMATION_GOVERNANCE' and source=='NAME' and target in {'MOBILE_PHONE','TELEPHONE','EMAIL'}:
        return False
    return True


def resolve(domain,subtype,rng,topic='',scenario_id=None):
    spec=copy.deepcopy(DEFINITIONS[domain,subtype])
    spec['compatible_relation_types']=sorted(RELATION_TYPES[subtype])
    scenarios=SCENARIOS.get(subtype,[])
    if scenario_id and not any(s[0]==scenario_id for s in scenarios):
        fail('SPEC_SCENARIO',f'Unsupported scenario for {domain}/{subtype}: {scenario_id}','STOP_RUN',True)
    if scenarios:
        chosen=next((s for s in scenarios if s[0]==scenario_id),None)
        if chosen is None:
            scores=[sum(word in topic for word in s[2]) for s in scenarios]
            chosen=scenarios[scores.index(max(scores))] if max(scores)>0 else rng.choice(scenarios)
        key,label,_,include,exclude=chosen
        spec['scenario']={'id':key,'label':label,'include':include,'exclude':exclude}
        if subtype=='refund_request':
            # Replace the general inspection field, so inactive branches never reach facts_to_develop.
            spec['sections'][2]['fact_fields']=[{'field_id':'F1','requirement':';'.join(include)},
                {'field_id':'F2','requirement':'자료별 확인 내용과 미확인 사항'}]
    else:
        spec['scenario']={'id':'case_from_spec','label':topic or spec['label'],
            'include':['계획 단계에서 조건별 적용 여부와 사건 상태를 확정'], 'exclude':[]}
    spec['checks']=[{'check_id':'author','section_id':'','requirement':f"{spec['writer']}가 {spec['reader']}에게 쓰는 관점과 당사자 역할이 본문에서 명확하다."},
                    {'check_id':'scope','section_id':'','requirement':'선택된 상황·조건별 적용 범위가 일관되고 제외된 내용이 없다. '+spec['conditional_rules'][0]}]
    spec['checks'] += [{'check_id':s['section_id'],'section_id':s['section_id'],
                       'requirement':s['structure']+'; '+'; '.join(f['requirement'] for f in s['fact_fields'])}
                      for s in spec['sections']]
    spec['checks'].append({'check_id':'complete','section_id':'','requirement':spec['completion_criterion']})
    return spec


def apply_spec(condition,cfg,rng):
    if cfg.get('spec_policy')!=VERSION:return condition
    selection=cfg.get('selection',{})
    topic=selection.get('topic','')
    spec=resolve(condition['domain'],condition['subtype'],rng,topic,selection.get('scenario'))
    spec['role_bindings']=[{'name_entity_id':person['name_entity_id'],'role_code':person['role'],
        'document_role':spec['participant_roles'][i] if i<len(spec['participant_roles']) else person['role']}
        for i,person in enumerate(condition['person_slots'])]
    if selection.get('viewpoint'):
        spec['voice']=selection['viewpoint']
        spec['writer_view_override']=selection['viewpoint']
    condition.update(spec_policy=VERSION,document_spec=spec,narrative_viewpoint=spec['voice'],
                     layout_variant='type_spec',fixed_format=True)
    if condition['subtype'].startswith('overseas_'):
        condition['document_format']='form'
    if not topic:
        condition['topic']=spec['scenario']['label']
        condition['topic_id']='spec_'+digest([spec['subtype'],spec['scenario']])[:12]
    sections=[]
    weights=[3 if s['mode'] in ('table','narrative','qa','clauses') else 2 for s in spec['sections']]
    total=condition['length_target']
    for section,weight in zip(spec['sections'],weights):
        sections.append({**copy.deepcopy(section),'allowed_kinds':MODES[section['mode']][1][:],
                         'required':True,'target_chars':total*weight//sum(weights)})
    sections[-1]['target_chars']+=total-sum(s['target_chars'] for s in sections)
    condition['section_plan']=sections
    condition['layout_variant_label']=spec['label']+' 전용 항목·순서'
    return condition


PLAN_GUIDANCE='''
[타입별 문서 설계]
document_spec의 작성자·독자·역할·항목 순서·조건·완성 기준을 따른다. 공통 상담 서식으로 바꾸지 않는다.
document_case에 구체적 사건·조건별 적용 여부·끝 상태를 확정한다. 선택되지 않은 상황은 섞지 않는다.
scene_notes의 content_facts는 각 field_id가 요구하는 실제 합성 사실·내역을 채운다. 제목이나 작성 지시를 반환하지 않는다.
금액·날짜·기간·과목·검사수치 등 비식별 사실은 실제 같은 구체값으로 만들고 계산·선후관계를 맞춘다.
예: '피해 금액을 기재한다' 대신 '9월 3일 두 차례 이체한 18만원과 12만원의 합계 30만원을 피해액으로 신고했다'.
없음·미확인은 이유와 확인 범위를 적고, 필수 항목을 모두 '해당 없음'으로 채우지 않는다.
당사자·실명·기관·식별값은 고정 그래프를 따른다. 새 엔티티나 관계를 추가하지 않는다.
표의 행 수·문답 수가 지정되어 있으면 해당 필드에 필요한 서로 다른 내역/문답을 계획한다. 표 내역은 문장 나열로도 표현할 수 있다.
'''

WRITE_GUIDANCE='''
[타입별 완성 문서 작성]
document_spec의 작성자·독자·당사자 역할과 각 section의 structure/fact_fields를 따른다.
내역은 표·목록·문장 나열 중 읽기 쉬운 방식으로 쓰며 항목별 값과 대응 관계를 명확히 한다. 표 헤더는 필수가 아니다. 문답은 질문과 구체 응답, 조항은 의무 주체·조건·기한으로 쓴다.
plan의 document_case와 장면별 확정 사실을 전개한다. 값·행위·관찰·판단 근거를 쓰며 '~을 기재해야 한다/관계를 명시한다' 같은 작성 안내로 대체하지 않는다.
제목·동의·일반 안내의 반복으로 분량을 채우지 않는다. 부족하면 사건 경위·내역·비교 근거·확인 질문을 더 설명한다.
조건과 scenario.exclude를 지킨다. 구독 환불에 제품 회수, 추천서에 신청 경위 중심 서술, 접수서에 개인정보 처리 해설을 끼워 넣지 않는다.
본문에 field_id/check_id/spec/ontology 같은 내부 구현 용어를 노출하지 않는다.
'''

REVIEW_GUIDANCE='''
[타입별 완성도 독립 검수]
document_spec은 문서의 공통 작성 요구이며 생성자의 확정 사실이나 정답 근거가 아니다.
spec_checks의 각 항목을 실제 본문으로 판정한다. 제목 존재만으로 통과시키지 않는다.
금액·기간·행동·관찰·표의 내역·문답 등 요구된 정보가 실제로 있는지, 화자·역할·상황 조건이 맞는지 확인한다.
문장 나열·목록도 허용된 표현이다. 표 헤더·행·구분선이 없거나 연결 산문 대신 문장 나열이라는 이유만으로 spec_checks, format_adherence, text_issues, quality를 감점하거나 미충족으로 판정하지 않는다. 표의 지정 행 수는 서로 다른 내역의 수로 확인한다. 필수 사실·계산·역할·근거의 실제 누락과 모순은 계속 검수한다.
통과 항목에는 내용을 입증하는 본문 S ID를 evidence_sentence_ids에 넣는다. 제목·일반 작성 안내만으로 입증하지 않는다.
부족한 항목은 passed=false와 구체적인 누락/오류 이유를 기록한다. 본문에 없는 항목은 근거를 만들지 않고 []로 둔다.
같은 기관 연락처·주소, 같은 사건 경위·증빙·조치·추천 의사를 문구만 바꾸어 두 번 이상 썼으면 의미 중복이다. 중복된 모든 S ID를 text_issues에 적고 suitability와 overall을 상으로 판정하지 않는다.
관계를 설명·명시·나타낸다고 말하거나 context_reason 같은 계획 문구를 본문으로 옮긴 문장은 실제 문서 사실이 아니다. 해당 S ID를 text_issues에 적고 suitability와 overall을 상으로 판정하지 않는다.
섹션 안에 제목처럼 보이는 사실 항목을 여러 heading으로 만들거나 같은 양식 필드명을 반복하면 형식 오류로 판정한다.
'''


def review_schema(base,condition,sentence_ids=None):
    # REVIEW reuses TEXT/BOOL objects; specialization must break those aliases.
    schema=json.loads(json.dumps(base))
    if not condition.get('document_spec'):return schema
    sid=string(sentence_ids) if sentence_ids else string()
    schema['properties']['spec_checks']=obj(**{c['check_id']:obj(passed=BOOL,
        evidence_sentence_ids={**array(sid),'maxItems':12},reason=string()) for c in condition['document_spec']['checks']})
    schema['required']=list(schema['properties'])
    return schema


def check_review_spec(review,condition,filled):
    response,semantic=[],[]
    sentences={s['sentence_id']:s for s in filled['sentences']}
    for requirement in condition.get('document_spec',{}).get('checks',[]):
        key=requirement['check_id']; finding=review['spec_checks'][key]
        ids=finding['evidence_sentence_ids']
        if len(ids)!=len(set(ids)) or any(sid not in sentences for sid in ids) or not finding['reason'].strip():
            response.append(Issue('SPEC_REVIEW_EVIDENCE',f'{key}: invalid evidence IDs or empty reason','RETRY_RESPONSE'))
        elif finding['passed'] and (not ids or not any(sentences[sid].get('kind')!='heading' and len(sentences[sid]['sentence'].strip())>8
                and (not requirement['section_id'] or sentences[sid]['section_id']==requirement['section_id']) for sid in ids)):
            response.append(Issue('SPEC_REVIEW_EVIDENCE',f'{key}: passing needs substantive body evidence','RETRY_RESPONSE'))
        if not finding['passed']:
            semantic.append(Issue('DOCUMENT_SPEC_INCOMPLETE',f'{key}: '+finding['reason'],'REWRITE_SCENE',
                                  section_id=requirement['section_id']))
    return response,semantic


def check_facts(response,condition):
    """Reject empty/meta-only facts before spending the draft call; meaning remains reviewed."""
    if not condition.get('document_spec'):return
    if any(len(value.strip())<8 for value in response['document_case'].values()):
        fail('SPEC_CASE_EMPTY','Provide a concrete situation, scope decisions and end state','RETRY_RESPONSE')
    for scene,note in response['scene_notes'].items():
        for field,value in note['content_facts'].items():
            if len(value.strip())<8 or re.fullmatch(r'.*(?:기재한다|서술한다|작성한다|명시한다|설명한다|기재해야 한다)[.!。]?\s*',value.strip()):
                fail('SPEC_FACT_NOT_CONCRETE',f'{scene}/{field}: provide an actual case fact instead of a writing instruction','RETRY_RESPONSE')
