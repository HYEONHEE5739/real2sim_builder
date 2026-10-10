from pathlib import Path
import copy
import xml.etree.ElementTree as ET
import numpy as np
import pytest
from app.core.scene import value
from app.exporters.geometry import parts
from app.exporters import usd,mujoco


def test_open_container_is_not_a_filled_convex_shape(scene,tmp_path):
    obj=copy.deepcopy(scene['objects'][1]);obj['id']='bin';obj['role']='receptacle';obj['dimensions']=value([.2,.15,.1],'measured')
    obj['visual']={'type':'container','wall':value(.005,'measured')};obj['collision']=copy.deepcopy(obj['visual']);scene['objects'].append(obj)
    components=parts(obj,'collision');assert len(components)==5
    assert all(p['type']=='box' for p in components)
    mujoco.export(scene,tmp_path,tmp_path/'scene.xml')
    import mujoco as engine
    assert engine.MjModel.from_xml_path(str(tmp_path/'scene.xml')).ngeom==14


def test_usd_transforms_camera_and_metres_load(scene,tmp_path):
    pxr=pytest.importorskip('pxr')
    from pxr import Usd,UsdGeom
    usd.export(scene,tmp_path,tmp_path/'scene.usd');stage=Usd.Stage.Open(str(tmp_path/'scene.usd'))
    assert stage.GetDefaultPrim() and UsdGeom.GetStageMetersPerUnit(stage)==1
    t=UsdGeom.Xformable(stage.GetPrimAtPath('/Scene/block')).ComputeLocalToWorldTransform(Usd.TimeCode.Default())
    assert np.allclose(np.asarray(t).T,np.asarray(scene['objects'][1]['pose']['value']))
    c=UsdGeom.Camera(stage.GetPrimAtPath('/Scene/side'));assert c.GetFocalLengthAttr().Get()==10


def test_offcenter_intrinsics_match_both_engine_projections(scene,tmp_path):
    from app.validation.render import Renderer
    from app.calibration.camera import project_point
    from app.core.scene import world_pose
    camera=scene['cameras'][0];camera['K']['value']=[[160.,0,91.],[0,135.,49.],[0,0,1]]
    block=scene['objects'][1];block['pose']['value'][2][3]=.1
    block['visual']={'type':'sphere'};block['collision']={'type':'sphere'};block['dimensions']['value']=[.04]*3
    expected,_=project_point(scene,camera,{'object':'block','point_m':[0,0,0]})
    with Renderer(scene,tmp_path,tmp_path/'scratch','software-egl') as renderer:
        y,x=np.nonzero(renderer.mask('side','block'))
        assert len(x)>0
        assert np.linalg.norm(np.array([x.mean()+.5,y.mean()+.5])-expected)<1.0
    pytest.importorskip('pxr')
    from pxr import Usd,UsdGeom
    usd.export(scene,tmp_path,tmp_path/'scene.usd');stage=Usd.Stage.Open(str(tmp_path/'scene.usd'))
    frustum=UsdGeom.Camera(stage.GetPrimAtPath('/Scene/side')).GetCamera(Usd.TimeCode.Default()).frustum
    point=np.r_[world_pose(scene,block)[:3,3],1.]
    clip=point@np.asarray(frustum.ComputeViewMatrix())@np.asarray(frustum.ComputeProjectionMatrix())
    ndc=clip[:3]/clip[3];w,h=camera['resolution'];pixel=np.array([(ndc[0]+1)*w/2,(1-ndc[1])*h/2])
    assert np.allclose(pixel,expected,atol=.001)


def test_textured_material_loads_with_surface_connection(scene,tmp_path):
    pytest.importorskip('pxr')
    from pxr import Usd,UsdShade,Sdf
    from PIL import Image
    from app.core.project import sha
    texture=tmp_path/'camera.png';Image.new('RGB',(8,8),(30,30,30)).save(texture)
    scene['assets']['camera_texture']={'path':'camera.png','sha256':sha(texture)}
    obj=scene['objects'][1];obj['visual']['texture']='camera_texture'
    destination=tmp_path/'scene.usd';usd.export(scene,tmp_path,destination)
    stage=Usd.Stage.Open(str(destination))
    material_path='/Scene/material_'+obj['id']
    surface=UsdShade.Shader(stage.GetPrimAtPath(material_path+'/Surface'))
    assert surface.GetInput('diffuseColor').GetAttr().GetConnections()==[Sdf.Path(material_path+'/Image.outputs:rgb')]
    image=UsdShade.Shader(stage.GetPrimAtPath(material_path+'/Image'))
    assert image.GetInput('file').Get().path=='camera.png'
    assert UsdShade.Material(stage.GetPrimAtPath(material_path)).GetSurfaceOutput().HasConnectedSource()
