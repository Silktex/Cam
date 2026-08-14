"""
Blender PBR Applicator — Apply fabric PBR maps to a 3D model (GLB/GLTF).

Imports a sofa (or any GLB model), applies PBR maps from our pipeline:
  - Albedo → Base Color
  - Normals → Normal Map
  - Roughness → Roughness
  - Height → Displacement (subdivision + modifier)

Renders a turntable preview (front, 45°, side views).

Usage (run from terminal):
  /Applications/Blender.app/Contents/MacOS/Blender --background --python blender_apply_pbr.py -- \
      --glb /path/to/sofa_web.glb \
      --pbr /path/to/pbr_v12_standalone/colored \
      --output /path/to/output_render

  Or run interactively in Blender's scripting tab (edit DEFAULTS below).

  For all 4 batches:
  /Applications/Blender.app/Contents/MacOS/Blender --background --python blender_apply_pbr.py -- --all
"""

import bpy
import sys
import os
import math
import numpy as np
from pathlib import Path

# ── DEFAULTS (used when running interactively in Blender) ──────────────
DEFAULT_GLB = "/Users/abhinavsrivastava/Downloads/sofa_web.glb"
DEFAULT_PBR_BASE = Path(__file__).resolve().parent.parent / "media" / "captures"
DEFAULT_OUTPUT = Path(__file__).resolve().parent.parent / "media" / "renders"

BATCHES = ["GRIMSBY-EARTH", "GRIMSBY-MUSHROOM", "MALVERN-SEAGREEN", "MALVERN-CHARCOAL"]
PBR_SUBFOLDER = "pbr_v13_standalone/colored"

# Render settings
RENDER_RESOLUTION = (960, 540)
RENDER_SAMPLES = 64
DISPLACEMENT_STRENGTH = 0.003  # Very subtle displacement for fabric
SUBDIVISION_LEVELS = 2          # For displacement detail
TEXTURE_SCALE = (18.0, 18.0, 18.0)  # UV tiling — fine fabric repeat across sofa

# Material type: fabric (parameter photometric stereo doesn't capture)
FABRIC_SPECULAR = 0.02          # Fabric has very low Fresnel reflectance

# ── Chromatic Adaptation: Scene Illuminant → D65 ──────────────────────
# Detected white patch values from ColorChecker under top light (linear sRGB).
# These represent the scene illuminant's color — ideally R=G=B for neutral.
# Measured: strongly blue-shifted (B/R = 1.48).
SCENE_WHITE_SRGB = np.array([0.451322, 0.586777, 0.665998])

# sRGB ↔ XYZ conversion matrices (linear sRGB, D65 reference)
_SRGB_TO_XYZ = np.array([
    [0.4124564, 0.3575761, 0.1804375],
    [0.2126729, 0.7151522, 0.0721750],
    [0.0193339, 0.1191920, 0.9503041],
])
_XYZ_TO_SRGB = np.linalg.inv(_SRGB_TO_XYZ)

# Bradford cone response matrix
_BRADFORD = np.array([
    [ 0.8951000,  0.2664000, -0.1614000],
    [-0.7502000,  1.7135000,  0.0367000],
    [ 0.0389000, -0.0685000,  1.0296000],
])
_BRADFORD_INV = np.linalg.inv(_BRADFORD)

# D65 white point in XYZ (CIE 1931 2°)
_D65_XYZ = np.array([0.95047, 1.00000, 1.08883])


def compute_d65_adaptation(scene_white_srgb):
    """
    Compute a 3×3 Bradford chromatic adaptation matrix that transforms
    linear sRGB pixels from the scene illuminant to D65.

    scene_white_srgb: (3,) array — detected white patch in linear sRGB.
    Returns: (3, 3) matrix to apply as: corrected = M @ pixel.
    """
    # Scene illuminant in XYZ, normalized to Y=1
    source_xyz = _SRGB_TO_XYZ @ scene_white_srgb
    source_xyz = source_xyz / source_xyz[1]

    # Cone responses
    cone_src = _BRADFORD @ source_xyz
    cone_dst = _BRADFORD @ _D65_XYZ

    # Adaptation in cone space
    scale = cone_dst / cone_src
    adapt_xyz = _BRADFORD_INV @ np.diag(scale) @ _BRADFORD

    # Combined: linear sRGB → XYZ → adapt → XYZ → linear sRGB
    combined = _XYZ_TO_SRGB @ adapt_xyz @ _SRGB_TO_XYZ

    print(f"  Bradford D65 adaptation matrix:")
    for r, ch in enumerate(['R', 'G', 'B']):
        print(f"    {ch}: [{combined[r,0]:+.4f}  {combined[r,1]:+.4f}  {combined[r,2]:+.4f}]")

    return combined


def adapt_albedo_to_d65(image):
    """
    Apply Bradford chromatic adaptation to a Blender image (in-place).
    Converts albedo from scene illuminant to D65 neutral daylight.
    """
    M = compute_d65_adaptation(SCENE_WHITE_SRGB)

    w, h = image.size
    pixels = np.array(image.pixels[:]).reshape(h, w, 4)

    # Extract RGB and keep a copy for stats
    rgb = pixels[:, :, :3].reshape(-1, 3).copy()

    # Apply 3×3 matrix to RGB channels
    adapted = (M @ rgb.T).T
    adapted = np.nan_to_num(adapted, nan=0.0, posinf=1.0, neginf=0.0)
    adapted = np.clip(adapted, 0, 1)
    pixels[:, :, :3] = adapted.reshape(h, w, 3)

    # Write back
    image.pixels[:] = pixels.flatten()
    image.update()

    # Stats
    print(f"  D65 adaptation applied ({w}x{h} = {rgb.shape[0]} pixels):")
    print(f"    R: {rgb[:,0].mean():.4f} → {adapted[:,0].mean():.4f}")
    print(f"    G: {rgb[:,1].mean():.4f} → {adapted[:,1].mean():.4f}")
    print(f"    B: {rgb[:,2].mean():.4f} → {adapted[:,2].mean():.4f}")
    luma_b = (rgb[:, 0] * 0.2126 + rgb[:, 1] * 0.7152 + rgb[:, 2] * 0.0722).mean()
    luma_a = (adapted[:, 0] * 0.2126 + adapted[:, 1] * 0.7152 + adapted[:, 2] * 0.0722).mean()
    print(f"    Luma: {luma_b:.4f} → {luma_a:.4f}")


