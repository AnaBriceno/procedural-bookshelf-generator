import sys
import os
import time
import gc
import bpy

addon_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if addon_dir not in sys.path:
    sys.path.insert(0, addon_dir)

import procedural_bookshelf as pb

def measure_generation_baseline():
    print("=" * 60)
    print("MEASURING BASELINE METRICS IN BLENDER 5.1.2")
    print("=" * 60)

    # 1. Test clean factory scene regeneration
    bpy.ops.wm.read_factory_settings(use_empty=True)
    
    out_file = os.path.join(addon_dir, "scratch", "baseline_results.txt")
    with open(out_file, "w", encoding="utf-8") as f:
        f.write("Starting baseline measurement...\n")

    # Measure Generation Time
    t0 = time.perf_counter()

    pb.generate_bookshelf(
        2.40, 2.20, 0.36, 5, 0.002, 2, 0.75, 0.5, 0.2, 1234,
        back_style="SOLID", plinth_height=0.10, crown_height=0.08, stile_width=0.06,
        has_doors=True, door_shelves_covered=2, door_style="RAISED_PANEL",
        door_count=3, door_count_mode="MANUAL", door_thickness=0.018,
        door_gap=0.002, door_angle=0.0, has_handles=True,
        handle_style="KNOB", handle_material="BRASS",
        furniture_finish="OAK_NATURAL", prop_density=1.0
    )

    t1 = time.perf_counter()
    gen_time_sec = t1 - t0

    with open(out_file, "a", encoding="utf-8") as f:
        f.write(f"Generation 1 complete in {gen_time_sec:.3f}s\n")

    # Collect datablock counts after generation
    post_objs = len(bpy.data.objects)
    post_meshes = len(bpy.data.meshes)
    post_mats = len(bpy.data.materials)
    post_imgs = len(bpy.data.images)

    # Calculate total polygon count
    total_verts = sum(len(o.data.vertices) for o in bpy.data.objects if o.type == 'MESH')
    total_faces = sum(len(o.data.polygons) for o in bpy.data.objects if o.type == 'MESH')

    # Group objects by prefix/category
    pb_objs = [o for o in bpy.data.objects if o.name.startswith("PB_")]
    book_objs = [o for o in pb_objs if "Book" in o.name]
    prop_objs = [o for o in pb_objs if "Prop" in o.name]
    door_objs = [o for o in pb_objs if "Door" in o.name]
    handle_objs = [o for o in pb_objs if "Handle" in o.name]
    struct_objs = [o for o in pb_objs if not ("Book" in o.name or "Prop" in o.name or "Door" in o.name or "Handle" in o.name)]

    results_text = f"""============================================================
BASELINE METRICS IN BLENDER 5.1.2
============================================================
Generation Time:           {gen_time_sec:.3f} seconds
Total Object Count:        {post_objs}
  - Bookshelf Structure:   {len(struct_objs)}
  - Book Objects:          {len(book_objs)}
  - Decorative Props:      {len(prop_objs)}
  - Door Leaves:           {len(door_objs)}
  - Handles:               {len(handle_objs)}
Total Mesh Datablocks:     {post_meshes}
Total Material Datablocks: {post_mats}
Total Image Datablocks:    {post_imgs}
Total Vertices:            {total_verts:,}
Total Polygons/Faces:      {total_faces:,}

--- Regeneration Leak Audit (3 Consecutive Runs) ---
"""
    print(results_text, flush=True)

    reg_times = []
    for run_idx in range(1, 4):
        tr0 = time.perf_counter()
        pb.generate_bookshelf(
            2.40, 2.20, 0.36, 5, 0.002, 2, 0.75, 0.5, 0.2, 1234 + run_idx,
            back_style="SOLID", plinth_height=0.10, crown_height=0.08, stile_width=0.06,
            has_doors=True, door_shelves_covered=2, door_style="RAISED_PANEL",
            door_count=3, door_count_mode="MANUAL", door_thickness=0.018,
            door_gap=0.002, door_angle=0.0, has_handles=True,
            handle_style="KNOB", handle_material="BRASS",
            furniture_finish="WALNUT_DARK", prop_density=1.0
        )
        tr1 = time.perf_counter()
        reg_times.append(tr1 - tr0)
        line_str = f"  Run {run_idx}: Time={tr1-tr0:.3f}s | Objs={len(bpy.data.objects)} | Meshes={len(bpy.data.meshes)} | Mats={len(bpy.data.materials)} | Imgs={len(bpy.data.images)}\n"
        results_text += line_str
        print(line_str, flush=True)

    results_text += f"\nMean Regeneration Time: {sum(reg_times)/len(reg_times):.3f}s\n"
    results_text += "============================================================\n"

    out_file = os.path.join(addon_dir, "scratch", "baseline_results.txt")
    with open(out_file, "w", encoding="utf-8") as f:
        f.write(results_text)
    print(f"Wrote baseline metrics to {out_file}", flush=True)

if __name__ == "__main__":
    measure_generation_baseline()
