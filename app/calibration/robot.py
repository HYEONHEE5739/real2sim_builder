"""URDF forward kinematics for reference geometry only; no control or actuators."""
from pathlib import Path
import xml.etree.ElementTree as ET
import numpy as np
from scipy.spatial.transform import Rotation
from app.core.scene import transform, value


def origin(node):
    t = np.eye(4)
    if node is not None:
        t[:3,3] = np.fromstring(node.get('xyz','0 0 0'), sep=' ')
        t[:3,:3] = Rotation.from_euler('xyz', np.fromstring(node.get('rpy','0 0 0'), sep=' ')).as_matrix()
    return t


def link_transforms(urdf, joints):
    if Path(urdf).suffix.lower() in ('.xml','.mjcf'):
        import mujoco
        model=mujoco.MjModel.from_xml_path(str(urdf));data=mujoco.MjData(model)
        names=[]
        for index in range(model.njnt):
            name=mujoco.mj_id2name(model,mujoco.mjtObj.mjOBJ_JOINT,index);names.append(name)
            if model.jnt_type[index] not in (mujoco.mjtJoint.mjJNT_HINGE,mujoco.mjtJoint.mjJNT_SLIDE):raise ValueError('Capture FK requires scalar named MJCF joints')
            if name not in joints or not np.isfinite(joints[name]):raise ValueError('Missing/nonfinite MJCF measured joint: '+str(name))
            data.qpos[model.jnt_qposadr[index]]=joints[name]
        if set(joints)!=set(names):raise ValueError('Measured joint names differ from model')
        mujoco.mj_forward(model,data);poses={}
        for index in range(model.nbody):
            name=mujoco.mj_id2name(model,mujoco.mjtObj.mjOBJ_BODY,index) or 'body_'+str(index)
            t=np.eye(4);t[:3,:3]=data.xmat[index].reshape(3,3);t[:3,3]=data.xpos[index];poses[name]=t
        return poses
    root = ET.parse(urdf).getroot()
    expected={j.get('name') for j in root.findall('joint') if j.get('type')!='fixed'}
    if set(joints)!=expected:raise ValueError('Measured joint names differ from model')
    edges = root.findall('joint'); children = {j.find('child').get('link') for j in edges}
    roots = {l.get('name') for l in root.findall('link')} - children
    if len(roots) != 1: raise ValueError('URDF must be a single tree')
    poses = {next(iter(roots)):np.eye(4)}
    pending = list(edges)
    while pending:
        before = len(pending)
        for joint in pending[:]:
            parent = joint.find('parent').get('link'); child = joint.find('child').get('link')
            if parent not in poses: continue
            kind = joint.get('type'); motion = np.eye(4)
            if kind != 'fixed':
                if joint.get('name') not in joints: raise ValueError('Reference joint state missing: '+joint.get('name'))
                q = float(joints[joint.get('name')])
                if not np.isfinite(q): raise ValueError('Nonfinite joint state')
                axis_node = joint.find('axis')
                axis = np.fromstring(axis_node.get('xyz','1 0 0') if axis_node is not None else '1 0 0', sep=' ')
                if np.linalg.norm(axis) == 0: raise ValueError('Zero joint axis')
                axis /= np.linalg.norm(axis)
                if kind in ('revolute','continuous'): motion[:3,:3] = Rotation.from_rotvec(axis*q).as_matrix()
                elif kind == 'prismatic': motion[:3,3] = axis*q
                else: raise ValueError('Unsupported reference joint: '+kind)
            poses[child] = poses[parent] @ origin(joint.find('origin')) @ motion
            pending.remove(joint)
        if before == len(pending): raise ValueError('Cyclic/disconnected URDF')
    return poses


