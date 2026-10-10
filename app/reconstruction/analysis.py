"""Deterministic visual inventory and minimal, specific missing-evidence requests."""
from pathlib import Path
import cv2
import numpy as np
from PIL import Image,ImageOps
from app.core.scene import empty,value
from app.core.project import write


def analyze(project):
    scene=project.scene if (project.root/'working/current_scene.yaml').exists() else empty(project.info['name'])
    rows=[]
    for image in project.evidence['images']:
        project.checkpoint()
        rgb=np.asarray(ImageOps.exif_transpose(Image.open(project.root/image['path'])).convert('RGB'))
        hsv=cv2.cvtColor(rgb,cv2.COLOR_RGB2HSV);foreground=((hsv[:,:,1]>65)&(hsv[:,:,2]>35)).astype(np.uint8)
        count,_,stats,centers=cv2.connectedComponentsWithStats(foreground)
        components=[{'bounds_xywh':s[:4].tolist(),'center_uv':centers[i].tolist(),'area_px':int(s[4]),
            'role':'unknown','depth_m':None,'dimensions_m':None} for i,s in enumerate(stats) if i and s[4]>max(30,rgb.shape[0]*rgb.shape[1]*.0003)]
        rows.append({'image':image['path'],'camera':image['camera'],'resolution':image['resolution'],
            'colored_regions':components,'metric_scale':'unknown_without_supporting_evidence'})
        if image.get('role')!='reference_context' and not any(c['id']==image['camera'] for c in scene['cameras']):
            scene['cameras'].append({'id':image['camera'],'frame':'world','pose':value(None),'K':value(None),
                'resolution':image['resolution'],'distortion':value([0.]*5,'estimated')})
    write(project.root/'working/analysis.json',{'images':rows,'videos':project.evidence['videos'],
        'objects':[{'id':o['id'],'role':o['role']} for o in scene['objects']],
        'note':'Image components are an inventory, not semantic identities or measured 3D geometry'})
    return scene


def missing_geometry(scene):
    needs=[]
    if not scene['objects']:needs.append({'need':'metric dimensions and pose of one support surface, with its visible corners identified',
        'reason':'Images alone do not determine metric scale, depth or hidden object geometry'})
    for camera in scene['cameras']:
        if camera['K']['value'] is None:needs.append({'need':f'{camera["id"]}: camera intrinsics at the input resolution',
            'reason':'Pixel size cannot be separated from focal length and scene scale'})
        if camera['pose']['value'] is None:needs.append({'need':f'{camera["id"]}: at least four non-collinear 3D/2D correspondences',
            'reason':'Camera extrinsics are not observable from the current evidence'})
    for obj in scene['objects']:
        for field in ('visual','collision'):
            if field=='collision' and not obj.get('collision_enabled',True):continue
            geometry=obj[field]
            if geometry['type']=='unknown':needs.append({'need':f'{obj["id"]}: supported {field} primitive or measured mesh','reason':'The shape cannot be inferred from the available metric evidence'})
            if geometry['type']=='container' and geometry['wall']['value'] is None:needs.append({'need':f'{obj["id"]}: measured wall thickness','reason':'Open receptacle collision requires an identifiable floor/wall thickness'})
        for field in ('dimensions','pose'):
            if obj[field]['value'] is None:needs.append({'need':f'{obj["id"]}: {field} in metres/workspace frame','reason':'Interaction-critical geometry is unresolved'})
    return needs
