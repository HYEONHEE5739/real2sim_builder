import copy
import json
from pathlib import Path
import numpy as np
import pytest
from PIL import Image
from app.core.project import Project,read,write,sha
from app.core.candidates import Candidate,rollback
from app.core.scene import value,validate
from app.core.evidence import add_image
from app.blender.backend import capability,description,workspace,BlenderRenderer,Unavailable,synchronize
from app.exporters import mujoco,usd
from app.validation.parity import check


def setup_project(tmp_path,scene):
    p=Project.create(tmp_path,'Agent test');p.save_scene(scene)
    image=tmp_path/'image.png';Image.fromarray(np.full((120,160,3),80,np.uint8)).save(image);add_image(p,image,'side')
    return p


def test_edit_protection_and_reject(tmp_path,scene):
    p=setup_project(tmp_path,scene);before=(p.root/'working/current_scene.yaml').read_bytes();c=Candidate.create(p,'trial')
    with pytest.raises(ValueError,match='Protected'):c.edit([{'op':'update_dimensions','id':'block','value':[.1,.1,.1]}])
    c.edit([{'op':'add_object','id':'new_bin','role':'receptacle','dimensions':[.2,.2,.1]}])
    assert c.scene['objects'][-1]['dimensions']['provenance']=='estimated'
    c.reject();assert (p.root/'working/current_scene.yaml').read_bytes()==before
    with pytest.raises(ValueError,match='not open'):c.edit([])


def test_evaluate_promote_assets_and_rollback(tmp_path,scene):
    p=setup_project(tmp_path,scene);original=copy.deepcopy(p.scene);c=Candidate.create(p,'trial')
    mesh=tmp_path/'box.obj';mesh.write_text('v 0 0 0\nv .01 0 0\nv 0 .01 0\nv 0 0 .01\nf 1 3 2\nf 1 2 4\nf 1 4 3\nf 2 3 4\n')
    asset=c.asset(mesh)['asset'];c.edit([{'op':'set_visual_mesh','id':'block','asset':asset}])
    c.evaluate('mujoco');c.promote();assert p.scene!=original
    assert p.scene['assets'][asset]['path'].startswith('working/assets/visual/')
    assert sha(p.root/p.scene['assets'][asset]['path'])==sha(mesh)
    rollback(p);assert p.scene==original


def test_stale_candidate_and_report_rejected(tmp_path,scene):
    p=setup_project(tmp_path,scene);c=Candidate.create(p,'trial');c.evaluate('mujoco')
    c.edit([{'op':'set_lighting','ambient':[.4]*3}])
    with pytest.raises(ValueError,match='stale'):c.promote()
    c.evaluate('mujoco');changed=p.scene;changed['lights']['ambient']['value']=[.2]*3;p.save_scene(changed)
    with pytest.raises(ValueError,match='base is stale'):c.promote()


def test_unvalidated_export_freshness(tmp_path,scene):
    from app.exporters.package import export_package
    p=setup_project(tmp_path,scene)
    with pytest.raises(ValueError,match='stale'):export_package(p,{'passed':False},True)


def test_structural_parity_detects_tamper(tmp_path,scene):
    pytest.importorskip('pxr')
    mujoco.export(scene,tmp_path,tmp_path/'scene.xml');usd.export(scene,tmp_path,tmp_path/'scene.usd')
    assert check(scene,tmp_path,tmp_path/'scene.xml',tmp_path/'scene.usd')['status']=='PASS'
    path=tmp_path/'scene.xml';text=path.read_text();text=text.replace('size="0.03 0.03 0.03"','size="0.06 0.03 0.03"');path.write_text(text)
    report=check(scene,tmp_path,path,tmp_path/'scene.usd');assert report['status']=='FAIL' and any('dimensions' in f for f in report['failures'])


