"""Read exported MJCF and USD back; compare geometry and cameras to the canonical recipe."""
from pathlib import Path
import xml.etree.ElementTree as ET
import json
import numpy as np
from scipy.spatial.transform import Rotation
from app.core.scene import world_pose, local_path
from app.core.cameras import render_pose
from app.exporters.geometry import parts,mesh_data

TOLERANCE=1e-5


def check(scene,root,mjcf,usd):
    failures=[];checks=[]
    def equal(name,actual,expected):
        a=np.asarray(actual);b=np.asarray(expected)
        okay=a.shape==b.shape and np.allclose(a,b,atol=TOLERANCE,rtol=TOLERANCE)
        (checks if okay else failures).append(name)
    def truth(name,condition): (checks if condition else failures).append(name)
    def pose(node):
        t=np.eye(4);t[:3,3]=np.fromstring(node.get('pos','0 0 0'),sep=' ')
        q=np.fromstring(node.get('quat','1 0 0 0'),sep=' ');t[:3,:3]=Rotation.from_quat(np.r_[q[1:],q[0]]).as_matrix();return t
    tree=ET.parse(mjcf).getroot();bodies={b.get('name'):b for b in tree.findall('worldbody/body')}
    ids={o['id'] for o in scene['objects']};truth('mujoco object IDs/count',set(bodies)==ids)
    meshes={m.get('name'):m for m in tree.findall('asset/mesh')}
    try:
        from pxr import Usd,UsdGeom
    except ImportError:
        return {'status':'UNAVAILABLE','reason':'pxr USD bindings required for structural parity (Isaac runtime not required)', 'failures':failures}
    stage=Usd.Stage.Open(str(usd))
    if stage is None: return {'status':'FAIL','failures':['USD load']}
    frame_node=tree.find("custom/text[@name='canonical_frames']")
    truth('MJCF canonical frame graph metadata',frame_node is not None and json.loads(frame_node.get('data'))==scene['frames'])
    frame_attr=stage.GetPrimAtPath('/Scene').GetAttribute('canonical_frames').Get()
    truth('USD canonical frame graph metadata',bool(frame_attr) and json.loads(frame_attr)==scene['frames'])
    role_node=tree.find("custom/text[@name='semantic_roles']")
    truth('MJCF semantic roles',role_node is not None and json.loads(role_node.get('data'))=={o['id']:o['role'] for o in scene['objects']})
    usd_objects={p.GetName() for p in stage.GetPrimAtPath('/Scene').GetChildren() if p.IsA(UsdGeom.Xform)}
    truth('usd object IDs/count',usd_objects==ids)
    equal('usd metre units',UsdGeom.GetStageMetersPerUnit(stage),1.)
    truth('usd Z up',UsdGeom.GetStageUpAxis(stage)=='Z')
    for obj in scene['objects']:
        name=obj['id'];body=bodies.get(name);prim=stage.GetPrimAtPath('/Scene/'+name)
        if body is None or not prim: failures.append(name+' missing');continue
        equal(name+' MJCF world pose',pose(body),world_pose(scene,obj))
        equal(name+' USD world pose',np.asarray(UsdGeom.Xformable(prim).ComputeLocalToWorldTransform(Usd.TimeCode.Default())).T,world_pose(scene,obj))
        truth(name+' USD semantic role',prim.GetAttribute('semantic_role').Get()==obj['role'])
        dynamic=obj['role']=='manipulable_object' and (obj['physics']['mass_kg']['value'] or 0)>0
        truth(name+' MJCF dynamic intent',(body.find('freejoint') is not None)==dynamic)
        truth(name+' USD dynamic intent',bool(prim.GetAttribute('physics:rigidBodyEnabled').Get())==dynamic)
        expected_count=sum(len(parts(obj,f)) for f in ('visual','collision'))
        equal(name+' MJCF part count',len(body.findall('geom')),expected_count)
        equal(name+' USD part count',len(list(prim.GetChildren())),expected_count)
        for field in ('visual','collision'):
            for i,part in enumerate(parts(obj,field)):
                label=name+'_'+field+'_'+str(i);node=body.find("geom[@name='"+label+"']")
                sub=stage.GetPrimAtPath('/Scene/'+name+'/'+field+'_'+str(i))
                if node is None or not sub: failures.append(label+' missing');continue
                equal(label+' MJCF local pose',pose(node),part['pose'])
                expected=part['pose'].copy();kind=part['type'];dims=part['dimensions']
                if kind=='box':expected[:3,:3]=expected[:3,:3]@np.diag(dims/2)
                equal(label+' USD local pose/scale',np.asarray(UsdGeom.Xformable(sub).GetLocalTransformation()).T,expected)
                truth(label+' primitive kind',node.get('type')==kind and sub.GetTypeName()=={'box':'Cube','sphere':'Sphere','cylinder':'Cylinder','mesh':'Mesh'}[kind])
                if kind in ('box','sphere','cylinder'):
                    expected_size=dims/2 if kind=='box' else [dims[0]/2] if kind=='sphere' else [dims[0]/2,dims[2]/2]
                    equal(label+' MJCF dimensions',np.fromstring(node.get('size'),sep=' '),expected_size)
                    if kind=='box':equal(label+' USD size',UsdGeom.Cube(sub).GetSizeAttr().Get(),2.)
                    elif kind=='sphere':equal(label+' USD radius',UsdGeom.Sphere(sub).GetRadiusAttr().Get(),dims[0]/2)
                    else:
                        equal(label+' USD radius',UsdGeom.Cylinder(sub).GetRadiusAttr().Get(),dims[0]/2)
                        equal(label+' USD height',UsdGeom.Cylinder(sub).GetHeightAttr().Get(),dims[2])
                else:
                    mesh=meshes[node.get('mesh')];asset=local_path(root,scene['assets'][part['asset']]['path'])
                    truth(label+' visual asset reference',(Path(mjcf).parent/mesh.get('file')).resolve()==asset)
                    scale=part.get('scale',[1,1,1]);equal(label+' mesh scale',np.fromstring(mesh.get('scale','1 1 1'),sep=' '),scale)
                    vertices,faces=mesh_data(asset);usdmesh=UsdGeom.Mesh(sub)
                    equal(label+' USD mesh vertices',usdmesh.GetPointsAttr().Get(),vertices*np.asarray(scale))
                    equal(label+' USD mesh faces',usdmesh.GetFaceVertexIndicesAttr().Get(),faces.ravel())
                texture=obj['visual'].get('texture') if field=='visual' else None
                if texture:
                    material=tree.find("asset/material[@name='"+node.get('material','')+"']")
                    tex=tree.find("asset/texture[@name='"+material.get('texture','')+"']") if material is not None else None
                    expected_asset=local_path(root,scene['assets'][texture]['path'])
                    truth(label+' MJCF texture reference',tex is not None and (Path(mjcf).parent/tex.get('file')).resolve()==expected_asset)
                    shader=stage.GetPrimAtPath('/Scene/material_'+name+'/Image')
                    usd_texture=shader.GetAttribute('inputs:file').Get() if shader else None
                    truth(label+' USD texture reference',usd_texture is not None and (Path(usd).parent/usd_texture.path).resolve()==expected_asset)
                truth(label+' collision meaning',(node.get('contype')=='1')==(field=='collision'))
                truth(label+' USD collision meaning',bool(sub.GetAttribute('physics:collisionEnabled').Get())==(field=='collision'))
    cameras={c.get('name'):c for c in tree.findall('worldbody/camera')}
    truth('camera IDs',set(cameras)=={c['id'] for c in scene['cameras']})
    for c in scene['cameras']:
        name=c['id'];k=np.asarray(c['K']['value']);w,h=c['resolution'];node=cameras.get(name)
        usd_cam=UsdGeom.Camera(stage.GetPrimAtPath('/Scene/'+name))
        if node is None or not usd_cam:failures.append(name+' camera missing');continue
        equal(name+' MJCF camera pose',pose(node),render_pose(scene,c))
        equal(name+' USD camera pose',np.asarray(UsdGeom.Xformable(usd_cam).ComputeLocalToWorldTransform(Usd.TimeCode.Default())).T,render_pose(scene,c))
        equal(name+' resolution',np.fromstring(node.get('resolution'),sep=' '),[w,h])
        equal(name+' MJCF focal pixels',np.fromstring(node.get('focalpixel'),sep=' '),[k[0,0],k[1,1]])
        equal(name+' MJCF principal pixels',np.fromstring(node.get('principalpixel'),sep=' '),[w/2-k[0,2],k[1,2]-h/2])
        focal=usd_cam.GetFocalLengthAttr().Get();ha=usd_cam.GetHorizontalApertureAttr().Get();va=usd_cam.GetVerticalApertureAttr().Get()
        equal(name+' USD focal pixels',[w*focal/ha,h*focal/va],[k[0,0],k[1,1]])
        equal(name+' USD principal pixels',[w/2-usd_cam.GetHorizontalApertureOffsetAttr().Get()*w/ha,h/2+usd_cam.GetVerticalApertureOffsetAttr().Get()*h/va],[k[0,2],k[1,2]])
    return {'status':'PASS' if not failures else 'FAIL','absolute_tolerance':TOLERANCE,'relative_tolerance':TOLERANCE,
            'checks':len(checks),'failures':failures,'hierarchy':'canonical frame graph is baked to equal world transforms; frame graph retained in manifest',
            'scope':'exported structural geometry/camera parity; not Isaac runtime/photometric parity'}
