"""Final bounded probe; reuse frozen, identical baseline runs without more API calls."""
import concurrent.futures
from .compare_original_inspired import PAIRS, REFERENCES
from .compare_naturalness import one_case, compare_case
from relation_pipeline.common import ROOT, atomic_json, read_json, now


def run():
    tag='original_inspired_20261004_v2b'
    previous=read_json(ROOT/'runs'/'original_inspired_20261004_v2_report.json')
    baseline=[c for c in previous['cases'] if c['arm']=='legacy']
    report={'tag':tag,'started_at':now(),'document_policy':'prose_v2',
        'baseline_source':previous['tag'],'cases':list(baseline),'comparisons':[],
        'adoption_rule':'Both ordinary pairs must stably prefer prose with identical graphs and conditions; at least one accepted prose document and more accepts than baseline. Reference probes separate.',
        'limits':{'new_candidates':4,'max_new_pipeline_requests':28,'max_comparison_requests':8,'max_new_cost_usd':2.2}}
    path=ROOT/'runs'/f'{tag}_report.json'
    atomic_json(path,report)
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        jobs=[executor.submit(one_case,tag,i,'purpose',case,'prose_v2',{'review_evidence_policy':'sentence_ids'})
              for i,case in enumerate(PAIRS[:2],1)]
        jobs += [executor.submit(one_case,tag,i,'purpose',('career_education','cover_letter',topic),'prose_v2',
                  {'review_evidence_policy':'sentence_ids','reference_profile':profile})
                 for i,(profile,topic) in enumerate(REFERENCES,3)]
        for job in concurrent.futures.as_completed(jobs):
            report['cases'].append(job.result())
            atomic_json(path,report)
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        jobs=[]
        for old in baseline:
            new=next(c for c in report['cases'] if c['arm']=='purpose' and c['index']==old['index'])
            jobs.append(executor.submit(compare_case,tag,old,new))
        for job in concurrent.futures.as_completed(jobs):
            try:
                report['comparisons'].append(job.result())
            except Exception as exc:
                report['comparisons'].append({'available':False,'error_type':type(exc).__name__})
            atomic_json(path,report)
    totals={arm:{'candidates':2,'accepted':sum(c['status']=='accepted' for c in report['cases'] if c['index']<=2 and c['arm']==arm)} for arm in ('legacy','purpose')}
    report['totals']=totals
    report['adopt']=len(report['comparisons'])==2 and all(c.get('available') and c.get('same_graph') and c.get('same_conditions') and c.get('stable_winner')=='purpose' for c in report['comparisons']) and totals['purpose']['accepted']>totals['legacy']['accepted']
    report['new_requests']=sum(len(c['calls']) for c in report['cases'] if c['arm']=='purpose')
    report['estimated_new_cost_usd']=sum(c['estimated_cost_usd'] for c in report['cases'] if c['arm']=='purpose')+sum(c.get('estimated_cost_usd',0) for c in report['comparisons'])
    report['finished_at']=now()
    atomic_json(path,report)
    print({'totals':totals,'adopt':report['adopt'],'report':str(path)},flush=True)


if __name__=='__main__':
    run()