def test_compound_and_obj_uv_pipeline(tmp_path,scene):
    pytest.importorskip('pxr')
    path=tmp_path/'tetra.obj';path.write_text('v 0 0 0\nv .01 0 0\nv 0 .01 0\nv 0 0 .01\nvt 0 0\nvt 1 0\nvt 0 1\nf 1/1 3/3 2/2\nf 1/1 2/2 4/3\nf 1/1 4/3 3/2\nf 2/1 3/2 4/3\n')
    scene['assets']['mesh']={'path':'tetra.obj','sha256':sha(path)}
    scene['objects'][1]['visual']={'type':'mesh','asset':'mesh','scale':[1,1,1]}
    scene['objects'][1]['collision']={'type':'compound','parts':[{'type':'box','dimensions':[.06]*3,'pose':np.eye(4).tolist()}]}
    mujoco.export(scene,tmp_path,tmp_path/'scene.xml');usd.export(scene,tmp_path,tmp_path/'scene.usd')
    assert check(scene,tmp_path,tmp_path/'scene.xml',tmp_path/'scene.usd')['status']=='PASS'
    import mujoco as mj
    assert mj.MjModel.from_xml_path(str(tmp_path/'scene.xml')).nmesh==1


def test_missing_blender_is_explicit(monkeypatch,tmp_path,scene):
    monkeypatch.setenv('REAL2SIM_BLENDER','/nonexistent/blender')
    assert capability()['available'] is False
    with pytest.raises(Unavailable):
        with BlenderRenderer(scene,tmp_path,tmp_path/'render') as renderer:renderer.rgb('side')


def test_blender_request_calibrated_camera(scene,tmp_path):
    scene['cameras'][0]['K']['value']=[[160,0,91],[0,135,49],[0,0,1]]
    spec=description(scene,tmp_path)['cameras'][0];settings=spec['intrinsics'];w,h=spec['resolution']
    fx=settings['lens']/settings['sensor_width']*w;ratio=settings['pixel_aspect_y']
    assert np.allclose([fx,fx/ratio,w/2-settings['shift_x']*w,h/2+settings['shift_y']*w/ratio],[160,135,91,49])


def test_sync_protects_measured_pose(tmp_path,scene):
    p=setup_project(tmp_path,scene);c=Candidate.create(p,'trial');rows=[]
    for obj in scene['objects']:
        pose=np.asarray(obj['pose']['value']).copy();pose[0,3]+=.1
        path=c.root/(obj['id']+'.obj');path.write_text('v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n')
        rows.append({'id':obj['id'],'role':obj['role'],'pose':pose.tolist(),'dimensions':obj['dimensions']['value'],
                     'color':obj['color']['value'],'roughness':.6,'metallic':0.,'mesh':str(path)})
    before=c.scene
    with pytest.raises(ValueError,match='Protected'):synchronize(c,{'objects':rows,'cameras':[]})
    assert c.scene==before


@pytest.mark.skipif(not capability()['available'],reason='Blender executable unavailable; no automatic installation')
def test_blender_headless_sync_export(tmp_path,scene):
    p=setup_project(tmp_path,scene);c=Candidate.create(p,'trial')
    workspace(c,'build');assert (c.root/'candidate.blend').is_file()
    report=c.evaluate('blender');assert report['images']
    from app.calibration.camera import project_point
    result=read(c.root/'renders/blender/result.json')
    for row in result['projections']:
        camera=next(x for x in c.scene['cameras'] if x['id']==row['camera'])
        expected,_=project_point(c.scene,camera,{'object':row['object'],'point_m':[0,0,0]})
        assert np.allclose(row['uv'],expected,atol=.05)
    mask=np.load(c.root/'renders/blender/side__block.npy');assert mask.any()
    workspace(c,'sync');assert all(o['visual']['type']=='mesh' for o in c.scene['objects'])
    c.evaluate('blender');c.promote()
    from app.exporters.package import export_package,verify_package
    path=export_package(p,{'passed':False,'input_signature':p.signature()},True)
    assert verify_package(path)['status']=='UNVALIDATED'