# ═══════════════════════════════════════════════════════════════════════
#  SCENE SETUP
# ═══════════════════════════════════════════════════════════════════════

def clear_scene():
    """Remove all objects, materials, and images from the scene."""
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)

    # Clear orphan data
    for block in bpy.data.meshes:
        if block.users == 0:
            bpy.data.meshes.remove(block)
    for block in bpy.data.materials:
        if block.users == 0:
            bpy.data.materials.remove(block)
    for block in bpy.data.images:
        if block.users == 0:
            bpy.data.images.remove(block)


def import_glb(glb_path):
    """Import GLB/GLTF model."""
    print(f"Importing GLB: {glb_path}")
    bpy.ops.import_scene.gltf(filepath=str(glb_path))

    imported = [obj for obj in bpy.context.selected_objects if obj.type == 'MESH']
    if not imported:
        imported = [obj for obj in bpy.data.objects if obj.type == 'MESH']

    print(f"  Imported {len(imported)} mesh objects")
    for obj in imported:
        print(f"    {obj.name}: verts={len(obj.data.vertices)} faces={len(obj.data.polygons)}")

    return imported


def normalize_model_scale(objects, target_size=2.0):
    """
    Normalize imported model so the longest dimension = target_size meters.
    Centers the model on the XY origin and sits it on the ground plane (Z=0).
    This makes all lighting, camera, and environment settings scale-independent.

    Handles GLB parent hierarchies (empties with transforms) by flattening first.
    """
    from mathutils import Vector

    # ── Step 1: Flatten parent hierarchy ──
    # GLB imports often have Empty parents with scale/location transforms.
    # Clear parents while keeping world-space transforms on the meshes.
    bpy.ops.object.select_all(action='DESELECT')
    for obj in objects:
        obj.select_set(True)
    if objects:
        bpy.context.view_layer.objects.active = objects[0]
        bpy.ops.object.parent_clear(type='CLEAR_KEEP_TRANSFORM')

    # Apply all transforms (location, rotation, scale) so mesh data is in world space
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)

    # ── Step 2: Compute world-space bounding box ──
    min_co = Vector((float('inf'), float('inf'), float('inf')))
    max_co = Vector((float('-inf'), float('-inf'), float('-inf')))

    for obj in objects:
        if obj.type != 'MESH':
            continue
        for v in obj.bound_box:
            world_co = obj.matrix_world @ Vector(v)
            min_co = Vector((min(min_co[i], world_co[i]) for i in range(3)))
            max_co = Vector((max(max_co[i], world_co[i]) for i in range(3)))

    dimensions = max_co - min_co
    longest = max(dimensions)

    if longest <= 0:
        print("  WARNING: Model has zero size, skipping normalization")
        return objects

    # ── Step 3: Scale and reposition ──
    scale_factor = target_size / longest
    center = (min_co + max_co) / 2

    print(f"  Model bounds: {dimensions.x:.3f} x {dimensions.y:.3f} x {dimensions.z:.3f}")
    print(f"  Scale factor: {scale_factor:.4f} (longest {longest:.3f} → {target_size})")

    for obj in objects:
        # Blender matrix: v_world = scale * v_local + location
        # So to center and ground after scaling, offsets must be: -scale * original_pos
        obj.location.x = -scale_factor * center.x
        obj.location.y = -scale_factor * center.y
        obj.location.z = -scale_factor * min_co.z
        obj.scale = (scale_factor, scale_factor, scale_factor)

    # Apply transforms again so everything is clean
    bpy.ops.object.select_all(action='DESELECT')
    for obj in objects:
        obj.select_set(True)
    if objects:
        bpy.context.view_layer.objects.active = objects[0]
        bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)

    # ── Step 4: Verify ──
    new_min = Vector((float('inf'), float('inf'), float('inf')))
    new_max = Vector((float('-inf'), float('-inf'), float('-inf')))
    for obj in objects:
        if obj.type != 'MESH':
            continue
        for v in obj.bound_box:
            world_co = obj.matrix_world @ Vector(v)
            new_min = Vector((min(new_min[i], world_co[i]) for i in range(3)))
            new_max = Vector((max(new_max[i], world_co[i]) for i in range(3)))
    new_dims = new_max - new_min
    print(f"  Normalized: {new_dims.x:.3f} x {new_dims.y:.3f} x {new_dims.z:.3f} (bottom at Z={new_min.z:.3f})")

    return objects


# ═══════════════════════════════════════════════════════════════════════
#  PBR MATERIAL
# ═══════════════════════════════════════════════════════════════════════

