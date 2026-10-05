"""Replay six frozen drafts through production additions/repairs and review."""
import argparse
from pathlib import Path
from collections import Counter

from experiments.compare_generation import register, summarize
from relation_pipeline.common import ROOT, atomic_json, digest, file_hash, load_config, now, read_json
from relation_pipeline.runner import Runner
from relation_pipeline.stages.stage00_prepare import prepare
from relation_pipeline.stages.stage05_assemble import diagnose
from relation_pipeline.statistics import export

DOMAINS = ['support','financial','legal','medical','contract','career_education']


def run(run_id, source, flow='legacy'):
    cfg = load_config()
    separated=flow=='separated_v1'
    cfg.update(generation_flow=flow,max_document_actions=2,run_request_budget=30 if separated else 36,run_cost_budget_usd=1.,
               max_provider_requests_per_candidate=5 if separated else 6,max_candidates_per_slot=1,max_candidates_per_domain=1)
    store = prepare(cfg,run_id,DOMAINS,target=1)
    if store.rows('SELECT candidate_id FROM candidates'):
        raise RuntimeError('Use a fresh run ID')
    runner = Runner(store)
    report = {'started_at':now(),'source_run':str(source.resolve()),'cases':[],
              'protocol':{'generation_flow':flow,'new_plan_or_draft_calls':0,'max_repairs_per_case':1 if separated else 2,
                          'max_additions_per_case':2 if separated else None,
                          'shared_retries_per_case':1 if separated else None,
                          'max_provider_requests':cfg['run_request_budget'],'max_cost_usd':1.,
                          'generation_model':cfg['generation_model'],'review_model':cfg['review_model'],
                          'length_policy':'original target and max(1500,int(target*.75)), no upper bound',
                          'acceptance':'unchanged production code, independent review and stage 8 acceptance'},
              'source_hashes':{str(p.relative_to(ROOT)):file_hash(p) for p in (ROOT/'relation_pipeline').rglob('*.py')}}
    path=store.run_dir/('separated_flow_report.json' if separated else 'additive_length_report.json')
    atomic_json(path,report)
    for domain in DOMAINS:
        slot=store.rows('SELECT * FROM slots WHERE domain=?',(domain,))[0]
        candidate=slot['slot_id']+'_c001'
        directory=source/'candidates'/candidate
        condition=read_json(directory/'condition.json')
        condition['run_id']=run_id
        assert condition['min_chars']==max(1500,int(condition['length_target']*.75))
        slot['subtype']=condition['subtype']
        store.execute('UPDATE slots SET subtype=? WHERE slot_id=?',(slot['subtype'],slot['slot_id']))
        plan=read_json(directory/'plan.json')
        values=read_json(directory/'value_map.json')
        draft=read_json(directory/'draft_versions/draft_v1.json')
        before,_=diagnose(draft,condition,plan,values)
        register(store,slot)
        runner.stage(candidate,1,{'config_hash':runner.cfg['config_hash'],
                     'slot':{k:slot[k] for k in ('slot_id','domain','subtype')},'ordinal':1},lambda:condition)
        store.save_artifact(candidate,'plan.json',plan)
        runner.stage(candidate,3,{'plan':plan,'candidate':candidate},lambda:values,private=True)
        store.save_artifact(candidate,'draft_versions/draft_v1.json',draft)
        store.save_artifact(candidate,'state.json',{'draft':draft,'revision':1})
        print(f'START {domain}/{condition["subtype"]} chars={before["metrics"].get("rendered_chars")} min={condition["min_chars"]}',flush=True)
        runner.run_candidate(slot,candidate,1)
        outcome=summarize(store,candidate)
        out=store.run_dir/'candidates'/candidate
        condition=read_json(out/'condition.json')
        versions=sorted((out/'draft_versions').glob('draft_v*.json'),key=lambda p:int(p.stem.split('_v')[1]))
        final=read_json(versions[-1])
        after,filled=diagnose(final,condition,plan,values)
        if filled:
            (out/'final_document.txt').write_text('\n'.join(s['sentence'] for s in filled['sentences'])+'\n',encoding='utf-8')
        preservation=[]
        for addition_path in sorted((out/'additions').glob('expansion_v*.json')):
            addition=read_json(addition_path)
            preservation.append({'revision':int(addition_path.stem.split('_v')[1]),
                                 'original_segments_unchanged':addition['original_segments_unchanged'],
                                 'added_chars':addition['added_chars']})
        for task_path in sorted((out/'repairs').glob('tasks_v*.json')):
            tasks=read_json(task_path)
            rev=int(task_path.stem.split('_v')[1])
            next_path=out/'draft_versions'/f'draft_v{rev+1}.json'
            if tasks.get('length_mode')=='append_only' and next_path.exists():
                a=read_json(out/'draft_versions'/f'draft_v{rev}.json')
                b=read_json(next_path)
                old={s['sentence_id']:s for s in a['segments']}
                retained=[s for s in b['segments'] if s['sentence_id'] in old]
                preservation.append({'revision':rev,'original_segments_unchanged':retained==a['segments'],
                                     'original_count':len(a['segments']),'new_count':len(b['segments'])-len(a['segments'])})
        outcome.update(before_chars=before['metrics'].get('rendered_chars'),
                       after_chars=after['metrics'].get('rendered_chars'),minimum=condition['min_chars'],
                       source_draft_hash=digest(draft),length_addition_audits=preservation,
                       final_code_issues=after['issues'])
        if (out/'call_policy.json').exists():
            outcome['call_policy']=read_json(out/'call_policy.json')
        outcome['effective_review_evidence_policy']=condition.get('review_evidence_policy')
        report['cases'].append(outcome)
        atomic_json(path,report)
        store.manifest()
        export(store,runner.cfg)
        print(f'RESULT {domain} {outcome["status"]} chars={outcome["after_chars"]} reasons={[i["code"] for i in outcome["reasons"]]}',flush=True)
    calls=[c for case in report['cases'] for c in case['calls']]
    assert not any(c['task'] in ('draft','plan') for c in calls)
    report.update(finished_at=now(),totals={'evaluated':len(report['cases']),
                  'accepted':sum(c['status']=='accepted' for c in report['cases']),
                  'length_met':sum((c['after_chars'] or 0)>=c['minimum'] for c in report['cases']),
                  'calls':dict(Counter(c['task'] for c in calls))})
    atomic_json(path,report)
    print(report['totals'],flush=True)
    store.close()


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run-id',required=True)
    p.add_argument('--source',type=Path,default=ROOT/'runs/smoke_legacy_short_20261004_v1')
    a=p.parse_args()
    run(a.run_id,a.source)
