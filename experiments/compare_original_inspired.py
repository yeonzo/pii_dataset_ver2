"""Bounded live test: three paired subtypes + two new reference-person cases.

Source authorship and reference-profile capabilities are evaluated separately.
Both writing arms use the same privacy policy and ID-only independent reviewer.
"""
import argparse
import concurrent.futures
from pathlib import Path
from relation_pipeline.common import ROOT,atomic_json,now
from experiments.compare_naturalness import one_case,compare_case

PAIRS=[('career_education','recommendation','품질 불량률 감소'),
       ('career_education','cover_letter','재고관리 자동화'),
       ('support','refund_request','구독 해지 후 재청구')]
REFERENCES=[('fictional_student','교재의 가상 학생 사례를 활용한 학습 프로그램 개선'),
            ('marie_curie_education','공개 위키 인물 소개를 활용한 과학 학습 자료 개선')]


def run(tag,policy='prose_v1',case_filter=None):
    pairs=[c for c in PAIRS if not case_filter or c[1] in case_filter.split(',')]
    count=len(pairs)
    path=ROOT/'runs'/f'{tag}_report.json'
    result={'started_at':now(),'tag':tag,'document_policy':policy,'cases':[],'comparisons':[],
        'adoption_rule':'At least 2/3 of pairs stably prefer prose, all pairs available with equal graph and constraints, at least one accepted prose candidate and more accepted candidates than baseline. Reference-only probes excluded from comparison.',
        'review':'Same GPT-5-mini ID-only evidence reviewer, purpose check and privacy policy v3 in both writing arms.',
        'limits':{'pipeline_candidates':count*2+2,'max_pipeline_requests':(count*2+2)*7,'max_comparison_requests':count*4,'max_cost_usd':(count*2+2)*.4+count*.3}}
    atomic_json(path,result)
    jobs=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        for index,case in enumerate(pairs,1):
            for arm in ('legacy','purpose'):
                jobs.append(executor.submit(one_case,tag,index,arm,case,policy,{'review_evidence_policy':'sentence_ids'}))
        for index,(profile,topic) in enumerate(REFERENCES,count+1):
            jobs.append(executor.submit(one_case,tag,index,'purpose',('career_education','cover_letter',topic),policy,
                {'review_evidence_policy':'sentence_ids','reference_profile':profile}))
        for future in concurrent.futures.as_completed(jobs):
            result['cases'].append(future.result())
            atomic_json(path,result)
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        futures=[]
        for index in range(1,count+1):
            pair={c['arm']:c for c in result['cases'] if c['index']==index}
            futures.append(executor.submit(compare_case,tag,pair['legacy'],pair['purpose']))
        for future in concurrent.futures.as_completed(futures):
            try:
                result['comparisons'].append(future.result())
            except Exception as exc:
                result['comparisons'].append({'available':False,'error_type':type(exc).__name__})
            atomic_json(path,result)
    totals={arm:{'candidates':count,'accepted':sum(c['status']=='accepted' for c in result['cases'] if c['index']<=count and c['arm']==arm),
                'requests':sum(len(c['calls']) for c in result['cases'] if c['index']<=count and c['arm']==arm)} for arm in ('legacy','purpose')}
    wins=sum(c.get('stable_winner')=='purpose' for c in result['comparisons'])
    comparable=len(result['comparisons'])==count and all(c.get('available') and c['same_graph'] and c['same_conditions'] for c in result['comparisons'])
    adopt=comparable and wins/count>=2/3 and totals['purpose']['accepted']>=1 and totals['purpose']['accepted']>totals['legacy']['accepted']
    result.update(totals=totals,stable_prose_wins=wins,adopt=adopt,finished_at=now(),
        estimated_cost_usd=sum(c['estimated_cost_usd'] for c in result['cases'])+sum(c.get('estimated_cost_usd',0) for c in result['comparisons']))
    atomic_json(path,result)
    print({'totals':totals,'stable_prose_wins':wins,'adopt':adopt,'report':str(path)},flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--tag',required=True)
    p.add_argument('--policy',choices=['prose_v1','prose_v2'],default='prose_v1')
    p.add_argument('--cases')
    args=p.parse_args()
    run(args.tag,args.policy,args.cases)
