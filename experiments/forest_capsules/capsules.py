"""Kitchen pin geometry/material, reusable with an existing animated root."""
import bpy
COLORS={'CHAR-0001':(.98,.36,.04),'CHAR-0002':(.15,.75,.20),'CHAR-0003':(.035,.45,.95)}
def material(name,color,stripes=False):
    m=bpy.data.materials.new(name);m.diffuse_color=(*color,1);m.use_nodes=True
    bs=m.node_tree.nodes.get('Principled BSDF');bs.inputs['Base Color'].default_value=(*color,1);bs.inputs['Roughness'].default_value=.65
    if stripes:
        w=m.node_tree.nodes.new('ShaderNodeTexWave');w.wave_type='BANDS';w.bands_direction='Z';w.inputs['Scale'].default_value=5
        r=m.node_tree.nodes.new('ShaderNodeValToRGB');r.color_ramp.interpolation='CONSTANT';r.color_ramp.elements[0].color=(.025,.025,.035,1)
        r.color_ramp.elements[1].position=.46;r.color_ramp.elements[1].color=(*color,1)
        m.node_tree.links.new(w.outputs['Fac'],r.inputs[0]);m.node_tree.links.new(r.outputs['Color'],bs.inputs['Base Color'])
    return m
def sphere(name,pos,scale,mat,parent):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=20,ring_count=12)
    obj=bpy.context.object;obj.name=name;obj.scale=scale;obj.parent=parent;obj.location=pos;obj.data.materials.append(mat)
    for face in obj.data.polygons:face.use_smooth=True
    return obj
def pin(ident,color,parent=None):
    if parent is None:
        parent=bpy.data.objects.new('PREVIS_'+ident,None);bpy.context.collection.objects.link(parent)
    m=material(ident+'_stripe',color,True)
    sphere(ident+'_body',(0,0,.75),(.22,.22,.64),m,parent)
    sphere(ident+'_head',(0,0,1.50),(.17,.17,.20),m,parent)
    sphere(ident+'_facing',(0,.17,1.51),(.06,.025,.06),material(ident+'_white',(1,1,1)),parent)
    return parent
def replace_previous_people():
    for ident,color in COLORS.items():
        root=bpy.data.objects['PREVIS_'+ident]
        for child in list(root.children_recursive):bpy.data.objects.remove(child,do_unlink=True)
        pin(ident,color,root)
        # Kitchen +Y face marker vs WorldOS +Z mapped into Blender -Y.
        root.delta_rotation_euler.z=-3.141592653589793
