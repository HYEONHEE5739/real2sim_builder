import copy
import json
from pathlib import Path
import numpy as np
import pytest
from PIL import Image
from app.core.project import Project,write,sha
from app.core.evidence import import_scene,import_metadata,add_image
from app.exporters.package import export_package,verify_package
from app.validation.render import configure


def test_mesh_assets_are_copied_and_hash_checked(tmp_path,scene):
    model=tmp_path/'triangle.stl'
    model.write_text('solid x\nfacet normal 0 0 1\nouter loop\nvertex 0 0 0\nvertex .05 0 0\nvertex 0 .05 0\nendloop\nendfacet\nendsolid x\n')
    # MuJoCo needs a volumetric visual mesh; use a box with triangulated faces.
    import struct
    vertices=np.array([[0,0,0],[.05,0,0],[0,.05,0],[0,0,.05]])
    faces=np.array([[0,2,1],[0,1,3],[0,3,2],[1,2,3]])
    data=bytearray(b'fixture'.ljust(80,b'\0')+struct.pack('<I',4))
    for face in faces:data.extend(struct.pack('<12fH',*([0.]*3),*vertices[face].ravel(),0))
    model.write_bytes(data);original=model.read_bytes()
    scene['assets']={'cad':{'path':'triangle.stl','sha256':sha(model)}}
    obj=copy.deepcopy(scene['objects'][1]);obj['id']='fixture';obj['role']='fixture';obj['visual']={'type':'mesh','asset':'cad'};obj['collision']={'type':'box'};scene['objects'].append(obj)
    write(tmp_path/'scene.yaml',scene);project=Project.create(tmp_path/'projects','CAD');import_scene(project,tmp_path/'scene.yaml')
    assert model.read_bytes()==original
    package=export_package(project,{'passed':False,'scope':'fixture export','input_signature':project.signature()},True)
    model.unlink();verify_package(package)
    import mujoco
    assert mujoco.MjModel.from_xml_path(str(package/'scene.xml')).nmesh==1
    copied=project.root/project.scene['assets']['cad']['path'];copied.write_bytes(b'changed')
    from app.core.scene import validate
    with pytest.raises(ValueError,match='hash'):validate(project.scene,project.root)


def test_measurement_import_preserves_calibrated_vs_measured_evidence(tmp_path):
    project=Project.create(tmp_path/'projects','Import');image=tmp_path/'real.png';mask=tmp_path/'mask.png'
    Image.fromarray(np.zeros((48,64,3),np.uint8)).save(image);Image.fromarray(np.ones((48,64),np.uint8)*255).save(mask)
    row=add_image(project,image,'side','train')
    metadata={'units':'m','objects':[{'id':'table','role':'support_surface','shape':'box','dimensions':[1,.8,.04],'pose':np.eye(4).tolist()}],
        'cameras':[{'id':'side','resolution':[64,48],'K':[[100,0,32],[0,100,24],[0,0,1]],'pose':np.eye(4).tolist()}],
        'masks':[{'image':'real.png','object':'table','path':'mask.png'}]}
    write(tmp_path/'measurements.yaml',metadata);import_metadata(project,tmp_path/'measurements.yaml')
    assert project.scene['objects'][0]['dimensions']['provenance']=='measured'
    assert project.evidence['masks'][0]['image']==row['path']
    assert (project.root/project.evidence['masks'][0]['path']).is_file()