def create_pbr_material(name, pbr_folder):
    """
    Create a Principled BSDF material with PBR texture maps.

    Node graph:
      [Albedo Tex] → Base Color
      [Normal Tex] → Normal Map Node → Normal
      [Roughness Tex] → Roughness
      [Height Tex] → Displacement Node → Material Output.Displacement
      [Texture Coordinate] → [Mapping] → all texture nodes (for UV tiling)
    """
    pbr_folder = Path(pbr_folder)

    def find_tex(name):
        """Find texture file, trying .tiff first (linear) then .png."""
        for ext in ('.tiff', '.tif', '.png'):
            p = pbr_folder / f"{name}{ext}"
            if p.exists():
                return p
        print(f"  WARNING: Missing texture '{name}' in {pbr_folder}")
        return None

    albedo_path = find_tex("albedo")
    normals_path = find_tex("normals")
    roughness_path = find_tex("roughness_normalized") or find_tex("roughness")
    height_path = find_tex("height_map")

    print(f"  Textures: albedo={albedo_path}, normals={normals_path}, roughness={roughness_path}, height={height_path}")

    # Create material
    mat = bpy.data.materials.new(name=name)
    # Blender 5.0+: materials always use nodes (use_nodes deprecated)
    try:
        mat.use_nodes = True
    except Exception:
        pass
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links

    # Clear default nodes
    for node in nodes:
        nodes.remove(node)

    # ── Output node ──
    output_node = nodes.new('ShaderNodeOutputMaterial')
    output_node.location = (800, 0)

    # ── Principled BSDF ──
    bsdf = nodes.new('ShaderNodeBsdfPrincipled')
    bsdf.location = (400, 0)
    links.new(bsdf.outputs['BSDF'], output_node.inputs['Surface'])

    # Material type: fabric — low specular (photometric stereo doesn't capture this)
    if 'Specular IOR Level' in bsdf.inputs:
        bsdf.inputs['Specular IOR Level'].default_value = FABRIC_SPECULAR
    elif 'Specular' in bsdf.inputs:
        bsdf.inputs['Specular'].default_value = FABRIC_SPECULAR

    # ── Texture Coordinate + Mapping (for UV tiling) ──
    tex_coord = nodes.new('ShaderNodeTexCoord')
    tex_coord.location = (-800, 0)

    mapping = nodes.new('ShaderNodeMapping')
    mapping.location = (-600, 0)
    mapping.inputs['Scale'].default_value = TEXTURE_SCALE
    links.new(tex_coord.outputs['UV'], mapping.inputs['Vector'])

    # ── Albedo (Base Color) ──
    if albedo_path:
        albedo_tex = nodes.new('ShaderNodeTexImage')
        albedo_tex.location = (-200, 300)
        albedo_tex.label = 'Albedo'
        albedo_tex.image = bpy.data.images.load(str(albedo_path))
        # Albedo TIFFs from full_pipeline are sRGB-encoded
        albedo_tex.image.colorspace_settings.name = 'sRGB'

        links.new(mapping.outputs['Vector'], albedo_tex.inputs['Vector'])
        links.new(albedo_tex.outputs['Color'], bsdf.inputs['Base Color'])

    # ── Normal Map ──
    if normals_path:
        normal_tex = nodes.new('ShaderNodeTexImage')
        normal_tex.location = (-200, 0)
        normal_tex.label = 'Normals'
        normal_tex.image = bpy.data.images.load(str(normals_path))
        normal_tex.image.colorspace_settings.name = 'Non-Color'
        links.new(mapping.outputs['Vector'], normal_tex.inputs['Vector'])

        normal_map = nodes.new('ShaderNodeNormalMap')
        normal_map.location = (100, 0)
        normal_map.inputs['Strength'].default_value = 1.0
        links.new(normal_tex.outputs['Color'], normal_map.inputs['Color'])
        links.new(normal_map.outputs['Normal'], bsdf.inputs['Normal'])

    # ── Roughness (direct — already normalized in pipeline) ──
    if roughness_path:
        rough_tex = nodes.new('ShaderNodeTexImage')
        rough_tex.location = (-200, -300)
        rough_tex.label = 'Roughness'
        rough_tex.image = bpy.data.images.load(str(roughness_path))
        rough_tex.image.colorspace_settings.name = 'Non-Color'
        links.new(mapping.outputs['Vector'], rough_tex.inputs['Vector'])
        links.new(rough_tex.outputs['Color'], bsdf.inputs['Roughness'])

    # ── Height → Displacement ──
    if height_path:
        height_tex = nodes.new('ShaderNodeTexImage')
        height_tex.location = (-200, -600)
        height_tex.label = 'Height'
        height_tex.image = bpy.data.images.load(str(height_path))
        height_tex.image.colorspace_settings.name = 'Non-Color'
        links.new(mapping.outputs['Vector'], height_tex.inputs['Vector'])

        disp_node = nodes.new('ShaderNodeDisplacement')
        disp_node.location = (400, -400)
        # Blender 5.0 renamed 'Midpoint' — handle both versions
        if 'Midpoint' in disp_node.inputs:
            disp_node.inputs['Midpoint'].default_value = 0.5
        if 'Scale' in disp_node.inputs:
            disp_node.inputs['Scale'].default_value = DISPLACEMENT_STRENGTH
        links.new(height_tex.outputs['Color'], disp_node.inputs['Height'])
        links.new(disp_node.outputs['Displacement'], output_node.inputs['Displacement'])

        # Enable displacement in material settings (API varies by Blender version)
        try:
            mat.cycles.displacement_method = 'BOTH'
        except AttributeError:
            # Blender 5.0+: displacement is set per-material differently
            try:
                mat.displacement_method = 'BOTH'
            except Exception:
                pass

    print(f"  Created material: {name}")
    return mat


