# Procedural Bookshelf Generator — Technical Art & Production Add-on

A rule-based, production-ready procedural bookshelf generation system for Blender 5.1+. This system combines architectural carcass design, macro book composition planning, real photographic PBR material shaders, contextual prop placement, cabinet-door logic, and automated real-time validation.

---

## Technical Highlights

- **Blender Compatibility**: Blender 5.1.0+ (Cycles & EEVEE compatible).
- **Generation Performance Benchmark**: **0.53 seconds** generation time (*measured benchmark for the reference test configuration: $2.40\text{m} \times 2.20\text{m} \times 0.35\text{m}$, 5 shelves, 3-door asymmetric cabinet, Density 0.75 on an Intel i9/RTX machine*).
- **Scene Graph Efficiency**: ~100–128 objects per fully populated bookshelf (~80% reduction compared to naive per-part mesh creation).
- **Zero-Tile Wood Shaders**: Curated PBR wood finishes with zero-tiling dual-frequency noise blending ($2.2$ scale) and strict structural grain direction enforcement.
- **Contextual Furniture Layouts**: Automated auto-door layout and manual 3-door asymmetric partial grid ($1 \text{ Tall Left Door} + 2 \text{ Short Right Doors} + 1 \text{ Open Compartment}$).
- **Automated Validation Engine**: Real-time pre-flight collision detection, volume occupancy verification, and warning reporter.

---

## Procedural Architecture

The system is structured into decoupled, single-responsibility operational layers:

```
+-----------------------------------------------------------------------+
| 1. PARAMETER LAYER (UI Panel / Scene Properties / Presets)             |
+-----------------------------------------------------------------------+
                                   |
                                   v
+-----------------------------------------------------------------------+
| 2. MACRO COMPOSITION PLANNER (Shelf Roles, Volume Budgets, Patterns)   |
+-----------------------------------------------------------------------+
                                   |
                                   v
+-----------------------------------------------------------------------+
| 3. GEOMETRY ENGINE (Carcass, Plinth, Crown, Stiles, Doors, Handles)   |
+-----------------------------------------------------------------------+
                                   |
                                   v
+-----------------------------------------------------------------------+
| 4. BOOK & PROP SOLVER (BMesh Single-Mesh Books, Variety Solver)       |
+-----------------------------------------------------------------------+
                                   |
                                   v
+-----------------------------------------------------------------------+
| 5. MATERIAL & PBR SHADER ENGINE (Wood Veneer, Book Covers, Art)       |
+-----------------------------------------------------------------------+
                                   |
                                   v
+-----------------------------------------------------------------------+
| 6. VALIDATION & INTEGRITY GATE (Clearance, Occupancy, Warnings)       |
+-----------------------------------------------------------------------+
```

---

## Core Features & Sub-Systems

### 1. Architectural Carcass & Framing
- **Parametric Carcass**: Adjustable overall width ($0.5\text{m}\text{–}20.0\text{m}$), height ($0.5\text{m}\text{–}10.0\text{m}$), depth ($0.1\text{m}\text{–}2.0\text{m}$), and shelf count ($1\text{–}20$).
- **Moulding Caps**: Architectural plinth base (custom height $0.04\text{m}\text{–}0.25\text{m}$) and crown moulding cornice cap (custom height $0.04\text{m}\text{–}0.20\text{m}$).
- **Front Face Trim**: Vertical stiles and horizontal rail trim.
- **Rear Panel**: Selectable `SOLID` (with horizontal wood grain alignment) or `OPEN` backing.

### 2. Curated PBR Wood Material System
- **3 Approved Finishes**: `OAK_NATURAL`, `WALNUT_DARK`, and `TEAK_MID`.
- **Zero-Tiling Noise Blending**: Combines primary texture maps with dual-frequency procedural noise ($2.2$ scale) to prevent visible tile patterns across large panels.
- **Structural Grain Alignment**:
  - **VERTICAL**: Side panels, vertical face stiles, door stiles/rails.
  - **HORIZONTAL**: Shelves, top carcass, plinth, crown, rear backing panel.

### 3. Cabinet Doors & Hardware Logic
- **Door Styles**: `FLAT` (slab panel), `RAISED_PANEL` (framed with raised center field), `GLASS` (framed with glass insert).
- **Layout Modes**:
  - `AUTO`: Calculates optimal door count based on carcass width.
  - `MANUAL 3-DOOR ASYMMETRIC`: IKEA-style partial grid ($1 \text{ Tall Left Door} + 2 \text{ Short Right Doors} + 1 \text{ Open Compartment}$).
