"""Lazy offscreen MuJoCo rendering; software/EGL comparisons use separate workers."""
import os
import sys
from pathlib import Path
import numpy as np
from app.exporters.mujoco import export
from app.core.scene import local_path


def configure(mode):
    modes={'egl':'egl','software-egl':'egl','osmesa':'osmesa'}
    if mode not in modes:raise ValueError('Unsupported renderer')
    if 'mujoco' in sys.modules:
        if os.environ.get('MUJOCO_GL')!=modes[mode] or (os.environ.get('LIBGL_ALWAYS_SOFTWARE')=='1')!=(mode=='software-egl'):
            raise RuntimeError('Change renderer in a new worker process')
        return
    os.environ['MUJOCO_GL']=modes[mode]
    if mode=='software-egl':
        os.environ['LIBGL_ALWAYS_SOFTWARE']='1'
        mesa='/usr/share/glvnd/egl_vendor.d/50_mesa.json'
        if Path(mesa).is_file():os.environ['__EGL_VENDOR_LIBRARY_FILENAMES']=mesa
    else:
        os.environ.pop('LIBGL_ALWAYS_SOFTWARE',None);os.environ.pop('__EGL_VENDOR_LIBRARY_FILENAMES',None)


class Renderer:
    def __init__(self,scene,root,scratch,mode='software-egl'):
        self.mode=mode
        configure(mode)
        import mujoco
        self.mj=mujoco;self.scene=scene;self.renderers={}
        scratch=Path(scratch);scratch.mkdir(parents=True,exist_ok=True)
        export(scene,root,scratch/'scene.xml')
        self.model=mujoco.MjModel.from_xml_path(str(scratch/'scene.xml'));self.data=mujoco.MjData(self.model)
        mujoco.mj_forward(self.model,self.data)

    def rgb(self,camera):
        c=next(c for c in self.scene['cameras'] if c['id']==camera);w,h=c['resolution']
        if camera not in self.renderers:self.renderers[camera]=self.mj.Renderer(self.model,height=h,width=w)
        renderer=self.renderers[camera];renderer.update_scene(self.data,camera=camera)
        rgb=renderer.render().copy()
        linear=rgb.astype(float)/255.;display=np.where(linear<=.0031308,12.92*linear,1.055*linear**(1/2.4)-.055)
        return np.rint(np.clip(display,0,1)*255).astype(np.uint8)

    def mask(self,camera,obj):
        self.rgb(camera);renderer=self.renderers[camera];renderer.enable_segmentation_rendering()
        try:
            renderer.update_scene(self.data,camera=camera);seg=renderer.render()
            body=self.mj.mj_name2id(self.model,self.mj.mjtObj.mjOBJ_BODY,obj)
            if body<0:raise ValueError('Unknown silhouette object')
            result=np.zeros(seg.shape[:2],bool)
            for gid in np.where(self.model.geom_bodyid==body)[0]:result|=(seg[:,:,0]==gid)&(seg[:,:,1]==int(self.mj.mjtObj.mjOBJ_GEOM))
            return result
        finally:renderer.disable_segmentation_rendering()

    def close(self):
        for r in self.renderers.values():r.close()
        self.renderers.clear()
    def __enter__(self):return self
    def __exit__(self,*args):self.close()


from contextlib import contextmanager

@contextmanager
def for_observation(project,scene,image,default,folder):
    if not image.get('session_id'):
        yield default;return
    from app.core.capture import observation_scene
    from app.blender.backend import BlenderRenderer
    posed=observation_scene(scene,image,project.root)
    factory=BlenderRenderer if getattr(default,'engine',None)=='blender' else Renderer
    with factory(posed,project.root,folder,getattr(default,'mode','software-egl')) as model:yield model