def apply_material_to_objects(objects, material):
    """
    Apply fabric material to sofa body and buttons only.
    Legs and metals keep their original materials.
    """
    # Keywords that identify fabric parts (body, buttons, cushion)
    FABRIC_KEYWORDS = ['body', 'button', 'cushion', 'seat', 'fabric']
    # Keywords that should NOT get fabric material (check first)
    SKIP_KEYWORDS = ['leg', 'metal', 'cooper', 'chrome', 'steel', 'wood', 'frame']

    applied = 0
    for obj in objects:
        if obj.type != 'MESH':
            continue

        name_lower = obj.name.lower()

        # Check if this part should get fabric material
        is_fabric = any(kw in name_lower for kw in FABRIC_KEYWORDS)
        is_skip = any(kw in name_lower for kw in SKIP_KEYWORDS)

        if is_skip and not is_fabric:
            print(f"    KEEP original: {obj.name}")
            continue

        if is_fabric or (not is_skip):
            obj.data.materials.clear()
            obj.data.materials.append(material)
            applied += 1

            # Add subdivision for displacement detail on fabric parts
            if SUBDIVISION_LEVELS > 0:
                for mod in obj.modifiers:
                    if mod.type == 'SUBSURF':
                        obj.modifiers.remove(mod)

                subsurf = obj.modifiers.new(name='Subdivision', type='SUBSURF')
                subsurf.levels = SUBDIVISION_LEVELS
                subsurf.render_levels = SUBDIVISION_LEVELS

            print(f"    FABRIC material: {obj.name}")
        else:
            print(f"    KEEP original: {obj.name}")

    print(f"  Applied fabric material to {applied}/{len(objects)} objects")


# ═══════════════════════════════════════════════════════════════════════
#  ROOM ENVIRONMENT
# ═══════════════════════════════════════════════════════════════════════

# Room dimensions (meters)
ROOM_WIDTH  = 6.0   # X axis
ROOM_DEPTH  = 5.0   # Y axis (camera looks from -Y)
ROOM_HEIGHT = 3.0   # Z axis

# Colors (linear sRGB)
WALL_COLOR      = (0.450, 0.420, 0.380, 1.0)   # Warm taupe/greige
BASEBOARD_COLOR = (0.75, 0.74, 0.72, 1.0)       # Off-white trim
FRAME_COLOR     = (0.04, 0.03, 0.025, 1.0)      # Dark walnut frame
CANVAS_COLOR    = (0.70, 0.68, 0.65, 1.0)        # Neutral linen canvas


def _make_simple_mat(name, color, roughness=0.5, specular=0.1):
    """Helper: create a basic Principled BSDF material."""
    mat = bpy.data.materials.new(name=name)
    try:
        mat.use_nodes = True
    except Exception:
        pass
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    for n in nodes:
        nodes.remove(n)

    out = nodes.new('ShaderNodeOutputMaterial')
    out.location = (400, 0)
    bsdf = nodes.new('ShaderNodeBsdfPrincipled')
    bsdf.location = (0, 0)
    bsdf.inputs['Base Color'].default_value = color
    bsdf.inputs['Roughness'].default_value = roughness
    if 'Specular IOR Level' in bsdf.inputs:
        bsdf.inputs['Specular IOR Level'].default_value = specular
    elif 'Specular' in bsdf.inputs:
        bsdf.inputs['Specular'].default_value = specular
    links.new(bsdf.outputs['BSDF'], out.inputs['Surface'])
    return mat, nodes, links, bsdf


def _create_wood_floor_material():
    """Procedural hardwood floor material using Blender noise textures."""
    mat = bpy.data.materials.new(name='Wood_Floor')
    try:
        mat.use_nodes = True
    except Exception:
        pass
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    for n in nodes:
        nodes.remove(n)

    out = nodes.new('ShaderNodeOutputMaterial')
    out.location = (800, 0)

    bsdf = nodes.new('ShaderNodeBsdfPrincipled')
    bsdf.location = (500, 0)
    bsdf.inputs['Roughness'].default_value = 0.45
    if 'Specular IOR Level' in bsdf.inputs:
        bsdf.inputs['Specular IOR Level'].default_value = 0.3
    links.new(bsdf.outputs['BSDF'], out.inputs['Surface'])

    # Texture coordinate → mapping (stretch Y for plank grain)
    tex_coord = nodes.new('ShaderNodeTexCoord')
    tex_coord.location = (-600, 0)
    mapping = nodes.new('ShaderNodeMapping')
    mapping.location = (-400, 0)
    mapping.inputs['Scale'].default_value = (4.0, 12.0, 1.0)
    links.new(tex_coord.outputs['Object'], mapping.inputs['Vector'])

    # Noise texture for wood grain
    noise = nodes.new('ShaderNodeTexNoise')
    noise.location = (-200, 100)
    noise.inputs['Scale'].default_value = 8.0
    noise.inputs['Detail'].default_value = 6.0
    noise.inputs['Distortion'].default_value = 2.5
    links.new(mapping.outputs['Vector'], noise.inputs['Vector'])

    # Color ramp: warm wood tones
    ramp = nodes.new('ShaderNodeValToRGB')
    ramp.location = (100, 100)
    ramp.color_ramp.elements[0].position = 0.3
    ramp.color_ramp.elements[0].color = (0.12, 0.07, 0.04, 1.0)  # Dark wood
    ramp.color_ramp.elements[1].position = 0.7
    ramp.color_ramp.elements[1].color = (0.28, 0.17, 0.10, 1.0)  # Light wood
    # Add a mid element
    mid = ramp.color_ramp.elements.new(0.5)
    mid.color = (0.20, 0.12, 0.07, 1.0)
    links.new(noise.outputs['Fac'], ramp.inputs['Fac'])
    links.new(ramp.outputs['Color'], bsdf.inputs['Base Color'])

    # Second noise for roughness variation
    noise2 = nodes.new('ShaderNodeTexNoise')
    noise2.location = (-200, -200)
    noise2.inputs['Scale'].default_value = 20.0
    noise2.inputs['Detail'].default_value = 3.0
    links.new(mapping.outputs['Vector'], noise2.inputs['Vector'])

    # Math: remap noise to 0.35-0.55 range for subtle roughness variation
    math_mul = nodes.new('ShaderNodeMath')
    math_mul.operation = 'MULTIPLY'
    math_mul.location = (0, -200)
    math_mul.inputs[1].default_value = 0.2
    links.new(noise2.outputs['Fac'], math_mul.inputs[0])

    math_add = nodes.new('ShaderNodeMath')
    math_add.operation = 'ADD'
    math_add.location = (200, -200)
    math_add.inputs[1].default_value = 0.35
    links.new(math_mul.outputs['Value'], math_add.inputs[0])
    links.new(math_add.outputs['Value'], bsdf.inputs['Roughness'])

    return mat


