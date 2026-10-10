"""Autonomous, resumable render → compare → diagnose → refine → validate loop."""
import copy
from pathlib import Path
import time
import cv2
import numpy as np
from PIL import Image,ImageOps
from app.core.project import write
from app.core.scene import validate,local_path
from app.core.evidence import extract_videos
from app.calibration.camera import fit_cameras,fit_geometry,landmark_metrics
from app.reconstruction.analysis import analyze,missing_geometry
from app.validation.render import Renderer
from app.validation.metrics import compare,mask_metrics
from app.exporters.package import export_package


def validate_scene(project,scene,renderer,folder,thresholds):
    images=project.evidence['images'];masks=project.evidence.get('masks',[]);rows=[];rendered={}
    excluded=[]
    for index,image in enumerate(images):
        if image.get('eligible') is False:
            excluded.append({'id':image.get('id'),'reasons':image.get('exclusion_reasons')});continue
        project.checkpoint()
        camera=next(c for c in scene['cameras'] if c['id']==image['camera'])
        if camera['resolution']!=image['resolution']:raise ValueError('Camera calibration resolution differs from evidence; rescale K explicitly')
        real=np.asarray(ImageOps.exif_transpose(Image.open(local_path(project.root,image['path']))).convert('RGB'))
        from app.validation.render import for_observation
        with for_observation(project,scene,image,renderer,folder/'posed'/str(index)) as posed_renderer:
            sim=posed_renderer.rgb(image['camera'])
            rendered_masks={m['object']:posed_renderer.mask(image['camera'],m['object']) for m in masks if m['image']==image['path']}
        rendered[image['path']]=sim
        metrics=compare(real,sim,folder/'previews'/f'{index:03d}_{image["camera"]}')
        if getattr(renderer,'engine',None)=='blender':Image.fromarray(sim).save(folder/'previews'/f'{index:03d}_{image["camera"]}'/'blender.png')
        from app.validation.metrics import paired_diagnostics
        paired=paired_diagnostics(project,image,real,sim,folder/'previews'/f'{index:03d}_{image["camera"]}'/'paired')
        if paired:metrics['paired_diagnostics']=paired
        metrics['silhouettes']=[]
        for mask in masks:
            if mask['image']!=image['path']:continue
            observed=np.asarray(Image.open(local_path(project.root,mask['path'])).convert('L'))>0
            metrics['silhouettes'].append({'object':mask['object'],**mask_metrics(observed,rendered_masks[mask['object']])})
        rows.append({'image':image['path'],'camera':image['camera'],'split':image['split'],**metrics})
    train=[r for r in project.evidence['landmarks'] if r.get('split','train')=='train' and not r.get('observation')]
    held=[r for r in project.evidence['landmarks'] if r.get('split','train')=='validation' and not r.get('observation')]
    calibration={'train':landmark_metrics(scene,train),'validation':landmark_metrics(scene,held)}
    held_images=[r for r in rows if r['split']=='validation'];needs=[]
    if not held_images:needs.append({'need':'one independent validation image from a reconstructed camera',
        'reason':'The current scene has no held-out view/frame'})
    constrained={m['object'] for r in held_images for m in r['silhouettes']}
    for object_id in {r['object'] for r in held if r.get('object')}:
        points=np.array([r['point_m'] for r in held if r.get('object')==object_id])
        if len(points)>=4 and np.linalg.matrix_rank(points-points.mean(0))>=2:constrained.add(object_id)
    observation_ids={i.get('id'):i for i in images if i.get('id') and i.get('eligible') is not False}
    held_pose=[r for r in project.evidence['landmarks'] if r.get('observation') in observation_ids and observation_ids[r['observation']]['split']=='validation' and r.get('visible',True) and r.get('weight',1)>0]
    for object_id in {r['object'] for r in held_pose if r.get('object')}:
        points=np.array([r.get('point_fraction',r.get('point_m')) for r in held_pose if r.get('object')==object_id])
        if len(points)>=4 and np.linalg.matrix_rank(points-points.mean(0))>=2:constrained.add(object_id)
    critical={o['id'] for o in scene['objects'] if o['role'] in ('support_surface','manipulable_object','receptacle')}
    unconstrained=critical-constrained
    if unconstrained:needs.append({'need':'held-out object masks or measured corner landmarks for '+', '.join(sorted(unconstrained)),
        'reason':'Global image similarity does not independently verify interaction-critical geometry'})
    from app.calibration.multipose import metrics as pose_metrics
    ids={i.get('id'):i for i in images if i.get('id')}
    pose_rows=[r for r in project.evidence['landmarks'] if r.get('observation') in ids]
    multipose={split:pose_metrics(project,scene,[r for r in pose_rows if ids[r['observation']]['split']==split]) for split in ('train','validation')}
    if project.evidence.get('capture_sessions'):
        train_groups={i['group_id'] for i in ids.values() if i.get('eligible') and i['split']=='train' and i.get('group_id')}
        held_groups={i['group_id'] for i in ids.values() if i.get('eligible') and i['split']=='validation' and i.get('group_id')}
        poses={tuple(i['q_measured']) for i in ids.values() if i.get('eligible') and i['split']=='train' and i.get('q_measured')}
        if train_groups & held_groups:raise ValueError('Train/holdout group leakage')
        if len(poses)<2:needs.append({'need':'at least two distinct measured calibration poses','reason':'Multi-pose consistency is unobservable from one pose'})
        if multipose['validation']['count']==0:needs.append({'need':'independent held-out pose landmarks','reason':'Multi-pose kinematic accuracy not validated'})
        if not scene.get('robot_model',{}).get('mapping_verified'):needs.append({'need':'verified real-feedback to model joint mapping','reason':'Capture mapping remains unverified'})
    photometric=bool(held_images) and all(r['mae']<=thresholds['mae'] for r in held_images)
    geometric=all(m['iou']>=thresholds['silhouette_iou'] and m['center_error_px'] is not None and m['center_error_px']<=thresholds['reprojection_px'] for r in held_images for m in r['silhouettes'])
    if held:geometric=geometric and calibration['validation']['rmse_px']<=thresholds['reprojection_px'] and calibration['validation']['behind_camera']==0
    if multipose['validation']['count']:geometric=geometric and multipose['validation']['rmse_px']<=thresholds['reprojection_px'] and multipose['validation']['behind_camera']==0
    return {'excluded_observations':excluded,'multipose':multipose,'physics_status':'PHYSICS_NOT_VALIDATED','validation_scope':'MULTIPOSE_GEOMETRY_VALIDATED' if not needs and photometric and geometric and pose_rows else 'VISUAL_ONLY','passed':not needs and photometric and geometric,'images':rows,'landmarks':calibration,'needs':needs,
        'thresholds':thresholds,'train_mae':float(np.mean([r['mae'] for r in rows if r['split']=='train'])) if any(r['split']=='train' for r in rows) else None,
        'holdout_used_for_fitting':False,'input_signature':project.signature(scene)},rendered


