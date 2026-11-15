# Blender side of case_render.py: run as
#   Blender -b --factory-startup -P case_render_blender.py -- scene.json
# Meshes arrive in case mm (X front->back, Y, Z up); Blender works in metres.
import bmesh
import bpy
import json
import math
import os
import sys
from mathutils import Vector

S = json.load(open(sys.argv[sys.argv.index("--") + 1]))
MM = 0.001


def lin(hexstr):
    """sRGB hex -> linear RGBA."""
    h = hexstr.lstrip("#")
    out = []
    for i in (0, 2, 4):
        c = int(h[i:i + 2], 16) / 255
        out.append(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4)
    return (*out, 1.0)


def material(name, colour, rough=0.45, coat=0.0, bump=0.0, **extra):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    p = nt.nodes["Principled BSDF"]
    p.inputs["Base Color"].default_value = colour
    p.inputs["Roughness"].default_value = rough
    p.inputs["Coat Weight"].default_value = coat
    for k, v in extra.items():
        p.inputs[k].default_value = v
    if bump:
        # a fine satin grain, like a moulded or lightly sanded finish
        tex = nt.nodes.new("ShaderNodeTexNoise")
        tex.inputs["Scale"].default_value = 4000.0
        tex.inputs["Detail"].default_value = 4.0
        b = nt.nodes.new("ShaderNodeBump")
        b.inputs["Strength"].default_value = bump
        b.inputs["Distance"].default_value = 0.00005
        nt.links.new(tex.outputs["Fac"], b.inputs["Height"])
        nt.links.new(b.outputs["Normal"], p.inputs["Normal"])
    return m


def tidy(obj, bevel=0.0):
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-7)
    bm.to_mesh(obj.data)
    bm.free()
    for poly in obj.data.polygons:
        poly.use_smooth = False
    if bevel:
        # a hair of edge break so the edges catch light, as real parts do
        mod = obj.modifiers.new("edge", "BEVEL")
        mod.width = bevel
        mod.segments = 3
        mod.limit_method = "ANGLE"
        mod.angle_limit = math.radians(30)
        mod.harden_normals = False


def import_stl(path, name):
    bpy.ops.wm.stl_import(filepath=path, global_scale=MM)
    obj = bpy.context.selected_objects[0]
    obj.name = name
    return obj


# --- scene --------------------------------------------------------------
bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene
sc.render.engine = "CYCLES"
try:
    prefs = bpy.context.preferences.addons["cycles"].preferences
    prefs.compute_device_type = "METAL"
    prefs.get_devices()
    for d in prefs.devices:
        d.use = True
    sc.cycles.device = "GPU"
except Exception as e:                                   # CPU is fine, just slower
    print("render: GPU not available,", e)
sc.cycles.samples = S["samples"]
sc.cycles.use_denoising = True
sc.render.resolution_x, sc.render.resolution_y = 2400, 1500
sc.render.resolution_percentage = S.get("scale", 100)
sc.view_settings.exposure = -0.3
sc.render.film_transparent = False
sc.view_settings.view_transform = "AgX"
try:
    sc.view_settings.look = "AgX - Medium High Contrast"
except TypeError:
    pass

world = bpy.data.worlds.new("studio")
sc.world = world
world.use_nodes = True
world.node_tree.nodes["Background"].inputs["Color"].default_value = lin("#E9E6E0")
world.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.12

C = S["colours"]
m_case = material("case_beige", lin(C["case"]), rough=0.42, bump=0.15,
                  **{"Specular IOR Level": 0.45})
m_logo = {k: material(f"logo_{k}", lin(C[k]), rough=0.35, coat=0.15)
          for k in ("orange", "grey", "black")}
for name, path in S["meshes"].items():
    o = import_stl(path, name)
    if name.startswith("logo_"):
        tidy(o, bevel=0.00008)
        o.data.materials.append(m_logo[name[5:]])
    else:
        tidy(o, bevel=0.0004)
        o.data.materials.append(m_case)

# the Rev 1.0 board, KiCad's own colours, on the standoffs
if S.get("board"):
    before = set(bpy.context.scene.objects)
    bpy.ops.import_scene.gltf(filepath=S["board"]["path"])
    for o in set(bpy.context.scene.objects) - before:
        if o.parent is None:
            o.location = S["board"]["at"]

# OB LEDs: 5 mm reds in the bores, domes standing out of the panel
m_on = material("led_on", lin("#FF2A12"), rough=0.15, **{"Emission Color": lin("#FF3A1A"),
                                                       "Emission Strength": 6.0})
m_off = material("led_off", lin("#5A0C06"), rough=0.08, coat=0.6,
                 **{"Transmission Weight": 0.6})