def _create_wall_material():
    """Wall paint material with subtle texture (not perfectly flat)."""
    mat, nodes, links, bsdf = _make_simple_mat('Wall_Paint', WALL_COLOR, roughness=0.85, specular=0.05)

    # Add subtle noise for wall texture
    tex_coord = nodes.new('ShaderNodeTexCoord')
    tex_coord.location = (-600, 0)
    noise = nodes.new('ShaderNodeTexNoise')
    noise.location = (-300, -200)
    noise.inputs['Scale'].default_value = 80.0
    noise.inputs['Detail'].default_value = 4.0
    links.new(tex_coord.outputs['Object'], noise.inputs['Vector'])

    # Mix base color with slight noise variation
    mix = nodes.new('ShaderNodeMix')
    mix.data_type = 'RGBA'
    mix.location = (-100, 100)
    mix.inputs[0].default_value = 0.03  # Factor — very subtle
    mix.inputs[6].default_value = WALL_COLOR
    mix.inputs[7].default_value = (0.40, 0.37, 0.33, 1.0)  # Slightly darker variation
    links.new(noise.outputs['Fac'], mix.inputs[0])
    links.new(mix.outputs[2], bsdf.inputs['Base Color'])

    return mat


def _add_box(name, location, dimensions, material):
    """Add a box (cube) at location with given dimensions and material."""
    bpy.ops.mesh.primitive_cube_add(size=1, location=location)
    obj = bpy.context.active_object
    obj.name = name
    obj.scale = (dimensions[0] / 2, dimensions[1] / 2, dimensions[2] / 2)
    bpy.ops.object.transform_apply(scale=True)
    obj.data.materials.clear()
    obj.data.materials.append(material)
    return obj


def _create_picture_frame(name, location, width, height, frame_thick=0.04, depth=0.03):
    """Create a picture frame with canvas on the wall.

    Frame is 4 thin boxes around a flat canvas plane.
    """
    import bmesh

    frame_mat, _, _, _ = _make_simple_mat(f'{name}_Frame', FRAME_COLOR, roughness=0.3, specular=0.2)
    canvas_mat, _, _, _ = _make_simple_mat(f'{name}_Canvas', CANVAS_COLOR, roughness=0.9, specular=0.02)

    objects = []
    x, y, z = location

    # Canvas (flat plane, slightly recessed)
    bpy.ops.mesh.primitive_plane_add(size=1, location=(x, y - depth * 0.4, z))
    canvas = bpy.context.active_object
    canvas.name = f'{name}_Canvas'
    canvas.scale = (width / 2 - frame_thick, 1, height / 2 - frame_thick)
    canvas.rotation_euler = (math.pi / 2, 0, 0)
    bpy.ops.object.transform_apply(scale=True, rotation=True)
    canvas.data.materials.clear()
    canvas.data.materials.append(canvas_mat)
    objects.append(canvas)

    # Frame — 4 bars
    hw = width / 2
    hh = height / 2
    ft = frame_thick
    fd = depth

    # Top bar
    _add_box(f'{name}_Top', (x, y, z + hh - ft / 2), (width, fd, ft), frame_mat)
    objects.append(bpy.context.active_object)
    # Bottom bar
    _add_box(f'{name}_Bot', (x, y, z - hh + ft / 2), (width, fd, ft), frame_mat)
    objects.append(bpy.context.active_object)
    # Left bar
    _add_box(f'{name}_Left', (x - hw + ft / 2, y, z), (ft, fd, height), frame_mat)
    objects.append(bpy.context.active_object)
    # Right bar
    _add_box(f'{name}_Right', (x + hw - ft / 2, y, z), (ft, fd, height), frame_mat)
    objects.append(bpy.context.active_object)

    print(f"    Frame: {name} at ({x:.1f}, {y:.1f}, {z:.1f}) size {width:.1f}x{height:.1f}m")
    return objects


