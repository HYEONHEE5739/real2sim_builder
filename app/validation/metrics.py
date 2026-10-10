"""Diagnostics do not confuse global image similarity with geometric correctness."""
from pathlib import Path
import numpy as np
from PIL import Image,ImageOps
import cv2


def compare(real,sim,folder):
    real=np.asarray(real,dtype=np.uint8);sim=np.asarray(sim,dtype=np.uint8)
    if real.shape!=sim.shape or real.ndim!=3 or real.shape[2]!=3:raise ValueError('Real/sim RGB resolution mismatch')
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    error=np.abs(real.astype(float)-sim.astype(float))/255.
    edge_a=cv2.Canny(real,70,160)>0;edge_b=cv2.Canny(sim,70,160)>0
    union=np.count_nonzero(edge_a|edge_b)
    metrics={'mae':float(error.mean()),'rmse':float(np.sqrt(np.mean(error**2))),
        'edge_iou':float(np.count_nonzero(edge_a&edge_b)/union) if union else 1.}
    for name,array in {'real':real,'sim':sim,'side_by_side':np.concatenate([real,sim],axis=1),
        'overlay':np.rint((real.astype(float)+sim)/2).astype(np.uint8),'difference':np.uint8(np.clip(error*255,0,255))}.items():
        Image.fromarray(array).save(folder/(name+'.png'))
    return metrics


def mask_metrics(observed,rendered):
    a=np.asarray(observed,bool);b=np.asarray(rendered,bool)
    if a.shape!=b.shape or not a.any():raise ValueError('Invalid silhouette masks')
    union=np.count_nonzero(a|b);ca=np.argwhere(a).mean(0);cb=np.argwhere(b).mean(0) if b.any() else None
    return {'iou':float(np.count_nonzero(a&b)/union),'center_error_px':float(np.linalg.norm(ca-cb)) if cb is not None else None}


def paired_diagnostics(project, observation, real, candidate, folder):
    """Three-way comparison; numerical clues require external agent interpretation."""
    baseline=observation.get('runtime_baseline')
    if not baseline:return None
    from app.core.scene import local_path
    from app.core.project import sha
    path=local_path(project.root,baseline['path'])
    if sha(path)!=baseline['sha256']:raise ValueError('Runtime baseline modified after import')
    runtime=np.asarray(Image.open(path).convert('RGB'))
    return {'real_runtime':compare(real,runtime,Path(folder)/'real_runtime'),
        'candidate_runtime':compare(candidate,runtime,Path(folder)/'candidate_runtime'),
        'workspace_context':baseline['workspace_context'],'runtime_engine':baseline['engine'],
        'meaning':'historical runtime baseline, not optimization ground truth',
        'diagnosis':'Agent must distinguish scene mismatch from adapter/render mismatch; image metrics alone do not establish cause'}