def refine_visual(project,scene,rendered):
    candidate=copy.deepcopy(scene);changes=[];images={i['path']:i for i in project.evidence['images']}
    for mask in project.evidence.get('masks',[]):
        image=images.get(mask['image'])
        if image is None or image['split']!='train' or image['path'] not in rendered:continue
        selection=np.asarray(Image.open(local_path(project.root,mask['path'])).convert('L'))>0
        real=np.asarray(Image.open(project.root/image['path']).convert('RGB'))/255.
        sim=rendered[image['path']]/255.
        if selection.shape!=real.shape[:2] or not selection.any():raise ValueError('Empty/wrong-resolution fitting mask')
        linear=lambda x:np.where(x<=.04045,x/12.92,((x+.055)/1.055)**2.4)
        gain=np.clip(linear(real[selection]).mean(0)/np.maximum(linear(sim[selection]).mean(0),.01),.5,2.)
        obj=next(o for o in candidate['objects'] if o['id']==mask['object'])
        original=np.asarray(obj['color']['value']);updated=np.clip(original*gain,0,1)
        if np.max(abs(original-updated))>.002:
            obj['color']['value']=updated.tolist();obj['color']['provenance']='optimized'
            obj['color']['evidence'].append('train-only object-mask rendered response refinement')
            changes.append(obj['id'])
    return candidate,changes