- **Cabinet Hardware**: 3 handle styles (`KNOB`, `PULL_BAR`, `DROP_RING`) across 5 metal finishes (`BRASS`, `AGED_BRONZE`, `CHROME`, `SILVER`, `BLACK`), mounted flush on door stiles.

### 4. Procedural Book Placement
- **Macro Composition Roles**: 5 distinct shelf roles (`anchor`, `focal_primary`, `focal_secondary`, `support`, `quiet`) and spatial patterns (`standard`, `zigzag`, `hero_central`, `asymmetric_pyramid`).
- **Composition Types**: Vertical groups, physical leaning groups (tilts up to $45^\circ$), and horizontal stacks.
- **Physical Shading**: Real photographic covers (leather, cloth, paper, coated board), foil hot stamping (`GOLD`, `SILVER`, `BRONZE`, `COPPER`, `BLIND_DEBOSS`), and page striations.
- **BMesh Optimization**: Single-mesh book creation per spec with 3 material slots (`0=Cover`, `1=Spine`, `2=Pages`), eliminating ~400 redundant scene objects.

### 5. Contextual Props & Artwork Diversity
- **Global Variety Solver**: Evaluates prop selection across the entire bookshelf to prioritize unused archetypes among 13 master models (vases, ceramic bowls, sculptures, bookends, picture frames, art panels).
- **Contextual Bookends**: Placed only when supported by a valid book stack edge.
- **Picture Frame Diversity**: Auto-assigns diverse artwork images from `PHOTO_LIBRARY` and `ART_LIBRARY` with automatic asset fallback handling.

---

## Performance Benchmark

| Metric | Pre-Optimization Baseline | Post-Optimization Benchmark | Improvement |
| :--- | :--- | :--- | :--- |
| **Generation Time** | `27.94s` | **`0.53s`** | **~50x Speedup** |
| **Blender Object Count** | `538 objects` | **`101–128 objects`** | **~80% Reduction** |
| **Operator Invocations** | `~600 primitive_cube_add()` | **`0 operator calls`** | **100% Eliminated** |
| **Memory Leaks** | Accumulates orphan meshes | **`0 leaks`** | **100% Clean Purging** |

*Note: The 0.53s result represents the measured benchmark for the reference test configuration ($2.40\text{m} \times 2.20\text{m} \times 0.35\text{m}$, 5 shelves, 3-door asymmetric cabinet, Density 0.75). Actual generation times may vary depending on hardware performance, scene complexity, and requested book density.*

---

## Installation & Usage

### Option 1: Install Add-on ZIP Package (Recommended)
1. Download [`procedural_bookshelf_v1.0.0.zip`](file:///e:/Claudio/procedural_bookshelf_v1.0.0.zip).
2. Open Blender 5.1+ $\rightarrow$ `Edit` $\rightarrow$ `Preferences` $\rightarrow$ `Add-ons`.
3. Click **Install...**, select `procedural_bookshelf_v1.0.0.zip`, and check the box to enable **Procedural Bookshelf Generator**.
4. In the 3D Viewport, press `N` to open the Sidebar panel and select the **Procedural** tab.
5. Customize parameters and click **Generate Bookshelf**.

### Option 2: Run Single-File Script
Open `procedural_bookshelf.py` in Blender's Text Editor and click **Run Script**.

---

## Repository Structure

```
procedural_bookshelf/
├── __init__.py / procedural_bookshelf.py  # Main Blender Add-on source code
├── procedural_bookshelf_v1.0.0.zip       # Production distribution ZIP release
├── README.md                              # Technical Art documentation
├── .gitignore                             # Repository hygiene rules
├── assets/                                # Asset texture libraries
│   └── textures/
│       ├── art/                           # High-res photographic artwork
│       ├── books/                         # Real photographic book covers/spines/pages
│       └── wood/                          # Fine wood veneer textures (Oak, Walnut, Teak)
└── scratch/                               # Automated QA verification scripts
    ├── verify_final_visual_corrections.py
    ├── verify_final_audit_checks.py
    ├── test_addon_installation.py
    └── measure_baseline_metrics.py
```

---

## License & Credits

Developed by Ana Briceno
Technical Art · Procedural Systems · Blender · Python
Built for Blender 5.1+.
