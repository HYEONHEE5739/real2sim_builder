import copy
import json
import subprocess
import sys
import numpy as np
import pytest
from PIL import Image
from app.core.scene import validate,local_path
from app.core.project import Project,write
from app.core.evidence import add_image,add_video,extract_videos,import_scene


def test_provenance_and_frames_are_not_optional(scene,tmp_path):
    validate(scene,complete=True)
    malformed=copy.deepcopy(scene);malformed['objects'][0]['dimensions']['provenance']='guessed_truth'
    with pytest.raises(ValueError):validate(malformed)
    malformed=copy.deepcopy(scene);malformed['frames']['world']['parent']='world'
    with pytest.raises(ValueError):validate(malformed)
    with pytest.raises(ValueError):local_path(tmp_path,'../outside')
    with pytest.raises(ValueError):local_path(tmp_path,'/etc/passwd')
    malformed=copy.deepcopy(scene);malformed['objects'][0]['pose']['value'][0][0]=2
    with pytest.raises(ValueError):validate(malformed)


def test_image_only_requests_metric_evidence_without_guessing(tmp_path):
    from app.reconstruction.pipeline import run
    project=Project.create(tmp_path,'Unknown workspace');path=tmp_path/'real.png'
    Image.fromarray(np.full((48,64,3),100,np.uint8)).save(path);before=path.read_bytes();add_image(project,path)
    state=run(project)
    assert state['status']=='NEEDS_MORE_DATA' and len(state['needs'])>=2
    assert project.scene['cameras'][0]['K']['value'] is None
    assert path.read_bytes()==before and not list((project.root/'exports').glob('*'))


def test_video_frames_and_timestamps_are_imported_automatically(tmp_path):
    import cv2
    source=tmp_path/'clip.avi';writer=cv2.VideoWriter(str(source),cv2.VideoWriter_fourcc(*'MJPG'),10.,(64,48))
    if not writer.isOpened():pytest.skip('MJPG codec unavailable')
    for i in range(10):writer.write(np.full((48,64,3),i*20,np.uint8))
    writer.release();project=Project.create(tmp_path/'projects','Video');add_video(project,source,split='validation',max_frames=4);extract_videos(project)
    images=project.evidence['images'];assert len(images)==4 and all(i['split']=='validation' for i in images)
    assert [i['timestamp'] for i in images]==[0,.3,.6,.9]
    extract_videos(project);assert len(project.evidence['images'])==4


def test_stop_then_resume_uses_saved_scene(tmp_path,scene):
    from app.reconstruction.pipeline import run
    project=Project.create(tmp_path,'Resume');project.save_scene(scene);project.control('stop')
    result=run(project);assert result['status']=='STOPPED'
    result=run(project);assert result['status']=='NEEDS_MORE_DATA'
    assert project.scene==scene
    assert not (project.root/'working/run.lock').exists()


def test_headless_cli_import_does_not_load_engines():
    code='import app.cli,sys;assert not any(n.split(".")[0] in ("mujoco","pxr","isaaclab","torch","PyQt6") for n in sys.modules)'
    result=subprocess.run([sys.executable,'-c',code],capture_output=True,text=True)
    assert result.returncode==0,result.stderr


def test_pause_checkpoint_waits_for_resume(tmp_path):
    import threading,time
    project=Project.create(tmp_path,'Pause');project.update(status='RUNNING');project.control('pause')
    worker=threading.Thread(target=project.checkpoint);worker.start()
    try:
        deadline=time.monotonic()+2
        while project.state['status']!='PAUSED' and time.monotonic()<deadline:time.sleep(.01)
        assert project.state['status']=='PAUSED' and worker.is_alive()
        project.control('resume');worker.join(timeout=2)
        assert not worker.is_alive() and project.state['status']=='RUNNING'
    finally:
        if worker.is_alive():project.control('stop');worker.join(timeout=2)


def test_workflow_edit_validation_and_export(scene,tmp_path):
    from app.core.scene import value
    from app.core.editing import apply
    from app.exporters.package import export_package,verify_package
    target=copy.deepcopy(scene['objects'][1]);target.update(id='basket',role='receptacle')
    target['dimensions']=value([.2,.15,.1],'estimated')
    target['visual']={'type':'container','wall':value(.005,'estimated')};target['collision']=copy.deepcopy(target['visual'])
    scene['objects'].append(target)
    w={'schema':'so101.scene-workflow/1','support_surface':'table','observation_cameras':['side'],
       'tasks':[{'id':'sort','pick':'block','place':'basket','instruction':'Place the block in the basket.',
                 'success':{'relation':'inside_region_and_settled','bounds_m':[[-.09,-.06,-.04],[.09,.06,.06]],'max_speed_m_s':.03}}],
       'provenance':{k:{'source':'estimated','status':'UNVALIDATED','evidence':['synthetic']} for k in ('tasks','reset','success','physics')}}
    project=Project.create(tmp_path,'Workflow package')
    authored=apply(scene,[{'op':'set_workflow','value':w}],project.root);project.save_scene(authored)
    report={'passed':False,'input_signature':project.signature(authored)}
    exported=export_package(project,report,allow_unvalidated=True)
    from app.core.project import read
    assert read(exported/'scene_manifest.yaml')['workflow']==w
    assert read(exported/'scene.yaml')['workflow']==w
    verify_package(exported)
    bad=copy.deepcopy(w);bad['tasks'][0]['pick']='missing'
    with pytest.raises(ValueError,match='pick/place'):apply(scene,[{'op':'set_workflow','value':bad}],project.root)
    bad=copy.deepcopy(w);bad['tasks'][0]['success'].pop('bounds_m')
    with pytest.raises(ValueError,match='bounds_m'):apply(scene,[{'op':'set_workflow','value':bad}],project.root)
    bad=copy.deepcopy(w);bad.pop('provenance')
    with pytest.raises(ValueError,match='provenance'):apply(scene,[{'op':'set_workflow','value':bad}],project.root)
    revised=copy.deepcopy(w);revised['tasks'][0]['instruction']='Move the block into the basket.'
    assert apply(authored,[{'op':'set_workflow','value':revised}],project.root)['workflow']==revised
    bad=copy.deepcopy(w);bad['object_physics']={'block':{'mass_kg':-1}}
    with pytest.raises(ValueError,match='physics'):apply(scene,[{'op':'set_workflow','value':bad}],project.root)