def reference_geometry(urdf, joints, import_asset, frame='robot_base', recorded_links=None):
    root = ET.parse(urdf).getroot()
    poses = {k:transform(v) for k,v in recorded_links.items()} if recorded_links else link_transforms(urdf,joints)
    result = []
    for link in root.findall('link'):
        for i, visual in enumerate(link.findall('visual')):
            geometry = visual.find('geometry'); mesh = geometry.find('mesh')
            if link.get('name') not in poses: raise ValueError('Missing reference FK link')
            if mesh is not None:
                path = mesh.get('filename')
                if path.startswith('package://'): raise ValueError('Resolve package:// meshes explicitly before import')
                source = (Path(urdf).parent/path).resolve()
                scale = np.fromstring(mesh.get('scale','1 1 1'),sep=' ').tolist()
                geom = {'type':'mesh','asset':import_asset(source),'scale':scale}
                from app.exporters.geometry import mesh_data
                vertices,_ = mesh_data(source)
                dims = np.maximum(np.ptp(vertices*np.asarray(scale),axis=0),1e-8).tolist()
            else:
                box=geometry.find('box'); sphere=geometry.find('sphere'); cylinder=geometry.find('cylinder')
                if box is not None: dims=np.fromstring(box.get('size'),sep=' ').tolist(); geom={'type':'box'}
                elif sphere is not None: dims=[2*float(sphere.get('radius'))]*3; geom={'type':'sphere'}
                elif cylinder is not None: dims=[2*float(cylinder.get('radius'))]*2+[float(cylinder.get('length'))]; geom={'type':'cylinder'}
                else: raise ValueError('Unsupported URDF visual')
            color=visual.find('material/color')
            rgb=np.fromstring(color.get('rgba'),sep=' ')[:3].tolist() if color is not None else [.55,.3,.8]
            result.append({'id':'robot_'+link.get('name')+'_'+str(i),'role':'reference_robot','frame':frame,
                'pose':value((poses[link.get('name')]@origin(visual.find('origin'))).tolist(),'derived',[str(urdf)]),
                'dimensions':value(dims,'derived',[str(urdf)]),'visual':geom,'collision':{'type':'unknown'},
                'color':value(rgb,'estimated'),'physics':{'mass_kg':value(None),'friction':value(None)},
                'collision_enabled':False,'link':link.get('name'),
                'link_local_pose':origin(visual.find('origin')).tolist()})
    return result,poses


