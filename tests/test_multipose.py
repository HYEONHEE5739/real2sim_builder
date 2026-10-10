import copy
import numpy as np
import pytest
from app.core.candidates import nonregression
from app.calibration.robot import link_transforms


def test_mjcf_named_fk(tmp_path):
    path=tmp_path/'robot.xml';path.write_text('<mujoco><worldbody><body name="arm"><joint name="joint" axis="0 0 1"/><geom type="box" pos=".1 0 0" size=".1 .01 .01" mass="1"/><body name="mount" pos=".2 0 0"/></body></worldbody></mujoco>')
    a=link_transforms(path,{'joint':0});b=link_transforms(path,{'joint':np.pi/2})
    assert np.allclose(a['mount'][:3,3],[.2,0,0])
    assert np.allclose(b['mount'][:3,3],[0,.2,0],atol=1e-6)
    with pytest.raises(ValueError):link_transforms(path,{'wrong':0})


def test_holdout_regression_blocks_train_gain():
    baseline={'multipose':{s:{'count':8,'rmse_px':2.,'behind_camera':0} for s in ('train','validation')},'images':[{'image':'held.png','split':'validation','mae':.1,'silhouettes':[]}]}
    proposal=copy.deepcopy(baseline);proposal['multipose']['train']['rmse_px']=1.
    assert nonregression(baseline,proposal)['passed']
    proposal['multipose']['validation']['rmse_px']=3.
    assert not nonregression(baseline,proposal)['passed']
    proposal['multipose']['validation']['rmse_px']=2.;proposal['images'][0]['mae']=.2
    assert not nonregression(baseline,proposal)['passed']


def test_independent_snapshot_import_without_so101_or_events(tmp_path):
    from PIL import Image
    from app.core.project import Project,write,sha
    from app.core.capture import import_snapshots,observation_scene
    root=tmp_path/'generic_snapshots';(root/'robot_model').mkdir(parents=True)
    model=root/'robot_model/robot.xml'
    model.write_text('<mujoco><worldbody><body name="arm"><joint name="joint" axis="0 0 1"/><geom type="box" pos=".1 0 0" size=".1 .01 .01" mass="1"/><body name="mount" pos=".2 0 0"/></body></worldbody></mujoco>')
    cameras=[{'id':'side','parent':'world','K':[[100,0,80],[0,100,60],[0,0,1]],'resolution':[160,120],
        'distortion':[0]*5,'T_parent_camera':np.eye(4).tolist(),'provenance':{'K':'calibrated'}}]
    manifest={'schema':'real2sim.snapshot/1','dataset_id':'generic_snapshots','scene_name':'Generic',
        'clock':{'domain':'host_monotonic_ns'},'joint_names':['joint'],'joint_units':['rad'],
        'q_measured_source':'physical_follower_feedback_converted_to_model','joint_mapping':{'source':'fixture'},
        'robot':{'path':'robot_model/robot.xml','format':'mjcf','T_world_base':np.eye(4).tolist()},
        'cameras':cameras,'scene_states':{'static_001':{}},'snapshots':[],
        'files':{'robot_model/robot.xml':sha(model)}}
    for i,q in enumerate([0.,.5,1.]):
        name=f'snapshot_{i+1:06d}';folder=root/'snapshots'/name;folder.mkdir(parents=True)
        Image.fromarray(np.tile((np.indices((120,160)).sum(0)%2*255).astype('uint8')[:,:,None],(1,1,3))).save(folder/'side.png')
        write(folder/'state.json',{'timestamp_ns':100,'q_measured':[q],
            'measured_samples':[{'timestamp_ns':0,'q_measured':[q]},{'timestamp_ns':100,'q_measured':[q]}],
            'real_stability':{'stable':True,'window_start_ns':0,'window_end_ns':100}})
        write(folder/'metadata.json',{'id':name,'scene_state_id':'static_001',
            'images':[{'path':'side.png','camera':'side','timestamp_ns':50,'read_start_ns':45,'q_measured':[q],
                'resolution':[160,120],'blur_variance':100.}],
            'files':{n:sha(folder/n) for n in ('side.png','state.json')}})
        (folder/'COMPLETE').write_text('1');manifest['snapshots'].append({'id':name,'scene_state_id':'static_001',
            'path':'snapshots/'+name,'metadata_sha256':sha(folder/'metadata.json')})
    write(root/'capture_manifest.yaml',manifest);(root/'COMPLETE').write_text('1')
    p=Project.create(tmp_path/'projects','Generic snapshot')
    assert import_snapshots(p,root,['snapshot_000003'])['eligible']==3
    assert not np.allclose(observation_scene(p.scene,p.evidence['images'][0],p.root)['frames']['robot_link_mount']['transform']['value'],
                           observation_scene(p.scene,p.evidence['images'][2],p.root)['frames']['robot_link_mount']['transform']['value'])
    assert not (root/'events.json').exists()
