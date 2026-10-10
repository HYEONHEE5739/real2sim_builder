"""Canonical metric scene: column vectors, right handed world Z up, optical cameras."""
import copy
import re
from pathlib import Path
import numpy as np

SCHEMA = 'real2sim.scene/1'
SOURCES = {'measured', 'calibrated', 'derived', 'optimized', 'estimated', 'unknown'}
ROLES = {'workspace', 'support_surface', 'manipulable_object', 'receptacle', 'fixture', 'background', 'reference_robot'}


def value(data, source='unknown', evidence=None):
    if source not in SOURCES or (data is None and source != 'unknown'):
        raise ValueError('Invalid evidence provenance')
    return {'value': data, 'provenance': source, 'evidence': evidence or []}


def transform(data):
    t = np.asarray(data, dtype=float)
    if t.shape != (4, 4) or not np.isfinite(t).all() or not np.allclose(t[3], [0, 0, 0, 1]):
        raise ValueError('Expected finite 4x4 homogeneous transform')
    if not np.allclose(t[:3, :3].T @ t[:3, :3], np.eye(3), atol=1e-5) or not np.isclose(np.linalg.det(t[:3, :3]), 1):
        raise ValueError('Rotation must be right handed and orthonormal')
    return t


def empty(name):
    return {'schema': SCHEMA, 'name': name, 'units': 'm',
        'coordinates': {'handedness': 'right', 'up': '+Z', 'camera': 'x_right_y_down_z_forward', 'matrix': 'T_parent_child; column vectors'},
        'frames': {'world': {'parent': None, 'transform': value(np.eye(4).tolist(), 'derived')}},
        'objects': [], 'cameras': [], 'assets': {}, 'lights': {'ambient': value([.3, .3, .3], 'estimated')},
        'uncertainties': []}


def checked_value(node):
    if not isinstance(node, dict) or node.get('provenance') not in SOURCES or 'value' not in node:
        raise ValueError('Every reconstructed field needs explicit provenance')
    if node['value'] is None and node['provenance'] != 'unknown': raise ValueError('Null field must be unknown')
    return node['value']


def identifier(name):
    if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', name):
        raise ValueError('IDs must be ASCII identifiers')
    return name


def local_path(root, relative):
    if Path(relative).is_absolute(): raise ValueError('Assets must be package-relative')
    p = (Path(root) / relative).resolve()
    if not p.is_relative_to(Path(root).resolve()): raise ValueError('Asset path escapes package')
    return p


