from copy import deepcopy
import unittest

from test_continuation import fixture
from relation_pipeline.common import StageFailure
from relation_pipeline.content_depth import DEPTH
from relation_pipeline.formats import CATALOG
from relation_pipeline.repair_tasks import build_tasks, repair_contract, decode_patch
from relation_pipeline.stages.stage05_assemble import diagnose, apply_patch, repair_input
from relation_pipeline.schemas import validate


class AdditiveLengthTests(unittest.TestCase):
    def setUp(self):
        self.plan, self.condition, self.values, self.draft = fixture()
        self.condition.update(min_chars=1500, length_target=2000)
        self.condition['section_plan'][0]['target_chars'] = 2000
        self.diagnosis, _ = diagnose(self.draft, self.condition, self.plan, self.values)
        self.draft = self.diagnosis['normalized_draft']

    def test_six_domain_content_coverage(self):
        self.assertEqual(len(CATALOG['domains']), 6)
        expected = {sub for domain in CATALOG['domains'].values() for sub in domain}
        self.assertEqual(set(DEPTH), expected)
        self.assertEqual(len(expected), 78)

    def test_length_only_response_has_no_edit_channels(self):
        tasks = build_tasks(self.draft,self.condition,self.plan,self.diagnosis)
        self.assertEqual(tasks['length_mode'], 'append_only')
        schema = repair_contract(self.draft,self.condition,self.plan,tasks)
        props = schema['properties']
        self.assertEqual(props['replacements']['properties'], {})
        self.assertEqual(props['relation_repairs']['properties'], {})
        self.assertEqual(props['refs']['maxItems'], 0)
        self.assertEqual(props['insertions']['maxItems'], 0)
        wire = {'base_draft_version':1,'insertions':[],'refs':[],
                'replacements':{},'relation_repairs':{},'relation_evidence_updates':{},
                'continuations':{'SC1':'오류 재현은 새 계정과 기존 계정에서 각각 확인했으며 기존 계정에서만 설정 저장에 실패했다.'}}
        patch = decode_patch(wire,schema,self.draft,self.condition,self.plan,tasks)
        merged = apply_patch(self.draft,patch,self.diagnosis)
        self.assertEqual(merged['segments'][:len(self.draft['segments'])], self.draft['segments'])
        self.assertEqual(merged['refs'],self.draft['refs'])
        self.assertEqual(merged['relation_evidence'],self.draft['relation_evidence'])
        wire['replacements'] = {'S1':self.draft['segments'][0]}
        with self.assertRaises(StageFailure): validate(wire,schema)

    def test_patch_layer_independently_rejects_rewrite_and_copy(self):
        patch = {'base_draft_version':1,'replacements':[], 'refs':[],
                 'relation_evidence_updates':[], 'insertions':[{'after_sentence_id':'S5',
                    'segments':[{**self.draft['segments'][0], 'sentence_id':'S6','text':'세부 확인을 추가했다.'}]}]}
        for field, item in [('replacements',self.draft['segments'][0]),
                            ('refs',self.draft['refs'][0]),
                            ('relation_evidence_updates',self.draft['relation_evidence'][0])]:
            changed=deepcopy(patch);changed[field]=[item]
            with self.assertRaises(StageFailure) as caught:
                apply_patch(self.draft,changed,self.diagnosis)
            self.assertEqual(caught.exception.issues[0].code,'LENGTH_REWRITE_FORBIDDEN')
        patch['insertions'][0]['segments'][0]['text']=self.draft['segments'][0]['text']
        with self.assertRaises(StageFailure) as caught:
            apply_patch(self.draft,patch,self.diagnosis)
        self.assertEqual(caught.exception.issues[0].code,'LENGTH_ADDITION_REPEATED')

    def test_full_body_and_concrete_depth_reach_expansion(self):
        payload = repair_input(self.draft,self.condition,self.plan,self.diagnosis)
        self.assertEqual(payload['draft']['segments'],self.draft['segments'])
        self.assertEqual(payload['condition']['min_chars'],1500)
        self.assertIn('진단 시도 3회와 각 결과',payload['condition']['content_depth']['facts_to_develop'])
        targets=payload['repair_tasks']['continuation_targets']
        self.assertGreaterEqual(sum(t['minimum_new_chars'] for t in targets),self.diagnosis['metrics']['shortage_chars'])
