import copy
import random
import unittest

from relation_pipeline.common import StageFailure
from relation_pipeline.formats import CATALOG,allowed_triples,sections_for
from relation_pipeline.persons import select_people
from relation_pipeline.planning_seed import seed_plan
from relation_pipeline.prose_writer import draft_request,decode_prose
from relation_pipeline.reference_people import select_reference,PROFILES
from relation_pipeline.review_evidence import id_only_schema,materialize_quotes
from relation_pipeline.repair_feedback import mask_known_feedback
from relation_pipeline.schemas import REVIEW,PLAN,validate
from relation_pipeline.stages.stage02_plan import check_plan,planning_contract,privacy_groups
from relation_pipeline.stages.stage03_values import select_values
from relation_pipeline.stages.stage07_review import check_review,review_input
from relation_pipeline.stages.stage08_accept import annotate
from relation_pipeline.renderer import render
from test_continuation import fixture,good_review


def reference_fixture(profile):
    c={'candidate_id':'reference_fixture','domain':'career_education','subtype':'recommendation',
       'subtype_label':'추천서','topic':'교재 개발','narrative_viewpoint':'first_person_recommender',
       'graph_policy':'scenario_v1','section_plan':sections_for('narrative',1800),
       'allowed_personal_types':CATALOG['domains']['career_education']['recommendation']['personal_types'],
       'allowed_public_types':['WORKPLACE','DEPARTMENT','SCHOOL','MAJOR','TELEPHONE','EMAIL','ADDRESS','POSITION'],
       'relation_count':4,'pii_relation_target':2,'non_pii_relation_target':2,'non_pii_only_min':2,
       'length_target':1800,'min_chars':1500,'required_relation_types':[],
       **select_people('career_education','recommendation',random.Random(1))}
    select_reference(c,{'reference_profile':profile})
    p=seed_plan(c,allowed_triples(c['domain']))
    return p,c


class ReferenceTests(unittest.TestCase):
    def test_all_registered_reference_kinds_preserve_real_party_count_and_budgets(self):
        for profile in PROFILES:
            p,c=reference_fixture(profile)
            check_plan(p,c)
            schema,_=planning_contract(c)
            validate(p,schema)
            self.assertEqual(len(p['relations']),4)
            self.assertEqual(sum(r['target_privacy']=='NON_PII' for r in p['relations']),2)
            self.assertEqual(sum(x['context_kind']=='actual_party' for x in p['persons']),2)
            ref=next(x for x in p['persons'] if x['context_kind']!='actual_party')
            self.assertEqual(privacy_groups(p)[ref['name_entity_id']],'NON_PII')

    def test_public_reference_values_come_from_verified_profile_not_random_pool(self):
        p,c=reference_fixture('marie_curie_education')
        rows=[{'NAME':name,'SCHOOL':'검증대학','MAJOR':'공학','TELEPHONE':'02-123-4567'}
              for name in ('테스트하나','테스트둘','테스트셋')]
        values=select_values(p,c,rows)
        ref=next(x for x in p['persons'] if x['context_kind']=='public_reference')
        v=values[ref['name_entity_id']]
        self.assertEqual(v['value'],'마리 퀴리')
        self.assertTrue(v['provenance']['urls'])
        self.assertIn('파리 대학교',[v['value'] for v in values.values()])

    def test_reference_cannot_be_given_unregistered_private_attribute_or_real_party_role(self):
        p,c=reference_fixture('marie_curie_education')
        ref=next(x for x in p['persons'] if x['context_kind']=='public_reference')
        edge=next(r for r in p['relations'] if r['source']==ref['name_entity_id'])
        edge['relation']='ORGANIZATIONAL_RELATION'
        with self.assertRaises(StageFailure) as raised:
            check_plan(p,c)
        self.assertIn('REFERENCE_FACT_SCOPE',[i.code for i in raised.exception.issues])
        p,c=reference_fixture('fictional_student')
        next(x for x in p['persons'] if x['context_kind']=='example_person')['context_kind']='actual_party'
        with self.assertRaises(StageFailure):
            check_plan(p,c)

    def test_actual_party_cannot_be_relabelled_non_pii(self):
        p,c=reference_fixture('fictional_story_student')
        next(r for r in p['relations'] if r['target_privacy']=='PII')['target_privacy']='NON_PII'
        with self.assertRaises(StageFailure) as raised:
            check_plan(p,c)
        self.assertIn('NAME_CONTEXT_POLICY',[i.code for i in raised.exception.issues])

    def test_unsupported_reference_document_does_not_silently_ignore_selection(self):
        _,c=reference_fixture('fictional_student')
        c.update(domain='medical',subtype='registration')
        with self.assertRaises(StageFailure):
            select_reference(c,{'reference_profile':'fictional_student'})

    def test_non_pii_name_mentions_remain_unmasked_and_actual_names_masked(self):
        p,c=reference_fixture('fictional_student')
        types={e['entity_id']:e['entity_type'] for e in p['entities']}
        segments=[{'sentence_id':f'S{i}','section_id':p['scenes'][0]['section_id'],'scene_id':'SC1','kind':'prose',
                   'text':f"<{types[r['source']]}:{r['source']}>의 사례 대상은 <{types[r['target']]}:{r['target']}>이다."}
                  for i,r in enumerate(p['relations'],1)]
        values={e['entity_id']:{'value':'테스트'+e['entity_id'],'canonical_form':'테스트'+e['entity_id']} for e in p['entities']}
        d={'draft_version':1,'segments':segments,'refs':[],'relation_evidence':[]}
        doc=annotate(render(d,p,values),p)
        ref=next(x for x in p['persons'] if x['context_kind']=='example_person')['name_entity_id']
        masked={s['form'] for row in doc['sentences'] for s in row['PII_set']}
        self.assertNotIn(values[ref]['value'],masked)
        self.assertTrue(all(values[x['name_entity_id']]['value'] in masked for x in p['persons'] if x['context_kind']=='actual_party'))


