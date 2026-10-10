"""Shared geometry decomposition so USD and MJCF do not diverge."""
from pathlib import Path
import re
import struct
import numpy as np
from scipy.spatial.transform import Rotation


def mesh_data(path):
    path=Path(path)
    if path.suffix.lower()=='.obj':
        vertices, faces, _ = obj_data(path)
    elif path.suffix.lower()=='.stl':
        data=path.read_bytes()
        count=struct.unpack('<I',data[80:84])[0] if len(data)>=84 else 0
        if len(data)==84+50*count:
            triangles=np.frombuffer(data, dtype=np.dtype([('normal','<f4',(3,)),('vertices','<f4',(3,3)),('attr','<u2')]), offset=84,count=count)['vertices'].astype(float)
        else:
            points=re.findall(rb'vertex\s+([-+\deE.]+)\s+([-+\deE.]+)\s+([-+\deE.]+)',data)
            triangles=np.asarray(points,dtype=float).reshape(-1,3,3)
        vertices=triangles.reshape(-1,3);faces=np.arange(len(vertices)).reshape(-1,3)
    else:
        import trimesh
        mesh=trimesh.load(path,force='mesh',process=False)
        vertices=np.asarray(mesh.vertices);faces=np.asarray(mesh.faces)
    if not len(vertices) or not np.isfinite(vertices).all(): raise ValueError('Invalid mesh vertices')
    return vertices,faces


def parts(obj, field):
    geom=obj[field];kind=geom['type'];dims=np.asarray(obj['dimensions']['value'],float)
    if field=='collision' and not obj.get('collision_enabled',True):return []
    if kind == 'compound':
        from app.core.scene import transform
        result = []
        for part in geom.get('parts', []):
            size = np.asarray(part['dimensions'], float)
            if part['type'] not in ('box','sphere','cylinder') or size.shape != (3,) or not np.isfinite(size).all() or min(size) <= 0:
                raise ValueError('Compound collision requires positive primitive dimensions')
            result.append({**part, 'pose': transform(part['pose']), 'dimensions': size})
        if not result: raise ValueError('Empty compound geometry')
        return result
    if kind in ('box','sphere','cylinder','mesh'):
        return [{**geom,'pose':np.eye(4),'dimensions':dims}]
    if kind!='container':raise ValueError('Unsupported/incomplete geometry: '+obj['id'])
    wall=float(geom['wall']['value']);x,y,z=dims
    def box(size,xyz,angle=0):
        pose=np.eye(4);pose[:3,3]=xyz;pose[:3,:3]=Rotation.from_euler('z',angle).as_matrix()
        return {'type':'box','pose':pose,'dimensions':np.asarray(size)}
    if not geom.get('round',False):
        return [box([x,y,wall],[0,0,-z/2+wall/2]),
            box([wall,y,z],[-(x-wall)/2,0,0]),box([wall,y,z],[(x-wall)/2,0,0]),
            box([x-2*wall,wall,z],[0,-(y-wall)/2,0]),box([x-2*wall,wall,z],[0,(y-wall)/2,0])]
    top=x/2;bottom=float(geom.get('bottom_diameter_m',x))/2
    result=[{'type':'cylinder','pose':np.eye(4),'dimensions':np.array([2*bottom,2*bottom,wall])}]
    result[0]['pose'][2,3]=-z/2+wall/2
    for ring in range(4):
        radius=bottom+(top-bottom)*(ring+.5)/4-wall/2
        for segment in range(32):
            angle=2*np.pi*segment/32
            result.append(box([wall,2*radius*np.tan(np.pi/32)*1.01,z/4],
                [radius*np.cos(angle),radius*np.sin(angle),-z/2+(ring+.5)*z/4],angle))
    return result


def write_stl(path,vertices,faces):
    """Canonical derived mesh snapshot, preserving metre vertices without scaling."""
    path=Path(path)
    with path.open('wb') as stream:
        stream.write(b'Real2Sim derived reference geometry'.ljust(80,b'\0'));stream.write(struct.pack('<I',len(faces)))
        for face in faces:
            triangle=np.asarray(vertices)[face]
            normal=np.cross(triangle[1]-triangle[0],triangle[2]-triangle[0]);length=np.linalg.norm(normal)
            normal=normal/length if length else np.zeros(3)
            stream.write(struct.pack('<12fH',*normal,*triangle.ravel(),0))


def obj_data(path):
    """Triangulated OBJ with expanded corners, preserving UV seams for both exporters."""
    source=[]; uv=[]; vertices=[]; texcoords=[]; faces=[]
    for line in Path(path).read_text().splitlines():
        row=line.split()
        if not row: continue
        if row[0]=='v': source.append([float(x) for x in row[1:4]])
        elif row[0]=='vt': uv.append([float(x) for x in row[1:3]])
        elif row[0]=='f':
            corners=row[1:]
            for i in range(1,len(corners)-1):
                face=[]
                for token in (corners[0],corners[i],corners[i+1]):
                    indexes=token.split('/'); vi=int(indexes[0]); face.append(len(vertices))
                    vertices.append(source[vi-1 if vi>0 else vi])
                    ti=int(indexes[1]) if len(indexes)>1 and indexes[1] else 0
                    texcoords.append(uv[ti-1 if ti>0 else ti] if ti else [0.,0.])
                faces.append(face)
    if not vertices: raise ValueError('OBJ has no faces')
    return np.asarray(vertices),np.asarray(faces),np.asarray(texcoords)
