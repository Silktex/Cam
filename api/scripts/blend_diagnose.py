"""Diagnose a .blend file: check images, materials, and node connections."""
import bpy
import sys

print("\n" + "=" * 60)
print("BLEND FILE DIAGNOSTIC")
print("=" * 60)

# List all images
print(f"\n--- IMAGES ({len(bpy.data.images)}) ---")
for img in bpy.data.images:
    packed = "PACKED" if img.packed_file else "EXTERNAL"
    print(f"  {img.name}: {img.size[0]}x{img.size[1]} {img.colorspace_settings.name} [{packed}]")
    if not img.packed_file:
        print(f"    filepath: {img.filepath}")
        print(f"    filepath_raw: {img.filepath_raw}")

# List all materials and their nodes
print(f"\n--- MATERIALS ({len(bpy.data.materials)}) ---")
for mat in bpy.data.materials:
    print(f"\n  Material: {mat.name}")
    if mat.node_tree:
        for node in mat.node_tree.nodes:
            print(f"    Node: {node.type} ({node.name})")
            if node.type == 'TEX_IMAGE':
                if node.image:
                    packed = "PACKED" if node.image.packed_file else "EXTERNAL"
                    print(f"      Image: {node.image.name} {node.image.size[0]}x{node.image.size[1]} [{packed}]")
                else:
                    print(f"      Image: NONE (missing!)")
            if node.type == 'BSDF_PRINCIPLED':
                for inp in node.inputs:
                    if inp.is_linked:
                        print(f"      {inp.name}: LINKED")
                    elif hasattr(inp, 'default_value'):
                        try:
                            print(f"      {inp.name}: {inp.default_value}")
                        except:
                            pass

# List mesh objects and their materials
print(f"\n--- MESH OBJECTS ---")
for obj in bpy.data.objects:
    if obj.type == 'MESH':
        mats = [slot.material.name if slot.material else "NONE" for slot in obj.material_slots]
        print(f"  {obj.name}: materials={mats}")

print("\n" + "=" * 60)