def run(project,renderer='software-egl',max_iterations=8,thresholds=None):
    thresholds=thresholds or {'mae':.12,'reprojection_px':5.,'silhouette_iou':.8}
    if not 1<=max_iterations<=100:raise ValueError('max_iterations must be in [1,100]')
    if any(not np.isfinite(v) or v<0 for v in thresholds.values()):raise ValueError('Invalid acceptance thresholds')
    lock=project.root/'working/run.lock'
    try:
        handle=lock.open('x')
    except FileExistsError:
        # A lock left by a terminated process may be reclaimed only after checking its PID.
        import os
        try:pid=int(lock.read_text());os.kill(pid,0)
        except ProcessLookupError:lock.unlink();handle=lock.open('x')
        else:raise RuntimeError('Another reconstruction process owns this project')
    import os
    handle.write(str(os.getpid()));handle.close()
    try:
        project.update(status='RUNNING',needs=[],error=None)
        project.checkpoint();project.update(stage='ANALYZE',task='Extract video frames and inventory evidence')
        extract_videos(project)
        from app.calibration.preprocess import undistort_evidence
        undistort_evidence(project)
        if not project.evidence['images']:
            return project.update(status='NEEDS_MORE_DATA',decision='NEEDS_MORE_DATA',needs=[{'need':'one real workspace image or video','reason':'No visual evidence was imported'}])
        scene=analyze(project);project.save_scene(scene)
        start=project.state.get('iteration',0)
        for iteration in range(start,start+max_iterations):
            project.checkpoint();project.update(stage='CAMERA & SCALE',iteration=iteration+1,task='Fit only supported camera parameters',decision='CONTINUE')
            # Never let an uncertain object pose anchor the camera and then refit
            # that same object's pose: the joint camera/object gauge is ambiguous.
            camera_rows=[r for r in project.evidence['landmarks'] if not r.get('observation') and (not r.get('object') or next(o for o in scene['objects'] if o['id']==r['object'])['pose']['provenance'] in ('measured','calibrated','derived'))]
            candidate,fit_report=fit_cameras(scene,camera_rows)
            candidate,geometry_report=fit_geometry(candidate,[r for r in project.evidence['landmarks'] if not r.get('observation')])
            from app.calibration.depth import fit_depth_geometry
            candidate,depth_report=fit_depth_geometry(candidate,project.evidence,project.root)
            scene=candidate;project.save_scene(scene)
            project.update(metrics={'camera_fit':fit_report,'geometry_fit':geometry_report,'depth_bounds':depth_report})
            needs=missing_geometry(scene)
            if needs:return project.update(status='NEEDS_MORE_DATA',decision='NEEDS_MORE_DATA',needs=needs)
            project.update(stage='GEOMETRY',task='Check metric geometry, frame graph and collision representations')
            validate(scene,project.root,complete=True)
            project.update(stage='VISUAL',task='Render calibrated cameras; preserve geometry while fitting appearance')
            folder=project.root/'working/validation'
            with Renderer(scene,project.root,project.root/'scratch',renderer) as engine:
                project.update(stage='PHYSICS',task='Check passive scene integrity; do not infer unobservable physical parameters')
                motion_report=[]
                if project.evidence.get('motions'):
                    from app.calibration.physics import fit
                    try:
                        scene,motion_report=fit(scene,project.root,project.root/'scratch',project.evidence['motions'])
                    except ValueError as exc:
                        return project.update(status='NEEDS_MORE_DATA',decision='NEEDS_MORE_DATA',needs=[{
                            'need':'measured passive-motion evidence sufficient to separate mass, support contact and timing',
                            'reason':str(exc)}])
                    project.save_scene(scene)
                    if any(r['split']=='validation' and r['rmse_m']>.005 for r in motion_report):
                        return project.update(status='NEEDS_MORE_DATA',decision='NEEDS_MORE_DATA',needs=[{
                            'need':'independent contact geometry/timing measurements for the failed passive-motion case',
                            'reason':'Held-out dynamics error exceeds 5 mm; physics parameters must not hide geometry/timing errors'}])
                # A static/known-mass scene should compile and remain finite without any robot controller.
                data=engine.mj.MjData(engine.model)
                for _ in range(20):engine.mj.mj_step(engine.model,data)
                if not np.isfinite(data.qpos).all():raise RuntimeError('Nonfinite passive physics')
                project.update(stage='VALIDATION',task='Compare pixels, silhouettes and held-out metric landmarks')
                report,rendered=validate_scene(project,scene,engine,folder,thresholds)
                report.update(iteration=iteration+1,camera_fit=fit_report,geometry_fit=geometry_report,depth_bounds=depth_report,physics={'scope':'passive finite scene check; unknown parameters not guessed','motions':motion_report},renderer=renderer)
            write(folder/'report.json',report)
            project.update(metrics={'train_mae':report['train_mae'],'holdout_landmarks':report['landmarks']['validation']},task='Diagnose dominant mismatch')
            if report['passed']:
                project.update(stage='EXPORT',decision='CONTINUE',task='Write and load dual-engine package')
                destination=export_package(project,report)
                return project.update(status='ACCEPTED',decision='ACCEPTED',export=destination.relative_to(project.root).as_posix(),needs=[])
            if report['needs']:
                return project.update(status='NEEDS_MORE_DATA',decision='NEEDS_MORE_DATA',needs=report['needs'])
            candidate,changes=refine_visual(project,scene,rendered)
            if not changes:
                return project.update(status='NEEDS_MORE_DATA',decision='NEEDS_MORE_DATA',needs=[{
                    'need':'measured landmarks or a train object mask for the camera/object with the largest mismatch',
                    'reason':'Current evidence does not support another identifiable camera/appearance correction'}])
            # Evaluate fit candidates on train error; hold-out views are reported, never select the candidate.
            with Renderer(candidate,project.root,project.root/'scratch',renderer) as engine:
                trial,_=validate_scene(project,candidate,engine,project.root/'scratch/candidate',thresholds)
            if report['train_mae'] is None or trial['train_mae'] is None or trial['train_mae']>=report['train_mae']-1e-5:
                return project.update(status='NEEDS_MORE_DATA',decision='NEEDS_MORE_DATA',needs=[{
                    'need':'material/lighting reference for '+', '.join(changes),
                    'reason':'Train render response does not improve; color and illumination remain ambiguous'}])
            scene=candidate;project.save_scene(scene);project.update(decision='RETRY',task='Train fit improved; rerender without geometry changes')
        return project.update(status='FAILED',decision='FAILED',error='Iteration budget exhausted without validation acceptance')
    except InterruptedError:
        return project.update(status='STOPPED',decision='CONTINUE',task='Resume from working/current_scene.yaml')
    except Exception as exc:
        project.update(status='FAILED',decision='FAILED',error=type(exc).__name__+': '+str(exc))
        raise
    finally:lock.unlink(missing_ok=True)