class ProseTests(unittest.TestCase):
    def test_required_section_tokens_do_not_force_single_sentence_evidence(self):
        plan,c,_,_=fixture(); c.update(document_policy='prose_v2')
        _,schema=draft_request(c,plan)
        response={'sections':{'main':{'relation_facts':{
            'R1':{'form':'linked_text','source_text':'<NAME:E1>의 신청을 받았다.','bridge_sentences':[],'target_text':'그가 제출한 연락처는 <MOBILE_PHONE:E2>이다.'},
            'R2':{'form':'sentence','text':'<WORKPLACE:E3>의 공용 메일은 <EMAIL:E4>이다.'},
            'R3':{'form':'sentence','text':'<WORKPLACE:E3>의 사무실은 <ADDRESS:E5>에 있다.'}},'context':'직원은 처리에 필요한 서류를 안내했다.'}}}
        d=decode_prose(response,c,plan,schema)
        self.assertEqual(d['relation_evidence'][0]['evidence_groups'],[['S1','S2']])
        response['sections']['main']['relation_facts']['R2']['text']='공용 메일을 확인했다.'
        with self.assertRaises(StageFailure):
            decode_prose(response,c,plan,schema)

    def test_review_feedback_cannot_copy_known_literal_contact_into_placeholder_draft(self):
        p,_,v,_=fixture()
        original={'issues':[{'code':'TEXT_FORMAT','message':'가온의 연락처 010-0000-0000을 본문에서 수정한다. <NAME:E1>은 유지한다.','sentence_id':'S1'}]}
        result=mask_known_feedback(original,p,v)
        self.assertIn('<NAME:E1>의 연락처 <MOBILE_PHONE:E2>',result['issues'][0]['message'])
        self.assertNotIn('010-0000-0000',str(result))
        self.assertIn('010-0000-0000',str(original))
        self.assertEqual(result['issues'][0]['sentence_id'],'S1')
        v['E3']['value']=v['E1']['value']
        v['E3']['canonical_form']=v['E1']['value']
        self.assertEqual(mask_known_feedback('가온',p,v),'가온')

    def test_simple_text_output_preserves_spans_and_does_not_claim_relation_semantics(self):
        plan,c,values,_=fixture()
        c.update(length_target=1800,min_chars=1500)
        _,schema=draft_request(c,plan)
        self.assertEqual(schema['properties']['sections']['properties']['main']['minItems'],1)
        response={'sections':{'main':['<NAME:E1>의 연락처는 <MOBILE_PHONE:E2>이다.',
                    '<WORKPLACE:E3>의 공용 메일은 <EMAIL:E4>이다.',
                    '그 기관의 사무실은 <ADDRESS:E5>에 있다.']}}
        draft=decode_prose(response,c,plan,schema)
        filled=render(draft,plan,values)
        self.assertEqual(len(filled['entities']),5)
        self.assertEqual(draft['relation_evidence'][2]['evidence_groups'],[['S2','S3']])
        review_payload=review_input(filled,plan,c)
        self.assertNotIn('relation_evidence',review_payload)
        self.assertNotIn('target_privacy',str(review_payload['relations']))

    def test_missing_endpoint_is_not_fabricated(self):
        plan,c,_,_=fixture()
        _,schema=draft_request(c,plan)
        d=decode_prose({'sections':{'main':['<NAME:E1>의 신청을 확인했다.']}},c,plan,schema)
        self.assertTrue(all(not e['evidence_groups'] for e in d['relation_evidence']))

    def test_quotes_are_exact_but_groups_and_labels_are_never_repaired(self):
        p,c,v,d=fixture(); filled=render(d,p,v)
        review=good_review(filled,p)
        before=copy.deepcopy(review)
        for item in [*review['relation_checks'],*review['reference_checks'],*review['person_checks']['observed_persons']]:
            item.pop('evidence_quotes')
        validate(review,id_only_schema(REVIEW))
        restored=materialize_quotes(review,filled)
        self.assertEqual(restored,before)
        self.assertTrue(check_review(restored,filled,p,c,d)['passed'])
        review['relation_checks'][0]['evidence_groups']=[['S2']]
        broken=materialize_quotes(review,filled)
        c['review_evidence_policy']='sentence_ids'
        checks=check_review(broken,filled,p,c,d)
        self.assertFalse(checks['passed'])
        self.assertFalse(checks['response_valid'])
        self.assertEqual(broken['relation_checks'][0]['evidence_groups'],[['S2']])
        review['relation_checks'][0]['evidence_groups']=[['UNKNOWN']]
        with self.assertRaises(StageFailure):
            materialize_quotes(review,filled)


if __name__=='__main__':
    unittest.main()
