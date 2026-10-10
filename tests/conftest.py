import numpy as np
import pytest
from app.core.scene import empty,value


@pytest.fixture
def scene():
    scene=empty('Synthetic measured workspace')
    def obj(name,role,dimensions,xyz,color):
        t=np.eye(4);t[:3,3]=xyz
        return {'id':name,'role':role,'frame':'world','pose':value(t.tolist(),'measured'),
            'dimensions':value(dimensions,'measured'),'visual':{'type':'box'},'collision':{'type':'box'},
            'color':value(color,'measured'),'physics':{'mass_kg':value(None),'friction':value(.1,'measured')}}
    scene['objects']=[obj('table','support_surface',[1,.8,.04],[0,0,-.02],[.5,.5,.5]),
        obj('block','manipulable_object',[.06,.06,.06],[0,0,.03],[.8,.15,.1])]
    for name,eye in [('side',[.6,.4,.5]),('left',[.6,-.4,.5])]:
        forward=-np.asarray(eye);forward/=np.linalg.norm(forward);right=np.cross(forward,[0,0,1]);right/=np.linalg.norm(right);down=np.cross(forward,right)
        t=np.eye(4);t[:3,:3]=np.column_stack([right,down,forward]);t[:3,3]=eye
        scene['cameras'].append({'id':name,'frame':'world','pose':value(t.tolist(),'calibrated'),
            'K':value([[160.,0,80.],[0,160.,60.],[0,0,1]],'calibrated'),'resolution':[160,120],
            'distortion':value([0.]*5,'calibrated')})
    return scene


@pytest.fixture(scope='session',autouse=True)
def rendering_mode():
    from app.validation.render import configure
    configure('software-egl')