def validate(scene, root=None, complete=False):
    if scene.get('schema') != SCHEMA or scene.get('units') != 'm': raise ValueError('Unsupported scene schema/units')
    convention=empty('')['coordinates']
    if scene.get('coordinates')!=convention:raise ValueError('Unsupported coordinate convention; explicitly convert to metre/+Z/optical frames')
    frames = scene.get('frames', {})
    if 'world' not in frames or frames['world']['parent'] is not None: raise ValueError('Missing world root')
    for name, frame in frames.items():
        identifier(name); transform(checked_value(frame['transform']))
        chain = set(); current = name
        while current is not None:
            if current in chain or current not in frames: raise ValueError('Cyclic or missing frame parent')
            chain.add(current); current = frames[current]['parent']
    ids = set()
    for obj in scene['objects']:
        identifier(obj['id'])
        if obj['id'] in ids or obj['role'] not in ROLES or obj['frame'] not in frames: raise ValueError('Invalid object identity/frame/role')
        ids.add(obj['id'])
        pose = checked_value(obj['pose']); dims = checked_value(obj['dimensions'])
        if complete and (pose is None or dims is None): raise ValueError('Metric geometry is incomplete: ' + obj['id'])
        if pose is not None: transform(pose)
        if dims is not None and (np.asarray(dims).shape != (3,) or not np.isfinite(dims).all() or np.any(np.asarray(dims) <= 0)):
            raise ValueError('Positive finite full dimensions required')
        for field in ('visual', 'collision'):
            geometry = obj[field]
            if field == 'collision' and not obj.get('collision_enabled', True): continue
            if geometry['type'] not in ('box', 'sphere', 'cylinder', 'container', 'mesh', 'compound', 'unknown'): raise ValueError('Unsupported geometry')
            if complete and geometry['type'] == 'unknown': raise ValueError('Unknown geometry')
            if geometry['type'] == 'compound':
                from app.exporters.geometry import parts
                parts(obj, field)  # Validate every collision part, including its transform.
            if geometry.get('texture') and geometry['texture'] not in scene['assets']: raise ValueError('Unknown texture asset')
            if geometry['type'] == 'mesh':
                scale = geometry.get('scale', [1, 1, 1])
                if np.asarray(scale).shape != (3,) or not np.isfinite(scale).all() or min(scale) <= 0: raise ValueError('Invalid mesh scale')
                if geometry['asset'] not in scene['assets']: raise ValueError('Unknown mesh asset')
                if field=='collision' and root:
                    from app.exporters.geometry import mesh_data
                    vertices,faces=mesh_data(local_path(root,scene['assets'][geometry['asset']]['path']))
                    # A convex surface has every vertex on the same side of every face plane.
                    unique=np.unique(vertices,axis=0)
                    for face in faces:
                        triangle=vertices[face];normal=np.cross(triangle[1]-triangle[0],triangle[2]-triangle[0]);length=np.linalg.norm(normal)
                        if length<1e-12:continue
                        distance=(unique-triangle[0])@(normal/length)
                        if distance.min() < -1e-6 and distance.max() > 1e-6:
                            raise ValueError('Concave collision mesh: use primitive/convex compound decomposition')
            if geometry['type'] == 'container':
                wall = checked_value(geometry['wall'])
                if complete and (wall is None or dims is None):raise ValueError('Incomplete open container geometry')
                if wall is not None and (not np.isfinite(wall) or wall<=0 or (dims is not None and wall>=min(dims)/2)): raise ValueError('Invalid open container wall thickness')
        for physics in obj['physics'].values():
            number = checked_value(physics)
            if number is not None and (not np.isfinite(number).all() or np.any(np.asarray(number) < 0)): raise ValueError('Invalid physics')
        for key, field in obj.get('material', {}).items():
            if key not in ('roughness', 'metallic'): raise ValueError('Unsupported material parameter')
            v = checked_value(field)
            if v is None or not np.isfinite(v) or not 0 <= v <= 1: raise ValueError('Material value outside [0,1]')
        color = checked_value(obj['color'])
        if color is not None and (len(color) != 3 or not np.isfinite(color).all() or min(color) < 0 or max(color) > 1): raise ValueError('RGB color outside [0,1]')
    ambient = checked_value(scene['lights']['ambient'])
    if np.asarray(ambient).shape != (3,) or not np.isfinite(ambient).all() or min(ambient) < 0: raise ValueError('Invalid ambient light')
    for light in scene['lights'].get('sources', []):
        identifier(light['id']);transform(checked_value(light['pose']))
        if light['type'] not in ('point','area','sun'): raise ValueError('Unsupported light type')
        for key in ('energy','size'):
            v=checked_value(light[key])
            if v is None or not np.isfinite(v) or v<0: raise ValueError('Invalid light parameter')
        rgb=checked_value(light['color'])
        if np.asarray(rgb).shape!=(3,) or not np.isfinite(rgb).all() or min(rgb)<0: raise ValueError('Invalid light color')
    names = set()
    for camera in scene['cameras']:
        identifier(camera['id'])
        if camera['id'] in names or camera['frame'] not in frames: raise ValueError('Invalid camera identity/frame')
        names.add(camera['id'])
        pose = checked_value(camera['pose']); k = checked_value(camera['K'])
        if complete and (pose is None or k is None): raise ValueError('Camera calibration is incomplete')
        if pose is not None: transform(pose)
        distortion=checked_value(camera['distortion'])
        if distortion is None or np.asarray(distortion).ndim!=1 or len(distortion) not in (4,5,8,12,14) or not np.isfinite(distortion).all():raise ValueError('Invalid OpenCV pinhole distortion coefficients')
        if k is not None:
            k = np.asarray(k)
            if k.shape != (3,3) or not np.isfinite(k).all() or min(k[0,0],k[1,1]) <= 0 or not np.allclose(k[2], [0,0,1]) or abs(k[0,1]) > 1e-9:
                raise ValueError('Invalid zero-skew camera K')
        w,h = camera['resolution']
        if type(w) is not int or type(h) is not int or min(w,h) < 1: raise ValueError('Invalid camera resolution')
    if complete and not scene['cameras']: raise ValueError('At least one reconstructed camera required')
    for asset in scene['assets'].values():
        if root:
            from app.core.project import sha
            file = local_path(root, asset['path'])
            if not file.is_file(): raise ValueError('Asset missing')
            if asset.get('sha256') and sha(file) != asset['sha256']: raise ValueError('Source asset hash changed')
    if 'workflow' in scene: validate_workflow(scene)
    return scene


def frame_world(scene, name):
    frame = scene['frames'][name]
    t = transform(frame['transform']['value'])
    return t if frame['parent'] is None else frame_world(scene, frame['parent']) @ t


def world_pose(scene, node):
    return frame_world(scene, node['frame']) @ transform(node['pose']['value'])


def uncertainties(scene):
    result = list(scene.get('uncertainties', []))
    for obj in scene['objects']:
        for field in ('pose', 'dimensions'):
            if obj[field]['provenance'] in ('unknown', 'estimated'):
                result.append(f'{obj["id"]}.{field}: {obj[field]["provenance"]}')
        for key, field in obj['physics'].items():
            if field['provenance'] in ('unknown','estimated'): result.append(f'{obj["id"]}.physics.{key}: {field["provenance"]}')
    return list(dict.fromkeys(result))


WORKFLOW_SCHEMA = 'so101.scene-workflow/1'

