"""Deterministic evidence rectification; original media/calibration stay intact."""
import copy
import cv2
import numpy as np
from PIL import Image, ImageOps
from app.core.project import write, sha
from app.core.scene import local_path, value
from app.core.evidence import copy_input


def undistort_evidence(project):
    if not (project.root / 'working/current_scene.yaml').exists():
        return
    scene = project.scene
    evidence = project.evidence
    changed = False
    for camera in scene['cameras']:
        distortion = np.asarray(camera.get('original_distortion', camera['distortion'])['value'], float)
        if not np.any(distortion) or camera['K']['value'] is None:
            continue
        k = np.asarray(camera['K']['value'], float)
        resolution = tuple(camera['resolution'])
        maps = cv2.initUndistortRectifyMap(k, distortion, None, k, resolution, cv2.CV_32FC1)
        for image in evidence['images']:
            if image.get('eligible') is False or image['camera'] != camera['id'] or image.get('rectification'):
                continue
            if tuple(image['resolution']) != resolution:
                raise ValueError('Distortion calibration and image resolutions differ')
            project.checkpoint()
            old_path = image['path']
            pixels = np.asarray(ImageOps.exif_transpose(Image.open(local_path(project.root, old_path))).convert('RGB'))
            corrected = cv2.remap(pixels, *maps, cv2.INTER_LINEAR)
            scratch = project.root / 'scratch/undistorted.png'
            Image.fromarray(corrected).save(scratch)
            image['original_path'] = old_path
            image['original_sha256'] = image['sha256']
            image['path'] = copy_input(project, scratch, 'calibrated')
            image['sha256'] = sha(project.root / image['path'])
            image['rectification'] = 'calibrated OpenCV pinhole; original K retained'
            for mask in evidence['masks']:
                if mask['image'] != old_path:
                    continue
                pixels = np.asarray(Image.open(local_path(project.root, mask['path'])).convert('L'))
                if pixels.shape[::-1] != resolution:
                    raise ValueError('Rectification mask has wrong resolution')
                Image.fromarray(cv2.remap(pixels, *maps, cv2.INTER_NEAREST)).save(scratch)
                mask['original_path'] = mask['path']
                mask['path'] = copy_input(project, scratch, 'calibrated')
                mask['image'] = image['path']
        for landmark in evidence['landmarks']:
            if landmark['camera'] == camera['id'] and 'original_uv' not in landmark:
                uv = np.asarray(landmark['uv'], float).reshape(1, 1, 2)
                landmark['original_uv'] = copy.deepcopy(landmark['uv'])
                landmark['uv'] = cv2.undistortPoints(uv, k, distortion, P=k).ravel().tolist()
        if 'original_distortion' not in camera:
            camera['original_distortion'] = copy.deepcopy(camera['distortion'])
        camera['distortion'] = value([0.] * len(distortion), 'derived', ['calibrated pinhole evidence rectification'])
        changed = True
    if changed:
        write(project.root / 'input/evidence.yaml', evidence)
        project.save_scene(scene)
