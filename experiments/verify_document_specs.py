"""Fresh six-domain pilot: new conditions, plans and drafts; at most 42 calls."""
import argparse
from collections import Counter
from experiments.compare_generation import register,summarize
from relation_pipeline.common import ROOT,atomic_json,load_config,now,read_json
from relation_pipeline.runner import Runner
from relation_pipeline.statistics import export
from relation_pipeline.stages.stage00_prepare import prepare
from relation_pipeline.stages.stage05_assemble import diagnose

CASES={'support':'refund_request','financial':'fraud_report','legal':'mediation_application',
       'medical':'registration','contract':'service','career_education':'recommendation'}


def run(run_id):
    cfg=load_config()
    cfg.update(run_request_budget=42,run_cost_budget_usd=1.5,max_candidates_per_slot=1,max_candidates_per_domain=1)
    cfg['relation_coverage']={**cfg['relation_coverage'],'enabled':False}
    store=prepare(cfg,run_id,list(CASES),1)
    if store.rows('SELECT * FROM candidates'):raise RuntimeError('Use a fresh run ID')
    runner=Runner(store)
    report={'started_at':now(),'protocol':{'fresh_plan_and_draft':True,'spec_policy':cfg['spec_policy'],
            'generation_model':cfg['generation_model'],'generation_temperature':cfg['generation_temperature'],
            'review_model':cfg['review_model'],'relation_review_policy':cfg.get('relation_review_policy'),
            'maximum_requests':42,'maximum_cost_usd':1.5,'coverage_enabled':False},'cases':[]}
    target=store.run_dir/'document_specs_report.json'
    atomic_json(target,report)
    for domain,subtype in CASES.items():
        slot=store.rows('SELECT * FROM slots WHERE domain=?',(domain,))[0]
        store.execute('UPDATE slots SET subtype=? WHERE slot_id=?',(subtype,slot['slot_id']))
        slot['subtype']=subtype
        candidate=register(store,slot)
        print('START',domain,subtype,flush=True)
        runner.run_candidate(slot,candidate,1)
        outcome=summarize(store,candidate)
        root=store.run_dir/'candidates'/candidate
        condition=read_json(root/'condition.json')
        outcome.update(minimum=condition['min_chars'],scenario=condition['document_spec']['scenario'])
        state_path=root/'state.json'
        if state_path.exists():
            draft=read_json(state_path)['draft']
            plan=read_json(root/'plan.json'); values=read_json(root/'value_map.json')
            checks,filled=diagnose(draft,condition,plan,values)
            outcome['final_chars']=checks['metrics'].get('rendered_chars')
            if filled:
                (root/'final_document.txt').write_text('\n'.join(s['sentence'] for s in filled['sentences'])+'\n',encoding='utf-8')
        report['cases'].append(outcome)
        atomic_json(target,report)
        export(store,runner.cfg);store.manifest()
        print('RESULT',domain,outcome['status'],outcome.get('final_chars'),[i['code'] for i in outcome['reasons']],flush=True)
    calls=[c for case in report['cases'] for c in case['calls']]
    report.update(finished_at=now(),totals={'evaluated':len(report['cases']),
        'accepted':sum(c['status']=='accepted' for c in report['cases']),
        'length_met':sum((c.get('final_chars') or 0)>=c['minimum'] for c in report['cases']),
        'calls':dict(Counter(c['task'] for c in calls)), 'cost_usd':sum(c['estimated_cost_usd'] for c in calls)})
    atomic_json(target,report);store.close()
    print(report['totals'],flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-id',required=True)
    run(parser.parse_args().run_id)