def test_mjcf_reference_uses_snapshot_pose_without_controls(tmp_path):
    from app.core.evidence import import_robot
    from app.core.scene import world_pose
    from app.exporters.geometry import mesh_data
    path=tmp_path/'robot.xml'
    path.write_text('<mujoco><worldbody><body pos=".1 .2 .3"><joint name="q" type="slide" axis="1 0 0"/><geom type="box" size=".02 .03 .04"/></body></worldbody></mujoco>')
    project=Project.create(tmp_path/'projects','MJCF reference')
    import_robot(project,path,{'q':.05})
    obj=project.scene['objects'][0]
    assert obj['role']=='reference_robot' and obj['collision_enabled'] is False
    assert np.allclose(world_pose(project.scene,obj)[:3,3],[.15,.2,.3])
    asset=project.scene['assets'][obj['visual']['asset']]
    vertices,faces=mesh_data(project.root/asset['path'])
    assert np.allclose(np.ptp(vertices,axis=0),[.04,.06,.08])


def test_usd_reference_bakes_units_and_world_transform(tmp_path):
    pytest.importorskip('pxr')
    from pxr import Usd,UsdGeom,Gf
    from app.core.evidence import import_robot
    from app.exporters.geometry import mesh_data
    path=tmp_path/'robot.usda';stage=Usd.Stage.CreateNew(str(path))
    UsdGeom.SetStageMetersPerUnit(stage,.01);UsdGeom.SetStageUpAxis(stage,'Z')
    cube=UsdGeom.Cube.Define(stage,'/Robot');cube.CreateSizeAttr(2.)
    cube.AddTranslateOp().Set(Gf.Vec3d(10,20,30));stage.GetRootLayer().Save()
    project=Project.create(tmp_path/'projects','USD reference');import_robot(project,path)
    obj=project.scene['objects'][0];asset=project.scene['assets'][obj['visual']['asset']]
    vertices,_=mesh_data(project.root/asset['path'])
    assert np.allclose(vertices.mean(0),[.1,.2,.3])
    assert np.allclose(np.ptp(vertices,axis=0),[.02,.02,.02])


def test_rectification_preserves_original_and_is_resume_safe(tmp_path,scene):
    from app.calibration.preprocess import undistort_evidence
    from app.calibration.camera import project_point
    project=Project.create(tmp_path/'projects','Lens');scene['cameras'][0]['distortion']['value']=[.2,0,0,0,0]
    project.save_scene(scene);path=tmp_path/'original.png'
    Image.fromarray(np.zeros((120,160,3),np.uint8)).save(path);original=path.read_bytes()
    row=add_image(project,path,'side','train');point={'camera':'side','point_m':[.1,0,0],'uv':[0,0],'split':'train'}
    point['uv']=project_point(scene,scene['cameras'][0],point)[0].tolist()
    evidence=project.evidence;evidence['landmarks'].append(point);write(project.root/'input/evidence.yaml',evidence)
    undistort_evidence(project);first=project.evidence
    assert first['images'][0]['original_path']==row['path'] and path.read_bytes()==original
    expected=project_point(project.scene,project.scene['cameras'][0],point)[0]
    assert np.allclose(first['landmarks'][0]['uv'],expected,atol=1e-3)
    undistort_evidence(project);assert project.evidence==first
    add_image(project,path,'side');assert len(project.evidence['images'])==1


def test_partial_cloud_does_not_invent_hidden_extent(tmp_path,scene):
    from app.calibration.depth import fit_depth_geometry
    from app.core.scene import value
    cloud=tmp_path/'cloud.npy';np.save(cloud,np.array([[-.03,-.03,0],[.03,-.03,0],[-.03,.03,.06],[.03,.03,.06]]))
    scene['objects'][1]['dimensions']=value(None)
    evidence={'point_clouds':[{'path':'cloud.npy','object':'block','frame':'world'}]}
    candidate,reports=fit_depth_geometry(scene,evidence,tmp_path)
    assert candidate['objects'][1]['dimensions']['value'] is None and reports[0]['complete_coverage'] is False
    evidence['point_clouds'][0]['full_bounds']=True
    candidate,reports=fit_depth_geometry(scene,evidence,tmp_path)
    assert candidate['objects'][1]['dimensions']['provenance']=='derived'
    assert np.allclose(candidate['objects'][1]['dimensions']['value'],[.06,.06,.06])