def evaluate_project(project, engine='blender', renderer='software-egl'):
    """No fitting: final held-out evaluation, MuJoCo sanity, structural dual-engine parity."""
    from app.core.candidates import exclusive
    from app.blender.backend import BlenderRenderer
    from app.exporters import mujoco, usd
    from app.validation.parity import check
    with exclusive(project):
        scene=project.scene;validate(scene,project.root,complete=True)
        factory=BlenderRenderer if engine=='blender' else Renderer
        folder=project.root/'working/validation'
        with factory(scene,project.root,project.root/'scratch/final_render',renderer) as model:
            report,_=validate_scene(project,scene,model,folder,{'mae':.12,'reprojection_px':5.,'silhouette_iou':.8})
        with Renderer(scene,project.root,project.root/'scratch/final_physics',renderer) as physics:
            data=physics.mj.MjData(physics.model)
            for _ in range(20):physics.mj.mj_step(physics.model,data)
            finite=bool(np.isfinite(data.qpos).all() and np.isfinite(data.qvel).all())
        parity_dir=project.root/'scratch/final_parity';parity_dir.mkdir(parents=True,exist_ok=True)
        mujoco.export(scene,project.root,parity_dir/'scene.xml');usd.export(scene,project.root,parity_dir/'scene.usd')
        parity=check(scene,project.root,parity_dir/'scene.xml',parity_dir/'scene.usd')
        report.update(engine=engine,physics={'finite':finite,'scope':'20 passive steps; not identified dynamics'},cross_engine_parity=parity)
        report['passed']=bool(report['passed'] and finite and parity['status']=='PASS')
        if parity['status']!='PASS':report['needs'].append({'need':'Cross-engine structural parity PASS','reason':str(parity)})
        write(folder/'report.json',report)
        if not report['passed']:
            project.update(status='NEEDS_MORE_DATA' if report['needs'] else 'FAILED',stage='VALIDATION',
                           decision='NEEDS_MORE_DATA' if report['needs'] else 'FAILED',needs=report['needs'],metrics={'train_mae':report['train_mae']},export=None)
        else:project.update(status='DRAFT',stage='VALIDATION',decision='CONTINUE',task='Validation passed; export to accept')
        return report