def test_light_recipe_and_parity(tmp_path,scene):
    pytest.importorskip('pxr')
    p=setup_project(tmp_path,scene);c=Candidate.create(p,'lights')
    c.edit([{'op':'set_lighting','ambient':[.3]*3,'sources':[{'id':'key','type':'area','pose':np.eye(4).tolist(),'color':[1,1,1],'energy':100.,'size':.5}]}])
    mujoco.export(c.scene,p.root,c.root/'scene.xml');usd.export(c.scene,p.root,c.root/'scene.usd')
    assert check(c.scene,p.root,c.root/'scene.xml',c.root/'scene.usd')['status']=='PASS'


def test_promotion_exception_restores_canonical(tmp_path,scene,monkeypatch):
    p=setup_project(tmp_path,scene);c=Candidate.create(p,'rollback_failure');c.edit([{'op':'set_lighting','ambient':[.5]*3}]);c.evaluate('mujoco')
    before=p.scene
    monkeypatch.setattr(p,'update',lambda **kwargs: (_ for _ in ()).throw(RuntimeError('injected state write failure')))
    with pytest.raises(RuntimeError,match='injected'):c.promote()
    assert p.scene==before and c.info['status']=='OPEN'


def test_package_metadata_and_fresh_report(tmp_path,scene):
    pytest.importorskip('pxr')
    from app.exporters.package import export_package,verify_package
    p=setup_project(tmp_path,scene)
    package=export_package(p,{'passed':False,'input_signature':p.signature()},True)
    manifest=verify_package(package)
    assert manifest['cross_engine_parity']['status']=='PASS'
    assert manifest['objects'][0]['semantic_role']=='support_surface'
    assert manifest['objects'][0]['dynamic_intent']=='static'
    assert manifest['camera_conventions']['clip_m']==[.001,1000.]
    assert 'Integration contract' in (package/'SCENE.md').read_text()


def test_no_measured_nested_overwrite():
    from app.core.editing import preserve
    with pytest.raises(ValueError,match='Protected'):
        preserve({'material':{'roughness':value(.2,'measured')}},{'material':{}})


def test_cli_candidate_roundtrip(tmp_path,scene):
    import subprocess,sys
    p=setup_project(tmp_path,scene)
    def call(*args,code=0):
        result=subprocess.run([sys.executable,'-B','-m','app.cli',*map(str,args)],capture_output=True,text=True)
        assert result.returncode==code,result.stdout+result.stderr
        return json.loads(result.stdout)
    info=call('inspect',p.root);assert len(info['evidence']['images'])==1
    assert call('candidate',p.root,'create','cli_trial')['status']=='OPEN'
    edits=tmp_path/'edits.json';write(edits,[{'op':'set_lighting','ambient':[.4]*3}])
    call('candidate',p.root,'edit','cli_trial','--edits',edits)
    report=call('candidate',p.root,'evaluate','cli_trial','--engine','mujoco');assert report['train_mae'] is not None
    assert call('candidate',p.root,'promote','cli_trial')['status']=='PROMOTED'
    assert call('rollback',p.root)['status']=='ROLLED_BACK'


def test_unsynchronized_blend_cannot_promote(tmp_path,scene):
    p=setup_project(tmp_path,scene);c=Candidate.create(p,'unsafe_blend');c.evaluate('mujoco')
    (c.root/'candidate.blend').write_bytes(b'changed authoring scene')
    with pytest.raises(ValueError,match='synchronization'):c.promote()


def test_blender_process_environment_isolated(monkeypatch):
    from app.blender.backend import worker_environment
    for key in ('PYTHONPATH','PYTHONHOME','LD_LIBRARY_PATH','LD_PRELOAD'):
        monkeypatch.setenv(key,'host-library-path')
    monkeypatch.setenv('REAL2SIM_BLENDER','/existing/blender')
    env=worker_environment()
    assert all(k not in env for k in ('PYTHONPATH','PYTHONHOME','LD_LIBRARY_PATH','LD_PRELOAD'))
    assert env['REAL2SIM_BLENDER']=='/existing/blender'
