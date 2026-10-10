import copy
import numpy as np
import pytest
from app.calibration.camera import project_point,fit_cameras,landmark_metrics
from app.calibration.robot import link_transforms


def test_camera_fit_uses_metric_train_points_and_preserves_geometry(scene):
    truth=copy.deepcopy(scene);camera=truth['cameras'][0];rows=[]
    for i,point in enumerate([[-.1,-.1,0],[.1,-.1,0],[-.1,.1,0],[.1,.1,0],[0,0,.1],[.04,-.05,.12],[.02,.02,.05]]):
        row={'camera':'side','point_m':point,'split':'train' if i<6 else 'validation'}
        row['uv']=project_point(truth,camera,row)[0].tolist();rows.append(row)
    scene['cameras'][0]['pose']['value'][0][3]+=.035
    before=copy.deepcopy(scene['objects']);fitted,report=fit_cameras(scene,rows)
    metrics=landmark_metrics(fitted,[rows[-1]])
    assert metrics['rmse_px']<.01 and fitted['objects']==before
    assert fitted['cameras'][0]['pose']['provenance']=='optimized'
    assert report[0]['points']==6


def test_robot_fk_does_not_depend_on_any_robot_project(tmp_path):
    urdf=tmp_path/'robot.urdf';urdf.write_text('''<robot name="reference"><link name="root"/><link name="tool"/><joint name="hinge" type="revolute"><parent link="root"/><child link="tool"/><origin xyz="1 0 0"/><axis xyz="0 0 1"/><limit lower="-3" upper="3" effort="1" velocity="1"/></joint></robot>''')
    pose=link_transforms(urdf,{'hinge':np.pi/2})['tool']
    assert np.allclose(pose[:3,3],[1,0,0]) and np.allclose(pose[:3,0],[0,1,0],atol=1e-8)
    with pytest.raises(ValueError):link_transforms(urdf,{})


def test_object_pose_is_recovered_from_calibrated_image_corners(scene):
    from app.calibration.camera import fit_geometry
    truth=copy.deepcopy(scene);obj=truth['objects'][1];rows=[]
    for i,point in enumerate([[-.03,-.03,-.03],[.03,-.03,-.03],[-.03,.03,-.03],[.03,.03,-.03],[-.03,-.03,.03],[.03,.03,.03]]):
        row={'camera':'side','object':'block','point_m':point,'split':'train'}
        row['uv']=project_point(truth,truth['cameras'][0],row)[0].tolist();rows.append(row)
    scene['objects'][1]['pose']['value']=None;scene['objects'][1]['pose']['provenance']='unknown'
    fitted,report=fit_geometry(scene,rows)
    assert np.allclose(fitted['objects'][1]['pose']['value'],obj['pose']['value'],atol=1e-4)
    assert report[0]['object']=='block'


def test_passive_motion_friction_fit_and_unobservable_mass(scene,tmp_path):
    from app.calibration.physics import trajectory,fit
    from app.core.scene import value
    scene['objects'][1]['physics']['mass_kg']=value(.12,'measured')
    scene['objects'][1]['physics']['friction']=value(.7,'measured')
    motion={'object':'block','support':'table','times_s':[0,.1,.2,.3,.4],
        'positions_world_m':[[0,0,.03]]*5,'initial_velocity_m_s':[1.,0,0],'split':'train','fit_parameters':['friction']}
    motion['positions_world_m']=trajectory(scene,tmp_path,tmp_path,motion).tolist()
    held=copy.deepcopy(motion);held['split']='validation';held['initial_velocity_m_s']=[.8,0,0]
    held['positions_world_m']=trajectory(scene,tmp_path,tmp_path,held).tolist()
    seed=copy.deepcopy(scene);seed['objects'][1]['physics']['friction']=value(.5,'estimated')
    fitted,report=fit(seed,tmp_path,tmp_path,[motion,held])
    assert abs(fitted['objects'][1]['physics']['friction']['value']-.7)<.05
    assert report[-1]['rmse_m']<.005
    seed['objects'][1]['physics']['mass_kg']=value(None)
    with pytest.raises(ValueError,match='measured object mass'):trajectory(seed,tmp_path,tmp_path,motion)