def validate_workflow(scene):
    """Declarative SO-101 pick/place intent. No control, LLM or inferred physics."""
    w = scene['workflow']
    if not isinstance(w, dict) or w.get('schema') != WORKFLOW_SCHEMA:
        raise ValueError('Unsupported workflow schema')
    allowed = {'schema','support_surface','observation_cameras','real_camera_bindings',
               'tasks','reset','physics','object_physics','roles','provenance'}
    if set(w) - allowed: raise ValueError('Unknown workflow fields: ' + str(sorted(set(w)-allowed)))
    objects = {o['id']:o for o in scene['objects']}
    cameras = {c['id'] for c in scene['cameras']}
    if objects.get(w.get('support_surface'), {}).get('role') != 'support_surface':
        raise ValueError('workflow support_surface must reference a support_surface object')
    views = w.get('observation_cameras', [])
    if not views or len(set(views)) != len(views) or not set(views) <= cameras:
        raise ValueError('Unknown/duplicate workflow observation camera')
    bindings = w.get('real_camera_bindings', {})
    if not set(bindings) <= cameras or len(set(bindings.values())) != len(bindings):
        raise ValueError('Invalid workflow real camera bindings')
    for key in bindings.values(): identifier(key)
    tasks = w.get('tasks', [])
    if not tasks: raise ValueError('workflow requires explicit pick/place tasks')
    seen = set()
    for t in tasks:
        identifier(t.get('id'))
        if t['id'] in seen: raise ValueError('Duplicate workflow task ID')
        seen.add(t['id'])
        if objects.get(t.get('pick'), {}).get('role') != 'manipulable_object' or objects.get(t.get('place'), {}).get('role') != 'receptacle':
            raise ValueError('Invalid workflow task pick/place role')
        if not isinstance(t.get('instruction'),str) or not t['instruction'].strip():
            raise ValueError('workflow task instruction required')
        success=t.get('success', {})
        if set(success)-{'relation','max_speed_m_s','bounds_m'}: raise ValueError('Unknown workflow success fields')
        speed=success.get('max_speed_m_s')
        if not isinstance(speed,(int,float)) or not np.isfinite(speed) or speed<=0:
            raise ValueError('Positive workflow success speed required')
        if success.get('relation') == 'inside_region_and_settled':
            b=np.asarray(success.get('bounds_m'),float)
            if b.shape!=(2,3) or not np.isfinite(b).all() or np.any(b[0]>=b[1]):
                raise ValueError('workflow success requires target-local bounds_m [min,max]')
        elif success.get('relation') == 'contained_and_settled':
            g=objects[t['place']]['collision']
            if g.get('type')!='container' or not g.get('round'): raise ValueError('Round container success requires a round target')
        else: raise ValueError('Unsupported workflow success relation')
    reset=w.get('reset', {})
    if set(reset)-{'mode','seed','support_object','margin_m','clearance_m','separation_m','yaw_rad','xy_jitter_m'}:
        raise ValueError('Unknown workflow reset fields')
    if reset.get('mode','uniform') not in ('uniform','four_anchors') or reset.get('yaw_rad',[0.,0.]) != [0.,0.]:
        raise ValueError('Unsupported workflow reset mode/yaw')
    if 'support_object' in reset and objects.get(reset['support_object'], {}).get('role') not in ('workspace','support_surface'):
        raise ValueError('Unknown workflow reset support object')
    for k in ('margin_m','clearance_m','separation_m','xy_jitter_m'):
        if k in reset and (not np.isfinite(reset[k]) or reset[k]<0): raise ValueError('Invalid workflow reset distance')
    def physical(values):
        if set(values)-{'mass_kg','static_friction','dynamic_friction','restitution','provenance','note'}:
            raise ValueError('Unknown workflow physics fields')
        for k in ('mass_kg','static_friction','dynamic_friction','restitution'):
            if k in values and (not np.isfinite(values[k]) or values[k]<0 or (k=='mass_kg' and values[k]==0) or (k=='restitution' and values[k]>1)):
                raise ValueError('Invalid workflow physics value')
    physical(w.get('physics', {}))
    for name,values in w.get('object_physics', {}).items():
        if objects.get(name, {}).get('role') not in ('manipulable_object','receptacle'):
            raise ValueError('Unknown workflow physics object')
        physical(values)
    for name,role in w.get('roles', {}).items():
        if name not in objects or objects[name]['role'] in ('manipulable_object','receptacle','reference_robot') or role not in ('STATIC_SUPPORT','STATIC_GEOMETRY','VISUAL_ONLY'):
            raise ValueError('Invalid workflow static role override')
    # Group-level evidence is mandatory when intent is supplied. It is not geometric acceptance.
    provenance=w.get('provenance', {})
    required={'tasks','success','reset','physics'}
    if not required <= provenance.keys(): raise ValueError('workflow provenance requires tasks/success/reset/physics')
    for key,row in provenance.items():
        if not isinstance(row,dict) or row.get('source') not in SOURCES or row.get('status') not in ('UNVALIDATED','VALIDATED','NOT_APPLICABLE'):
            raise ValueError('Invalid workflow provenance/status: '+key)
        if not isinstance(row.get('evidence'),list) or not all(isinstance(e,str) for e in row['evidence']):
            raise ValueError('workflow evidence must be an explicit list')
        if row['source']=='unknown' and row['status']=='VALIDATED': raise ValueError('Unknown workflow values cannot be validated')
    return w