def create_studio_environment():
    """
    Create a realistic living room environment:
    - Hardwood floor with procedural wood grain
    - Painted walls (back + left + right) with subtle texture
    - White baseboards along the bottom of each wall
    - Picture frames on the back wall
    """
    hw = ROOM_WIDTH / 2
    hd = ROOM_DEPTH / 2

    # ── Materials ──
    floor_mat = _create_wood_floor_material()
    wall_mat = _create_wall_material()
    baseboard_mat, _, _, _ = _make_simple_mat('Baseboard', BASEBOARD_COLOR, roughness=0.4, specular=0.15)

    room_objects = []

    # ── Floor ──
    # size=1 gives a 1x1 plane (±0.5). Scale multiplies vertices directly.
    # So scale=ROOM_WIDTH gives total width = ROOM_WIDTH.
    bpy.ops.mesh.primitive_plane_add(size=1, location=(0, 0, 0))
    floor = bpy.context.active_object
    floor.name = 'Room_Floor'
    floor.scale = (ROOM_WIDTH, ROOM_DEPTH, 1)
    bpy.ops.object.transform_apply(scale=True)
    floor.data.materials.clear()
    floor.data.materials.append(floor_mat)
    room_objects.append(floor)

    # ── Back wall (Y = +hd, facing -Y toward camera) ──
    # After rotation (pi/2,0,0): local Y becomes world Z.
    # Scale X = ROOM_WIDTH (wall width), Y = ROOM_HEIGHT (becomes wall height).
    bpy.ops.mesh.primitive_plane_add(size=1, location=(0, hd, ROOM_HEIGHT / 2))
    back_wall = bpy.context.active_object
    back_wall.name = 'Room_BackWall'
    back_wall.scale = (ROOM_WIDTH, ROOM_HEIGHT, 1)
    back_wall.rotation_euler = (math.pi / 2, 0, 0)
    bpy.ops.object.transform_apply(scale=True, rotation=True)
    back_wall.data.materials.clear()
    back_wall.data.materials.append(wall_mat)
    room_objects.append(back_wall)

    # ── Left wall (X = -hw, facing +X) ──
    # After rotation (0,-pi/2,0): local X becomes world Z, local Y stays Y.
    # Scale X = ROOM_HEIGHT (becomes height), Y = ROOM_DEPTH (stays depth).
    bpy.ops.mesh.primitive_plane_add(size=1, location=(-hw, 0, ROOM_HEIGHT / 2))
    left_wall = bpy.context.active_object
    left_wall.name = 'Room_LeftWall'
    left_wall.scale = (ROOM_HEIGHT, ROOM_DEPTH, 1)
    left_wall.rotation_euler = (0, -math.pi / 2, 0)
    bpy.ops.object.transform_apply(scale=True, rotation=True)
    left_wall.data.materials.clear()
    left_wall.data.materials.append(wall_mat)
    room_objects.append(left_wall)

    # ── Right wall (X = +hw, facing -X) ──
    bpy.ops.mesh.primitive_plane_add(size=1, location=(hw, 0, ROOM_HEIGHT / 2))
    right_wall = bpy.context.active_object
    right_wall.name = 'Room_RightWall'
    right_wall.scale = (ROOM_HEIGHT, ROOM_DEPTH, 1)
    right_wall.rotation_euler = (0, math.pi / 2, 0)
    bpy.ops.object.transform_apply(scale=True, rotation=True)
    right_wall.data.materials.clear()
    right_wall.data.materials.append(wall_mat)
    room_objects.append(right_wall)

    # ── Baseboards (thin strips at bottom of each wall) ──
    baseboard_h = 0.12   # 12cm tall
    baseboard_d = 0.015  # 1.5cm thick

    # Back baseboard
    _add_box('Baseboard_Back',
             (0, hd - baseboard_d / 2, baseboard_h / 2),
             (ROOM_WIDTH, baseboard_d, baseboard_h), baseboard_mat)
    room_objects.append(bpy.context.active_object)

    # Left baseboard
    _add_box('Baseboard_Left',
             (-hw + baseboard_d / 2, 0, baseboard_h / 2),
             (baseboard_d, ROOM_DEPTH, baseboard_h), baseboard_mat)
    room_objects.append(bpy.context.active_object)

    # Right baseboard
    _add_box('Baseboard_Right',
             (hw - baseboard_d / 2, 0, baseboard_h / 2),
             (baseboard_d, ROOM_DEPTH, baseboard_h), baseboard_mat)
    room_objects.append(bpy.context.active_object)

    # ── Picture frames on back wall ──
    wall_y = hd - 0.02  # Slightly off the wall

    # Large frame (center-right, landscape)
    frame1_objs = _create_picture_frame(
        'Frame_Large',
        location=(0.6, wall_y, 1.65),
        width=0.80, height=0.60,
    )
    room_objects.extend(frame1_objs)

    # Small frame (left of large, portrait)
    frame2_objs = _create_picture_frame(
        'Frame_Small',
        location=(-0.7, wall_y, 1.70),
        width=0.40, height=0.55,
    )
    room_objects.extend(frame2_objs)

    # Tiny frame (far left, square)
    frame3_objs = _create_picture_frame(
        'Frame_Tiny',
        location=(-1.4, wall_y, 1.55),
        width=0.30, height=0.30,
    )
    room_objects.extend(frame3_objs)

    print(f"  Room environment: {ROOM_WIDTH}x{ROOM_DEPTH}x{ROOM_HEIGHT}m, "
          f"wood floor, painted walls, 3 baseboards, 3 frames")
    return floor, back_wall


# ═══════════════════════════════════════════════════════════════════════
#  LIGHTING + CAMERA
# ═══════════════════════════════════════════════════════════════════════

def setup_lighting(objects):
    """
    Natural interior lighting for a living room scene.
    Simulates daylight from camera side + warm ceiling fixtures.

    - Window light: large area from front-left (simulating daylight through a window)
    - Ceiling light: warm area above the sofa (room fixture)
    - Accent light: small area on the right side for fill
    - Soft ambient via world background
    """

    # ── Window light (large area — daylight from front-left) ──
    bpy.ops.object.light_add(type='AREA', location=(-2.5, -2.0, 2.2))
    window = bpy.context.active_object
    window.name = 'Window_Light'
    window.data.energy = 200
    window.data.size = 2.5
    window.data.size_y = 2.0
    window.data.color = (0.95, 0.95, 1.0)  # Cool daylight
    window.rotation_euler = (math.radians(60), 0, math.radians(-50))

    # ── Ceiling light (warm overhead — room fixture) ──
    bpy.ops.object.light_add(type='AREA', location=(0, 0.5, 2.8))
    ceiling = bpy.context.active_object
    ceiling.name = 'Ceiling_Light'
    ceiling.data.energy = 80
    ceiling.data.size = 1.5
    ceiling.data.size_y = 1.5
    ceiling.data.color = (1.0, 0.92, 0.82)  # Warm tungsten
    ceiling.rotation_euler = (0, 0, 0)  # Points straight down

    # ── Accent fill (small area — right side, softer) ──
    bpy.ops.object.light_add(type='AREA', location=(2.5, -1.5, 1.5))
    accent = bpy.context.active_object
    accent.name = 'Accent_Light'
    accent.data.energy = 40
    accent.data.size = 1.0
    accent.data.size_y = 1.0
    accent.data.color = (1.0, 0.95, 0.90)
    accent.rotation_euler = (math.radians(50), 0, math.radians(40))

    # ── World environment: soft warm ambient ──
    world = bpy.data.worlds.get('World')
    if world is None:
        world = bpy.data.worlds.new('World')
    bpy.context.scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes.get('Background')
    if bg:
        bg.inputs['Color'].default_value = (0.95, 0.90, 0.85, 1.0)  # Warm ambient
        bg.inputs['Strength'].default_value = 0.15  # Low fill

    print(f"  Room lighting: window=200W ceiling=80W accent=40W + warm ambient")


