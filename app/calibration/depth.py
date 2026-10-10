"""Metric depth/cloud bounds, using explicit segmentation and coverage evidence."""
import copy
import numpy as np
from PIL import Image
from app.core.scene import frame_world, world_pose, local_path, value


def array(path):
    if path.suffix.lower() == '.npy':
        return np.load(path, allow_pickle=False)
    if path.suffix.lower() == '.npz':
        with np.load(path, allow_pickle=False) as stored:
            if len(stored.files) != 1:
                raise ValueError('Cloud/depth NPZ must contain one named array')
            return stored[stored.files[0]]
    return np.loadtxt(path)


def fit_depth_geometry(scene, evidence, root):
    """Partial observations yield bounds only; full extents need explicit coverage."""
    candidate = copy.deepcopy(scene)
    reports = []
    observations = [('cloud', r) for r in evidence.get('point_clouds', [])]
    observations += [('depth', r) for r in evidence.get('depths', [])]
    for kind, row in observations:
        if row.get('split', 'train') != 'train':
            continue
        if not row.get('object'):
            raise ValueError('Depth/cloud bounds need a segmented object ID')
        obj = next(o for o in candidate['objects'] if o['id'] == row['object'])
        pixels = array(local_path(root, row['path'])).astype(float)
        if pixels.size > 6_000_000:
            raise ValueError('Downsample depth/cloud observations to at most two million points/pixels')
        if kind == 'cloud':
            if pixels.ndim != 2 or pixels.shape[1] != 3:
                raise ValueError('Point cloud must be N x 3 XYZ in metres')
            points = pixels[np.isfinite(pixels).all(axis=1)]
            reference = frame_world(candidate, row.get('frame', 'world'))
        else:
            camera = next(c for c in candidate['cameras'] if c['id'] == row['camera'])
            if camera['K']['value'] is None or camera['pose']['value'] is None:
                reports.append({'object':obj['id'],'decision':'NEEDS_MORE_DATA','need':'calibrated camera intrinsics/pose for metric depth'})
                continue
            if pixels.shape != tuple(camera['resolution'][::-1]):
                raise ValueError('Depth and camera resolutions differ')
            if np.any(camera.get('original_distortion', camera['distortion'])['value']):
                raise ValueError('Rectify depth with its calibrated RGB stream before import')
            if not row.get('mask'):
                raise ValueError('Depth geometry requires an explicit segmented object mask')
            selection = np.asarray(Image.open(local_path(root, row['mask'])).convert('L')) > 0
            if selection.shape != pixels.shape:
                raise ValueError('Depth mask resolution differs')
            selection &= np.isfinite(pixels) & (pixels > 0)
            y, x = np.nonzero(selection)
            depth = pixels[y, x]
            k = np.asarray(camera['K']['value'], float)
            points = np.column_stack([(x-k[0, 2])*depth/k[0, 0], (y-k[1, 2])*depth/k[1, 1], depth])
            reference = world_pose(candidate, camera)
        if len(points) < 4:
            raise ValueError('At least four finite segmented metric points are needed')
        world_points = (np.c_[points, np.ones(len(points))] @ reference.T)[:, :3]
        if obj['pose']['value'] is None:
            reports.append({'object': obj['id'], 'decision': 'NEEDS_MORE_DATA', 'need': 'object orientation/pose to interpret point bounds'})
            continue
        local = (np.c_[world_points, np.ones(len(points))] @ np.linalg.inv(world_pose(candidate, obj)).T)[:, :3]
        lo, hi = local.min(0), local.max(0)
        report = {'object': obj['id'], 'points': len(points), 'observed_extent_m': (hi-lo).tolist(), 'complete_coverage': bool(row.get('full_bounds', False))}
        # The caller must declare opposing-face coverage; a single visible depth
        # surface is not enough to determine the hidden object's thickness.
        if row.get('full_bounds', False) and obj['visual']['type'] == 'box':
            extent = hi-lo
            if min(extent) <= 0:
                raise ValueError('Full box bounds must have volume')
            if obj['dimensions']['provenance'] in ('unknown', 'estimated'):
                obj['dimensions'] = value(extent.tolist(), 'derived', [row['path'], 'declared opposing-face coverage'])
                pose = np.asarray(obj['pose']['value'], float)
                pose[:3, 3] += pose[:3, :3] @ ((hi+lo)/2)
                obj['pose'] = value(pose.tolist(), 'derived', [row['path'], 'calibrated point bounds'])
                report['applied'] = True
        reports.append(report)
    return candidate, reports
