"""Self-contained scene package, explicit uncertainty, engine maps and file hashes."""
import copy
import importlib.util
from pathlib import Path
import shutil
import uuid
from app.core.project import write,sha,read
from app.core.scene import validate,uncertainties,local_path
from . import mujoco,usd
from app.core.cameras import CONVENTIONS


def export_package(project,report,allow_unvalidated=False):
    if not report.get('passed') and not allow_unvalidated:raise ValueError('Only validated scenes can be accepted/exported')
    scene=copy.deepcopy(project.scene);validate(scene,project.root,complete=True)
    if report.get('input_signature')!=project.signature(scene):
        raise ValueError('Validation is stale or missing its input signature; rerun reconstruction before accepted export')
    destination=project.root/'exports'/project.info['id'];temporary=project.root/'exports'/('.building-'+uuid.uuid4().hex)
    temporary.mkdir()
    try:
        for key,asset in scene['assets'].items():
            source=local_path(project.root,asset['path']);kind='textures' if source.suffix.lower() in ('.png','.jpg','.jpeg') else 'meshes'
            target=Path('assets')/kind/(sha(source)+source.suffix.lower());(temporary/target).parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(source,temporary/target);asset['path']=target.as_posix()
        if scene.get('robot_model'):
            model=scene['robot_model'];source=local_path(project.root,model['path'])
            destination_model=temporary/'assets/robot_model'
            shutil.copytree(source.parent,destination_model)
            model['path']=(destination_model/source.name).relative_to(temporary).as_posix()
        write(temporary/'scene.yaml',scene)
        mj_map=mujoco.export(scene,temporary,temporary/'scene.xml');usd_map=usd.export(scene,temporary,temporary/'scene.usd')
        import mujoco as engine
        model=engine.MjModel.from_xml_path(str(temporary/'scene.xml'))
        engines={'mujoco':{'loaded':True,'ngeom':model.ngeom},'usd':{'loaded':False,'reason':'Optional pxr binding is unavailable'}}
        if importlib.util.find_spec('pxr'):
            from pxr import Usd
            stage=Usd.Stage.Open(str(temporary/'scene.usd'))
            if stage is None or not stage.GetDefaultPrim():raise ValueError('USD loader rejected exported scene')
            engines['usd']={'loaded':True,'prims':sum(1 for _ in stage.Traverse())}
        elif report.get('passed'):
            raise ImportError('Accepted dual-engine packages require the pxr USD loader. Use an existing USD Python environment or install the optional usd extra in a separate environment.')
        from app.validation.parity import check
        parity=check(scene,temporary,temporary/'scene.xml',temporary/'scene.usd')
        if parity['status']=='FAIL' or (report.get('passed') and parity['status']!='PASS'):
            raise ValueError('Cross-engine parity did not pass: '+str(parity))
        final_report={**report,'cross_engine_parity':parity,'engines':engines,'publication':'unvalidated candidate' if not report.get('passed') else 'accepted geometry/visual scope'}
        write(temporary/'validation/report.json',final_report)
        if (project.root/'working/validation/previews').exists():shutil.copytree(project.root/'working/validation/previews',temporary/'validation/previews')
        write(temporary/'source/reconstruction.yaml',{'canonical_scene':'../scene.yaml','project':project.info,
            'evidence':project.evidence,'algorithm':'canonical scene authoring with explicit agent candidates or deterministic measured-landmark fitting',
            'physics_scope':'passive scene; no task/control; unknown mass/friction remain unknown',
            'validation_scope':str(report.get('engine',report.get('renderer','unspecified')))+' rendered correspondence; structural MJCF/USD parity; no Isaac runtime validation'})
        manifest={'schema':'real2sim.package/1','name':scene['name'],'canonical':'scene.yaml',
            'status':'ACCEPTED' if report.get('passed') else 'UNVALIDATED','coordinates':scene['coordinates'],'units':'m',
            'reconstruction_state':scene.get('reconstruction_state'),
            'observations':[{k:i.get(k) for k in ('id','snapshot_id','scene_state_id','camera','split','group_id','timestamp_ns','joint_names','q_measured','sha256','eligible','runtime_baseline')} for i in project.evidence['images'] if i.get('session_id')],
            'robot_model':scene.get('robot_model'),'dataset_provenance':project.evidence.get('capture_sessions',[]),
            'validation_scope':report.get('validation_scope','VISUAL_ONLY'),'physics_status':report.get('physics_status','PHYSICS_NOT_VALIDATED'),
            'frames':scene['frames'],'objects':scene['objects'],'cameras':scene['cameras'],'assets':scene['assets'],
            'physics_defaults':{'unknown_mass':'static body; downstream project must measure before enabling dynamics',
                'unknown_friction':'engine default, unvalidated; not a reconstructed physical property'},
            'uncertainties':uncertainties(scene),'validation':final_report,'cross_engine_parity':parity,
            'scene':{'id':project.info['id'],'canonical_schema':scene['schema']},
            'refinement':{'candidate':project.state.get('candidate'),'canonical_signature':project.signature(),
                'validation_input_signature':report.get('input_signature'),'nonregression':report.get('nonregression'),
                'scope':'External agent candidates; paired runtime images are historical diagnostics'},
            'camera_conventions':CONVENTIONS,
            'engine_differences':['Frame hierarchy is baked to world transforms; canonical frames retained here.',
                'MuJoCo headlight, Blender world illumination, USD distant light differ; appearance parity is not claimed.',
                'USD mesh vertices/UV are embedded; MJCF references the same packaged OBJ/STL.'],
            'exports':{'isaac':{'file':'scene.usd','mapping':usd_map,'loader_validation':engines['usd']},
                'mujoco':{'file':'scene.xml','mapping':mj_map,'loader_validation':engines['mujoco']}},
            'files':{p.relative_to(temporary).as_posix():sha(p) for p in sorted(temporary.rglob('*')) if p.is_file()}}
        if 'workflow' in scene:
            manifest['workflow'] = copy.deepcopy(scene['workflow'])
            manifest['workflow_status'] = 'DECLARATIVE_METADATA; not an executed task validation'
        for obj in manifest['objects']:
            obj['semantic_role']=obj['role']
            obj['dynamic_intent']='dynamic' if obj['role']=='manipulable_object' and (obj['physics']['mass_kg']['value'] or 0)>0 else 'static'
        write(temporary/'scene_manifest.yaml',manifest)
        lines=['# '+scene['name'],'','Status: '+manifest['status'],
            '','Metric, right-handed world with +Z up. T_parent_child maps child column vectors into the parent frame.',
            'Camera optical frame: +X right, +Y down, +Z forward. Exporters convert to OpenGL camera axes.',
            '','Validation scope: '+manifest['validation_scope']+'; '+manifest['physics_status'],
            'Dataset session manifests and hashes: '+str(manifest['dataset_provenance']),
            'Exported robot geometry is one snapshot; robot_model and link_local_pose support offline FK, not a controller.',
            '','## Objects','']
        for obj in scene['objects']:
            lines.append('- `'+obj['id']+'`: '+obj['role']+'; dimensions '+str(obj['dimensions']['value'])+' m ('+obj['dimensions']['provenance']+'); frame `'+obj['frame']+'`.')
        lines.extend(['','### Visual and collision assets',''])
        for obj in scene['objects']:
            visual=obj['visual'];asset=scene['assets'].get(visual.get('asset'),{})
            lines.append('- `'+obj['id']+'`: visual '+visual['type']+' '+str(asset.get('path',''))+'; collision '+obj['collision']['type']+'; dynamic intent '+obj['dynamic_intent']+'.')
        lines.extend(['','## Integration contract','',
            'Canonical scene.yaml is the source of truth. Object IDs and roles are stable; poses are T_parent_child.',
            'Use collision, never the visual mesh, to build interaction geometry. Static/dynamic intent follows known mass and manipulable_object role.',
            'Workflow metadata, when present, declares downstream task/reset/success intent; it is not a controller or proof of task execution.',
            'Cross-engine structural parity: '+parity['status']+'. See validation/report.json for tolerances and failures.',
            'Blender/world, MuJoCo/headlight and USD/distant-light appearance differs; no Isaac runtime validation is claimed.'])
        if 'workflow' in scene:
            lines.extend(['','## Workflow metadata','',
                'Schema: '+scene['workflow']['schema'],
                'Task IDs: '+', '.join(t['id'] for t in scene['workflow']['tasks']),
                'Provenance: '+str(scene['workflow']['provenance']),
                'Geometry validation does not validate grasp, dynamics, task feasibility or hardware bindings.'])
        lines.extend(['','## Cameras','']+[f'- `{c["id"]}`: {c["resolution"]}, intrinsics {c["K"]["provenance"]}, pose {c["pose"]["provenance"]}.' for c in scene['cameras']])
        lines.extend(['','## Uncertainty and downstream use','',
            'Reference robots are geometry/FK snapshots. Robot integration, task logic, reset, rewards, observations, actions and learning belong to the consuming project.',
            'Receptacles have open tops with separate floor/wall collisions, never a filled convex collision hull.',
            'Physics tuning is not claimed without measured motion evidence. Unknown mass exports as static geometry.']+
            ['- '+item for item in manifest['uncertainties']]+['','## Load','',
            'MuJoCo: `mujoco.MjModel.from_xml_path("scene.xml")`. Isaac: open `scene.usd`, preserve metre units and +Z up.',
            'Read `scene_manifest.yaml` for object IDs, frame graph, engine paths, source hashes and evidence provenance.'])
        (temporary/'SCENE.md').write_text('\n'.join(lines)+'\n')
        # SCENE.md participates in integrity checks as well.
        manifest['files']['SCENE.md']=sha(temporary/'SCENE.md');write(temporary/'scene_manifest.yaml',manifest)
        previous=destination.with_name(destination.name+'.previous')
        if previous.exists():shutil.rmtree(previous)
        if destination.exists():destination.rename(previous)
        try: temporary.rename(destination)
        except Exception:
            if previous.exists() and not destination.exists(): previous.rename(destination)
            raise
        if previous.exists():shutil.rmtree(previous)
        return destination
    finally:
        if temporary.exists():shutil.rmtree(temporary)


def verify_package(path):
    path=Path(path).resolve();manifest=read(path/'scene_manifest.yaml')
    if manifest.get('schema')!='real2sim.package/1':raise ValueError('Unknown scene package')
    for relative,digest in manifest['files'].items():
        asset=local_path(path,relative)
        if not asset.is_file() or sha(asset)!=digest:raise ValueError('Package file missing/changed: '+relative)
    validate(read(local_path(path,manifest['canonical'])),path,complete=True)
    return manifest