def setup_camera(objects):
    """
    Position camera for interior room photography of a normalized ~2m model.
    - 35mm focal length (wider to show room context)
    - 3/4 front view, human eye-level (~1.5m)
    - Subtle depth of field
    """
    from mathutils import Vector

    # Compute bounding box of all objects
    min_co = Vector((float('inf'), float('inf'), float('inf')))
    max_co = Vector((float('-inf'), float('-inf'), float('-inf')))

    for obj in objects:
        if obj.type != 'MESH':
            continue
        for v in obj.bound_box:
            world_co = obj.matrix_world @ Vector(v)
            min_co = Vector((min(min_co[i], world_co[i]) for i in range(3)))
            max_co = Vector((max(max_co[i], world_co[i]) for i in range(3)))

    center = (min_co + max_co) / 2
    model_height = max_co.z - min_co.z

    # Camera position: 3/4 front view, human eye-level
    # Must stay inside the room (Y > -ROOM_DEPTH/2 = -2.5)
    cam_distance = 2.8
    cam_angle_h = math.radians(25)  # 25° from front = slight 3/4 view
    cam_z = 1.3  # Human eye level when seated/viewing

    cam_x = cam_distance * math.sin(cam_angle_h)
    cam_y = -cam_distance * math.cos(cam_angle_h)
    # Clamp inside room
    cam_y = max(cam_y, -ROOM_DEPTH / 2 + 0.3)

    bpy.ops.object.camera_add(location=(cam_x, cam_y, cam_z))
    camera = bpy.context.active_object
    camera.name = 'Room_Camera'

    # Look at sofa center (slightly above geometric center)
    look_at = Vector((center.x, center.y, center.z + model_height * 0.1))
    direction = look_at - camera.location
    camera.rotation_euler = direction.to_track_quat('-Z', 'Y').to_euler()

    # Lens: wider to show room context
    camera.data.lens = 35  # 35mm — shows room context
    camera.data.sensor_width = 36
    camera.data.clip_start = 0.1
    camera.data.clip_end = 100.0

    # Depth of field — architectural/interior style (f/4)
    camera.data.dof.use_dof = True
    camera.data.dof.focus_distance = direction.length
    camera.data.dof.aperture_fstop = 4.0

    bpy.context.scene.camera = camera
    print(f"  Camera: 35mm f/4, distance={cam_distance:.1f}m, room interior view")

    return camera


# ═══════════════════════════════════════════════════════════════════════
#  RENDER
# ═══════════════════════════════════════════════════════════════════════

def setup_render():
    """Configure render settings for quality output."""
    scene = bpy.context.scene

    # Use Cycles for accurate PBR
    scene.render.engine = 'CYCLES'

    # Try GPU (Metal on macOS), fall back to CPU
    try:
        prefs = bpy.context.preferences.addons.get('cycles')
        if prefs:
            prefs.preferences.compute_device_type = 'METAL'
            # Refresh device list
            prefs.preferences.get_devices()
            # Enable all available GPU devices
            for device in prefs.preferences.devices:
                device.use = True
            scene.cycles.device = 'GPU'
            print(f"  Render device: GPU (Metal)")
    except Exception as e:
        scene.cycles.device = 'CPU'
        print(f"  Render device: CPU (GPU setup failed: {e})")

    scene.cycles.samples = RENDER_SAMPLES
    scene.cycles.use_denoising = True

    scene.render.resolution_x = RENDER_RESOLUTION[0]
    scene.render.resolution_y = RENDER_RESOLUTION[1]
    scene.render.resolution_percentage = 100

    # Filmic view transform
    scene.view_settings.view_transform = 'Filmic'
    scene.view_settings.look = 'None'
    scene.view_settings.exposure = 0.0

    # Output format
    scene.render.image_settings.file_format = 'PNG'
    scene.render.image_settings.color_depth = '16'

    # Room visible — not transparent background
    scene.render.film_transparent = False

    print(f"  Render: Cycles {RENDER_RESOLUTION[0]}x{RENDER_RESOLUTION[1]} @ {RENDER_SAMPLES} samples")


def render_views(camera, objects, output_dir, batch_name):
    """Render front, 45°, and side views by orbiting the camera."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Compute center and radius for orbit
    min_co = [float('inf')] * 3
    max_co = [float('-inf')] * 3
    from mathutils import Vector

    for obj in objects:
        if obj.type != 'MESH':
            continue
        for v in obj.bound_box:
            world_co = obj.matrix_world @ Vector(v)
            for i in range(3):
                min_co[i] = min(min_co[i], world_co[i])
                max_co[i] = max(max_co[i], world_co[i])

    center = Vector([(min_co[i] + max_co[i]) / 2 for i in range(3)])
    size = max(max_co[i] - min_co[i] for i in range(3))
    radius = size * 2.0
    height = center.z + size * 0.3

    views = {
        'front': 0,
        'front_right': 45,
        'side': 90,
        'rear_right': 135,
        'rear': 180,
    }

    rendered = []
    for view_name, angle_deg in views.items():
        angle = math.radians(angle_deg)
        cam_x = center.x + radius * math.sin(angle)
        cam_y = center.y - radius * math.cos(angle)
        cam_z = height

        camera.location = (cam_x, cam_y, cam_z)

        # Point at center
        direction = center - camera.location
        camera.rotation_euler = direction.to_track_quat('-Z', 'Y').to_euler()

        # Render
        output_path = str(output_dir / f"{batch_name}_{view_name}.png")
        bpy.context.scene.render.filepath = output_path
        bpy.ops.render.render(write_still=True)

        rendered.append(output_path)
        print(f"    Rendered: {view_name} -> {output_path}")

    return rendered


# ═══════════════════════════════════════════════════════════════════════
#  SAVE BLEND FILE
# ═══════════════════════════════════════════════════════════════════════

def save_blend(output_dir, batch_name):
    """Save the .blend file for manual inspection/tweaking."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    blend_path = output_dir / f"{batch_name}_pbr.blend"

    # Pack all external images into the .blend so textures work on any machine
    bpy.ops.file.pack_all()
    print(f"  Packed all external files into .blend")

    bpy.ops.wm.save_as_mainfile(filepath=str(blend_path))
    print(f"  Saved blend: {blend_path}")
    return blend_path


