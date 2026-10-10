"""Single intentional CLI for project creation, evidence, reconstruction and export."""
import argparse
import json
from pathlib import Path
from app.core.project import Project,read,write


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    p=sub.add_parser('import-capture');p.add_argument('project');p.add_argument('session')
    p=sub.add_parser('import-snapshots');p.add_argument('project');p.add_argument('dataset');p.add_argument('--validation',nargs='*',default=[]);p.add_argument('--scene-state')
    p=sub.add_parser('import-paired');p.add_argument('project');p.add_argument('dataset');p.add_argument('--validation',nargs='*',default=[]);p.add_argument('--scene-state')
    sub.add_parser('capabilities')
    p=sub.add_parser('inspect');p.add_argument('project')
    p=sub.add_parser('candidate');p.add_argument('project');p.add_argument('action',choices=['create','edit','asset','render','evaluate','promote','reject','blender-build','blender-author','blender-sync','fit']);p.add_argument('name');p.add_argument('--target');p.add_argument('--edits');p.add_argument('--path');p.add_argument('--kind',choices=['visual','collision','textures'],default='visual');p.add_argument('--engine',choices=['blender','mujoco'],default='blender');p.add_argument('--renderer',choices=['software-egl','egl','osmesa'],default='software-egl');p.add_argument('--validation',action='store_true')
    p=sub.add_parser('rollback');p.add_argument('project')
    p=sub.add_parser('validate');p.add_argument('project');p.add_argument('--engine',choices=['blender','mujoco'],default='blender');p.add_argument('--renderer',choices=['software-egl','egl','osmesa'],default='software-egl')
    p=sub.add_parser('new');p.add_argument('name');p.add_argument('--projects',default='projects')
    p=sub.add_parser('add');p.add_argument('project');p.add_argument('paths',nargs='+');p.add_argument('--kind',choices=['image','reference','video','measurements','calibration','scene','robot','brief'],default='image');p.add_argument('--camera',default='side');p.add_argument('--split',choices=['train','validation'],default='train');p.add_argument('--joints');p.add_argument('--base')
    p=sub.add_parser('import-reference');p.add_argument('project');p.add_argument('--workspace',required=True);p.add_argument('--capture',required=True)
    p=sub.add_parser('run');p.add_argument('project');p.add_argument('--renderer',choices=['software-egl','egl','osmesa'],default='software-egl');p.add_argument('--max-iterations',type=int,default=8);p.add_argument('--mae',type=float,default=.12);p.add_argument('--reprojection-px',type=float,default=5);p.add_argument('--silhouette-iou',type=float,default=.8)
    p=sub.add_parser('control');p.add_argument('project');p.add_argument('action',choices=['pause','resume','stop'])
    p=sub.add_parser('status');p.add_argument('project')
    p=sub.add_parser('export');p.add_argument('project');p.add_argument('--allow-unvalidated',action='store_true')
    p=sub.add_parser('verify');p.add_argument('package')
    p=sub.add_parser('ui');p.add_argument('--projects',default='projects')
    args=parser.parse_args(argv)
    if args.command=='capabilities':
        from app.blender.backend import capability
        import importlib.util
        print(json.dumps({'capture_schema':['real2sim.snapshot/1','real2sim.capture/1 (legacy)'],'per_observation_fk':['urdf','scalar_joint_mjcf'],'multipose_fit':'weighted_soft_l1_landmarks','articulated_action_replay':False,'workflow_schema':'so101.scene-workflow/1','workflow_authoring':'candidate edit --edits (set_workflow)','workflow_recipe':'SO101 pick/place only; metadata validation is not executed-task validation','blender':capability(), **{n:importlib.util.find_spec(n) is not None for n in ('mujoco','pxr')}},indent=2));return 0
    if args.command=='new':print(Project.create(args.projects,args.name).root);return
    if args.command=='verify':
        from app.exporters.package import verify_package
        print(json.dumps(verify_package(args.package),indent=2));return
    if args.command=='ui':
        from app.ui.window import launch
        launch(Path(args.projects));return
    project=Project(args.project)
    if args.command=='import-capture':
        from app.core.capture import import_session
        from app.core.candidates import exclusive
        with exclusive(project):
            if read(Path(args.session)/'capture_manifest.yaml').get('schema')=='real2sim.snapshot/1':
                from app.core.capture import import_snapshots
                result=import_snapshots(project,args.session)
            else:result=import_session(project,args.session)
        print(json.dumps(result,indent=2));return 0
    if args.command in ('import-snapshots','import-paired'):
        from app.core.capture import import_snapshots, import_paired
        from app.core.candidates import exclusive
        with exclusive(project):result=(import_paired if args.command=='import-paired' else import_snapshots)(project,args.dataset,args.validation,args.scene_state)
        print(json.dumps(result,indent=2));return 0
    if args.command=='inspect':
        print(json.dumps({'project':project.info,'state':project.state,'evidence':project.evidence,
            'scene':project.scene if (project.root/'working/current_scene.yaml').exists() else None,
            'candidates':sorted(p.parent.name for p in (project.root/'scratch/agent').glob('*/candidate.json'))},indent=2));return 0
    if args.command=='rollback':
        from app.core.candidates import rollback
        print(json.dumps(rollback(project)));return 0
    if args.command=='validate':
        from app.reconstruction.pipeline import evaluate_project
        result=evaluate_project(project,args.engine,args.renderer);print(json.dumps(result,indent=2));return 0 if result['passed'] else 2
    if args.command=='candidate':
        from app.core.candidates import Candidate
        from app.blender.backend import workspace,Unavailable
        try:
            c=Candidate.create(project,args.name) if args.action=='create' else Candidate(project,args.name)
            if args.action=='create':result=c.info
            elif args.action=='edit':result=c.edit(read(args.edits))
            elif args.action=='fit':result=c.fit(args.target)
            elif args.action=='asset':result=c.asset(args.path,args.kind)
            elif args.action in ('render','evaluate'):result=c.evaluate(args.engine,args.renderer,args.validation,args.action=='render')
            elif args.action=='promote':result=c.promote()
            elif args.action=='reject':result=c.reject()
            else:result=workspace(c,{'blender-build':'build','blender-author':'author','blender-sync':'sync'}[args.action],args.path)
            print(json.dumps(result,indent=2));return 0
        except Unavailable as exc:
            print(json.dumps({'status':'UNAVAILABLE','engine':'blender','reason':str(exc)}));return 3
    if args.command in ('add','import-reference') and (project.root/'working/run.lock').exists():
        raise RuntimeError('Stop/resume the reconstruction worker before changing this project input')
    if args.command=='add':
        from app.core import evidence
        for path in args.paths:
            if args.kind=='brief':evidence.add_brief(project,path)
            elif args.kind in ('image','reference'):evidence.add_image(project,path,args.camera,args.split,context_only=args.kind=='reference')
            elif args.kind=='video':evidence.add_video(project,path,args.camera,args.split)
            elif args.kind=='scene':evidence.import_scene(project,path)
            elif args.kind in ('calibration','measurements'):evidence.import_metadata(project,path,args.kind)
            elif args.kind=='robot':evidence.import_robot(project,path,read(args.joints) if args.joints else {},read(args.base) if args.base else None)
    elif args.command=='import-reference':
        from app.core.evidence import import_reference
        import_reference(project,args.workspace,args.capture)
    elif args.command=='control':project.control(args.action)
    elif args.command=='status':print(json.dumps(project.state,indent=2))
    elif args.command=='run':
        from app.reconstruction.pipeline import run
        state=run(project,args.renderer,args.max_iterations,{'mae':args.mae,'reprojection_px':args.reprojection_px,'silhouette_iou':args.silhouette_iou})
        print(json.dumps(state,indent=2));return 1 if state['status']=='FAILED' else 0
    elif args.command=='export':
        from app.exporters.package import export_package
        from app.core.candidates import exclusive
        with exclusive(project):
            report=read(project.root/'working/validation/report.json')
            path=export_package(project,report,args.allow_unvalidated)
            if report.get('passed'):project.update(status='ACCEPTED',decision='ACCEPTED',stage='EXPORT',export=path.relative_to(project.root).as_posix())
            print(path)
    return 0


if __name__=='__main__':
    try: raise SystemExit(main())
    except Exception as exc:
        from app.blender.backend import Unavailable
        print(json.dumps({'status':'UNAVAILABLE' if isinstance(exc,Unavailable) else 'FAILED','error':type(exc).__name__,'reason':str(exc)}))
        raise SystemExit(3 if isinstance(exc,Unavailable) else 1)
