"""One identifiable shared parameter group at a time; measured q is frozen evidence."""
import copy
import numpy as np
from scipy.optimize import least_squares
from scipy.spatial.transform import Rotation
from app.core.capture import observation_scene
from app.core.scene import value
from .camera import project_point


def metrics(project,scene,rows):
    observations={i.get('id'):i for i in project.evidence['images'] if i.get('id')}
    grouped={};errors=[];behind=0
    for row in rows:
        if row.get('visible',True) is False or row.get('weight',1)<=0:continue
        image=observations[row['observation']]
        if not image.get('eligible',False):continue
        posed=observation_scene(scene,image,project.root);camera=next(c for c in posed['cameras'] if c['id']==image['camera'])
        uv,z=project_point(posed,camera,row);err=float(np.linalg.norm(uv-np.asarray(row['uv'])))
        errors.append(err);behind+=int(z<=0);grouped.setdefault(image['id'],[]).append(err)
    return {'count':len(errors),'rmse_px':float(np.sqrt(np.mean(np.square(errors)))) if errors else None,'behind_camera':behind,
            'per_observation':{k:float(np.sqrt(np.mean(np.square(v)))) for k,v in grouped.items()}}


def fit(project,scene,target):
    candidate=copy.deepcopy(scene);kind,name=target.split(':',1)
    if kind in ('camera','intrinsics'):
        node=next(c for c in candidate['cameras'] if c['id']==name);field='K' if kind=='intrinsics' else 'pose'
    elif kind=='base':node=candidate['frames'][name];field='transform'
    elif kind in ('object','dimensions'):
        node=next(o for o in candidate['objects'] if o['id']==name);field='dimensions' if kind=='dimensions' else 'pose'
    else:raise ValueError('Fit one camera/intrinsics/base/object/dimensions group')
    if node[field]['provenance'] in ('measured','calibrated'):raise ValueError('Measured/calibrated parameter locked')
    observations={i.get('id'):i for i in project.evidence['images'] if i.get('id')}
    rows=[r for r in project.evidence['landmarks'] if r.get('observation') in observations and observations[r['observation']]['eligible'] and r.get('visible',True) and r.get('weight',1)>0]
    train=[r for r in rows if observations[r['observation']]['split']=='train'];held=[r for r in rows if observations[r['observation']]['split']=='validation']
    groups={observations[r['observation']]['group_id'] for r in train};hold_groups={observations[r['observation']]['group_id'] for r in held}
    if groups & hold_groups:raise ValueError('Train/holdout group leakage')
    poses={tuple(observations[r['observation']]['q_measured']) for r in train}
    if len(poses)<2 or len(train)<8 or not held:
        return scene,{'status':'NEEDS_MORE_DATA','need':'Two distinct measured poses with >=8 train landmarks and independent held-out pose landmarks'}
    if field=='K':
        k=np.asarray(node[field]['value']);seed=np.array([k[0,0],k[1,1],k[0,2],k[1,2]]);radius=np.array([seed[0]*.2,seed[1]*.2,30,30])
        def assign(x):node[field]['value']=[[float(x[0]),0,float(x[2])],[0,float(x[1]),float(x[3])],[0,0,1]]
    elif field=='dimensions':
        seed=np.asarray(node[field]['value']);radius=seed*.2
        def assign(x):node[field]['value']=x.tolist()
    else:
        t=np.asarray(node[field]['value']);seed=np.r_[t[:3,3],Rotation.from_matrix(t[:3,:3]).as_rotvec()];radius=np.r_[[.1]*3,[.4]*3]
        def assign(x):
            t=np.eye(4);t[:3,3]=x[:3];t[:3,:3]=Rotation.from_rotvec(x[3:]).as_matrix();node[field]['value']=t.tolist()
    def residual(x):
        assign(x);result=[]
        for row in train:
            image=observations[row['observation']];posed=observation_scene(candidate,image,project.root)
            camera=next(c for c in posed['cameras'] if c['id']==image['camera'])
            uv,z=project_point(posed,camera,row);weight=np.sqrt(row.get('weight',1.))
            result.extend((uv-np.asarray(row['uv']))*weight);result.append(max(0,.001-z)*10000)
        return result
    before=metrics(project,scene,train);hold_before=metrics(project,scene,held)
    solution=least_squares(residual,seed,bounds=(seed-radius,seed+radius),loss='soft_l1',max_nfev=100)
    rank=int(np.linalg.matrix_rank(solution.jac));assign(solution.x)
    after=metrics(project,candidate,train);hold_after=metrics(project,candidate,held)
    report={'target':target,'jacobian_rank':rank,'parameter_count':len(seed),'train_before':before,'train_after':after,
            'holdout_before':hold_before,'holdout_after':hold_after,'scope':'KINEMATIC_REPLAY_ONLY','physics_status':'PHYSICS_NOT_VALIDATED'}
    if rank<len(seed):return scene,{**report,'status':'NEEDS_MORE_DATA','need':'Independent non-collinear measured landmarks and more diverse poses; parameter group is unobservable'}
    if after['rmse_px']>=before['rmse_px']-1e-6 or hold_after['rmse_px']>hold_before['rmse_px']+1e-6 or hold_after['behind_camera']:
        return scene,{**report,'status':'REJECTED','reason':'Train did not improve or independent holdout regressed'}
    node[field]['provenance']='optimized';node[field]['evidence'].append('multi-pose train-only robust landmark fit; independent holdout checked')
    return candidate,{**report,'status':'IMPROVED'}