def reference_model(path,joints,import_asset,scratch):
    """MJCF/USD reference snapshots. Derive geometry, never import control/task code."""
    from app.exporters.geometry import write_stl
    path=Path(path);scratch=Path(scratch);scratch.mkdir(parents=True,exist_ok=True);objects=[]
    def append(name,vertices,faces,t,color):
        mesh=scratch/(name+'.stl');write_stl(mesh,vertices,faces);asset=import_asset(mesh)
        dimensions=np.maximum(np.ptp(vertices,axis=0),1e-8).tolist()
        objects.append({'id':name,'role':'reference_robot','frame':'robot_base','pose':value(t.tolist(),'derived',[str(path)]),
            'dimensions':value(dimensions,'derived',[str(path)]),'visual':{'type':'mesh','asset':asset},'collision':{'type':'unknown'},
            'collision_enabled':False,'color':value(color,'derived',[str(path)]),'physics':{'mass_kg':value(None),'friction':value(None)}})
    import trimesh
    poses={'root':np.eye(4)}
    if path.suffix.lower() in ('.xml','.mjcf'):
        import mujoco
        model=mujoco.MjModel.from_xml_path(str(path));data=mujoco.MjData(model)
        for j in range(model.njnt):
            name=mujoco.mj_id2name(model,mujoco.mjtObj.mjOBJ_JOINT,j)
            if model.jnt_type[j] not in (mujoco.mjtJoint.mjJNT_HINGE,mujoco.mjtJoint.mjJNT_SLIDE):raise ValueError('MJCF reference requires scalar joints or a baked static model')
            if name not in joints:raise ValueError('Reference joint state missing: '+str(name))
            data.qpos[model.jnt_qposadr[j]]=float(joints[name])
        mujoco.mj_forward(model,data)
        poses=link_transforms(path,joints)
        for i in range(model.ngeom):
            size=model.geom_size[i];kind=model.geom_type[i]
            if kind==mujoco.mjtGeom.mjGEOM_MESH:
                m=model.geom_dataid[i];v=model.mesh_vertadr[m];f=model.mesh_faceadr[m]
                vertices=model.mesh_vert[v:v+model.mesh_vertnum[m]];faces=model.mesh_face[f:f+model.mesh_facenum[m]]
            elif kind==mujoco.mjtGeom.mjGEOM_BOX:
                mesh=trimesh.creation.box(extents=2*size);vertices,faces=mesh.vertices,mesh.faces
            elif kind==mujoco.mjtGeom.mjGEOM_SPHERE:
                mesh=trimesh.creation.icosphere(subdivisions=2,radius=size[0]);vertices,faces=mesh.vertices,mesh.faces
            elif kind==mujoco.mjtGeom.mjGEOM_CYLINDER:
                mesh=trimesh.creation.cylinder(radius=size[0],height=2*size[1]);vertices,faces=mesh.vertices,mesh.faces
            elif kind==mujoco.mjtGeom.mjGEOM_CAPSULE:
                mesh=trimesh.creation.capsule(radius=size[0],height=2*size[1]);vertices,faces=mesh.vertices,mesh.faces
            else:raise ValueError('Unsupported MJCF reference visual geom: '+str(kind))
            t=np.eye(4);t[:3,3]=data.geom_xpos[i];t[:3,:3]=data.geom_xmat[i].reshape(3,3)
            append('reference_geom_'+str(i),vertices,faces,t,model.geom_rgba[i,:3].tolist())
            body=int(model.geom_bodyid[i]);objects[-1]['link']=mujoco.mj_id2name(model,mujoco.mjtObj.mjOBJ_BODY,body) or 'body_'+str(body)
    elif path.suffix.lower() in ('.usd','.usda','.usdc'):
        if joints:raise ValueError('USD references must be baked poses; use URDF/MJCF for joint FK')
        from pxr import Usd,UsdGeom
        stage=Usd.Stage.Open(str(path))
        if stage is None:raise ValueError('Cannot open USD reference')
        scale=UsdGeom.GetStageMetersPerUnit(stage);up=UsdGeom.GetStageUpAxis(stage)
        conversion=np.eye(3) if up=='Z' else Rotation.from_euler('x',90,degrees=True).as_matrix()
        for prim in stage.Traverse():
            if not prim.IsA(UsdGeom.Gprim) or prim.GetAttribute('visibility').Get()=='invisible':continue
            if prim.IsA(UsdGeom.Mesh):
                geom=UsdGeom.Mesh(prim);vertices=np.asarray(geom.GetPointsAttr().Get(),float);indices=list(geom.GetFaceVertexIndicesAttr().Get());counts=list(geom.GetFaceVertexCountsAttr().Get());faces=[];offset=0
                for count in counts:
                    polygon=indices[offset:offset+count];offset+=count
                    faces.extend([[polygon[0],polygon[j],polygon[j+1]] for j in range(1,count-1)])
                faces=np.asarray(faces,int)
            elif prim.IsA(UsdGeom.Cube):
                mesh=trimesh.creation.box(extents=[UsdGeom.Cube(prim).GetSizeAttr().Get()]*3);vertices,faces=mesh.vertices,mesh.faces
            elif prim.IsA(UsdGeom.Sphere):
                mesh=trimesh.creation.icosphere(subdivisions=2,radius=UsdGeom.Sphere(prim).GetRadiusAttr().Get());vertices,faces=mesh.vertices,mesh.faces
            elif prim.IsA(UsdGeom.Cylinder):
                geom=UsdGeom.Cylinder(prim)
                if geom.GetAxisAttr().Get()!='Z':raise ValueError('USD reference cylinder requires Z axis')
                mesh=trimesh.creation.cylinder(radius=geom.GetRadiusAttr().Get(),height=geom.GetHeightAttr().Get());vertices,faces=mesh.vertices,mesh.faces
            else:raise ValueError('Unsupported USD reference Gprim: '+prim.GetTypeName())
            t=np.asarray(UsdGeom.Xformable(prim).ComputeLocalToWorldTransform(Usd.TimeCode.Default())).T
            vertices=(np.c_[vertices,np.ones(len(vertices))]@t.T)[:,:3]*scale;vertices=vertices@conversion.T
            color=UsdGeom.Gprim(prim).GetDisplayColorAttr().Get();rgb=list(color[0]) if color else [.6,.6,.6]
            append('reference_geom_'+str(len(objects)),vertices,faces,np.eye(4),rgb)
    else:raise ValueError('Reference model must be URDF, MJCF/XML or USD')
    if not objects:raise ValueError('Reference model has no supported geometry')
    return objects,poses