# ═══════════════════════════════════════════════════════════════════════
#  PROCESS ONE BATCH
# ═══════════════════════════════════════════════════════════════════════

def process_batch(glb_path, pbr_folder, output_dir, batch_name, do_render=True):
    """
    Full pipeline for one batch:
      1. Clear scene
      2. Import GLB
      3. Normalize model scale (2m, on ground)
      4. Create PBR material from maps
      5. Apply to all mesh objects
      6. Create studio environment (ground + backdrop)
      7. Setup studio lighting (area softboxes) + camera
      8. Configure render settings
      9. Save .blend
      10. Render views
    """
    print(f"\n{'='*60}")
    print(f"BATCH: {batch_name}")
    print(f"  GLB:  {glb_path}")
    print(f"  PBR:  {pbr_folder}")
    print(f"  Out:  {output_dir}")
    print(f"{'='*60}")

    # 1. Clear
    clear_scene()

    # 2. Import model
    objects = import_glb(glb_path)
    if not objects:
        print("  ERROR: No mesh objects imported")
        return None

    # 3. Normalize model scale (2m longest dimension, sitting on ground)
    objects = normalize_model_scale(objects, target_size=2.0)

    # 4. Create PBR material
    material = create_pbr_material(f"Fabric_{batch_name}", pbr_folder)

    # 5. Apply to all meshes
    apply_material_to_objects(objects, material)

    # 6. Studio environment (ground plane + curved backdrop)
    create_studio_environment()

    # 7. Lighting + camera
    setup_lighting(objects)
    camera = setup_camera(objects)

    # 8. Render setup
    setup_render()

    # 9. Save .blend (so user can open and tweak)
    blend_path = save_blend(output_dir, batch_name)

    # 10. Render views
    rendered = []
    if do_render:
        rendered = render_views(camera, objects, output_dir, batch_name)

    return {
        'batch': batch_name,
        'blend': str(blend_path),
        'renders': rendered,
    }


# ═══════════════════════════════════════════════════════════════════════
#  CLI ARGUMENT PARSING
# ═══════════════════════════════════════════════════════════════════════

def parse_args():
    """Parse arguments after '--' separator in Blender command line."""
    argv = sys.argv
    if '--' in argv:
        argv = argv[argv.index('--') + 1:]
    else:
        # Running interactively — use defaults
        return {
            'glb': DEFAULT_GLB,
            'all': True,
            'pbr': None,
            'output': str(DEFAULT_OUTPUT),
            'batch': None,
            'no_render': False,
        }

    args = {
        'glb': DEFAULT_GLB,
        'all': False,
        'pbr': None,
        'output': str(DEFAULT_OUTPUT),
        'batch': None,
        'no_render': False,
    }

    i = 0
    while i < len(argv):
        if argv[i] == '--glb' and i + 1 < len(argv):
            args['glb'] = argv[i + 1]
            i += 2
        elif argv[i] == '--pbr' and i + 1 < len(argv):
            args['pbr'] = argv[i + 1]
            i += 2
        elif argv[i] == '--output' and i + 1 < len(argv):
            args['output'] = argv[i + 1]
            i += 2
        elif argv[i] == '--batch' and i + 1 < len(argv):
            args['batch'] = argv[i + 1]
            i += 2
        elif argv[i] == '--all':
            args['all'] = True
            i += 1
        elif argv[i] == '--no-render':
            args['no_render'] = True
            i += 1
        else:
            i += 1

    return args


# ═══════════════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════════════

def main():
    args = parse_args()

    glb_path = args['glb']
    output_base = Path(args['output'])
    do_render = not args['no_render']

    print("=" * 60)
    print("BLENDER PBR APPLICATOR")
    print(f"  GLB:    {glb_path}")
    print(f"  Output: {output_base}")
    print(f"  Render: {do_render}")
    print("=" * 60)

    if args['all']:
        # Process all batches
        results = []
        for batch_name in BATCHES:
            pbr_folder = DEFAULT_PBR_BASE / batch_name / PBR_SUBFOLDER
            if not pbr_folder.exists():
                print(f"\n  SKIP {batch_name}: {pbr_folder} not found")
                continue
            batch_output = output_base / batch_name
            result = process_batch(glb_path, pbr_folder, batch_output, batch_name, do_render)
            if result:
                results.append(result)

        # Summary
        print(f"\n{'='*60}")
        print("SUMMARY")
        print(f"{'='*60}")
        for r in results:
            print(f"  {r['batch']}:")
            print(f"    Blend: {r['blend']}")
            for rp in r['renders']:
                print(f"    Render: {rp}")

    elif args['pbr']:
        # Single batch with explicit PBR folder
        batch_name = args['batch'] or 'custom'
        result = process_batch(glb_path, args['pbr'], output_base / batch_name,
                               batch_name, do_render)
    else:
        print("ERROR: Specify --pbr <folder> or --all")
        return 1

    return 0


if __name__ == '__main__':
    main()
