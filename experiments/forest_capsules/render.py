import json
import bpy
from paths import OUT
checks=json.loads((OUT/'film_checks.json').read_text());assert checks['status']=='pass'
bpy.ops.wm.open_mainfile(filepath=str(OUT/'candidate_scene.blend'),load_ui=False,use_scripts=False)
scope=json.loads((OUT/'film_render_scope.json').read_text())
for name in scope['excluded_distant_background']:bpy.data.objects[name].hide_render=True
s=bpy.context.scene;s.render.engine='BLENDER_EEVEE';s.eevee.taa_render_samples=8;s.render.resolution_x=768;s.render.resolution_y=432;s.render.resolution_percentage=100;s.render.use_motion_blur=False
if hasattr(s.render.image_settings,'media_type'):s.render.image_settings.media_type='VIDEO'
s.render.image_settings.file_format='FFMPEG';s.render.ffmpeg.format='MPEG4';s.render.ffmpeg.codec='H264';s.render.ffmpeg.constant_rate_factor='HIGH';s.render.filepath=str(OUT/'forest_capsule_preview.mp4')
bpy.ops.render.render(animation=True);print('CAPSULE_FILM_RENDERED',flush=True)
