"""Executed only by Blender --background --python. JSON in, files + JSON out."""
import json
from pathlib import Path
import runpy
import sys
import bpy
import numpy as np
from mathutils import Matrix, Vector


def material(row):
    mat=bpy.data.materials.new(row['id']+'_material');mat.use_nodes=True
    node=mat.node_tree.nodes.get('Principled BSDF')
    node.inputs['Base Color'].default_value=(*row['color'],1.)
    node.inputs['Roughness'].default_value=row['roughness'];node.inputs['Metallic'].default_value=row['metallic']
    if row.get('texture'):
        texture=mat.node_tree.nodes.new('ShaderNodeTexImage');texture.image=bpy.data.images.load(row['texture']);texture.image.pack()
        mat.node_tree.links.new(texture.outputs['Color'],node.inputs['Base Color'])
    return mat


def build(description):
    bpy.ops.object.select_all(action='SELECT');bpy.ops.object.delete(use_global=False)
    scene=bpy.context.scene;scene.render.engine='CYCLES';scene.cycles.device='CPU';scene.cycles.samples=16;scene.cycles.seed=0
    scene.render.image_settings.file_format='PNG';scene.render.image_settings.color_mode='RGB'
    scene.view_settings.view_transform='Standard';scene.view_settings.exposure=0;scene.view_settings.gamma=1
    scene.world=bpy.data.worlds.new('CanonicalWorld');scene.world.use_nodes=True
    background=scene.world.node_tree.nodes.get('Background');background.inputs['Color'].default_value=(*description['ambient'],1);background.inputs['Strength'].default_value=1
    for row in description['objects']:
        meshes=[];mat=material(row)
        for part in row['parts']:
            kind=part['type'];dims=part['dimensions']
            if kind=='mesh':
                mesh=bpy.data.meshes.new(row['id']);mesh.from_pydata(part['vertices'],[],part['faces']);mesh.update()
                obj=bpy.data.objects.new(row['id'],mesh);scene.collection.objects.link(obj)
                mesh.transform(Matrix.Diagonal((*part.get('scale',[1,1,1]),1.)))
                if part.get('uv'):
                    layer=mesh.uv_layers.new(name='UVMap')
                    for loop in mesh.loops:layer.data[loop.index].uv=part['uv'][loop.vertex_index]
            else:
                if kind=='box':bpy.ops.mesh.primitive_cube_add(size=1);scale=dims
                elif kind=='sphere':bpy.ops.mesh.primitive_uv_sphere_add(segments=32,ring_count=16,radius=.5);scale=dims
                elif kind=='cylinder':bpy.ops.mesh.primitive_cylinder_add(vertices=64,radius=.5,depth=1);scale=dims
                else:raise ValueError('Unsupported visual part '+kind)
                obj=bpy.context.object;obj.data.transform(Matrix.Diagonal((*scale,1.)))
            obj.data.transform(Matrix(part['pose']));obj.data.materials.clear();obj.data.materials.append(mat);meshes.append(obj)
        bpy.ops.object.select_all(action='DESELECT')
        for obj in meshes:obj.select_set(True)
        bpy.context.view_layer.objects.active=meshes[0];bpy.ops.object.join();obj=bpy.context.object
        obj.name=row['id'];obj['r2s_id']=row['id'];obj['r2s_role']=row['role'];obj.matrix_world=Matrix(row['pose'])
    for row in description['cameras']:
        data=bpy.data.cameras.new(row['id']);obj=bpy.data.objects.new(row['id'],data);scene.collection.objects.link(obj)
        obj.matrix_world=Matrix(row['pose']);obj['r2s_id']=row['id'];obj['r2s_resolution']=row['resolution']
        obj['r2s_pixel_aspect']=[row['intrinsics']['pixel_aspect_x'],row['intrinsics']['pixel_aspect_y']]
        data.type='PERSP';data.clip_start=description['conventions']['clip_m'][0];data.clip_end=description['conventions']['clip_m'][1]
        for key in ('sensor_fit','sensor_width','lens','shift_x','shift_y'):setattr(data,key,row['intrinsics'][key])
    for row in description.get('lights',[]):
        data=bpy.data.lights.new(row['id'],{'point':'POINT','area':'AREA','sun':'SUN'}[row['type']])
        obj=bpy.data.objects.new(row['id'],data);scene.collection.objects.link(obj);obj.matrix_world=Matrix(row['pose']['value']);obj['r2s_id']=row['id']
        data.energy=row['energy']['value'];data.color=row['color']['value']
        if data.type=='AREA':data.size=row['size']['value']
    bpy.context.view_layer.update()


