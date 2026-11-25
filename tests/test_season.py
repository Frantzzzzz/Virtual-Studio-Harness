import copy
import unittest
from season.continuity import initial_state, check_scene_script, context_packet, affected_artifacts
from season.motion import compile_scene, initial_physical_state, quaternion_angle_error
from season.direct_camera import validate_camera
from season.camera_envelope import swept_target_corners
from season.plan_series import validate_plan


class ContinuityTests(unittest.TestCase):
    def setUp(self):
        self.series = {'title':'test','premise':'test','characters':[], 'episodes':[],
                       'facts':[{'id':'F01','text':'one','initial_knowers':['A'],'requires':[]},
                                {'id':'F02','text':'two','initial_knowers':['B'],'requires':['F01']}]}
        self.scene = {'id':'s01','duration_s':10,'new_public_facts':['F01'],'box_end':'pickup'}
        self.script = {'summary':'one disclosed','box_end':'pickup','dialogue':[
            {'start_s':0,'end_s':5,'speaker':'A','text':'a'*20,'uses_facts':['F01'],'reveals_facts':['F01']},
            {'start_s':5,'end_s':10,'speaker':'C','text':'b'*20,'uses_facts':['F01'],'reveals_facts':[]}]}

    def test_reveal_becomes_known_to_all_present_without_mutating_entry(self):
        entry = initial_state(self.series)
        after, errors, _ = check_scene_script(self.scene,self.script,entry,self.series)
        self.assertFalse(errors)
        self.assertNotIn('F01',entry['knowledge']['C'])
        self.assertIn('F01',after['knowledge']['C'])

    def test_a_speaker_cannot_use_a_future_revelation(self):
        self.script['dialogue'][0].update(speaker='C')
        _,errors,_ = check_scene_script(self.scene,self.script,initial_state(self.series),self.series)
        self.assertTrue(any('unknown fact' in e for e in errors))

    def test_deduction_requires_public_evidence(self):
        self.scene['new_public_facts']=['F02']
        self.script['dialogue'][0].update(speaker='B',uses_facts=['F02'],reveals_facts=['F02'])
        _,errors,_ = check_scene_script(self.scene,self.script,initial_state(self.series),self.series)
        self.assertTrue(any('missing public evidence' in e for e in errors))

    def test_cycles_are_rejected(self):
        self.series['facts'][0]['requires']=['F02']
        with self.assertRaisesRegex(ValueError,'Cyclic'):
            initial_state(self.series)

    def test_context_does_not_grow_with_raw_history(self):
        state=initial_state(self.series)
        state['history']=[{'scene':str(i),'summary':'brief'} for i in range(100)]
        packet=context_packet(self.series,{'id':'ep05'},state)
        self.assertEqual(len(packet['recent_scene_summaries']),3)
        self.assertNotIn('history',packet['entry_state'])

    def test_camera_change_does_not_invalidate_story_or_motion(self):
        dependencies={'script':['facts'],'motion':['script'],'camera':['motion'],'video':['camera']}
        self.assertEqual(affected_artifacts({'camera'},dependencies),{'camera','video'})
        self.assertEqual(affected_artifacts({'facts'},dependencies),set(dependencies)|{'facts'})

    def test_idle_padding_is_rejected(self):
        self.script['dialogue']=self.script['dialogue'][:1]
        _,errors,_=check_scene_script(self.scene,self.script,initial_state(self.series),self.series)
        self.assertTrue(any('silence' in e or '75%' in e for e in errors))


class ActionBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.studio={'anchors':{name:{'position':point} for name,point in {
            'west_entry':[-3,0,0],'pickup_stand':[-1.1,0,.95],
            'handover_A':[-.5,0,0],'handover_B':[.5,0,0],
            'east_wait':[2.5,0,0],'observer':[0,0,-2]}.items()},
            'interaction':{'pickup_box':[-.34,.8,.95],'drop_box':[2.7,.8,-2]}}
        self.entry=initial_physical_state()
        self.op={'kind':'take','actor':'A','other':None,'route':[],'site':'pickup',
                 'start_s':1,'contact_s':2,'transfer_s':2,'end_s':3}

    def compile(self, operation):
        def unexpected_backend(*args,**kwargs):
            raise AssertionError('Bad plan reached backend')
        return compile_scene({'duration_s':10,'box_end':'A'},{'operations':[operation]},
                             self.entry,self.studio,{'routes':[]},unexpected_backend,unexpected_backend)

    def test_take_requires_the_measured_standing_point(self):
        with self.assertRaisesRegex(ValueError,'must stand at pickup_stand'):
            self.compile(self.op)

    def test_take_cannot_steal_an_already_held_prop(self):
        self.entry['actors']['A']['node']='pickup_stand';self.entry['box']='B'
        with self.assertRaisesRegex(ValueError,'already-held box'):
            self.compile(self.op)

    def test_route_cannot_start_at_a_convenient_fake_position(self):
        self.op.update(kind='move',route=['pickup_stand','handover_A'],contact_s=None,transfer_s=None)
        with self.assertRaisesRegex(ValueError,'actual node west_entry'):
            self.compile(self.op)

    def test_cannot_walk_an_unmeasured_edge(self):
        self.op.update(kind='move',route=['west_entry','handover_A'],contact_s=None,transfer_s=None)
        with self.assertRaisesRegex(ValueError,'Unmeasured route'):
            self.compile(self.op)


class PlanBoundaryTests(unittest.TestCase):
    def plan(self):
        return {'characters':[{'id':a} for a in 'ABC'],
                'episodes':[{'id':f'ep{i:02d}','scenes':[{'id':f'ep{i:02d}_s{j:02d}','duration_s':80} for j in range(1,7)]} for i in range(1,6)]}

    def test_generated_ids_cannot_escape_artifact_directory(self):
        plan=self.plan();plan['episodes'][0]['scenes'][0]['id']='../../elsewhere'
        with self.assertRaisesRegex(ValueError,'safe episode-local'):
            validate_plan(plan)

    def test_extra_minutes_cannot_be_hidden_in_a_season_plan(self):
        plan=self.plan();plan['episodes'][0]['scenes'][0]['duration_s']=90
        with self.assertRaisesRegex(ValueError,'480 seconds'):
            validate_plan(plan)


class EnvelopeTests(unittest.TestCase):
    def test_quaternion_error_is_not_float_norm_or_sign_error(self):
        q=(.707106769,0,.707106769,0)
        self.assertLess(quaternion_angle_error(q,tuple(-x for x in q)),1e-7)

    def test_static_camera_envelope_contains_both_ends_of_a_walk(self):
        rows=[{'actors':{'A':{'position':[x,0,0]}},'props':{'box':{'position':[x,0,1]}}} for x in (0,4)]
        corners=swept_target_corners(rows,['A'],[.22,.14,.1])['A_head']
        self.assertAlmostEqual(min(p[0] for p in corners),-.17)
        self.assertAlmostEqual(max(p[0] for p in corners),4.17)

    def test_follow_camera_envelope_removes_its_authored_translation(self):
        rows=[{'actors':{'A':{'position':[x,0,0]}},'props':{'box':{'position':[x,0,1]}}} for x in (0,4)]
        corners=swept_target_corners(rows,['A','box'],[.22,.14,.1],'A',[2,0,0])
        self.assertAlmostEqual(min(p[0] for p in corners['A_head']),1.83)
        self.assertAlmostEqual(max(p[0] for p in corners['A_head']),2.17)


if __name__=='__main__':unittest.main()