r = (S["led_d"] / 2 - 0.15) * MM
px = S["panel_x"] * MM
for led in S["leds"]:
    y, z = led["y"] * MM, led["z"] * MM
    bpy.ops.mesh.primitive_cylinder_add(radius=r, depth=S["wall"] * MM + 0.0015,
                                        location=(px + S["wall"] * MM / 2 - 0.00075, y, z),
                                        rotation=(0, math.radians(90), 0), vertices=48)
    body = bpy.context.object
    bpy.ops.mesh.primitive_uv_sphere_add(radius=r, location=(px - 0.0015, y, z),
                                         segments=48, ring_count=24)
    dome = bpy.context.object
    for o in (body, dome):
        o.name = f"{led['ref']}_{o.name}"
        o.data.materials.append(m_on if led["on"] else m_off)
        bpy.ops.object.select_all(action="DESELECT")
        o.select_set(True)
        bpy.context.view_layer.objects.active = o
        bpy.ops.object.shade_smooth()

# --- set: a cyclorama sweep, lights -----------------------------------------
x0, y0, z0, x1, y1, z1 = (v * MM for v in S["bbox"])
centre = Vector(((x0 + x1) / 2, (y0 + y1) / 2, 0.0))
size = max(x1 - x0, y1 - y0)


def cyclorama(azimuth):
    """Floor + curved back wall, the wall standing opposite the camera."""
    R, depth, height, width = 0.6, 2.5, 2.5, 6.0
    prof = [(-depth, 0.0)]
    for k in range(17):
        a = math.radians(90 * k / 16)
        prof.append((size + 0.4 + R * math.sin(a), R - R * math.cos(a)))
    prof.append((size + 0.4 + R, height))
    bm = bmesh.new()
    rows = []
    for u, v in prof:
        rows.append([bm.verts.new((u, s * width / 2, v)) for s in (-1, 1)])
    for a, b in zip(rows, rows[1:]):
        bm.faces.new((a[0], a[1], b[1], b[0]))
    me = bpy.data.meshes.new("cyc")
    bm.to_mesh(me)
    bm.free()
    o = bpy.data.objects.new("cyc", me)
    sc.collection.objects.link(o)
    for poly in me.polygons:
        poly.use_smooth = True
    o.location = centre
    o.rotation_euler = (0, 0, azimuth)
    o.data.materials.append(material("cyc", lin("#A8A39B"), rough=0.9))
    return o


def area(name, loc, energy, sz, colour=(1, 1, 1)):
    ld = bpy.data.lights.new(name, "AREA")
    ld.energy, ld.size, ld.color = energy, sz, colour
    lo = bpy.data.objects.new(name, ld)
    sc.collection.objects.link(lo)
    lo.location = loc
    tgt = Vector((centre.x, centre.y, (z1 - z0) / 2))
    lo.rotation_euler = (tgt - lo.location).to_track_quat("-Z", "Y").to_euler()
    return lo


target = bpy.data.objects.new("target", None)
sc.collection.objects.link(target)
cam_d = bpy.data.cameras.new("cam")
cam = bpy.data.objects.new("cam", cam_d)
sc.collection.objects.link(cam)
sc.camera = cam
tc = cam.constraints.new("TRACK_TO")
tc.target, tc.track_axis, tc.up_axis = target, "TRACK_NEGATIVE_Z", "UP_Y"

# (direction from the centre, distance m, lens mm, look-at height m, look-at x offset)
# Seen from the front the viewer's left is +Y.
# + resolution factor, lid shown
VIEWS = {
    "hero": ((-0.80, 0.52, 0.36), 1.35, 70, 0.045, 0.0, 1.0, True),
    "front": ((-1.0, 0.0, 0.10), 1.25, 105, 0.055, -0.12, 1.5, True),
    "rear": ((0.78, -0.55, 0.40), 1.35, 70, 0.045, 0.0, 1.0, True),
    "open": ((-0.62, 0.42, 0.85), 1.45, 60, 0.03, 0.02, 1.0, False),
}
lid_obj = bpy.data.objects.get("lid")
for view in S["views"]:
    d, dist, lens, look_z, look_dx, res, lid_on = VIEWS[view]
    sc.render.resolution_x, sc.render.resolution_y = int(2400 * res), int(1500 * res)
    if lid_obj:
        lid_obj.hide_render = not lid_on
    d = Vector(d).normalized()
    for o in [o for o in sc.objects if o.name.startswith(("cyc", "key", "fill", "rim"))]:
        bpy.data.objects.remove(o)
    az = math.atan2(-d.y, -d.x)                       # wall faces the camera
    cyclorama(az)
    cam.location = centre + d * dist + Vector((0, 0, look_z))
    target.location = (centre.x + look_dx, centre.y, look_z)
    cam_d.lens = lens
    cam_d.dof.use_dof = True
    cam_d.dof.focus_object = target
    cam_d.dof.aperture_fstop = 11.0
    # key: big and soft, high on the camera's left; fill low right; rim behind
    side = Vector((-d.y, d.x, 0)).normalized()
    area("key", centre + d * 0.9 + side * 0.9 + Vector((0, 0, 1.2)), 55, 1.4)
    area("fill", centre + d * 1.1 - side * 1.1 + Vector((0, 0, 0.35)), 12, 1.8, (0.95, 0.97, 1.0))
    area("rim", centre - d * 0.9 + Vector((0, 0, 1.0)), 45, 1.0, (1.0, 0.96, 0.9))
    sc.render.filepath = os.path.join(S["out"], f"dino_case_{view}.png")
    bpy.ops.render.render(write_still=True)
    print("render: wrote", sc.render.filepath)