def camera_setup(camera):
    scene=bpy.context.scene;scene.camera=camera
    w,h=camera['r2s_resolution'];scene.render.resolution_x=w;scene.render.resolution_y=h;scene.render.resolution_percentage=100
    scene.render.pixel_aspect_x,scene.render.pixel_aspect_y=camera['r2s_pixel_aspect']


def render(folder):
    scene=bpy.context.scene;objects=[o for o in scene.objects if o.type=='MESH' and o.get('r2s_id')]
    cameras=[o for o in scene.objects if o.type=='CAMERA' and o.get('r2s_id')]
    projections=[]
    from bpy_extras.object_utils import world_to_camera_view
    for camera in cameras:
        camera_setup(camera)
        w,h=camera['r2s_resolution']
        for obj in objects:
            ndc=world_to_camera_view(scene,camera,obj.matrix_world.translation)
            projections.append({'camera':camera['r2s_id'],'object':obj['r2s_id'],'uv':[float(ndc.x*w),float((1-ndc.y)*h)]})
        scene.render.filepath=str(folder/(camera['r2s_id']+'.png'));bpy.ops.render.render(write_still=True)
    # Emission label pass shares camera, occlusion and geometry; no inferred masks.
    old=[(o,list(o.data.materials),[p.material_index for p in o.data.polygons]) for o in objects]
    scene.view_settings.view_transform='Raw';background=scene.world.node_tree.nodes.get('Background');background.inputs['Color'].default_value=(0,0,0,1)
    for index,obj in enumerate(objects,1):
        rgb=[(index>>shift)&255 for shift in (0,8,16)]
        mat=bpy.data.materials.new('id_'+str(index));mat.use_nodes=True;nodes=mat.node_tree.nodes;nodes.clear()
        out=nodes.new('ShaderNodeOutputMaterial');emission=nodes.new('ShaderNodeEmission');emission.inputs['Color'].default_value=(*(v/255 for v in rgb),1)
        mat.node_tree.links.new(emission.outputs[0],out.inputs['Surface']);obj.data.materials.clear();obj.data.materials.append(mat)
        for polygon in obj.data.polygons:polygon.material_index=0
    for camera in cameras:
        camera_setup(camera);path=folder/(camera['r2s_id']+'_labels.png');scene.render.filepath=str(path);bpy.ops.render.render(write_still=True)
        im=bpy.data.images.load(str(path),check_existing=False);im.colorspace_settings.name='Non-Color'
        pixels=np.asarray(im.pixels[:]).reshape(im.size[1],im.size[0],4)[::-1,:,:3]
        rgb=np.rint(pixels*255).astype(np.int32);labels=rgb[:,:,0]+256*rgb[:,:,1]+65536*rgb[:,:,2]
        for index,obj in enumerate(objects,1):np.save(folder/(camera['r2s_id']+'__'+obj['r2s_id']+'.npy'),labels==index)
    for obj,mats,indices in old:
        obj.data.materials.clear()
        for mat in mats:obj.data.materials.append(mat)
        for polygon,index in zip(obj.data.polygons,indices):polygon.material_index=index
    return {'projections':projections}


