import copy
import unittest

from relation_pipeline.document_purpose import CAREER, PURPOSES, apply_purpose, brief_for, prose_metrics
from relation_pipeline.formats import CATALOG
from relation_pipeline.renderer import render
from relation_pipeline.stages.stage02_plan import planning_input
from relation_pipeline.stages.stage07_review import review_input
from relation_pipeline.repair_tasks import build_tasks, repair_contract
from relation_pipeline.stages.stage05_assemble import diagnose
from test_continuation import fixture


class DocumentPurposeTests(unittest.TestCase):
    def test_all_catalog_types_have_reader_expectations(self):
        self.assertEqual(set(CAREER),set(CATALOG['domains']['career_education']))
        for domain,subtypes in CATALOG['domains'].items():
            if domain != 'career_education':
                self.assertEqual(set(PURPOSES[domain]),set(subtypes))
            for subtype in subtypes:
                spec=brief_for(domain,subtype)
                self.assertEqual(len(spec['section_functions']),4)
                self.assertTrue(spec['goal'])

    def test_legacy_condition_and_explicit_viewpoint_are_preserved(self):
        _,condition,_,_=fixture()
        before=copy.deepcopy(condition)
        self.assertEqual(apply_purpose(condition,{'document_policy':'legacy'}),before)
        condition.update(domain='career_education',subtype='cover_letter',narrative_viewpoint='custom',layout_variant='narrative',layout_variant_label='old')
        original=copy.deepcopy(condition)
        apply_purpose(condition,{'document_policy':'purpose_v1','selection':{'viewpoint':'custom'}})
        self.assertEqual(condition['narrative_viewpoint'],'custom')
        self.assertEqual(condition['relation_count'],original['relation_count'])
        self.assertEqual(condition['section_plan'][0]['section_id'],original['section_plan'][0]['section_id'])

    def test_purpose_is_shared_but_private_plan_is_not_given_to_reviewer(self):
        plan,condition,values,draft=fixture()
        condition.update(purpose_review=True,topic='배송 문제')
        payload=review_input(render(draft,plan,values),plan,condition)
        self.assertEqual(payload['topic'],'배송 문제')
        self.assertIn('document_expectation',payload)
        self.assertNotIn('scene_notes',payload)
        self.assertNotIn('context_reason',str(payload['relations']))
        self.assertNotIn('target_privacy',str(payload['relations']))

    def test_new_planner_does_not_echo_boilerplate_and_keeps_graph(self):
        _,condition,_,_=fixture()
        old,_=planning_input(condition)
        condition['document_policy']='purpose_v1'
        new,_=planning_input(condition)
        for before,after in zip(old['seed_plan']['relations'],new['seed_plan']['relations']):
            self.assertEqual({k:v for k,v in before.items() if k!='context_reason'},
                             {k:v for k,v in after.items() if k!='context_reason'})
            self.assertEqual(after['context_reason'],'')
        self.assertTrue(all(s['outline']=='' for s in new['seed_plan']['scenes']))

    def test_repeat_observation_does_not_confuse_changed_facts_with_exact_repetition(self):
        text='<NAME:E1>은 제출된 신청 내용과 첨부된 관련 자료를 확인하고 담당자에게 전달했다.'
        d={'segments':[{'kind':'prose','text':text},{'kind':'prose','text':text},
                       {'kind':'prose','text':'불량의 원인은 출고 전 검사 단계의 누락으로 확인되어 검수 순서를 조정했다.'}]}
        self.assertEqual(prose_metrics(d)['near_duplicate_sentences'],1)

    def test_fact_schema_requires_actual_notes_but_preserves_fixed_graph(self):
        _,condition,_,_=fixture()
        old,_=planning_input(condition)
        condition['document_policy']='purpose_v2'
        new,schema=planning_input(condition)
        fields=('relation_id','source','target','relation','target_privacy')
        self.assertEqual([[r[k] for k in fields] for r in old['seed_plan']['relations']],
                         [[r[k] for k in fields] for r in new['seed_plan']['relations']])
        self.assertTrue(all(not r['scene_id'] for r in new['seed_plan']['relations']))
        for note in schema['properties']['scene_notes']['properties'].values():
            self.assertIn('facts',note['required'])
            self.assertGreaterEqual(note['properties']['facts']['minItems'],2)

    def test_factual_repair_keeps_sentence_evidence_and_forbids_fragment_joining(self):
        plan,condition,values,draft=fixture()
        condition.update(document_policy='purpose_v2',min_chars=0,length_target=800)
        for section in condition['section_plan']:
            section['target_chars']=800
        draft['segments'][0]['text']='신청 내용을 확인했다.'
        diagnosis,_=diagnose(draft,condition,plan,values)
        tasks=build_tasks(draft,condition,plan,diagnosis)
        schema=repair_contract(draft,condition,plan,tasks)
        self.assertTrue(schema['properties']['relation_repairs']['properties'])
        for unit in schema['properties']['relation_repairs']['properties'].values():
            self.assertEqual({b['properties']['form']['enum'][0] for b in unit['anyOf']},{'sentence','linked_text'})


if __name__=='__main__':
    unittest.main()
