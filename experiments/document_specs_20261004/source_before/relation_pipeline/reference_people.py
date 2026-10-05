"""Explicit fictional/public-reference contexts; never infer privacy from fame.

Only registered facts are supplied for public biographies. Actual applicants
remain actual parties even when their names are synthetic or well known.
"""
from __future__ import annotations

import copy
from .common import ROOT, Issue, fail, read_json
from .formats import allowed_triples

PROFILES = read_json(ROOT / 'assets/reference_people.json')
SUPPORTED = {'cover_letter','career_statement','job_application','recommendation',
             'admission_application','scholarship_application'}


def select_reference(condition, cfg):
    key = cfg.get('selection',{}).get('reference_profile') or cfg.get('reference_profile')
    if not key:
        return condition
    if key not in PROFILES:
        fail('REFERENCE_PROFILE', 'Unknown reference profile', 'STOP_CANDIDATE')
    if condition['domain'] != 'career_education' or condition['subtype'] not in SUPPORTED:
        fail('REFERENCE_FORMAT', 'This reference profile is supported only in career/education narrative documents', 'STOP_CANDIDATE')
    profile = PROFILES[key]
    condition['reference_profile'] = key
    condition['reference_context'] = {k:copy.deepcopy(profile[k]) for k in ('context_kind','category','role','fact','source')}
    condition['max_example_persons'] = int(profile['context_kind']=='example_person')
    condition['max_public_reference_persons'] = int(profile['context_kind']=='public_reference')
    # This is an optional extra person, never a replacement for a real party.
    return condition


def add_reference_graph(plan, condition):
    key = condition.get('reference_profile')
    if not key:
        return plan
    p = PROFILES[key]
    triple = ['NAME',p['relation'],p['target_type']]
    if triple not in allowed_triples(condition['domain']):
        fail('REFERENCE_TRIPLE', 'Registered fact is outside domain ontology', 'REPLAN')
    # Replace one eligible public edge, preserving total/privacy counts and all
    # required coverage relations. Existing personal edges are never relabelled.
    eligible = [r for r in plan['relations'] if r['target_privacy']=='NON_PII'
                and r['relation'] not in condition.get('required_relation_types',[])]
    if not eligible:
        fail('REFERENCE_CAPACITY', 'No unreserved NON_PII slot for reference fact', 'REPLAN')
    r = eligible[-1]
    number = max(int(e['entity_id'][1:]) for e in plan['entities'])+1
    source,target = f'E{number}',f'E{number+1}'
    plan['entities'].extend([
        {'entity_id':source,'entity_type':'NAME','context_role':f'reference:{key}:name','slot_group':f'reference_{key}'},
        {'entity_id':target,'entity_type':p['target_type'],'context_role':f'reference:{key}:attribute','slot_group':f'reference_{key}'}])
    r.update(source=source,target=target,relation=p['relation'],context_reason=p['fact'])
    incident = {e for edge in plan['relations'] for e in (edge['source'],edge['target'])}
    plan['entities'] = [e for e in plan['entities'] if e['entity_id'] in incident]
    return plan


def extra_people(plan, condition):
    key = condition.get('reference_profile')
    if not key:
        return []
    p = PROFILES[key]
    name = next(e['entity_id'] for e in plan['entities'] if e['context_role']==f'reference:{key}:name')
    return [{'person_id':f"P{condition['n_parties']+1}",'name_entity_id':name,
             'role':p['role'],'context_kind':p['context_kind']}]


def reference_plan_issues(plan, condition):
    issues=[]
    nonparties=[p for p in plan['persons'] if p['context_kind']!='actual_party']
    key=condition.get('reference_profile')
    if not nonparties:
        if key:
            issues.append(Issue('REFERENCE_MISSING','Requested reference person is missing','REPLAN'))
        return issues
    if not key or key not in PROFILES:
        return [Issue('REFERENCE_PROVENANCE','Nonparty person needs a registered context/fact','REPLAN')]
    profile=PROFILES[key]
    entities={e['entity_id']:e for e in plan['entities']}
    if len(nonparties)!=1:
        issues.append(Issue('REFERENCE_COUNT','Exactly one selected reference person is allowed','REPLAN'))
    for person in nonparties:
        name=person['name_entity_id']
        edges=[r for r in plan['relations'] if name in (r['source'],r['target'])]
        valid=(person['context_kind']==profile['context_kind'] and person['role']==profile['role']
               and entities.get(name,{}).get('context_role')==f'reference:{key}:name' and len(edges)==1)
        for edge in edges:
            target=entities.get(edge['target'],{})
            valid=valid and edge['source']==name and edge['relation']==profile['relation'] and edge['target_privacy']=='NON_PII' and target.get('entity_type')==profile['target_type'] and target.get('context_role')==f'reference:{key}:attribute'
        if not valid:
            issues.append(Issue('REFERENCE_FACT_SCOPE','Reference identity or relation exceeds the registered fact','REPLAN',entity_id=name))
    return issues


def fixed_reference_values(plan, condition):
    key=condition.get('reference_profile')
    if not key:
        return {}
    profile=PROFILES[key]
    return {e['entity_id']:{'value':profile['name'] if e['entity_type']=='NAME' else profile['target_value'],
            'provenance':{'profile_id':key,'category':profile['category'],**copy.deepcopy(profile['source'])}}
            for e in plan['entities'] if e['context_role'].startswith(f'reference:{key}:')}