def synchronize(folder):
    assets=folder/'assets';assets.mkdir(exist_ok=True);result={'objects':[],'cameras':[],'lights':[]}
    background=bpy.context.scene.world.node_tree.nodes.get('Background')
    if background.inputs['Color'].is_linked or background.inputs['Strength'].is_linked:raise ValueError('Bake environment lighting before canonical sync')
    result['ambient']=[v*background.inputs['Strength'].default_value for v in background.inputs['Color'].default_value[:3]]
    graph=bpy.context.evaluated_depsgraph_get()
    for obj in bpy.context.scene.objects:
        if not obj.get('r2s_id'):
            if obj.type in ('MESH','CAMERA','LIGHT') and not obj.hide_render:raise ValueError('Tag authored objects with r2s_id and meshes with r2s_role before sync')
            continue
        name=obj['r2s_id']
        if not name.replace('_','a').isalnum() or not name.isascii():raise ValueError('Invalid canonical object ID')
        if obj.type=='MESH':
            evaluated=obj.evaluated_get(graph);mesh=evaluated.to_mesh();mesh.calc_loop_triangles()
            try:
                translation,rotation,scale=obj.matrix_world.decompose()
                reconstructed=Matrix.LocRotScale(translation,rotation,scale)
                if not np.allclose(np.asarray(reconstructed),np.asarray(obj.matrix_world),atol=1e-6) or min(scale)<=0:raise ValueError('Bake shear/negative scale before sync')
                if len(obj.data.materials)>1:raise ValueError('One material per canonical object required; split semantic objects explicitly')
                vertices=np.array([[v.co[i]*scale[i] for i in range(3)] for v in mesh.vertices]);path=assets/(name+'.obj')
                lines=['v '+' '.join(map(str,v)) for v in vertices];uv=mesh.uv_layers.active
                if uv:lines+=['vt '+str(d.uv.x)+' '+str(d.uv.y) for d in uv.data]
                for triangle in mesh.loop_triangles:
                    tokens=[str(v+1)+'/'+str(loop+1) if uv else str(v+1) for v,loop in zip(triangle.vertices,triangle.loops)]
                    lines.append('f '+' '.join(tokens))
                path.write_text('\n'.join(lines)+'\n');mat=obj.active_material
                node=mat.node_tree.nodes.get('Principled BSDF') if mat and mat.use_nodes else None
                if node is None:raise ValueError('Sync supports Principled BSDF materials only')
                color=node.inputs['Base Color'];texture=None
                if color.is_linked:
                    source=color.links[0].from_node
                    if source.type!='TEX_IMAGE' or source.image is None:raise ValueError('Bake procedural materials to an image before sync')
                    texture=assets/(name+'_texture.png');image=source.image.copy();image.filepath_raw=str(texture);image.file_format='PNG';image.save();bpy.data.images.remove(image)
                result['objects'].append({'id':name,'role':obj.get('r2s_role','fixture'),
                    'pose':np.asarray(Matrix.LocRotScale(translation,rotation,Vector((1,1,1)))).tolist(),
                    'dimensions':np.ptp(vertices,axis=0).tolist(),'mesh':str(path),'texture':str(texture) if texture else None,
                    'color':list(color.default_value[:3]),'roughness':node.inputs['Roughness'].default_value,'metallic':node.inputs['Metallic'].default_value})
            finally:evaluated.to_mesh_clear()
        elif obj.type=='LIGHT':
            if obj.data.type not in ('POINT','AREA','SUN'):raise ValueError('Unsupported light type')
            result['lights'].append({'id':name,'type':obj.data.type.lower(),'pose':np.asarray(obj.matrix_world).tolist(),
                'color':list(obj.data.color),'energy':obj.data.energy,'size':obj.data.size if obj.data.type=='AREA' else 0.})
        elif obj.type=='CAMERA':
            data=obj.data;w,h=obj['r2s_resolution'];ax,ay=obj['r2s_pixel_aspect'];ratio=ay/ax
            if data.type!='PERSP' or data.sensor_fit!='HORIZONTAL':raise ValueError('Use canonical horizontal-fit perspective cameras')
            fx=data.lens/data.sensor_width*w;fy=fx/ratio;cx=w/2-data.shift_x*w;cy=h/2+data.shift_y*w/ratio
            result['cameras'].append({'id':name,'pose':(np.asarray(obj.matrix_world)@np.diag([1,-1,-1,1])).tolist(),
                'K':[[fx,0,cx],[0,fy,cy],[0,0,1]],'resolution':[w,h]})
    return result


def main():
    request=json.loads(Path(sys.argv[sys.argv.index('--')+1]).read_text());folder=Path(request['output']);folder.mkdir(parents=True,exist_ok=True)
    action=request['action']
    if action in ('build','render'):build(request['scene'])
    else:bpy.ops.wm.open_mainfile(filepath=request['blend'])
    result={'status':'OK','action':action}
    if action=='author':runpy.run_path(request['script'],run_name='__main__')
    if action in ('build','author'):
        bpy.ops.file.pack_all();bpy.ops.wm.save_as_mainfile(filepath=request['blend'])
    elif action in ('render','render-blend'):result.update(render(folder))
    elif action=='sync':result.update(synchronize(folder))
    (folder/'result.json').write_text(json.dumps(result,allow_nan=False,indent=2))

if __name__=='__main__':main()
