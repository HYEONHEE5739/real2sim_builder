import copy
from pathlib import Path
import numpy as np
from PIL import Image
from app.core.project import Project,write,read
from app.core.evidence import add_image,copy_input
from app.validation.render import Renderer
from app.reconstruction.pipeline import run
from app.exporters.package import verify_package,export_package


def observed_project(tmp_path,scene):
    project=Project.create(tmp_path/'projects','Measured fixture')
    evidence=project.evidence
    with Renderer(scene,project.root,project.root/'scratch','software-egl') as engine:
        for camera,split in [('side','train'),('left','validation')]:
            image=tmp_path/(camera+'.png');Image.fromarray(engine.rgb(camera)).save(image)
            row=add_image(project,image,camera,split)
            for obj in scene['objects']:
                mask=tmp_path/(camera+'_'+obj['id']+'.png');Image.fromarray(engine.mask(camera,obj['id']).astype(np.uint8)*255).save(mask)
                evidence['masks'].append({'image':row['path'],'object':obj['id'],'path':copy_input(project,mask,'metadata')})
    current=project.evidence;current['masks']=evidence['masks'];write(project.root/'input/evidence.yaml',current)
    project.save_scene(scene)
    return project


def test_known_scene_is_accepted_and_package_is_portable(tmp_path,scene):
    project=observed_project(tmp_path,scene);result=run(project)
    assert result['status']=='ACCEPTED'
    path=project.root/result['export'];manifest=verify_package(path)
    assert manifest['exports']['mujoco']['loader_validation']['loaded']
    for file in ('scene.xml','scene.usd','scene.yaml','scene_manifest.yaml','SCENE.md','validation/report.json','source/reconstruction.yaml'):assert (path/file).is_file()
    import shutil,mujoco
    moved=tmp_path/'moved_package';shutil.copytree(path,moved);shutil.rmtree(path)
    assert mujoco.MjModel.from_xml_path(str(moved/'scene.xml')).ngeom==4
    verify_package(moved)
    (moved/'SCENE.md').write_text('tampered')
    import pytest
    with pytest.raises(ValueError):verify_package(moved)


def test_autonomous_loop_retries_and_fits_train_only(tmp_path,scene):
    project=observed_project(tmp_path,scene)
    seed=copy.deepcopy(scene);seed['objects'][1]['color']['value']=[.2,.04,.025];project.save_scene(seed)
    result=run(project,max_iterations=8,thresholds={'mae':.0008,'reprojection_px':5.,'silhouette_iou':.8})
    assert result['status']=='ACCEPTED',result
    assert result['iteration']>1
    assert project.scene['objects'][0]['dimensions']==scene['objects'][0]['dimensions']
    assert project.scene['objects'][1]['color']['provenance']=='optimized'
    assert read(project.root/'working/validation/report.json')['holdout_used_for_fitting'] is False
    assert 'RETRY' in (project.root/'history.jsonl').read_text()


def test_global_similarity_cannot_accept_without_geometry_evidence(tmp_path,scene):
    project=observed_project(tmp_path,scene);evidence=project.evidence;evidence['masks']=[];write(project.root/'input/evidence.yaml',evidence)
    result=run(project);assert result['status']=='NEEDS_MORE_DATA'
    assert 'held-out object masks' in result['needs'][0]['need']
    assert not list((project.root/'exports').glob('*'))


def test_input_changes_cannot_reuse_an_accepted_report(tmp_path,scene):
    import pytest
    project=observed_project(tmp_path,scene);assert run(project)['status']=='ACCEPTED'
    report=read(project.root/'working/validation/report.json')
    changed=copy.deepcopy(project.scene);changed['objects'][1]['dimensions']['value'][0]*=2
    project.save_scene(changed)
    assert project.state['status']=='DRAFT' and project.state['export'] is None
    with pytest.raises(ValueError,match='stale'):export_package(project,report)
    # Modifying bytes behind an evidence path also invalidates the signature.
    project.save_scene(scene)
    image=project.root/project.evidence['images'][0]['path'];image.write_bytes(b'changed')
    with pytest.raises(ValueError,match='stale'):export_package(project,report)
