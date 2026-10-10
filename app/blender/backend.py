"""JSON bridge to an existing Blender executable, never installs or imports bpy here."""
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import numpy as np
from app.core.project import write, read, sha
from app.core.scene import validate, world_pose, frame_world, local_path, value
from app.core.cameras import blender_intrinsics, render_pose, CONVENTIONS
from app.core.editing import preserve
from app.exporters.geometry import parts, mesh_data, obj_data


class Unavailable(RuntimeError): pass


def worker_environment():
    """Blender ships its own Python/USD/MaterialX; isolate host binding paths."""
    environment = os.environ.copy()
    for key in ('PYTHONPATH', 'PYTHONHOME', 'LD_LIBRARY_PATH', 'LD_PRELOAD'):
        environment.pop(key, None)
    return environment


def capability():
    requested=os.environ.get('REAL2SIM_BLENDER','blender')
    executable=shutil.which(requested)
    if not executable: return {'available':False,'reason':'Blender executable not found; set REAL2SIM_BLENDER to an existing executable','requested':requested}
    try:
        result=subprocess.run([executable,'--version'],capture_output=True,text=True,timeout=15,env=worker_environment())
        if result.returncode: raise RuntimeError(result.stderr)
        return {'available':True,'executable':executable,'version':result.stdout.splitlines()[0]}
    except (OSError,subprocess.SubprocessError,RuntimeError) as exc:
        return {'available':False,'reason':str(exc),'requested':requested}


def invoke(request, folder):
    available=capability()
    if not available['available']: raise Unavailable(available['reason'])
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    write(folder/'request.json',request)
    command=[available['executable'],'--background','-noaudio','--factory-startup','--python-exit-code','1',
             '--python',str(Path(__file__).with_name('worker.py')),'--',str(folder/'request.json')]
    with (folder/'blender.log').open('w') as stream:
        subprocess.run(command,stdout=stream,stderr=subprocess.STDOUT,check=True,timeout=600,env=worker_environment())
    return read(folder/'result.json')


def description(scene, root):
    validate(scene,root);objects=[]
    for obj in scene['objects']:
        pieces=[]
        for part in parts(obj,'visual'):
            row={k:(v.tolist() if isinstance(v,np.ndarray) else v) for k,v in part.items()}
            if part['type']=='mesh':
                path=local_path(root,scene['assets'][part['asset']]['path'])
                vertices,faces=mesh_data(path)
                row.update(vertices=vertices.tolist(),faces=faces.tolist())
                if path.suffix.lower()=='.obj': row['uv']=obj_data(path)[2].tolist()
            pieces.append(row)
        texture=obj['visual'].get('texture')
        objects.append({'id':obj['id'],'role':obj['role'],'pose':world_pose(scene,obj).tolist(),'parts':pieces,
                        'color':obj['color']['value'] or [.5]*3,
                        'roughness':obj.get('material',{}).get('roughness',{}).get('value',.6),
                        'metallic':obj.get('material',{}).get('metallic',{}).get('value',0.),
                        'texture':str(local_path(root,scene['assets'][texture]['path'])) if texture else None})
    cameras=[]
    for c in scene['cameras']:
        if any(c['distortion']['value']): raise ValueError('Undistort evidence before Blender rendering')
        cameras.append({'id':c['id'],'pose':render_pose(scene,c).tolist(),'resolution':c['resolution'],
                        'intrinsics':blender_intrinsics(c)})
    return {'objects':objects,'cameras':cameras,'ambient':scene['lights']['ambient']['value'],'lights':scene['lights'].get('sources',[]),'conventions':CONVENTIONS}


class BlenderRenderer:
    engine = 'blender'
    def __init__(self,scene,root,scratch,mode=None):
        self.scene=scene;self.root=Path(root);self.folder=Path(scratch).resolve();self.done=False;self.blend=None
    def prepare(self):
        if not self.done:
            request={'action':'render','scene':description(self.scene,self.root),'output':str(self.folder)}
            if self.blend: request.update(action='render-blend',blend=str(self.blend))
            invoke(request,self.folder)
            self.done=True
    def rgb(self,camera):
        from PIL import Image
        self.prepare();return np.asarray(Image.open(self.folder/(camera+'.png')).convert('RGB'))
    def mask(self,camera,obj):
        self.prepare();return np.load(self.folder/(camera+'__'+obj+'.npy'),allow_pickle=False)
    def close(self): pass
    def __enter__(self): return self
    def __exit__(self,*args): self.close()


