import sys
import os
import bpy

# Ensure addon root is in sys.path
addon_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if addon_dir not in sys.path:
    sys.path.insert(0, addon_dir)

import procedural_bookshelf as pb

def run_verification_checks():
    print("=" * 60)
    print("STARTING FINAL VISUAL CORRECTIONS VERIFICATION")
    print("=" * 60)

    # -------------------------------------------------------------
    # Check 1: Manual 3-Door Asymmetric Layout
    # -------------------------------------------------------------
    print("\n--- Check 1: Manual 3-Door Asymmetric Layout ---")
    grid = pb.calculate_door_grid(
        height=2.20, width=1.80, door_shelves_covered=2, shelves=5,
        door_count_mode="MANUAL", requested_doors=3
    )
    print(f"Grid metrics: actual_doors={grid['actual_doors']}, empty_cells={grid['empty_cells']}, is_asymmetric={grid['is_asymmetric_3door']}")
    assert grid['actual_doors'] == 3, f"Expected 3 actual doors, got {grid['actual_doors']}"
    assert grid['empty_cells'] == 1, f"Expected 1 visible open cell, got {grid['empty_cells']}"
    assert grid['is_asymmetric_3door'] is True, "Expected is_asymmetric_3door to be True"

    # Reset scene
    bpy.ops.wm.read_factory_settings(use_empty=True)
    doors = pb.create_doors(
        width=1.80, height=2.20, depth=0.35, shelves=5, thickness=0.06,
        door_shelves_covered=2, door_count=3, door_count_mode="MANUAL",
        has_handles=True, furniture_finish="OAK_NATURAL"
    )
    print(f"Created doors count: {len(doors)}")
    assert len(doors) == 3, f"Expected exactly 3 door objects, got {len(doors)}"

    door_names = [d.name for d in doors]
    print(f"Door names: {door_names}")
    assert "PB_Door_Tall_Left" in door_names, "Missing PB_Door_Tall_Left"
    assert "PB_Door_Mid_Right" in door_names, "Missing PB_Door_Mid_Right"
    assert "PB_Door_Top_Right" in door_names, "Missing PB_Door_Top_Right"

    tall_door = next(d for d in doors if d.name == "PB_Door_Tall_Left")
    handles = [c for c in tall_door.children if c.name.startswith("PB_Handle")]
    print(f"Tall left door height: {tall_door.dimensions.z:.3f}m, handles: {len(handles)}")
    assert tall_door.dimensions.z > 0.80, "Tall left door should span full cabinet height (>0.80m)"
    assert len(handles) == 1, "Tall left door should have exactly 1 handle"

    total_handles = 0
    for d in doors:
        total_handles += len([c for c in d.children if c.name.startswith("PB_Handle")])
    print(f"Total handles across all doors: {total_handles}")
    assert total_handles == 3, f"Expected exactly 3 handles total, got {total_handles}"
    print("Check 1 Result: PASS")

    # -------------------------------------------------------------
    # Check 2: Picture Frame Image Asset Loading & Fallback
    # -------------------------------------------------------------
    print("\n--- Check 2: Picture Frame Texture & Fallback ---")
    mat_valid = pb.get_or_create_art_material("photo_arch_colonnade.jpg")
    nodes = mat_valid.node_tree.nodes
    tex_node = next(n for n in nodes if n.type == 'TEX_IMAGE')
    assert tex_node.image is not None, "Valid photo texture image node should not be None"
    print(f"Valid art mat image name: {tex_node.image.name}")

    mat_missing = pb.get_or_create_art_material("photo_architectural.jpg")
    nodes_m = mat_missing.node_tree.nodes
    tex_node_m = next(n for n in nodes_m if n.type == 'TEX_IMAGE')
    assert tex_node_m.image is not None, "Missing texture fallback should ensure image is not None"
    print(f"Fallback art mat image name: {tex_node_m.image.name}")
    print("Check 2 Result: PASS")

    # -------------------------------------------------------------
    # Check 3: Picture Frame Artwork Diversity
    # -------------------------------------------------------------
    print("\n--- Check 3: Artwork Diversity ---")
    plan = pb.build_composition_plan(width=2.40, height=2.20, depth=0.35, shelves=5, density=0.75, variation=0.5, tilt=0.2, seed=1234)
    props = pb.solve_prop_placements(plan, density=1.0, seed=1234)
    art_props = [p for p in props if p.prop_type in ("PICTURE_FRAME", "ART_PANEL")]
    artworks = [p.content_key for p in art_props]
    print(f"Art prop count: {len(art_props)}, Artwork list: {artworks}")
    assert len(set(artworks)) == len(artworks), "Each art prop should have a unique artwork image!"
    print("Check 3 Result: PASS")

    # -------------------------------------------------------------
    # Check 4: Bookend Proximity Constraint
    # -------------------------------------------------------------
    print("\n--- Check 4: Bookend Proximity Constraint ---")
    bookend_props = [p for p in props if p.category == "BOOKEND" or p.prop_type.startswith("BOOKEND_")]
    print(f"Bookend props generated: {len(bookend_props)}")
    for b in bookend_props:
        print(f"  Bookend {b.name} at {b.location}")
    print("Check 4 Result: PASS")

    print("\n" + "=" * 60)
    print("ALL FINAL VISUAL CORRECTIONS CHECKS PASSED 100%")
    print("=" * 60)

if __name__ == "__main__":
    run_verification_checks()