def workspace(candidate, action='build', script=None):
    from app.core.candidates import exclusive
    with exclusive(candidate.project):
        candidate.require_open(); folder=candidate.root/'blender';blend=candidate.root/'candidate.blend'
        request={'action':action,'output':str(folder),'blend':str(blend)}
        if action=='build':
            request['scene']=description(candidate.scene,candidate.project.root)
        else:
            record=read(folder/'canonical_signature.json')
            if record!=candidate.project.signature(candidate.scene): raise ValueError('Canonical changed since Blender build; rebuild workspace')
            if not blend.is_file(): raise ValueError('Build the Blender workspace first')
        if action=='author':
            if script is None or not Path(script).is_file(): raise ValueError('Author requires a bpy script path')
            request['script']=str(Path(script).resolve())
        result=invoke(request,folder)
        if action=='build': write(folder/'canonical_signature.json',candidate.project.signature(candidate.scene))
        if action=='sync':
            synchronize(candidate,result)
            write(folder/'canonical_signature.json',candidate.project.signature(candidate.scene))
            write(folder/'sync.json',{'blend_sha256':sha(blend),'input_signature':candidate.project.signature(candidate.scene)})
        return result


def synchronize(candidate, result):
    """Explicit visual sync; preserve collision and protected measured/calibrated values."""
    scene=copy.deepcopy(candidate.scene);p=candidate.project
    original={o['id']:o for o in scene['objects']}
    if set(original)-{o['id'] for o in result['objects']}: raise ValueError('Remove canonical objects explicitly through edit, not implicit Blender deletion')
    def import_asset(path,kind):
        path=Path(path).resolve()
        if not path.is_relative_to(candidate.root): raise ValueError('Blender asset escapes candidate workspace')
        digest=sha(path);key='asset_'+digest[:16]
        scene['assets'][key]={'path':path.relative_to(p.root).as_posix(),'sha256':digest,'source':'blender_reconstruction','category':kind}
        return key
    def update(node,key,data):
        old=node.get(key)
        if old is not None and old.get('value') is not None and np.allclose(old['value'],data,atol=1e-6,rtol=1e-6): return
        node[key]=value(data,'estimated',['explicit Blender visual reconstruction synchronization'])
    for row in result['objects']:
        obj=next((o for o in scene['objects'] if o['id']==row['id']),None)
        if obj is None:
            obj={'id':row['id'],'role':row['role'],'frame':'world','pose':value(None),'dimensions':value(None),
                 'color':value(None),'visual':{'type':'unknown'},'collision':{'type':'unknown'},
                 'physics':{'mass_kg':value(None),'friction':value(None)}}
            scene['objects'].append(obj)
        old=copy.deepcopy(obj)
        update(obj,'pose',(np.linalg.inv(frame_world(scene,obj['frame']))@np.asarray(row['pose'])).tolist())
        update(obj,'dimensions',row['dimensions']);update(obj,'color',row['color'])
        obj['role']=row['role'];obj['visual']={'type':'mesh','asset':import_asset(row['mesh'],'visual'),
                                           'scale':[1,1,1],'source':'blender_reconstruction','provenance':'estimated'}
        if row.get('texture'):obj['visual']['texture']=import_asset(row['texture'],'textures')
        material=obj.setdefault('material',{})
        for key in ('roughness','metallic'):update(material,key,row[key])
        preserve(old,obj,obj['id'])
    for row in result['cameras']:
        c=next((c for c in scene['cameras'] if c['id']==row['id']),None)
        if c is None:
            c={'id':row['id'],'frame':'world','pose':value(None),'K':value(None),'distortion':value([0.]*5,'estimated'),'resolution':row['resolution']}
            scene['cameras'].append(c)
        old=copy.deepcopy(c)
        update(c,'pose',(np.linalg.inv(frame_world(scene,c['frame']))@np.asarray(row['pose'])).tolist())
        update(c,'K',row['K']);c['resolution']=row['resolution'];preserve(old,c,c['id'])
    if 'ambient' in result:
        old=copy.deepcopy(scene['lights']);update(scene['lights'],'ambient',result['ambient'])
        scene['lights']['sources']=[]
        for row in result.get('lights',[]):
            node=next((copy.deepcopy(x) for x in old.get('sources',[]) if x['id']==row['id']),{'id':row['id'],'type':row['type']})
            before=copy.deepcopy(node)
            for key in ('pose','energy','color','size'):update(node,key,row[key])
            preserve(before,node,'light.'+row['id']);scene['lights']['sources'].append(node)
        preserve(old,scene['lights'],'lights')
    candidate.save(scene)
