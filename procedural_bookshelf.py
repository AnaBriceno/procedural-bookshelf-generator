bl_info = {
    "name": "Procedural Bookshelf Generator",
    "author": "Antigravity Technical Art",
    "version": (1, 0, 0),
    "blender": (5, 1, 0),
    "location": "View3D > Sidebar > Procedural",
    "description": "Production-ready procedural bookshelf generator with physical books, fine wood veneer materials, and decorative props.",
    "category": "3D View",
}

import bpy
import bmesh
import mathutils
import os
import random
import math
import zlib
from dataclasses import dataclass, field
from typing import List, Optional, Tuple


# Ángulo máximo de inclinación física, alcanzado solo cuando
# Tilt = 1.0. 45° da un libro claramente recostado contra su
# vecino sin llegar a quedar horizontal (eso es un
# orientation="horizontal" real, generado por los stacks, no
# una inclinación extrema de este ángulo).

MAX_TILT_ANGLE = math.radians(45)


# Longitud propia de un libro acostado (independiente del
# ancho de la zona que lo contiene) — ver generate_horizontal_
# stack_books. Sin este tope, un stack en una zona ancha podía
# producir libros que parecían tablas en vez de libros.

HORIZONTAL_BOOK_MIN_LENGTH = 0.25
HORIZONTAL_BOOK_MAX_LENGTH = 0.55


# =========================================================
# MATERIALES DE LIBROS (Fase 9)
# =========================================================
#
# Un puñado de colores fijos, reutilizados entre TODOS los
# libros — no un material nuevo por libro. Con cientos de
# libros, crear un material único por cada uno sería justo lo
# que se pidió evitar ("no crear cientos de materiales únicos
# innecesariamente"). Cada libro solo elige un ÍNDICE dentro
# de estas paletas, de forma determinista según su nombre.

# ==============================================================================
# CURATED COLOR PALETTE (DECOUPLED FROM PHYSICAL SHADERS)
# ==============================================================================

BOOK_PALETTE = {
    # Primary Hero Tones (Deep, saturated editorial albedos to prevent overexposure wash and hold strong catalog presence)
    "BURGUNDY":     (0.090, 0.003, 0.006, 1.0),  # Deep Antique Wine / Rich Crimson Oxblood
    "NAVY":          (0.003, 0.010, 0.080, 1.0),  # Prussian Midnight Navy / Royal Depth
    "CHARCOAL":      (0.015, 0.015, 0.017, 1.0),  # Dark Graphite / Obsidian
    "FOREST_GREEN":  (0.004, 0.055, 0.012, 1.0),  # Deep Hunter / British Racing Green
    "COGNAC":        (0.110, 0.038, 0.005, 1.0),  # Antique Saddle Leather / Warm Amber Cognac

    # Secondary Atmospheric Tones (Refined for luxury editorial book design)
    "MUTED_CREAM":   (0.240, 0.205, 0.150, 1.0),  # Archival Warm French Parchment
    "SAGE_GREEN":    (0.024, 0.070, 0.038, 1.0),  # Muted Herbal Bookcloth Sage
    "DUSTY_OCHRE":   (0.110, 0.040, 0.010, 1.0),  # Burnt Terracotta / Earth Ochre
    "SLATE_BLUE":    (0.015, 0.035, 0.080, 1.0),  # Weathered Nordic Slate Blue
    "DUSTY_PLUM":    (0.075, 0.010, 0.045, 1.0),  # Deep Heather Plum / Rich Aubergine
}

FOIL_PALETTE = {
    "GOLD":          (0.960, 0.800, 0.320, 1.0),
    "SILVER":        (0.920, 0.940, 0.980, 1.0),
    "BRONZE":        (0.850, 0.580, 0.320, 1.0),
    "COPPER":        (0.950, 0.540, 0.380, 1.0),
    "BLIND_DEBOSS":  (0.020, 0.015, 0.010, 1.0),
}

PAGE_PALETTE = {
    "WARM_CREAM":     (0.94, 0.90, 0.82, 1.0),
    "AGED_PARCHMENT": (0.88, 0.82, 0.70, 1.0),
    "SOFT_IVORY":     (0.95, 0.93, 0.88, 1.0),
}


# ==============================================================================
# REAL PHOTOGRAPHIC BOOK MATERIALS (APPROVED SHADER SYSTEM)
# ==============================================================================

def _get_addon_dir():
    """Dynamically resolves the root directory of the installed Add-on package or script."""
    if "__file__" in globals() and __file__:
        addon_dir = os.path.dirname(os.path.abspath(__file__))
        if os.path.exists(os.path.join(addon_dir, "assets")):
            return addon_dir
    cwd = os.getcwd()
    if os.path.exists(os.path.join(cwd, "assets")):
        return cwd
    return os.getcwd()

_WORKSPACE_DIR = _get_addon_dir()
TEXTURES_DIR = os.path.join(_WORKSPACE_DIR, "assets", "textures", "books")

def _get_book_texture_image(filename):
    """Loads a real photographic image texture or retrieves it if already loaded in bpy.data.images."""
    img = bpy.data.images.get(filename)
    if img is None:
        path = os.path.join(TEXTURES_DIR, filename)
        if not os.path.exists(path):
            raise FileNotFoundError(f"Real book texture file not found: {path}")
        img = bpy.data.images.load(path, check_existing=True)
    return img


# ==============================================================================
# REUSABLE SHADER NODE GROUPS (THE 6 SHARED PHYSICAL MATERIAL FAMILIES)
# ==============================================================================

def get_or_create_leather_node_group(name="PB_NodeGroup_DyedLeather"):
    """
    Physical Node Group: Real Leather
    Driven by real photographic calfskin scan with restrained pore breakup and dual-sheen luster.
    """
    if name in bpy.data.node_groups:
        return bpy.data.node_groups[name]

    ng = bpy.data.node_groups.new(name, type='ShaderNodeTree')
    nodes = ng.nodes
    links = ng.links

    ng.interface.new_socket(name="Cover Texture", in_out='INPUT', socket_type='NodeSocketColor')
    ng.interface.new_socket(name="Tex Luminance", in_out='INPUT', socket_type='NodeSocketFloat')
    ng.interface.new_socket(name="Roughness Min", in_out='INPUT', socket_type='NodeSocketFloat')
    ng.interface.items_tree["Roughness Min"].default_value = 0.34
    ng.interface.new_socket(name="Roughness Max", in_out='INPUT', socket_type='NodeSocketFloat')
    ng.interface.items_tree["Roughness Max"].default_value = 0.44
    ng.interface.new_socket(name="From Min", in_out='INPUT', socket_type='NodeSocketFloat')
    ng.interface.items_tree["From Min"].default_value = 0.0
    ng.interface.new_socket(name="From Max", in_out='INPUT', socket_type='NodeSocketFloat')
    ng.interface.items_tree["From Max"].default_value = 1.0
    ng.interface.new_socket(name="Specular Level", in_out='INPUT', socket_type='NodeSocketFloat')
    ng.interface.items_tree["Specular Level"].default_value = 0.35
    ng.interface.new_socket(name="Bump Distance", in_out='INPUT', socket_type='NodeSocketFloat')
    ng.interface.items_tree["Bump Distance"].default_value = 0.000055
    ng.interface.new_socket(name="Bump Strength", in_out='INPUT', socket_type='NodeSocketFloat')
    ng.interface.items_tree["Bump Strength"].default_value = 0.44

    ng.interface.new_socket(name="BSDF", in_out='OUTPUT', socket_type='NodeSocketShader')
    ng.interface.new_socket(name="Out Color", in_out='OUTPUT', socket_type='NodeSocketColor')
    ng.interface.new_socket(name="Out Roughness", in_out='OUTPUT', socket_type='NodeSocketFloat')
    ng.interface.new_socket(name="Out Normal", in_out='OUTPUT', socket_type='NodeSocketVector')

    group_in = nodes.new("NodeGroupInput"); group_in.location = (-600, 0)
    group_out = nodes.new("NodeGroupOutput"); group_out.location = (600, 0)
    bsdf = nodes.new("ShaderNodeBsdfPrincipled"); bsdf.location = (200, 0)
    links.new(bsdf.outputs["BSDF"], group_out.inputs["BSDF"])

    links.new(group_in.outputs["Cover Texture"], bsdf.inputs["Base Color"])
    links.new(group_in.outputs["Cover Texture"], group_out.inputs["Out Color"])

    # Waxy satin roughness driven by hide scan luminance
    map_r = nodes.new("ShaderNodeMapRange"); map_r.location = (-200, -100)
    links.new(group_in.outputs["Tex Luminance"], map_r.inputs["Value"])
    links.new(group_in.outputs["From Min"], map_r.inputs["From Min"])
    links.new(group_in.outputs["From Max"], map_r.inputs["From Max"])
    links.new(group_in.outputs["Roughness Min"], map_r.inputs["To Min"])
    links.new(group_in.outputs["Roughness Max"], map_r.inputs["To Max"])
    links.new(map_r.outputs["Result"], bsdf.inputs["Roughness"])
    links.new(map_r.outputs["Result"], group_out.inputs["Out Roughness"])

    if "Specular IOR Level" in bsdf.inputs:
        links.new(group_in.outputs["Specular Level"], bsdf.inputs["Specular IOR Level"])

    # Organic hide relief bump
    bump = nodes.new("ShaderNodeBump"); bump.location = (-100, -300)
    links.new(group_in.outputs["Bump Strength"], bump.inputs["Strength"])
    links.new(group_in.outputs["Bump Distance"], bump.inputs["Distance"])
    links.new(group_in.outputs["Tex Luminance"], bump.inputs["Height"])
    links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    links.new(bump.outputs["Normal"], group_out.inputs["Out Normal"])

    if "Subsurface Weight" in bsdf.inputs:
        bsdf.inputs["Subsurface Weight"].default_value = 0.0

    return ng


def get_or_create_bookcloth_node_group(name="PB_NodeGroup_Bookcloth"):
    """
    Physical Node Group: Real Bookcloth
    Driven by real photographic woven textile scan.
    """
    if name in bpy.data.node_groups:
        return bpy.data.node_groups[name]

    ng = bpy.data.node_groups.new(name, type='ShaderNodeTree')
    nodes = ng.nodes
    links = ng.links

    ng.interface.new_socket(name="Cover Texture", in_out='INPUT', socket_type='NodeSocketColor')
    ng.interface.new_socket(name="Tex Luminance", in_out='INPUT', socket_type='NodeSocketFloat')
    ng.interface.new_socket(name="Roughness", in_out='INPUT', socket_type='NodeSocketFloat')
    ng.interface.items_tree["Roughness"].default_value = 0.78
    ng.interface.new_socket(name="Specular Level", in_out='INPUT', socket_type='NodeSocketFloat')
    ng.interface.items_tree["Specular Level"].default_value = 0.08
    ng.interface.new_socket(name="Sheen Weight", in_out='INPUT', socket_type='NodeSocketFloat')
    ng.interface.items_tree["Sheen Weight"].default_value = 0.38
    ng.interface.new_socket(name="Bump Distance", in_out='INPUT', socket_type='NodeSocketFloat')
    ng.interface.items_tree["Bump Distance"].default_value = 0.000045
    ng.interface.new_socket(name="Bump Strength", in_out='INPUT', socket_type='NodeSocketFloat')
    ng.interface.items_tree["Bump Strength"].default_value = 0.50

    ng.interface.new_socket(name="BSDF", in_out='OUTPUT', socket_type='NodeSocketShader')
    ng.interface.new_socket(name="Out Color", in_out='OUTPUT', socket_type='NodeSocketColor')
    ng.interface.new_socket(name="Out Roughness", in_out='OUTPUT', socket_type='NodeSocketFloat')
    ng.interface.new_socket(name="Out Normal", in_out='OUTPUT', socket_type='NodeSocketVector')

    group_in = nodes.new("NodeGroupInput"); group_in.location = (-600, 0)
    group_out = nodes.new("NodeGroupOutput"); group_out.location = (600, 0)
    bsdf = nodes.new("ShaderNodeBsdfPrincipled"); bsdf.location = (200, 0)
    links.new(bsdf.outputs["BSDF"], group_out.inputs["BSDF"])

    links.new(group_in.outputs["Cover Texture"], bsdf.inputs["Base Color"])
    links.new(group_in.outputs["Cover Texture"], group_out.inputs["Out Color"])

    # High textile diffuse roughness
    links.new(group_in.outputs["Roughness"], bsdf.inputs["Roughness"])
    links.new(group_in.outputs["Roughness"], group_out.inputs["Out Roughness"])

    if "Specular IOR Level" in bsdf.inputs:
        links.new(group_in.outputs["Specular Level"], bsdf.inputs["Specular IOR Level"])

    # Sheen for grazing textile highlight
    if "Sheen Weight" in bsdf.inputs:
        links.new(group_in.outputs["Sheen Weight"], bsdf.inputs["Sheen Weight"])
    if "Sheen Tint" in bsdf.inputs:
        links.new(group_in.outputs["Cover Texture"], bsdf.inputs["Sheen Tint"])

    # Woven thread relief bump from real scan
    bump = nodes.new("ShaderNodeBump"); bump.location = (-100, -300)
    links.new(group_in.outputs["Bump Strength"], bump.inputs["Strength"])
    links.new(group_in.outputs["Bump Distance"], bump.inputs["Distance"])
    links.new(group_in.outputs["Tex Luminance"], bump.inputs["Height"])
    links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    links.new(bump.outputs["Normal"], group_out.inputs["Out Normal"])

    return ng


def get_or_create_matte_paper_node_group(name="PB_NodeGroup_MattePaper"):
    """
    Physical Node Group: Real Matte Paper
    Driven by real photographic paper pulp scan.
    """
    if name in bpy.data.node_groups:
        return bpy.data.node_groups[name]

    ng = bpy.data.node_groups.new(name, type='ShaderNodeTree')
    nodes = ng.nodes
    links = ng.links

    ng.interface.new_socket(name="Cover Texture", in_out='INPUT', socket_type='NodeSocketColor')
    ng.interface.new_socket(name="Tex Luminance", in_out='INPUT', socket_type='NodeSocketFloat')
    ng.interface.new_socket(name="Roughness Min", in_out='INPUT', socket_type='NodeSocketFloat')
    ng.interface.items_tree["Roughness Min"].default_value = 0.74
    ng.interface.new_socket(name="Roughness Max", in_out='INPUT', socket_type='NodeSocketFloat')
    ng.interface.items_tree["Roughness Max"].default_value = 0.94
    ng.interface.new_socket(name="From Min", in_out='INPUT', socket_type='NodeSocketFloat')
    ng.interface.items_tree["From Min"].default_value = 0.58
    ng.interface.new_socket(name="From Max", in_out='INPUT', socket_type='NodeSocketFloat')
    ng.interface.items_tree["From Max"].default_value = 0.88
    ng.interface.new_socket(name="Specular Level", in_out='INPUT', socket_type='NodeSocketFloat')
    ng.interface.items_tree["Specular Level"].default_value = 0.07
    ng.interface.new_socket(name="Bump Distance", in_out='INPUT', socket_type='NodeSocketFloat')
    ng.interface.items_tree["Bump Distance"].default_value = 0.000065
    ng.interface.new_socket(name="Bump Strength", in_out='INPUT', socket_type='NodeSocketFloat')
    ng.interface.items_tree["Bump Strength"].default_value = 0.70

    ng.interface.new_socket(name="BSDF", in_out='OUTPUT', socket_type='NodeSocketShader')
    ng.interface.new_socket(name="Out Color", in_out='OUTPUT', socket_type='NodeSocketColor')
    ng.interface.new_socket(name="Out Roughness", in_out='OUTPUT', socket_type='NodeSocketFloat')
    ng.interface.new_socket(name="Out Normal", in_out='OUTPUT', socket_type='NodeSocketVector')

    group_in = nodes.new("NodeGroupInput"); group_in.location = (-600, 0)
    group_out = nodes.new("NodeGroupOutput"); group_out.location = (600, 0)
    bsdf = nodes.new("ShaderNodeBsdfPrincipled"); bsdf.location = (200, 0)
    links.new(bsdf.outputs["BSDF"], group_out.inputs["BSDF"])

    links.new(group_in.outputs["Cover Texture"], bsdf.inputs["Base Color"])
    links.new(group_in.outputs["Cover Texture"], group_out.inputs["Out Color"])

    # Tactile paper roughness variation driven by real paper fibers
    map_r = nodes.new("ShaderNodeMapRange"); map_r.location = (-200, -100)
    links.new(group_in.outputs["Tex Luminance"], map_r.inputs["Value"])
    links.new(group_in.outputs["From Min"], map_r.inputs["From Min"])
    links.new(group_in.outputs["From Max"], map_r.inputs["From Max"])
    links.new(group_in.outputs["Roughness Min"], map_r.inputs["To Min"])
    links.new(group_in.outputs["Roughness Max"], map_r.inputs["To Max"])
    links.new(map_r.outputs["Result"], bsdf.inputs["Roughness"])
    links.new(map_r.outputs["Result"], group_out.inputs["Out Roughness"])

    if "Specular IOR Level" in bsdf.inputs:
        links.new(group_in.outputs["Specular Level"], bsdf.inputs["Specular IOR Level"])

    # Paper pulp tooth bump
    bump = nodes.new("ShaderNodeBump"); bump.location = (-100, -300)
    links.new(group_in.outputs["Bump Strength"], bump.inputs["Strength"])
    links.new(group_in.outputs["Bump Distance"], bump.inputs["Distance"])
    links.new(group_in.outputs["Tex Luminance"], bump.inputs["Height"])
    links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    links.new(bump.outputs["Normal"], group_out.inputs["Out Normal"])

    return ng


def get_or_create_coated_board_node_group(name="PB_NodeGroup_CoatedBoard"):
    """
    Physical Node Group: Printed / Coated Paperboard (Matte/Satin Bookboard)
    Driven by real photographic binder's board / paperboard substrate scan.
    """
    if name in bpy.data.node_groups:
        return bpy.data.node_groups[name]

    ng = bpy.data.node_groups.new(name, type='ShaderNodeTree')
    nodes = ng.nodes
    links = ng.links

    ng.interface.new_socket(name="Cover Texture", in_out='INPUT', socket_type='NodeSocketColor')
    ng.interface.new_socket(name="Tex Luminance", in_out='INPUT', socket_type='NodeSocketFloat')
    ng.interface.new_socket(name="Roughness Min", in_out='INPUT', socket_type='NodeSocketFloat')
    ng.interface.items_tree["Roughness Min"].default_value = 0.62
    ng.interface.new_socket(name="Roughness Max", in_out='INPUT', socket_type='NodeSocketFloat')
    ng.interface.items_tree["Roughness Max"].default_value = 0.78
    ng.interface.new_socket(name="From Min", in_out='INPUT', socket_type='NodeSocketFloat')
    ng.interface.items_tree["From Min"].default_value = 0.18
    ng.interface.new_socket(name="From Max", in_out='INPUT', socket_type='NodeSocketFloat')
    ng.interface.items_tree["From Max"].default_value = 0.38
    ng.interface.new_socket(name="Specular Level", in_out='INPUT', socket_type='NodeSocketFloat')
    ng.interface.items_tree["Specular Level"].default_value = 0.12
    ng.interface.new_socket(name="Bump Distance", in_out='INPUT', socket_type='NodeSocketFloat')
    ng.interface.items_tree["Bump Distance"].default_value = 0.000045
    ng.interface.new_socket(name="Bump Strength", in_out='INPUT', socket_type='NodeSocketFloat')
    ng.interface.items_tree["Bump Strength"].default_value = 0.55

    ng.interface.new_socket(name="BSDF", in_out='OUTPUT', socket_type='NodeSocketShader')
    ng.interface.new_socket(name="Out Color", in_out='OUTPUT', socket_type='NodeSocketColor')
    ng.interface.new_socket(name="Out Roughness", in_out='OUTPUT', socket_type='NodeSocketFloat')
    ng.interface.new_socket(name="Out Normal", in_out='OUTPUT', socket_type='NodeSocketVector')

    group_in = nodes.new("NodeGroupInput"); group_in.location = (-600, 0)
    group_out = nodes.new("NodeGroupOutput"); group_out.location = (600, 0)
    bsdf = nodes.new("ShaderNodeBsdfPrincipled"); bsdf.location = (200, 0)
    links.new(bsdf.outputs["BSDF"], group_out.inputs["BSDF"])

    links.new(group_in.outputs["Cover Texture"], bsdf.inputs["Base Color"])
    links.new(group_in.outputs["Cover Texture"], group_out.inputs["Out Color"])

    # Matte / Satin paperboard roughness
    map_r = nodes.new("ShaderNodeMapRange"); map_r.location = (-200, -100)
    links.new(group_in.outputs["Tex Luminance"], map_r.inputs["Value"])
    links.new(group_in.outputs["From Min"], map_r.inputs["From Min"])
    links.new(group_in.outputs["From Max"], map_r.inputs["From Max"])
    links.new(group_in.outputs["Roughness Min"], map_r.inputs["To Min"])
    links.new(group_in.outputs["Roughness Max"], map_r.inputs["To Max"])
    links.new(map_r.outputs["Result"], bsdf.inputs["Roughness"])
    links.new(map_r.outputs["Result"], group_out.inputs["Out Roughness"])

    if "Specular IOR Level" in bsdf.inputs:
        links.new(group_in.outputs["Specular Level"], bsdf.inputs["Specular IOR Level"])

    # Restrained paperboard substrate bump
    bump = nodes.new("ShaderNodeBump"); bump.location = (-100, -300)
    links.new(group_in.outputs["Bump Strength"], bump.inputs["Strength"])
    links.new(group_in.outputs["Bump Distance"], bump.inputs["Distance"])
    links.new(group_in.outputs["Tex Luminance"], bump.inputs["Height"])
    links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    links.new(bump.outputs["Normal"], group_out.inputs["Out Normal"])

    return ng


def get_or_create_foil_node_group(name="PB_NodeGroup_Foil"):
    """
    Physical Node Group: Foil (Hot-Stamping)
    High metallic reflectivity with beveled die stamping impression.
    """
    if name in bpy.data.node_groups:
        return bpy.data.node_groups[name]

    ng = bpy.data.node_groups.new(name, type='ShaderNodeTree')
    nodes = ng.nodes
    links = ng.links

    ng.interface.new_socket(name="Foil Color", in_out='INPUT', socket_type='NodeSocketColor')
    ng.interface.items_tree["Foil Color"].default_value = (0.96, 0.80, 0.32, 1.0)
    ng.interface.new_socket(name="Roughness", in_out='INPUT', socket_type='NodeSocketFloat')
    ng.interface.items_tree["Roughness"].default_value = 0.12

    ng.interface.new_socket(name="BSDF", in_out='OUTPUT', socket_type='NodeSocketShader')

    group_in = nodes.new("NodeGroupInput"); group_in.location = (-400, 0)
    group_out = nodes.new("NodeGroupOutput"); group_out.location = (400, 0)
    bsdf = nodes.new("ShaderNodeBsdfPrincipled"); bsdf.location = (0, 0)
    links.new(bsdf.outputs["BSDF"], group_out.inputs["BSDF"])

    links.new(group_in.outputs["Foil Color"], bsdf.inputs["Base Color"])
    if "Metallic" in bsdf.inputs:
        bsdf.inputs["Metallic"].default_value = 0.98
    if "Roughness" in bsdf.inputs:
        links.new(group_in.outputs["Roughness"], bsdf.inputs["Roughness"])
    if "Specular IOR Level" in bsdf.inputs:
        bsdf.inputs["Specular IOR Level"].default_value = 0.65

    return ng


def get_or_create_page_block_node_group(name="PB_NodeGroup_PageBlock"):
    """
    Physical Node Group: Page Block
    Driven by real photographic page block scan with realistic edge tooth.
    """
    if name in bpy.data.node_groups:
        return bpy.data.node_groups[name]

    ng = bpy.data.node_groups.new(name, type='ShaderNodeTree')
    nodes = ng.nodes
    links = ng.links

    ng.interface.new_socket(name="Page Texture", in_out='INPUT', socket_type='NodeSocketColor')
    ng.interface.new_socket(name="Tex Luminance", in_out='INPUT', socket_type='NodeSocketFloat')
    ng.interface.new_socket(name="BSDF", in_out='OUTPUT', socket_type='NodeSocketShader')

    group_in = nodes.new("NodeGroupInput"); group_in.location = (-600, 0)
    group_out = nodes.new("NodeGroupOutput"); group_out.location = (600, 0)
    bsdf = nodes.new("ShaderNodeBsdfPrincipled"); bsdf.location = (200, 0)
    links.new(bsdf.outputs["BSDF"], group_out.inputs["BSDF"])

    links.new(group_in.outputs["Page Texture"], bsdf.inputs["Base Color"])

    if "Roughness" in bsdf.inputs:
        bsdf.inputs["Roughness"].default_value = 0.82
    if "Specular IOR Level" in bsdf.inputs:
        bsdf.inputs["Specular IOR Level"].default_value = 0.12

    bump = nodes.new("ShaderNodeBump"); bump.location = (-100, -300)
    bump.inputs["Strength"].default_value = 0.65
    bump.inputs["Distance"].default_value = 0.000080
    links.new(group_in.outputs["Tex Luminance"], bump.inputs["Height"])
    links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])

    return ng


# ==============================================================================
# MATERIAL FACTORIES
# ==============================================================================

def create_physical_cover_material(name, family, texture_or_color=None, scale=(4.0, 4.0, 4.0), shader_params=None):
    """
    Creates a physical cover material using the approved real photographic textures.
    Backwards compatible with both texture filename strings and RGB color tuples.
    """
    existing = bpy.data.materials.get(name)
    if existing:
        return existing
    mat = bpy.data.materials.new(name=name)
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()

    output = nodes.new("ShaderNodeOutputMaterial"); output.location = (600, 0)
    group_node = nodes.new("ShaderNodeGroup"); group_node.location = (300, 0)

    # Determine default texture and node group by family
    default_textures = {
        "leather": "leather_oxblood.jpg",
        "cloth": "bookcloth_muted_olive.jpg",
        "paper": "paper_warm_ivory.jpg",
        "coated": "coated_charcoal_slate.jpg",
    }
    texture_file = texture_or_color if isinstance(texture_or_color, str) else default_textures.get(family, "leather_oxblood.jpg")

    if family == "leather":
        group_node.node_tree = get_or_create_leather_node_group()
    elif family == "cloth":
        group_node.node_tree = get_or_create_bookcloth_node_group()
    elif family == "paper":
        group_node.node_tree = get_or_create_matte_paper_node_group()
    elif family == "coated":
        group_node.node_tree = get_or_create_coated_board_node_group()
    elif family == "foil":
        group_node.node_tree = get_or_create_foil_node_group()
        foil_col = texture_or_color if (isinstance(texture_or_color, (list, tuple)) and len(texture_or_color) >= 3) else (0.96, 0.80, 0.32, 1.0)
        group_node.inputs["Foil Color"].default_value = foil_col
        links.new(group_node.outputs["BSDF"], output.inputs["Surface"])
        return mat
    elif family == "page":
        return create_physical_page_material(name, "page_block_ivory.jpg")
    else:
        raise ValueError(f"Unknown family '{family}'")

    # Apply fine-tuned shader parameters if provided
    if shader_params:
        param_map = {
            "rough_min": "Roughness Min",
            "rough_max": "Roughness Max",
            "from_min": "From Min",
            "from_max": "From Max",
            "rough": "Roughness",
            "spec": "Specular Level",
            "sheen": "Sheen Weight",
            "bump_dist": "Bump Distance",
            "bump_strength": "Bump Strength"
        }
        for k, v in shader_params.items():
            sock = param_map.get(k)
            if sock and sock in group_node.inputs:
                group_node.inputs[sock].default_value = v

    links.new(group_node.outputs["BSDF"], output.inputs["Surface"])

    # Photographic texture mapping setup
    tex_coord = nodes.new("ShaderNodeTexCoord"); tex_coord.location = (-600, 0)
    mapping = nodes.new("ShaderNodeMapping"); mapping.location = (-400, 0)
    mapping.inputs["Scale"].default_value = scale
    links.new(tex_coord.outputs["Object"], mapping.inputs["Vector"])

    tex_node = nodes.new("ShaderNodeTexImage"); tex_node.location = (-150, 0)
    tex_node.image = _get_book_texture_image(texture_file)
    tex_node.projection = 'BOX'
    tex_node.projection_blend = 0.1
    links.new(mapping.outputs["Vector"], tex_node.inputs["Vector"])

    rgb_to_bw = nodes.new("ShaderNodeRGBToBW"); rgb_to_bw.location = (80, -100)
    links.new(tex_node.outputs["Color"], rgb_to_bw.inputs["Color"])

    links.new(tex_node.outputs["Color"], group_node.inputs["Cover Texture"])
    links.new(rgb_to_bw.outputs["Val"], group_node.inputs["Tex Luminance"])

    return mat


def create_spine_composite_material(
    name,
    family,
    texture_or_color=None,
    foil_key_or_color="GOLD",
    spine_style="clean",
    has_ribs=True,
    scale=(4.0, 4.0, 4.0),
    shader_params=None,
    crown_bump_dist=0.0025
):
    """
    Creates a spine material that combines the real photographic cover material with
    beveled foil die stamping, convex spine crown profile, and restrained Gaussian ribs.
    """
    existing = bpy.data.materials.get(name)
    if existing:
        return existing
    mat = bpy.data.materials.new(name=name)
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()

    output = nodes.new("ShaderNodeOutputMaterial"); output.location = (800, 0)
    bsdf = nodes.new("ShaderNodeBsdfPrincipled"); bsdf.location = (500, 0)
    links.new(bsdf.outputs["BSDF"], output.inputs["Surface"])

    cover_group = nodes.new("ShaderNodeGroup"); cover_group.location = (-300, 250)

    default_textures = {
        "leather": "leather_oxblood.jpg",
        "cloth": "bookcloth_muted_olive.jpg",
        "paper": "paper_warm_ivory.jpg",
        "coated": "coated_charcoal_slate.jpg",
    }
    texture_file = texture_or_color if isinstance(texture_or_color, str) else default_textures.get(family, "leather_oxblood.jpg")

    if family == "leather":
        cover_group.node_tree = get_or_create_leather_node_group()
    elif family == "cloth":
        cover_group.node_tree = get_or_create_bookcloth_node_group()
    elif family == "paper":
        cover_group.node_tree = get_or_create_matte_paper_node_group()
    elif family == "coated":
        cover_group.node_tree = get_or_create_coated_board_node_group()
    else:
        raise ValueError(f"Unknown family '{family}'")

    spec_level = 0.35
    if shader_params:
        param_map = {
            "rough_min": "Roughness Min",
            "rough_max": "Roughness Max",
            "from_min": "From Min",
            "from_max": "From Max",
            "rough": "Roughness",
            "spec": "Specular Level",
            "sheen": "Sheen Weight",
            "bump_dist": "Bump Distance",
            "bump_strength": "Bump Strength"
        }
        for k, v in shader_params.items():
            sock = param_map.get(k)
            if sock and sock in cover_group.inputs:
                cover_group.inputs[sock].default_value = v
            if k == "spec":
                spec_level = v

    tex_coord = nodes.new("ShaderNodeTexCoord"); tex_coord.location = (-1000, 300)
    mapping = nodes.new("ShaderNodeMapping"); mapping.location = (-800, 300)
    mapping.inputs["Scale"].default_value = scale
    links.new(tex_coord.outputs["Object"], mapping.inputs["Vector"])

    tex_node = nodes.new("ShaderNodeTexImage"); tex_node.location = (-580, 300)
    tex_node.image = _get_book_texture_image(texture_file)
    tex_node.projection = 'BOX'
    tex_node.projection_blend = 0.1
    links.new(mapping.outputs["Vector"], tex_node.inputs["Vector"])

    rgb_to_bw = nodes.new("ShaderNodeRGBToBW"); rgb_to_bw.location = (-400, 100)
    links.new(tex_node.outputs["Color"], rgb_to_bw.inputs["Color"])

    links.new(tex_node.outputs["Color"], cover_group.inputs["Cover Texture"])
    links.new(rgb_to_bw.outputs["Val"], cover_group.inputs["Tex Luminance"])

    sep_xyz = nodes.new("ShaderNodeSeparateXYZ"); sep_xyz.location = (-800, -200)
    links.new(tex_coord.outputs["Generated"], sep_xyz.inputs["Vector"])

    # 1. Convex Spine Crown Profile
    crown_sub = nodes.new("ShaderNodeMath"); crown_sub.operation = 'SUBTRACT'; crown_sub.inputs[0].default_value = 1.0
    links.new(sep_xyz.outputs["X"], crown_sub.inputs[1])
    crown_mult = nodes.new("ShaderNodeMath"); crown_mult.operation = 'MULTIPLY'
    links.new(sep_xyz.outputs["X"], crown_mult.inputs[0]); links.new(crown_sub.outputs["Value"], crown_mult.inputs[1])
    crown_scale = nodes.new("ShaderNodeMath"); crown_scale.operation = 'MULTIPLY'; crown_scale.inputs[1].default_value = 4.0
    links.new(crown_mult.outputs["Value"], crown_scale.inputs[0])

    # 2. Gaussian Spine Ribs
    rib_nodes = []
    rib_centers = [0.18, 0.34, 0.50, 0.66, 0.82]
    if has_ribs:
        for idx, zc in enumerate(rib_centers):
            sub = nodes.new("ShaderNodeMath"); sub.operation = 'SUBTRACT'; sub.location = (-650, -100 - idx * 60)
            links.new(sep_xyz.outputs["Z"], sub.inputs[0]); sub.inputs[1].default_value = zc
            sqr_n = nodes.new("ShaderNodeMath"); sqr_n.operation = 'MULTIPLY'; sqr_n.location = (-500, -100 - idx * 60)
            links.new(sub.outputs["Value"], sqr_n.inputs[0]); links.new(sub.outputs["Value"], sqr_n.inputs[1])
            div_n = nodes.new("ShaderNodeMath"); div_n.operation = 'DIVIDE'; div_n.location = (-350, -100 - idx * 60)
            div_n.inputs[1].default_value = -0.000030
            links.new(sqr_n.outputs["Value"], div_n.inputs[0])
            exp_n = nodes.new("ShaderNodeMath"); exp_n.operation = 'EXPONENT'; exp_n.location = (-200, -100 - idx * 60)
            links.new(div_n.outputs["Value"], exp_n.inputs[0])
            rib_nodes.append(exp_n)

        total_ribs = rib_nodes[0]
        for r in rib_nodes[1:]:
            add_n = nodes.new("ShaderNodeMath"); add_n.operation = 'MAXIMUM'
            links.new(total_ribs.outputs["Value"], add_n.inputs[0])
            links.new(r.outputs["Value"], add_n.inputs[1])
            total_ribs = add_n

    # 3. Tooling Rules
    def make_rule(zc, thick=0.0035, x_min=0.18, x_max=0.82, slope=0.0010):
        hw_x = (x_max - x_min) / 2.0; mid_x = (x_min + x_max) / 2.0
        hw_z = thick / 2.0; mid_z = zc
        sub_x = nodes.new("ShaderNodeMath"); sub_x.operation = 'SUBTRACT'; sub_x.inputs[1].default_value = mid_x
        links.new(sep_xyz.outputs["X"], sub_x.inputs[0])
        abs_x = nodes.new("ShaderNodeMath"); abs_x.operation = 'ABSOLUTE'
        links.new(sub_x.outputs["Value"], abs_x.inputs[0])
        dist_x = nodes.new("ShaderNodeMath"); dist_x.operation = 'SUBTRACT'; dist_x.inputs[0].default_value = hw_x
        links.new(abs_x.outputs["Value"], dist_x.inputs[1])
        grad_x = nodes.new("ShaderNodeMath"); grad_x.operation = 'DIVIDE'; grad_x.inputs[1].default_value = slope
        links.new(dist_x.outputs["Value"], grad_x.inputs[0])

        sub_z = nodes.new("ShaderNodeMath"); sub_z.operation = 'SUBTRACT'; sub_z.inputs[1].default_value = mid_z
        links.new(sep_xyz.outputs["Z"], sub_z.inputs[0])
        abs_z = nodes.new("ShaderNodeMath"); abs_z.operation = 'ABSOLUTE'
        links.new(sub_z.outputs["Value"], abs_z.inputs[0])
        dist_z = nodes.new("ShaderNodeMath"); dist_z.operation = 'SUBTRACT'; dist_z.inputs[0].default_value = hw_z
        links.new(abs_z.outputs["Value"], dist_z.inputs[1])
        grad_z = nodes.new("ShaderNodeMath"); grad_z.operation = 'DIVIDE'; grad_z.inputs[1].default_value = slope
        links.new(dist_z.outputs["Value"], grad_z.inputs[0])

        m_min = nodes.new("ShaderNodeMath"); m_min.operation = 'MINIMUM'
        links.new(grad_x.outputs["Value"], m_min.inputs[0]); links.new(grad_z.outputs["Value"], m_min.inputs[1])
        c_min = nodes.new("ShaderNodeMath"); c_min.operation = 'MINIMUM'; c_min.inputs[1].default_value = 1.0
        links.new(m_min.outputs["Value"], c_min.inputs[0])
        c_max = nodes.new("ShaderNodeMath"); c_max.operation = 'MAXIMUM'; c_max.inputs[1].default_value = 0.0
        links.new(c_min.outputs["Value"], c_max.inputs[0])
        return c_max

    def combine_masks(masks):
        if not masks:
            val = nodes.new("ShaderNodeValue"); val.outputs[0].default_value = 0.0; return val
        res = masks[0]
        for m in masks[1:]:
            mx = nodes.new("ShaderNodeMath"); mx.operation = 'MAXIMUM'
            links.new(res.outputs["Value"], mx.inputs[0]); links.new(m.outputs["Value"], mx.inputs[1])
            res = mx
        return res

    rule_masks = []
    if spine_style in ("classical_fillet", "classical"):
        for zc in rib_centers:
            rule_masks.append(make_rule(zc - 0.020, thick=0.003, x_min=0.20, x_max=0.80))
            rule_masks.append(make_rule(zc + 0.020, thick=0.003, x_min=0.20, x_max=0.80))
        rule_masks.append(make_rule(0.93, thick=0.004, x_min=0.15, x_max=0.85))
        rule_masks.append(make_rule(0.07, thick=0.004, x_min=0.15, x_max=0.85))
        foil_mask = combine_masks(rule_masks)
    elif spine_style in ("literary_deboss", "literary"):
        for zc in rib_centers:
            rule_masks.append(make_rule(zc - 0.018, thick=0.004, x_min=0.22, x_max=0.78))
            rule_masks.append(make_rule(zc + 0.018, thick=0.004, x_min=0.22, x_max=0.78))
        foil_mask = combine_masks(rule_masks)
    elif spine_style in ("fine_rules", "poetry"):
        r_top = make_rule(0.88, thick=0.0035, x_min=0.25, x_max=0.75)
        r_bot = make_rule(0.10, thick=0.0035, x_min=0.35, x_max=0.65)
        foil_mask = combine_masks([r_top, r_bot])
    elif spine_style in ("academic_letterpress", "academic", "letterpress"):
        r_top1 = make_rule(0.89, thick=0.0030, x_min=0.20, x_max=0.80)
        r_top2 = make_rule(0.87, thick=0.0018, x_min=0.20, x_max=0.80)
        r_bot = make_rule(0.09, thick=0.0030, x_min=0.20, x_max=0.80)
        foil_mask = combine_masks([r_top1, r_top2, r_bot])
    elif spine_style in ("minimal_fine", "minimalist", "contemporary"):
        r_top = make_rule(0.86, thick=0.0025, x_min=0.30, x_max=0.70)
        r_bot = make_rule(0.12, thick=0.0025, x_min=0.38, x_max=0.62)
        foil_mask = combine_masks([r_top, r_bot])
    else:
        val = nodes.new("ShaderNodeValue"); val.outputs[0].default_value = 0.0
        foil_mask = val

    is_blind_deboss = (foil_key_or_color == "BLIND_DEBOSS" or foil_key_or_color == FOIL_PALETTE.get("BLIND_DEBOSS"))
    if isinstance(foil_key_or_color, str):
        foil_color = FOIL_PALETTE.get(foil_key_or_color, (0.85, 0.70, 0.25, 1.0))
    else:
        foil_color = foil_key_or_color if foil_key_or_color else (0.85, 0.70, 0.25, 1.0)

    mix_color = nodes.new("ShaderNodeMix"); mix_color.data_type = 'RGBA'; mix_color.location = (150, 200)
    links.new(foil_mask.outputs["Value"], mix_color.inputs["Factor"])
    links.new(cover_group.outputs["Out Color"], mix_color.inputs[6])

    if is_blind_deboss:
        deboss_tint = nodes.new("ShaderNodeMix"); deboss_tint.data_type = 'RGBA'; deboss_tint.location = (0, 100)
        deboss_tint.blend_type = 'MULTIPLY'
        deboss_tint.inputs["Factor"].default_value = 0.85
        links.new(cover_group.outputs["Out Color"], deboss_tint.inputs[6])
        deboss_tint.inputs[7].default_value = (0.35, 0.28, 0.22, 1.0)
        links.new(deboss_tint.outputs[2], mix_color.inputs[7])
    else:
        mix_color.inputs[7].default_value = foil_color
    links.new(mix_color.outputs[2], bsdf.inputs["Base Color"])

    if not is_blind_deboss and spine_style != "clean":
        links.new(foil_mask.outputs["Value"], bsdf.inputs["Metallic"])
        mix_r = nodes.new("ShaderNodeMix"); mix_r.data_type = 'FLOAT'; mix_r.location = (150, 50)
        links.new(foil_mask.outputs["Value"], mix_r.inputs["Factor"])
        links.new(cover_group.outputs["Out Roughness"], mix_r.inputs[2])
        mix_r.inputs[3].default_value = 0.14
        links.new(mix_r.outputs[1], bsdf.inputs["Roughness"])
    else:
        links.new(cover_group.outputs["Out Roughness"], bsdf.inputs["Roughness"])

    if "Specular IOR Level" in bsdf.inputs:
        bsdf.inputs["Specular IOR Level"].default_value = spec_level

    deboss_bump = nodes.new("ShaderNodeBump"); deboss_bump.location = (300, -200)
    deboss_bump.inputs["Strength"].default_value = 0.75
    deboss_bump.inputs["Distance"].default_value = -0.00015
    links.new(foil_mask.outputs["Value"], deboss_bump.inputs["Height"])
    links.new(cover_group.outputs["Out Normal"], deboss_bump.inputs["Normal"])

    if has_ribs:
        rib_bump = nodes.new("ShaderNodeBump"); rib_bump.location = (100, -350)
        rib_bump.inputs["Strength"].default_value = 0.55
        rib_bump.inputs["Distance"].default_value = 0.0012
        links.new(total_ribs.outputs["Value"], rib_bump.inputs["Height"])
        links.new(deboss_bump.outputs["Normal"], rib_bump.inputs["Normal"])
        final_normal_out = rib_bump.outputs["Normal"]
    else:
        final_normal_out = deboss_bump.outputs["Normal"]

    if crown_bump_dist > 0.00005:
        crown_bump = nodes.new("ShaderNodeBump"); crown_bump.location = (300, -350)
        crown_bump.inputs["Strength"].default_value = 0.30
        crown_bump.inputs["Distance"].default_value = crown_bump_dist
        links.new(crown_scale.outputs["Value"], crown_bump.inputs["Height"])
        links.new(final_normal_out, crown_bump.inputs["Normal"])
        links.new(crown_bump.outputs["Normal"], bsdf.inputs["Normal"])
    else:
        links.new(final_normal_out, bsdf.inputs["Normal"])

    return mat


def create_physical_page_material(name="PB_Mat_Page_Ivory", texture_file="page_block_ivory.jpg"):
    """
    Creates a physical page-block material using real photographic page striations.
    """
    existing = bpy.data.materials.get(name)
    if existing:
        return existing
    mat = bpy.data.materials.new(name=name)
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()

    output = nodes.new("ShaderNodeOutputMaterial"); output.location = (600, 0)
    group_node = nodes.new("ShaderNodeGroup"); group_node.location = (300, 0)
    group_node.node_tree = get_or_create_page_block_node_group()
    links.new(group_node.outputs["BSDF"], output.inputs["Surface"])

    tex_coord = nodes.new("ShaderNodeTexCoord"); tex_coord.location = (-600, 0)
    mapping = nodes.new("ShaderNodeMapping"); mapping.location = (-400, 0)
    mapping.inputs["Scale"].default_value = (3.0, 18.0, 3.0)
    mapping.inputs["Rotation"].default_value[2] = math.radians(90.0)
    links.new(tex_coord.outputs["Object"], mapping.inputs["Vector"])

    tex_node = nodes.new("ShaderNodeTexImage"); tex_node.location = (-150, 0)
    tex_node.image = _get_book_texture_image(texture_file)
    tex_node.projection = 'BOX'
    tex_node.projection_blend = 0.05
    links.new(mapping.outputs["Vector"], tex_node.inputs["Vector"])

    rgb_to_bw = nodes.new("ShaderNodeRGBToBW"); rgb_to_bw.location = (80, -100)
    links.new(tex_node.outputs["Color"], rgb_to_bw.inputs["Color"])

    links.new(tex_node.outputs["Color"], group_node.inputs["Page Texture"])
    links.new(rgb_to_bw.outputs["Val"], group_node.inputs["Tex Luminance"])

    return mat


# ==============================================================================
# DETERMINISTIC BOOK MATERIAL PRESETS & DEDUPLICATING RESOLVER
# ==============================================================================

BOOK_COVER_PRESETS = [
    # (preset_id, family, texture_file, scale, shader_params, foil_key, spine_style, has_ribs, crown_bump_dist)
    ("BURGUNDY_LEATHER",  "leather", "leather_oxblood.jpg",       (4.0, 4.0, 4.0), {"rough_min": 0.34, "rough_max": 0.44, "from_min": 0.00, "from_max": 1.00, "spec": 0.35, "bump_dist": 0.000055, "bump_strength": 0.44}, "GOLD",         "classical_fillet",    True,  0.0025),
    ("OLIVE_BOOKCLOTH",   "cloth",   "bookcloth_muted_olive.jpg", (4.5, 4.5, 4.5), {"rough": 0.78, "spec": 0.08, "sheen": 0.38, "bump_dist": 0.000045, "bump_strength": 0.50},                                    "BRONZE",       "fine_rules",          False, 0.0025),
    ("NAVY_BOOKCLOTH",    "cloth",   "bookcloth_navy.jpg",        (4.2, 4.2, 4.2), {"rough": 0.80, "spec": 0.06, "sheen": 0.35, "bump_dist": 0.000085, "bump_strength": 0.70},                                    "SILVER",       "fine_rules",          False, 0.0004),
    ("IVORY_PAPER",       "paper",   "paper_warm_ivory.jpg",      (5.5, 5.5, 5.5), {"rough_min": 0.74, "rough_max": 0.94, "from_min": 0.58, "from_max": 0.88, "spec": 0.07, "bump_dist": 0.000065, "bump_strength": 0.70}, "BLIND_DEBOSS", "academic_letterpress", False, 0.0000),
    ("COGNAC_LEATHER",    "leather", "leather_cognac.jpg",        (4.0, 4.0, 4.0), {"rough_min": 0.54, "rough_max": 0.72, "from_min": 0.15, "from_max": 0.55, "spec": 0.14, "bump_dist": 0.000075, "bump_strength": 0.65}, "BLIND_DEBOSS", "literary_deboss",     True,  0.0003),
    ("SLATE_PAPERBOARD",  "coated",  "coated_charcoal_slate.jpg", (3.6, 3.6, 3.6), {"rough_min": 0.62, "rough_max": 0.78, "from_min": 0.18, "from_max": 0.38, "spec": 0.12, "bump_dist": 0.000045, "bump_strength": 0.55}, "SILVER",       "minimal_fine",        False, 0.0003),
    ("BURGUNDY_GOLD_LIT", "leather", "leather_oxblood.jpg",       (4.0, 4.0, 4.0), {"rough_min": 0.34, "rough_max": 0.44, "from_min": 0.00, "from_max": 1.00, "spec": 0.35, "bump_dist": 0.000055, "bump_strength": 0.44}, "GOLD",         "literary_deboss",     True,  0.0025),
    ("NAVY_GOLD_CLASSIC", "cloth",   "bookcloth_navy.jpg",        (4.2, 4.2, 4.2), {"rough": 0.80, "spec": 0.06, "sheen": 0.35, "bump_dist": 0.000085, "bump_strength": 0.70},                                    "GOLD",         "classical_fillet",    False, 0.0004),
    ("OLIVE_COPPER_ACAD", "cloth",   "bookcloth_muted_olive.jpg", (4.5, 4.5, 4.5), {"rough": 0.78, "spec": 0.08, "sheen": 0.38, "bump_dist": 0.000045, "bump_strength": 0.50},                                    "COPPER",       "academic_letterpress",False, 0.0025),
    ("COGNAC_GOLD_HERO",  "leather", "leather_cognac.jpg",        (4.0, 4.0, 4.0), {"rough_min": 0.54, "rough_max": 0.72, "from_min": 0.15, "from_max": 0.55, "spec": 0.14, "bump_dist": 0.000075, "bump_strength": 0.65}, "GOLD",         "classical_fillet",    True,  0.0003),
    ("SLATE_BLIND_MIN",   "coated",  "coated_charcoal_slate.jpg", (3.6, 3.6, 3.6), {"rough_min": 0.62, "rough_max": 0.78, "from_min": 0.18, "from_max": 0.38, "spec": 0.12, "bump_dist": 0.000045, "bump_strength": 0.55}, "BLIND_DEBOSS", "minimal_fine",        False, 0.0003),
    ("IVORY_SILVER_LIT",  "paper",   "paper_warm_ivory.jpg",      (5.5, 5.5, 5.5), {"rough_min": 0.74, "rough_max": 0.94, "from_min": 0.58, "from_max": 0.88, "spec": 0.07, "bump_dist": 0.000065, "bump_strength": 0.70}, "SILVER",       "literary_deboss",     False, 0.0000),
]

def _ensure_book_physical_node_groups():
    """Ensures all 6 shared physical Node Groups exist in bpy.data.node_groups."""
    get_or_create_leather_node_group()
    get_or_create_bookcloth_node_group()
    get_or_create_matte_paper_node_group()
    get_or_create_coated_board_node_group()
    get_or_create_foil_node_group()
    get_or_create_page_block_node_group()

def _get_or_create_book_materials(spec_name, rng):
    """
    Deterministic resolver that assigns curated real photographic materials to books.
    Strictly caches materials by style key so identical styles share the same datablock.
    """
    _ensure_book_physical_node_groups()
    preset_idx = rng.randrange(len(BOOK_COVER_PRESETS))
    preset_id, family, texture_file, scale, shader_params, foil_key, spine_style, has_ribs, crown_bump_dist = BOOK_COVER_PRESETS[preset_idx]

    cover_name = f"PB_Mat_Cover_{preset_id}"
    cover_mat = bpy.data.materials.get(cover_name)
    if cover_mat is None:
        cover_mat = create_physical_cover_material(
            cover_name, family, texture_file, scale=scale, shader_params=shader_params
        )

    rib_tag = "r" if has_ribs else "nr"
    spine_style_short = spine_style[:14]
    spine_name = f"PB_Spine_{preset_id}_{foil_key}_{spine_style_short}_{rib_tag}"
    spine_mat = bpy.data.materials.get(spine_name)
    if spine_mat is None:
        spine_mat = create_spine_composite_material(
            spine_name, family, texture_file, foil_key_or_color=foil_key,
            spine_style=spine_style, has_ribs=has_ribs, scale=scale,
            shader_params=shader_params, crown_bump_dist=crown_bump_dist
        )

    page_name = "PB_Mat_Page_Ivory"
    page_mat = bpy.data.materials.get(page_name)
    if page_mat is None:
        page_mat = create_physical_page_material(page_name, "page_block_ivory.jpg")

    return cover_mat, spine_mat, page_mat



# =========================================================
# CAPA DE DATOS: BOOK SPEC + GROUP SPEC
# =========================================================
#
# Un BookSpec sigue sin ser geometría — es la descripción de
# UN libro. `orientation` usa el vocabulario que necesitamos
# para composición real: vertical, leaning_left, leaning_right,
# horizontal. Los cuatro ya se generan.
#
# GroupSpec describe una ZONA de la repisa (un tramo en X) y
# qué tipo de composición contiene (vertical_group,
# leaning_group, horizontal_stack), junto with los BookSpec que
# produjo.

@dataclass
class BookSpec:

    name: str
    location: tuple
    dimensions: tuple
    rotation_euler: tuple  # (rx, ry, rz) en radianes
    bevel_width: float
    orientation: str = "vertical"


@dataclass
class GroupSpec:

    group_type: str  # "vertical_group" | "leaning_group" | "horizontal_stack" | "empty"
    x_start: float
    x_end: float
    books: list


# =========================================================
# CAPA DE PLANIFICACIÓN: ESTRUCTURAS DE DATOS (Fase 1)
# =========================================================

@dataclass
class GroupPlan:
    """Representa un grupo intencional de libros dentro de una zona activa."""
    group_type: str  # "vertical_group" | "leaning_group" | "horizontal_stack" | "empty"
    x_start: float
    x_end: float
    role: str = "support"  # "focal_primary" | "focal_secondary" | "support" | "accent" | "quiet"
    mass_budget: float = 0.75  # Presupuesto de masa / ocupación visual (0.0 a 1.0)
    mass_anchor: float = 0.5   # Ancla de posición de masa dentro de la zona [0.0 = izq, 0.5 = centro, 1.0 = der]
    lean_direction: int = 1    # -1 (izquierda) | 1 (derecha)
    min_books: int = 1
    internal_role: str = "primary"  # "primary" | "secondary" | "accent"

    def __post_init__(self):
        if not (0.0 <= self.mass_anchor <= 1.0):
            raise ValueError(
                f"mass_anchor debe estar entre 0.0 y 1.0, se recibió {self.mass_anchor}"
            )


@dataclass
class ZonePlan:
    """Representa una región espacial concreta dentro de la repisa."""
    zone_index: int
    x_start: float
    x_end: float
    zone_type: str  # "MARGIN" | "NEGATIVE_SPACE" | "ACTIVE_GROUP"
    group: Optional[GroupPlan] = None


@dataclass
class ShelfMacroIntent:
    """Intención compositiva macro asignada a una repisa concreta por CompositionPlan."""
    shelf_index: int
    role: str               # "anchor" | "focal_primary" | "focal_secondary" | "support" | "quiet"
    shelf_mass_ratio: float # Presupuesto teórico de masa de la repisa (0.0 a 1.0) antes del factor global de calibración
    target_anchor: float    # Tendencia de anclaje espacial (0.0 a 1.0)
    target_group_count: int # Cantidad preferida de grupos activos (1, 2 o 3)
    accent_kind: str        # "none" | "leaning" | "stack"
    accent_anchor: float    # Posición preferida del acento (0.0 a 1.0)


@dataclass
class ShelfPlan:
    """Representa la intención compositiva y desglose de zonas de una repisa."""
    shelf_index: int
    z_location: float
    available_width: float
    available_height: float
    intent: str = "standard_shelf"  # "hero_shelf" | "standard_shelf" | "light_shelf" | "anchor_shelf"
    macro_intent: Optional[ShelfMacroIntent] = None
    zones: List[ZonePlan] = field(default_factory=list)


@dataclass
class CompositionPlan:
    """Estructura compositiva global del librero previo a la geometría."""
    total_width: float
    total_height: float
    total_depth: float
    shelves_count: int
    density: float
    variation: float
    tilt: float
    seed: int
    macro_pattern: str = "standard"
    macro_intents: List[ShelfMacroIntent] = field(default_factory=list)
    shelves: List[ShelfPlan] = field(default_factory=list)


# =========================================================
# CREAR UNA PIEZA
# =========================================================

def create_box(
    name,
    location,
    dimensions,
    bevel_width,
    bevel_segments
):

    bpy.ops.mesh.primitive_cube_add(
        location=location
    )

    obj = bpy.context.object

    obj.name = name

    obj.dimensions = dimensions

    bpy.ops.object.transform_apply(
        location=False,
        rotation=False,
        scale=True
    )

    # -----------------------------------------------------
    # BEVEL
    # -----------------------------------------------------

    if bevel_width > 0:

        bevel = obj.modifiers.new(
            name="Bevel",
            type='BEVEL'
        )

        bevel.width = bevel_width
        bevel.segments = bevel_segments
        bevel.limit_method = 'ANGLE'
        bevel.angle_limit = 0.8
        bevel.profile = 0.5
        bevel.harden_normals = True

    # -----------------------------------------------------
    # SHADING
    # -----------------------------------------------------

    for polygon in obj.data.polygons:

        polygon.use_smooth = False

    return obj


def _get_or_create_beadboard_material():

    name = "PB_Mat_Beadboard"

    mat = bpy.data.materials.get(name)

    if mat is not None:

        return mat

    mat = bpy.data.materials.new(name)

    mat.use_nodes = True

    nodes = mat.node_tree.nodes

    links = mat.node_tree.links

    bsdf = nodes.get("Principled BSDF")

    if bsdf is not None:

        bsdf.inputs["Base Color"].default_value = (0.22, 0.18, 0.14, 1.0)

        if "Roughness" in bsdf.inputs:

            bsdf.inputs["Roughness"].default_value = 0.50

        # Procedural V-grooves (beadboard)
        tex_wave = nodes.new("ShaderNodeTexWave")

        tex_wave.wave_type = 'BANDS'

        tex_wave.bands_direction = 'X'

        tex_wave.inputs["Scale"].default_value = 45.0

        tex_wave.inputs["Distortion"].default_value = 0.0

        bump = nodes.new("ShaderNodeBump")

        bump.inputs["Distance"].default_value = 0.005

        bump.inputs["Strength"].default_value = 0.85

        links.new(tex_wave.outputs["Color"], bump.inputs["Height"])

        links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])

    mat.diffuse_color = (0.22, 0.18, 0.14, 1.0)

    return mat


def apply_continuous_side_panel_uvs(obj):
    if obj is None or obj.type != 'MESH':
        return
    mesh = obj.data
    if not mesh.uv_layers:
        mesh.uv_layers.new(name="UVMap")
    uv_layer = mesh.uv_layers.active.data

    xs = [v.co.x for v in mesh.vertices]
    ys = [v.co.y for v in mesh.vertices]
    zs = [v.co.z for v in mesh.vertices]

    if not xs or not ys or not zs:
        return

    xmin, xmax = min(xs), max(xs)
    ymin, ymax = min(ys), max(ys)
    zmin, zmax = min(zs), max(zs)

    depth = max(0.001, ymax - ymin)
    thickness = max(0.001, xmax - xmin)

    for poly in mesh.polygons:
        normal = poly.normal
        for loop_idx in poly.loop_indices:
            v_idx = mesh.loops[loop_idx].vertex_index
            v_co = mesh.vertices[v_idx].co

            # V is vertical height (Z) along panel
            v_val = v_co.z - zmin

            # Continuous physical perimeter arc length U
            # Normalize vertex X and Y relative to bounding box
            rel_x = (v_co.x - xmin) / thickness  # 0.0 (left) to 1.0 (right)
            rel_y = (v_co.y - ymin) / depth      # 0.0 (front) to 1.0 (back)

            if normal.z > 0.9 or normal.z < -0.9:
                # Top / bottom caps
                u_val = v_co.x - xmin
                v_val = v_co.y - ymin
            else:
                # Vertical side faces, front edge, bevels, and interior return
                is_right_panel = (obj.location.x > 0) or ((xmin + xmax) / 2.0 > 0)
                if is_right_panel:
                    if rel_x > 0.5 and rel_y >= 0.05:
                        # Exterior side face (moving from back Y=1.0 to front Y=0.0)
                        u_val = (1.0 - rel_y) * depth
                    elif rel_y < 0.05:
                        # Front edge (moving from outer right X=1.0 to inner left X=0.0)
                        u_val = depth + (1.0 - rel_x) * thickness
                    else:
                        # Interior return face (moving from front Y=0.0 to back Y=1.0)
                        u_val = depth + thickness + rel_y * depth
                else:
                    if rel_x < 0.5 and rel_y >= 0.05:
                        # Exterior side face (moving from back Y=1.0 to front Y=0.0)
                        u_val = (1.0 - rel_y) * depth
                    elif rel_y < 0.05:
                        # Front edge & front corner bevels (moving from left X=0.0 to right X=1.0)
                        u_val = depth + rel_x * thickness
                    else:
                        # Interior return face (moving from front Y=0.0 to back Y=1.0)
                        u_val = depth + thickness + rel_y * depth

            uv_layer[loop_idx].uv = (u_val, v_val)


COMPONENT_MAPPING_CONFIGS = {
    "GENERAL":          {"loc": (0.00, 0.00, 0.00), "scale": (0.83, 0.83, 0.83)},
    "SIDE_PANEL_LEFT":  {"loc": (0.00, 0.00, 0.00), "scale": (0.50, 0.50, 0.50)},
    "SIDE_PANEL_RIGHT": {"loc": (0.45, 0.30, 0.00), "scale": (0.50, 0.50, 0.50)},
    "DOOR_STILE_L":     {"loc": (0.00, 0.00, 0.00), "scale": (0.83, 0.42, 0.83)},
    "DOOR_STILE_R":     {"loc": (0.50, 0.20, 0.00), "scale": (0.83, 0.42, 0.83)},
    "DOOR_RAIL_T":      {"loc": (0.15, 0.40, 0.00), "scale": (0.42, 0.83, 0.83)},
    "DOOR_RAIL_B":      {"loc": (0.60, 0.10, 0.00), "scale": (0.42, 0.83, 0.83)},
    "DOOR_PANEL":       {"loc": (0.10, 0.10, 0.00), "scale": (0.83, 0.42, 0.83)},
    "PLINTH":           {"loc": (0.00, 0.00, 0.00), "scale": (0.50, 0.50, 0.50)},
    "CROWN":            {"loc": (0.35, 0.25, 0.00), "scale": (0.42, 0.83, 0.83)},
    "FACE_FRAME":       {"loc": (0.20, 0.15, 0.00), "scale": (0.83, 0.42, 0.83)},
    "BACK_PANEL":       {"loc": (0.15, 0.25, 0.00), "scale": (0.83, 0.42, 0.83)},
    "SHELF":            {"loc": (0.00, 0.00, 0.00), "scale": (0.42, 0.83, 0.83)},
}

SPECIES_SURFACE_POLISH = {
    "OAK_NATURAL":      {"hue": 0.495, "sat": 1.08, "val": 0.96, "rough_min": 0.30, "rough_max": 0.40, "bump_strength": 0.12},
    "WALNUT_DARK":     {"hue": 0.500, "sat": 1.02, "val": 0.95, "rough_min": 0.28, "rough_max": 0.38, "bump_strength": 0.12},
    "TEAK_MID":         {"hue": 0.498, "sat": 1.06, "val": 1.00, "rough_min": 0.35, "rough_max": 0.45, "bump_strength": 0.14},
}

def apply_box_meter_uvs(obj, grain_orientation="VERTICAL"):
    """
    Applies physical meter-scale UV mapping to a component box mesh (1.0 UV unit = 1.0 meter).
    - grain_orientation == "VERTICAL": V axis aligns with 3D Z (vertical height).
    - grain_orientation == "HORIZONTAL": V axis aligns with 3D X (horizontal width/length).
    Guarantees physical grain scale invariance across arbitrary component dimensions.
    """
    if obj is None or obj.type != 'MESH':
        return
    mesh = obj.data
    if not mesh.uv_layers:
        mesh.uv_layers.new(name="UVMap")
    uv_layer = mesh.uv_layers.active.data

    xs = [v.co.x for v in mesh.vertices]
    ys = [v.co.y for v in mesh.vertices]
    zs = [v.co.z for v in mesh.vertices]

    if not xs or not ys or not zs:
        return

    xmin, xmax = min(xs), max(xs)
    ymin, ymax = min(ys), max(ys)
    zmin, zmax = min(zs), max(zs)

    for poly in mesh.polygons:
        normal = poly.normal
        for loop_idx in poly.loop_indices:
            v_idx = mesh.loops[loop_idx].vertex_index
            v_co = mesh.vertices[v_idx].co

            if abs(normal.y) > 0.5:
                # Main front/back face (XZ plane)
                if grain_orientation == "VERTICAL":
                    u_val = v_co.x - xmin
                    v_val = v_co.z - zmin
                else:
                    u_val = v_co.z - zmin
                    v_val = v_co.x - xmin
            elif abs(normal.x) > 0.5:
                # Side end faces (YZ plane)
                if grain_orientation == "VERTICAL":
                    u_val = v_co.y - ymin
                    v_val = v_co.z - zmin
                else:
                    u_val = v_co.z - zmin
                    v_val = v_co.y - ymin
            else:
                # Top/bottom faces (XY plane)
                if grain_orientation == "HORIZONTAL":
                    u_val = v_co.y - ymin
                    v_val = v_co.x - xmin
                else:
                    u_val = v_co.x - xmin
                    v_val = v_co.y - ymin

            uv_layer[loop_idx].uv = (u_val, v_val)


def apply_planar_component_uvs(obj):
    apply_box_meter_uvs(obj, grain_orientation="VERTICAL")


def _get_or_create_structure_material(
    furniture_finish="OAK_NATURAL",
    grain_orientation="VERTICAL",
    component_role="GENERAL",
    component_index=0
):
    import os
    finish = furniture_finish if furniture_finish else "OAK_NATURAL"
    finish_dir_map = {
        "OAK_NATURAL": os.path.join(_WORKSPACE_DIR, "assets", "textures", "wood", "oak_natural"),
        "WALNUT_DARK": os.path.join(_WORKSPACE_DIR, "assets", "textures", "wood", "walnut_dark"),
        "TEAK_MID": os.path.join(_WORKSPACE_DIR, "assets", "textures", "wood", "teak_mid")
    }

    if finish in finish_dir_map:
        target_dir = finish_dir_map[finish]
        bc_path = os.path.join(target_dir, "basecolor.png")
        rg_path = os.path.join(target_dir, "roughness.png")
        nm_path = os.path.join(target_dir, "normal.png")

        orient_suffix = "V" if grain_orientation == "VERTICAL" else "H"
        name = f"PB_Mat_Furniture_{finish}_{orient_suffix}_{component_role}_{component_index}"

        mat = bpy.data.materials.get(name)
        if mat is not None:
            return mat

        if os.path.exists(bc_path) and os.path.exists(rg_path) and os.path.exists(nm_path):
            mat = bpy.data.materials.new(name)
            mat.use_nodes = True
            nodes = mat.node_tree.nodes
            links = mat.node_tree.links
            bsdf = nodes.get("Principled BSDF")

            if bsdf is not None:
                import zlib
                seed_str = f"{finish}_{component_role}_{component_index}"
                h_val = (zlib.crc32(seed_str.encode('utf-8')) & 0xffffffff) / 4294967295.0
                h_val2 = (zlib.crc32(f"{seed_str}_y".encode('utf-8')) & 0xffffffff) / 4294967295.0
                offset_x = (h_val * 3.7) % 2.5
                offset_y = (h_val2 * 2.9) % 2.5

                tex_coord = nodes.new("ShaderNodeTexCoord")

                # Primary mapping (2.2 scale = fine physical veneer density)
                mapping = nodes.new("ShaderNodeMapping")
                mapping.inputs["Scale"].default_value = (2.2, 2.2, 2.2)
                mapping.inputs["Location"].default_value = (offset_x, offset_y, 0.0)

                # Secondary mapping (2.882 non-commensurate scale for zero-tiling blend)
                mapping2 = nodes.new("ShaderNodeMapping")
                mapping2.inputs["Scale"].default_value = (2.882, 2.882, 2.882)
                mapping2.inputs["Location"].default_value = (offset_x + 0.63, offset_y + 0.47, 0.0)

                coord_output = tex_coord.outputs["UV"]
                links.new(coord_output, mapping.inputs["Vector"])
                links.new(coord_output, mapping2.inputs["Vector"])

                # Organic noise mask for seamless surface blending
                try:
                    noise_mask = nodes.new("ShaderNodeTexNoise")
                except Exception:
                    noise_mask = nodes.new("ShaderNodeNoiseTexture")
                if "Scale" in noise_mask.inputs:
                    noise_mask.inputs["Scale"].default_value = 1.2
                if "Detail" in noise_mask.inputs:
                    noise_mask.inputs["Detail"].default_value = 2.0
                links.new(coord_output, noise_mask.inputs["Vector"])
                mask_fac = noise_mask.outputs.get("Fac") or noise_mask.outputs.get("Factor") or noise_mask.outputs[0]

                img_bc = bpy.data.images.load(bc_path, check_existing=True)
                tex_bc1 = nodes.new("ShaderNodeTexImage"); tex_bc1.image = img_bc
                tex_bc2 = nodes.new("ShaderNodeTexImage"); tex_bc2.image = img_bc
                links.new(mapping.outputs["Vector"], tex_bc1.inputs["Vector"])
                links.new(mapping2.outputs["Vector"], tex_bc2.inputs["Vector"])

                mix_bc = nodes.new("ShaderNodeMix"); mix_bc.data_type = 'RGBA'
                links.new(mask_fac, mix_bc.inputs["Factor"])
                links.new(tex_bc1.outputs["Color"], mix_bc.inputs[6])
                links.new(tex_bc2.outputs["Color"], mix_bc.inputs[7])

                img_rg = bpy.data.images.load(rg_path, check_existing=True)
                img_rg.colorspace_settings.name = 'Non-Color'
                tex_rg1 = nodes.new("ShaderNodeTexImage"); tex_rg1.image = img_rg
                tex_rg2 = nodes.new("ShaderNodeTexImage"); tex_rg2.image = img_rg
                links.new(mapping.outputs["Vector"], tex_rg1.inputs["Vector"])
                links.new(mapping2.outputs["Vector"], tex_rg2.inputs["Vector"])

                mix_rg = nodes.new("ShaderNodeMix"); mix_rg.data_type = 'RGBA'
                links.new(mask_fac, mix_rg.inputs["Factor"])
                links.new(tex_rg1.outputs["Color"], mix_rg.inputs[6])
                links.new(tex_rg2.outputs["Color"], mix_rg.inputs[7])

                img_nm = bpy.data.images.load(nm_path, check_existing=True)
                img_nm.colorspace_settings.name = 'Non-Color'
                tex_nm1 = nodes.new("ShaderNodeTexImage"); tex_nm1.image = img_nm
                tex_nm2 = nodes.new("ShaderNodeTexImage"); tex_nm2.image = img_nm
                links.new(mapping.outputs["Vector"], tex_nm1.inputs["Vector"])
                links.new(mapping2.outputs["Vector"], tex_nm2.inputs["Vector"])

                mix_nm = nodes.new("ShaderNodeMix"); mix_nm.data_type = 'RGBA'
                links.new(mask_fac, mix_nm.inputs["Factor"])
                links.new(tex_nm1.outputs["Color"], mix_nm.inputs[6])
                links.new(tex_nm2.outputs["Color"], mix_nm.inputs[7])

                polish_cfg = SPECIES_SURFACE_POLISH.get(finish, SPECIES_SURFACE_POLISH["OAK_NATURAL"])

                normal_map = nodes.new("ShaderNodeNormalMap")
                normal_map.inputs["Strength"].default_value = polish_cfg["bump_strength"]

                hsv = nodes.new("ShaderNodeHueSaturation")
                hsv.inputs["Hue"].default_value = polish_cfg["hue"]
                hsv.inputs["Saturation"].default_value = polish_cfg["sat"]
                hsv.inputs["Value"].default_value = polish_cfg["val"]

                map_rg = nodes.new("ShaderNodeMapRange")
                map_rg.inputs["From Min"].default_value = 0.0
                map_rg.inputs["From Max"].default_value = 1.0
                map_rg.inputs["To Min"].default_value = polish_cfg["rough_min"]
                map_rg.inputs["To Max"].default_value = polish_cfg["rough_max"]

                links.new(mix_bc.outputs[2], hsv.inputs["Color"])
                links.new(hsv.outputs["Color"], bsdf.inputs["Base Color"])

                links.new(mix_rg.outputs[2], map_rg.inputs["Value"])
                links.new(map_rg.outputs["Result"], bsdf.inputs["Roughness"])

                links.new(mix_nm.outputs[2], normal_map.inputs["Color"])
                links.new(normal_map.outputs["Normal"], bsdf.inputs["Normal"])

            return mat

    # Fallback / Painted Finish Handling
    orient_suffix = "V" if grain_orientation == "VERTICAL" else "H"
    name = f"PB_Mat_Furniture_{finish}_{orient_suffix}_{component_role}_{component_index}"
    mat = bpy.data.materials.get(name)
    if mat is not None:
        return mat

    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    bsdf = nodes.get("Principled BSDF")

    if bsdf is not None:
        if finish == "PAINTED_WHITE":
            bsdf.inputs["Base Color"].default_value = (0.88, 0.87, 0.84, 1.0)
            if "Roughness" in bsdf.inputs:
                bsdf.inputs["Roughness"].default_value = 0.30
        elif finish == "PAINTED_NAVY":
            bsdf.inputs["Base Color"].default_value = (0.015, 0.045, 0.12, 1.0)
            if "Roughness" in bsdf.inputs:
                bsdf.inputs["Roughness"].default_value = 0.28
        elif finish == "PAINTED_CHARCOAL":
            bsdf.inputs["Base Color"].default_value = (0.04, 0.045, 0.055, 1.0)
            if "Roughness" in bsdf.inputs:
                bsdf.inputs["Roughness"].default_value = 0.38
        elif finish == "PAINTED_SAGE":
            bsdf.inputs["Base Color"].default_value = (0.12, 0.18, 0.14, 1.0)
            if "Roughness" in bsdf.inputs:
                bsdf.inputs["Roughness"].default_value = 0.35
        else:
            bsdf.inputs["Base Color"].default_value = (0.12, 0.08, 0.05, 1.0)
            if "Roughness" in bsdf.inputs:
                bsdf.inputs["Roughness"].default_value = 0.38

    return mat


def _assign_material(obj, mat):
    if obj is None or mat is None:
        return
    if obj.data.materials:
        obj.data.materials[0] = mat
    else:
        obj.data.materials.append(mat)
def create_back_panel(
    width,
    height,
    depth,
    thickness,
    back_style="SOLID",
    back_thickness=0.015,
    bevel_width=0.0,
    bevel_segments=2,
    furniture_finish="OAK_NATURAL"
):
    if back_style == "OPEN":
        return None

    shelf_width = width - thickness * 2
    side_height = height + thickness
    y_pos = depth / 2 - back_thickness / 2

    obj = create_box(
        "PB_BackPanel",
        (0.0, y_pos, height / 2),
        (shelf_width, back_thickness, side_height),
        bevel_width,
        bevel_segments
    )
    apply_box_meter_uvs(obj, grain_orientation="HORIZONTAL")

    mat = _get_or_create_structure_material(furniture_finish, grain_orientation="HORIZONTAL", component_role="BACK_PANEL")
    _assign_material(obj, mat)
    return obj


# =========================================================
# FASE 4B: REMATES ESTRUCTURALES (Plinth, Crown, FaceFrame)
# =========================================================

def create_plinth(
    width,
    depth,
    thickness,
    plinth_height=0.10,
    bevel_width=0.0,
    bevel_segments=2,
    furniture_finish="OAK_NATURAL"
):
    z_pos = -thickness / 2 - plinth_height / 2
    obj = create_box(
        "PB_Plinth",
        (0.0, 0.0, z_pos),
        (width, depth, plinth_height),
        bevel_width,
        bevel_segments
    )
    apply_box_meter_uvs(obj, grain_orientation="HORIZONTAL")
    _assign_material(obj, _get_or_create_structure_material(furniture_finish, grain_orientation="HORIZONTAL", component_role="PLINTH"))
    return obj


def create_crown(
    width,
    height,
    depth,
    thickness,
    crown_height=0.08,
    overhang_w=0.025,
    overhang_d=0.025,
    bevel_width=0.0,
    bevel_segments=2,
    furniture_finish="OAK_NATURAL"
):
    z_pos = height + thickness / 2 + crown_height / 2
    y_pos = -overhang_d / 2
    obj = create_box(
        "PB_Crown",
        (0.0, y_pos, z_pos),
        (width + overhang_w * 2, depth + overhang_d, crown_height),
        max(bevel_width, 0.008),
        bevel_segments
    )
    apply_box_meter_uvs(obj, grain_orientation="HORIZONTAL")
    _assign_material(obj, _get_or_create_structure_material(furniture_finish, grain_orientation="HORIZONTAL", component_role="CROWN"))
    return obj


def create_face_frame(
    width,
    height,
    depth,
    shelves,
    thickness,
    stile_width=0.06,
    trim_thickness=0.015,
    rail_height=0.03,
    bevel_width=0.0,
    bevel_segments=2,
    furniture_finish="OAK_NATURAL"
):
    y_pos = -depth / 2 - trim_thickness / 2
    side_height = height + thickness
    spacing = height / shelves

    parts = []

    left_stile = create_box(
        "PB_Stile_L_temp",
        (-width / 2 + stile_width / 2, y_pos, height / 2),
        (stile_width, trim_thickness, side_height),
        0.0, 1
    )
    apply_box_meter_uvs(left_stile, grain_orientation="VERTICAL")
    _assign_material(left_stile, _get_or_create_structure_material(furniture_finish, grain_orientation="VERTICAL", component_role="FACE_FRAME_STILE_L"))
    parts.append(left_stile)

    right_stile = create_box(
        "PB_Stile_R_temp",
        (width / 2 - stile_width / 2, y_pos, height / 2),
        (stile_width, trim_thickness, side_height),
        0.0, 1
    )
    apply_box_meter_uvs(right_stile, grain_orientation="VERTICAL")
    _assign_material(right_stile, _get_or_create_structure_material(furniture_finish, grain_orientation="VERTICAL", component_role="FACE_FRAME_STILE_R"))
    parts.append(right_stile)

    inner_rail_width = max(0.01, width - 2 * stile_width)
    for i in range(shelves + 1):
        z_pos = i * spacing
        rail = create_box(
            f"PB_Rail_{i:02d}_temp",
            (0.0, y_pos, z_pos),
            (inner_rail_width, trim_thickness, rail_height),
            0.0, 1
        )
        apply_box_meter_uvs(rail, grain_orientation="HORIZONTAL")
        _assign_material(rail, _get_or_create_structure_material(furniture_finish, grain_orientation="HORIZONTAL", component_role="FACE_FRAME_RAIL", component_index=i))
        parts.append(rail)

    bpy.ops.object.select_all(action='DESELECT')
    for part in parts:
        part.select_set(True)
    bpy.context.view_layer.objects.active = parts[0]
    bpy.ops.object.join()

    face_frame = bpy.context.view_layer.objects.active
    face_frame.name = "PB_FaceFrame"

    if bevel_width > 0:
        mod = face_frame.modifiers.new(name="Bevel", type='BEVEL')
        mod.width = bevel_width
        mod.segments = bevel_segments
        mod.limit_method = 'ANGLE'
        mod.angle_limit = 0.8
        mod.harden_normals = True

    return face_frame


# =========================================================
# MATERIAL DE VIDRIO PARA PUERTAS (Fase 4C)
# =========================================================

def _get_or_create_glass_material():

    name = "PB_Mat_Glass"

    mat = bpy.data.materials.get(name)

    if mat is not None:

        return mat

    mat = bpy.data.materials.new(name)

    mat.use_nodes = True

    nodes = mat.node_tree.nodes

    bsdf = nodes.get("Principled BSDF")

    if bsdf is not None:
        bsdf.inputs["Base Color"].default_value = (0.95, 0.98, 1.0, 1.0)
        if "Transmission Weight" in bsdf.inputs:
            bsdf.inputs["Transmission Weight"].default_value = 1.0
        elif "Transmission" in bsdf.inputs:
            bsdf.inputs["Transmission"].default_value = 1.0

        if "Roughness" in bsdf.inputs:
            bsdf.inputs["Roughness"].default_value = 0.015

        if "IOR" in bsdf.inputs:
            bsdf.inputs["IOR"].default_value = 1.52

        if "Specular IOR Level" in bsdf.inputs:
            bsdf.inputs["Specular IOR Level"].default_value = 0.50

        if "Alpha" in bsdf.inputs:
            bsdf.inputs["Alpha"].default_value = 1.0

    mat.diffuse_color = (0.95, 0.98, 1.0, 0.15)
    if hasattr(mat, "blend_method"):
        try:
            mat.blend_method = 'BLEND'
        except Exception:
            pass
    if hasattr(mat, "shadow_method"):
        try:
            mat.shadow_method = 'NONE'
        except Exception:
            pass
    return mat


# =========================================================
# FASE 4C: SISTEMA DE PUERTAS DE GABINETE
# =========================================================

def create_door_leaf(
    name,
    width,
    height,
    thickness=0.018,
    style="RAISED_PANEL",
    bevel_width=0.002,
    bevel_segments=2,
    is_left=True,
    furniture_finish="OAK_NATURAL"
):
    """
    Construye una hoja de puerta (FLAT, RAISED_PANEL o GLASS) con su pivote/origen
    ubicado exactamente en su borde de bisagra trasera (Y = 0 en cara trasera local).
    """
    center_x = width / 2 if is_left else -width / 2
    center_y = -thickness / 2

    if style == "FLAT":

        obj = create_box(
            name,
            (center_x, center_y, 0.0),
            (width, thickness, height),
            bevel_width,
            bevel_segments
        )
        apply_box_meter_uvs(obj, grain_orientation="VERTICAL")

        bpy.ops.object.select_all(action='DESELECT')

        obj.select_set(True)

        bpy.context.view_layer.objects.active = obj

        bpy.context.scene.cursor.location = (0.0, 0.0, 0.0)

        bpy.ops.object.origin_set(type='ORIGIN_CURSOR')

        _assign_material(obj, _get_or_create_structure_material(furniture_finish, grain_orientation="VERTICAL"))

        return obj

    elif style == "RAISED_PANEL":
        frame_w = min(0.05, width * 0.25)

        mat_stile_l = _get_or_create_structure_material(furniture_finish, grain_orientation="VERTICAL", component_role="DOOR_STILE_L")
        mat_stile_r = _get_or_create_structure_material(furniture_finish, grain_orientation="VERTICAL", component_role="DOOR_STILE_R")
        mat_rail_t  = _get_or_create_structure_material(furniture_finish, grain_orientation="HORIZONTAL", component_role="DOOR_RAIL_T")
        mat_rail_b  = _get_or_create_structure_material(furniture_finish, grain_orientation="HORIZONTAL", component_role="DOOR_RAIL_B")
        mat_panel   = _get_or_create_structure_material(furniture_finish, grain_orientation="VERTICAL", component_role="DOOR_PANEL")

        parts = []
        left_stile_x = (center_x - width / 2) + frame_w / 2
        right_stile_x = (center_x + width / 2) - frame_w / 2

        ls = create_box(f"{name}_Stile_L_temp", (left_stile_x, center_y, 0.0), (frame_w, thickness, height), 0.0, 1)
        apply_box_meter_uvs(ls, "VERTICAL")
        _assign_material(ls, mat_stile_l)
        rs = create_box(f"{name}_Stile_R_temp", (right_stile_x, center_y, 0.0), (frame_w, thickness, height), 0.0, 1)
        apply_box_meter_uvs(rs, "VERTICAL")
        _assign_material(rs, mat_stile_r)
        parts.extend([ls, rs])

        inner_rail_w = max(0.001, width - 2 * frame_w)
        top_rail_z = height / 2 - frame_w / 2
        bot_rail_z = -height / 2 + frame_w / 2

        tr = create_box(f"{name}_Rail_T_temp", (center_x, center_y, top_rail_z), (inner_rail_w, thickness, frame_w), 0.0, 1)
        apply_box_meter_uvs(tr, "HORIZONTAL")
        _assign_material(tr, mat_rail_t)
        br = create_box(f"{name}_Rail_B_temp", (center_x, center_y, bot_rail_z), (inner_rail_w, thickness, frame_w), 0.0, 1)
        apply_box_meter_uvs(br, "HORIZONTAL")
        _assign_material(br, mat_rail_b)
        parts.extend([tr, br])

        panel_w = max(0.001, width - 2 * frame_w)
        panel_h = max(0.001, height - 2 * frame_w)
        panel_t = thickness * 0.75

        p = create_box(f"{name}_Panel_temp", (center_x, center_y, 0.0), (panel_w, panel_t, panel_h), max(bevel_width, 0.003), bevel_segments)
        apply_box_meter_uvs(p, "VERTICAL")
        _assign_material(p, mat_panel)
        parts.append(p)

        bpy.ops.object.select_all(action='DESELECT')
        for part in parts:
            part.select_set(True)
        bpy.context.view_layer.objects.active = parts[0]
        bpy.ops.object.join()

        door_obj = bpy.context.view_layer.objects.active
        door_obj.name = name

        bpy.ops.object.select_all(action='DESELECT')
        door_obj.select_set(True)
        bpy.context.view_layer.objects.active = door_obj

        bpy.context.scene.cursor.location = (0.0, 0.0, 0.0)
        bpy.ops.object.origin_set(type='ORIGIN_CURSOR')

        if bevel_width > 0:
            mod = door_obj.modifiers.new(name="Bevel", type='BEVEL')
            mod.width = bevel_width
            mod.segments = bevel_segments
            mod.limit_method = 'ANGLE'
            mod.angle_limit = 0.8
            mod.harden_normals = True

        return door_obj

    else:  # "GLASS"

        frame_w = min(0.05, width * 0.25)

        parts = []

        left_stile_x = (center_x - width / 2) + frame_w / 2

        right_stile_x = (center_x + width / 2) - frame_w / 2

        ls = create_box(f"{name}_Stile_L_temp", (left_stile_x, center_y, 0.0), (frame_w, thickness, height), 0.0, 1)
        apply_box_meter_uvs(ls, "VERTICAL")
        _assign_material(ls, _get_or_create_structure_material(furniture_finish, grain_orientation="VERTICAL", component_role="DOOR_STILE_L"))

        rs = create_box(f"{name}_Stile_R_temp", (right_stile_x, center_y, 0.0), (frame_w, thickness, height), 0.0, 1)
        apply_box_meter_uvs(rs, "VERTICAL")
        _assign_material(rs, _get_or_create_structure_material(furniture_finish, grain_orientation="VERTICAL", component_role="DOOR_STILE_R"))

        parts.extend([ls, rs])

        inner_rail_w = max(0.001, width - 2 * frame_w)

        top_rail_z = height / 2 - frame_w / 2

        bot_rail_z = -height / 2 + frame_w / 2

        tr = create_box(f"{name}_Rail_T_temp", (center_x, center_y, top_rail_z), (inner_rail_w, thickness, frame_w), 0.0, 1)
        apply_box_meter_uvs(tr, "HORIZONTAL")
        _assign_material(tr, _get_or_create_structure_material(furniture_finish, grain_orientation="HORIZONTAL", component_role="DOOR_RAIL_T"))

        br = create_box(f"{name}_Rail_B_temp", (center_x, center_y, bot_rail_z), (inner_rail_w, thickness, frame_w), 0.0, 1)
        apply_box_meter_uvs(br, "HORIZONTAL")
        _assign_material(br, _get_or_create_structure_material(furniture_finish, grain_orientation="HORIZONTAL", component_role="DOOR_RAIL_B"))

        parts.extend([tr, br])

        bpy.ops.object.select_all(action='DESELECT')

        for part in parts:

            part.select_set(True)

        bpy.context.view_layer.objects.active = parts[0]

        bpy.ops.object.join()

        frame_obj = bpy.context.view_layer.objects.active

        frame_obj.name = f"{name}_Frame"

        bpy.ops.object.select_all(action='DESELECT')

        frame_obj.select_set(True)

        bpy.context.view_layer.objects.active = frame_obj

        bpy.context.scene.cursor.location = (0.0, 0.0, 0.0)

        bpy.ops.object.origin_set(type='ORIGIN_CURSOR')

        if bevel_width > 0:

            mod = frame_obj.modifiers.new(name="Bevel", type='BEVEL')

            mod.width = bevel_width

            mod.segments = bevel_segments

            mod.limit_method = 'ANGLE'

            mod.angle_limit = 0.8

            mod.harden_normals = True

        glass_w = max(0.001, width - 2 * frame_w)

        glass_h = max(0.001, height - 2 * frame_w)

        glass_t = thickness * 0.25

        glass_obj = create_box(f"{name}_GlassPane", (center_x, center_y, 0.0), (glass_w, glass_t, glass_h), 0.0, 1)

        _assign_material(glass_obj, _get_or_create_glass_material())

        root = bpy.data.objects.new(name, None)

        bpy.context.collection.objects.link(root)

        root.empty_display_type = 'PLAIN_AXES'

        root.empty_display_size = 0.02

        frame_obj.parent = root

        glass_obj.parent = root

        return root


def _get_or_create_hardware_material(material_name="GOLD"):
    mat_name = f"PB_Mat_Hardware_{material_name}"
    if mat_name in bpy.data.materials:
        return bpy.data.materials[mat_name]

    mat = bpy.data.materials.new(name=mat_name)
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    bsdf = nodes.get("Principled BSDF")
    if bsdf:
        if material_name in ("GOLD", "BRASS"):
            bsdf.inputs["Base Color"].default_value = (0.85, 0.70, 0.25, 1.0)
            bsdf.inputs["Metallic"].default_value = 0.90
            if "Roughness" in bsdf.inputs:
                bsdf.inputs["Roughness"].default_value = 0.22
        elif material_name in ("SILVER", "CHROME", "POLISHED_NICKEL"):
            bsdf.inputs["Base Color"].default_value = (0.80, 0.82, 0.84, 1.0)
            bsdf.inputs["Metallic"].default_value = 0.95
            if "Roughness" in bsdf.inputs:
                bsdf.inputs["Roughness"].default_value = 0.20
        elif material_name in ("BLACK", "BLACK_IRON", "AGED_BRONZE"):
            bsdf.inputs["Base Color"].default_value = (0.05, 0.05, 0.05, 1.0)
            bsdf.inputs["Metallic"].default_value = 0.90
            if "Roughness" in bsdf.inputs:
                bsdf.inputs["Roughness"].default_value = 0.35
        else:
            bsdf.inputs["Base Color"].default_value = (0.85, 0.70, 0.25, 1.0)
            bsdf.inputs["Metallic"].default_value = 0.90
            if "Roughness" in bsdf.inputs:
                bsdf.inputs["Roughness"].default_value = 0.22
    return mat


def create_handle(
    name,
    style="KNOB",
    material_name="BRASS",
    bevel_width=0.002,
    bevel_segments=2,
    door_h=0.50
):
    """
    Construye un tirador / jaladera (KNOB, PULL_BAR, PULL_RECESSED o DROP_RING) con su origen
    en la base trasera de montaje (Y = 0 local), escalado proporcionalmente a la altura de la puerta.
    """
    mat = _get_or_create_hardware_material(material_name)

    if style == "KNOB":
        head_r = min(0.018, max(0.010, door_h * 0.025))  # Proportional knob radius
        head_t = 0.015
        neck_r = head_r * 0.48
        neck_t = 0.010

        neck = create_box(f"{name}_Neck_temp", (0.0, -neck_t / 2, 0.0), (neck_r * 2, neck_t, neck_r * 2), 0.0, 1)
        head = create_box(f"{name}_Head_temp", (0.0, -neck_t - head_t / 2, 0.0), (head_r * 2, head_t, head_r * 2), bevel_width, bevel_segments)

        bpy.ops.object.select_all(action='DESELECT')
        neck.select_set(True)
        head.select_set(True)
        bpy.context.view_layer.objects.active = neck
        bpy.ops.object.join()

        handle_obj = bpy.context.view_layer.objects.active
        handle_obj.name = name
        bpy.ops.object.select_all(action='DESELECT')
        handle_obj.select_set(True)
        bpy.context.view_layer.objects.active = handle_obj
        bpy.context.scene.cursor.location = (0.0, 0.0, 0.0)
        bpy.ops.object.origin_set(type='ORIGIN_CURSOR')
        _assign_material(handle_obj, mat)
        return handle_obj

    elif style in ("PULL_BAR", "PULL_RECESSED"):
        # Proportional vertical bar pull length based on door height (e.g. 120mm - 220mm)
        bar_len = min(0.22, max(0.08, door_h * 0.18))
        bar_r = 0.005      # 10mm bar diameter
        proj = 0.030       # 30mm projection from door surface
        post_r = 0.004     # 8mm diameter post
        post_spacing = bar_len * 0.70
        post_len = proj - bar_r

        # Create smooth vertical tubular bar along Z
        bpy.ops.mesh.primitive_cylinder_add(
            radius=bar_r, depth=bar_len, location=(0.0, -proj, 0.0), rotation=(0, 0, 0)
        )
        bar = bpy.context.object
        bar.name = f"{name}_Bar_temp"

        # Create top and bottom mounting posts extending from Y=0 to Y=-proj
        bpy.ops.mesh.primitive_cylinder_add(
            radius=post_r, depth=post_len, location=(0.0, -post_len / 2, +post_spacing / 2), rotation=(math.pi / 2, 0, 0)
        )
        post_T = bpy.context.object
        post_T.name = f"{name}_PostT_temp"

        bpy.ops.mesh.primitive_cylinder_add(
            radius=post_r, depth=post_len, location=(0.0, -post_len / 2, -post_spacing / 2), rotation=(math.pi / 2, 0, 0)
        )
        post_B = bpy.context.object
        post_B.name = f"{name}_PostB_temp"

        bpy.ops.object.select_all(action='DESELECT')
        bar.select_set(True)
        post_T.select_set(True)
        post_B.select_set(True)
        bpy.context.view_layer.objects.active = bar
        bpy.ops.object.join()

        handle_obj = bpy.context.view_layer.objects.active
        handle_obj.name = name
        bpy.ops.object.select_all(action='DESELECT')
        handle_obj.select_set(True)
        bpy.context.view_layer.objects.active = handle_obj
        bpy.ops.object.shade_smooth()
        bpy.context.scene.cursor.location = (0.0, 0.0, 0.0)
        bpy.ops.object.origin_set(type='ORIGIN_CURSOR')
        _assign_material(handle_obj, mat)
        return handle_obj

    else:  # "DROP_RING"
        bp_w = 0.030
        bp_h = min(0.060, max(0.030, door_h * 0.060))
        bp_t = 0.003

        bp = create_box(f"{name}_Plate_temp", (0.0, -bp_t / 2, 0.0), (bp_w, bp_t, bp_h), 0.001, 1)

        bpy.ops.mesh.primitive_cylinder_add(
            radius=0.004, depth=0.006, location=(0.0, -bp_t - 0.003, 0.008), rotation=(math.pi / 2, 0, 0)
        )
        mount = bpy.context.object
        mount.name = f"{name}_Mount_temp"

        bpy.ops.mesh.primitive_torus_add(
            major_radius=0.014, minor_radius=0.003,
            location=(0.0, -bp_t - 0.007, -0.006),
            rotation=(0, 0, 0)
        )
        ring = bpy.context.object
        ring.name = f"{name}_Ring_temp"

        bpy.ops.object.select_all(action='DESELECT')
        bp.select_set(True)
        mount.select_set(True)
        ring.select_set(True)
        bpy.context.view_layer.objects.active = bp
        bpy.ops.object.join()

        handle_obj = bpy.context.view_layer.objects.active
        handle_obj.name = name
        bpy.ops.object.select_all(action='DESELECT')
        handle_obj.select_set(True)
        bpy.context.view_layer.objects.active = handle_obj
        bpy.ops.object.shade_smooth()
        bpy.context.scene.cursor.location = (0.0, 0.0, 0.0)
        bpy.ops.object.origin_set(type='ORIGIN_CURSOR')
        _assign_material(handle_obj, mat)
        return handle_obj


def calculate_door_grid(height, width, door_shelves_covered, shelves, door_count_mode, requested_doors, stile_width=0.06):
    """
    Calcula la distribución en cuadrícula (rows x cols) de las puertas de gabinete.
    Garantiza de forma ESTRICTA que ninguna hoja supere los 0.90m de altura (H_leaf <= 0.90m).
    """
    spacing = height / shelves
    h_cabinet = door_shelves_covered * spacing
    
    # 1. Filas mínimas requeridas para que H_leaf <= 0.90m
    max_leaf_h = 0.90
    rows = max(1, math.ceil(h_cabinet / max_leaf_h))
    
    usable_w = max(0.20, width - 2 * stile_width)
    is_asymmetric_3door = False
    
    if door_count_mode != 'AUTO' and requested_doors == 2:
        rows = 1
        cols = 2
        capacity = 2
        actual_doors = 2
        empty_cells = 0
        leaf_height = max(0.05, min(0.85, h_cabinet))
        leaf_width = max(0.05, usable_w / cols)
    elif door_count_mode != 'AUTO' and requested_doors == 3:
        rows = 3
        cols = 2
        capacity = 6
        actual_doors = 3
        empty_cells = 1  # 1 tall left door covers 3 rows; 2 right doors cover top 2 rows; 1 visible open cell at bottom-right
        leaf_height = max(0.05, (h_cabinet - 4 * 0.002) / 3.0)
        leaf_width = max(0.05, (usable_w - 3 * 0.002) / 2.0)
        is_asymmetric_3door = True
    elif door_count_mode == 'AUTO' or requested_doors <= 0:
        cols = max(1, int(round(usable_w / 0.55)))
        capacity = rows * cols
        actual_doors = capacity
        empty_cells = capacity - actual_doors
        leaf_height = max(0.05, h_cabinet / rows)
        leaf_width = max(0.05, usable_w / cols)
    else:
        req = max(1, requested_doors)
        cols = max(1, math.ceil(req / rows))
        capacity = rows * cols
        actual_doors = min(req, capacity)
        empty_cells = capacity - actual_doors
        leaf_height = max(0.05, h_cabinet / rows)
        leaf_width = max(0.05, usable_w / cols)
    
    return {
        "rows": rows,
        "cols": cols,
        "capacity": capacity,
        "actual_doors": actual_doors,
        "empty_cells": empty_cells,
        "total_leaves": actual_doors,
        "leaf_height": leaf_height,
        "leaf_width": leaf_width,
        "h_cabinet": h_cabinet,
        "is_asymmetric_3door": is_asymmetric_3door
    }


def create_doors(
    width,
    height,
    depth,
    shelves,
    thickness,
    stile_width=0.06,
    plinth_height=0.10,
    door_shelves_covered=1,
    door_style="RAISED_PANEL",
    door_count=2,
    door_count_mode="AUTO",
    door_thickness=0.018,
    door_gap=0.002,
    door_angle=0.0,
    has_handles=True,
    handle_style="KNOB",
    handle_material="BRASS",
    bevel_width=0.002,
    bevel_segments=2,
    furniture_finish="OAK_NATURAL"
):
    """
    Calcula la geometría y posición exacta de montaje de las puertas de gabinete (Fase 4C)
    y jaladeras (Fase 4D) organizadas en una cuadrícula (rows x cols) donde H_leaf <= 0.90m.
    Respetando el plano frontal Y = -depth/2 - trim_thickness.
    """
    grid = calculate_door_grid(height, width, door_shelves_covered, shelves, door_count_mode, door_count, stile_width)
    rows = grid["rows"]
    cols = grid["cols"]
    h_cabinet = grid["h_cabinet"]

    trim_thickness = 0.015
    y_pivot = -depth / 2 - trim_thickness
    z_bot = thickness / 2
    usable_w = max(0.20, width - 2 * stile_width)

    if grid.get("is_asymmetric_3door", False):
        doors = []
        door_w = max(0.02, (usable_w - 3 * door_gap) / 2.0)
        door_h_short = max(0.05, (h_cabinet - 4 * door_gap) / 3.0)
        door_h_tall = max(0.05, h_cabinet - 2 * door_gap)

        # 1. Left column (c=0): 1 tall door leaf spanning full h_cabinet
        x_left_col = -width / 2.0 + stile_width + door_gap
        x_pivot_left = x_left_col
        z_center_tall = z_bot + door_gap + door_h_tall / 2.0

        leaf_tall = create_door_leaf(
            "PB_Door_Tall_Left", door_w, door_h_tall, door_thickness,
            door_style, bevel_width, bevel_segments, is_left=True,
            furniture_finish=furniture_finish
        )
        leaf_tall.location = (x_pivot_left, y_pivot, z_center_tall)
        leaf_tall.rotation_euler = (0.0, 0.0, -door_angle)
        doors.append(leaf_tall)

        if has_handles:
            frame_w = min(0.05, door_w * 0.25)
            stile_center_offset = max(frame_w / 2.0, 0.02)
            x_handle = door_w - stile_center_offset
            h_obj = create_handle(
                "PB_Handle_Tall_Left", handle_style, handle_material,
                bevel_width, bevel_segments, door_h=door_h_tall
            )
            h_obj.location = (x_handle, -door_thickness, 0.0)
            h_obj.parent = leaf_tall

        # 2. Right column (c=1): 2 shorter doors in row 1 (middle) and row 2 (top); row 0 (bottom) OPEN
        x_right_col = x_left_col + door_w + door_gap
        x_pivot_right = x_right_col + door_w  # Right pivot (hinged on right edge, opens from center)

        # Right Door 1 (Middle row, r=1)
        z_center_mid = z_bot + door_gap + 1 * door_h_short + 1 * door_gap + door_h_short / 2.0
        leaf_mid = create_door_leaf(
            "PB_Door_Mid_Right", door_w, door_h_short, door_thickness,
            door_style, bevel_width, bevel_segments, is_left=False,
            furniture_finish=furniture_finish
        )
        leaf_mid.location = (x_pivot_right, y_pivot, z_center_mid)
        leaf_mid.rotation_euler = (0.0, 0.0, +door_angle)
        doors.append(leaf_mid)

        if has_handles:
            frame_w = min(0.05, door_w * 0.25)
            stile_center_offset = max(frame_w / 2.0, 0.02)
            x_handle = -door_w + stile_center_offset
            h_obj = create_handle(
                "PB_Handle_Mid_Right", handle_style, handle_material,
                bevel_width, bevel_segments, door_h=door_h_short
            )
            h_obj.location = (x_handle, -door_thickness, 0.0)
            h_obj.parent = leaf_mid

        # Right Door 2 (Top row, r=2)
        z_center_top = z_bot + door_gap + 2 * door_h_short + 2 * door_gap + door_h_short / 2.0
        leaf_top = create_door_leaf(
            "PB_Door_Top_Right", door_w, door_h_short, door_thickness,
            door_style, bevel_width, bevel_segments, is_left=False,
            furniture_finish=furniture_finish
        )
        leaf_top.location = (x_pivot_right, y_pivot, z_center_top)
        leaf_top.rotation_euler = (0.0, 0.0, +door_angle)
        doors.append(leaf_top)

        if has_handles:
            frame_w = min(0.05, door_w * 0.25)
            stile_center_offset = max(frame_w / 2.0, 0.02)
            x_handle = -door_w + stile_center_offset
            h_obj = create_handle(
                "PB_Handle_Top_Right", handle_style, handle_material,
                bevel_width, bevel_segments, door_h=door_h_short
            )
            h_obj.location = (x_handle, -door_thickness, 0.0)
            h_obj.parent = leaf_top

        return doors

    # Altura y ancho por hoja (descontando holgura reveal gap exacta sin duplicar)
    col_width = usable_w / cols
    door_w = max(0.02, (usable_w - (cols + 1) * door_gap) / cols)
    col_pitch = door_w + door_gap

    row_height = h_cabinet / rows
    door_h = max(0.05, (h_cabinet - (rows + 1) * door_gap) / rows)
    row_pitch = door_h + door_gap

    doors = []
    actual_doors = grid["actual_doors"]

    # Deterministic top-to-bottom, left-to-right cell ordering
    # For N actual doors in an R x C grid, first N cells get doors, remaining (R*C - N) bottom-right cells remain OPEN
    cell_idx = 0
    for r in reversed(range(rows)):
        z_center = z_bot + door_gap + (r + 0.5) * door_h + r * door_gap

        for c in range(cols):
            if cell_idx >= actual_doors:
                # Deterministic partial grid: cell remains OPEN (intentional undoored compartment)
                cell_idx += 1
                continue

            cell_idx += 1
            is_left_pivot = (c % 2 == 0)

            x_left = -width / 2.0 + stile_width + door_gap + c * col_pitch
            x_right = x_left + door_w

            if is_left_pivot:
                x_pivot = x_left
                angle = -door_angle
            else:
                x_pivot = x_right
                angle = +door_angle

            leaf = create_door_leaf(
                f"PB_Door_{r:02d}_{c:02d}", door_w, door_h, door_thickness,
                door_style, bevel_width, bevel_segments, is_left=is_left_pivot,
                furniture_finish=furniture_finish
            )
            leaf.location = (x_pivot, y_pivot, z_center)
            leaf.rotation_euler = (0.0, 0.0, angle)
            doors.append(leaf)

            if has_handles:
                # Geometrically derived handle placement inside solid wood stile bounds
                frame_w = min(0.05, door_w * 0.25)
                stile_center_offset = max(frame_w / 2.0, 0.02)
                
                if is_left_pivot:
                    # Hinge at X=0, opening edge at X=door_w. Wood stile spans [door_w - frame_w, door_w]
                    x_handle = door_w - stile_center_offset
                else:
                    # Hinge at X=0, opening edge at X=-door_w. Wood stile spans [-door_w, -door_w + frame_w]
                    x_handle = -door_w + stile_center_offset

                h_obj = create_handle(
                    f"PB_Handle_{r:02d}_{c:02d}", handle_style, handle_material,
                    bevel_width, bevel_segments, door_h=door_h
                )
                # Mount flush on front face of wood stile (Y = -door_thickness local), proud of door surface
                # Auto-centered vertically on each individual door leaf (Z = 0.0 local)
                h_obj.location = (x_handle, -door_thickness, 0.0)
                h_obj.parent = leaf

    return doors


# =========================================================
# PIEZA DE LIBRO (ligera — sin bevel)
# =========================================================
#
# A diferencia de create_box, esta NO agrega modifier de
# Bevel. Un librero con cientos de libros implica miles de
# estas piezas (4 por libro); un bevel por pieza es justo el
# tipo de costo que se pidió evitar ("evitar bevels pesados en
# cada pieza"). El bevel de la estructura (repisas/laterales)
# no se toca — solo las piezas de los libros se mantienen
# deliberadamente más simples.

def _bmesh_add_box(bm, dimensions, center, material_index):
    w, d, h = dimensions
    cx, cy, cz = center
    res = bmesh.ops.create_cube(bm, size=1.0)
    verts = res['verts']
    for v in verts:
        v.co.x = v.co.x * w + cx
        v.co.y = v.co.y * d + cy
        v.co.z = v.co.z * h + cz
    faces = [f for f in bm.faces if any(v in verts for v in f.verts)]
    for f in faces:
        f.material_index = material_index


def _build_upright_book_bmesh(bm, width, depth, height):
    half_x = width / 2.0
    half_y = depth / 2.0

    spine_t = min(max(depth * 0.03, 0.002), 0.008, depth * 0.2)
    if depth - spine_t <= 0.001:
        spine_t = depth * 0.1

    cover_t = min(max(width * 0.05, 0.0015), 0.004, width * 0.25)
    if width - 2 * cover_t <= 0.001:
        cover_t = width * 0.15

    cover_depth = max(0.0005, depth - spine_t)
    cover_center_y = -half_y + spine_t + cover_depth / 2.0

    # 1. Spine (Material Index 1)
    _bmesh_add_box(bm, (width, spine_t, height), (0.0, -half_y + spine_t / 2.0, 0.0), 1)

    # 2. Front Cover (Material Index 0)
    _bmesh_add_box(bm, (cover_t, cover_depth, height), (-half_x + cover_t / 2.0, cover_center_y, 0.0), 0)

    # 3. Back Cover (Material Index 0)
    _bmesh_add_box(bm, (cover_t, cover_depth, height), (half_x - cover_t / 2.0, cover_center_y, 0.0), 0)

    # 4. Pages (Material Index 2)
    page_margin_y = min(max(depth * 0.02, 0.001), 0.003, depth * 0.1)
    page_margin_z = min(max(height * 0.01, 0.001), 0.003, height * 0.1)

    pages_width = max(0.0005, width - 2 * cover_t)
    pages_depth = max(0.0005, depth - spine_t - page_margin_y)
    pages_height = max(0.0005, height - 2 * page_margin_z)
    pages_center_y = -half_y + spine_t + pages_depth / 2.0

    _bmesh_add_box(bm, (pages_width, pages_depth, pages_height), (0.0, pages_center_y, 0.0), 2)


def _build_horizontal_book_bmesh(bm, length, depth, thickness):
    half_y = depth / 2.0
    half_z = thickness / 2.0

    cover_t = min(max(thickness * 0.15, 0.0015), 0.006, thickness * 0.35)
    if thickness - 2 * cover_t <= 0.001:
        cover_t = thickness * 0.15

    spine_t = min(max(depth * 0.12, 0.002), 0.006, depth * 0.3)
    if depth - spine_t <= 0.001:
        spine_t = depth * 0.15

    cover_depth = max(0.0005, depth - spine_t)
    cover_center_y = -half_y + spine_t + cover_depth / 2.0

    # 1. Spine (Material Index 1)
    _bmesh_add_box(bm, (length, spine_t, thickness), (0.0, -half_y + spine_t / 2.0, 0.0), 1)

    # 2. Front Cover (Top) (Material Index 0)
    _bmesh_add_box(bm, (length, cover_depth, cover_t), (0.0, cover_center_y, half_z - cover_t / 2.0), 0)

    # 3. Back Cover (Bottom) (Material Index 0)
    _bmesh_add_box(bm, (length, cover_depth, cover_t), (0.0, cover_center_y, -half_z + cover_t / 2.0), 0)

    page_margin_x = min(max(length * 0.02, 0.001), 0.003, length * 0.1)
    page_margin_y = min(max(depth * 0.02, 0.001), 0.003, depth * 0.1)

    pages_length = max(0.0005, length - 2 * page_margin_x)
    pages_depth = max(0.0005, depth - spine_t - page_margin_y)
    pages_thickness = max(0.0005, thickness - 2 * cover_t)
    pages_center_y = -half_y + spine_t + pages_depth / 2.0

    _bmesh_add_box(bm, (pages_length, pages_depth, pages_thickness), (0.0, pages_center_y, 0.0), 2)


# =========================================================
# LIBRO PROCEDURAL (Fase 11 — BMesh Single-Mesh Optimization)
# =========================================================

def create_procedural_book(spec):
    width, depth, height = spec.dimensions

    if width <= 0.0 or depth <= 0.0 or height <= 0.0:
        raise ValueError(f"dimensiones inválidas para {spec.name}: {spec.dimensions}")

    local_seed = zlib.crc32(spec.name.encode("utf-8"))
    rng = random.Random(local_seed)

    cover_mat, spine_mat, page_mat = _get_or_create_book_materials(spec.name, rng)

    bm = bmesh.new()
    if spec.orientation == "horizontal":
        _build_horizontal_book_bmesh(bm, width, depth, height)
    else:
        _build_upright_book_bmesh(bm, width, depth, height)

    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)

    me = bpy.data.meshes.new(spec.name)
    bm.to_mesh(me)
    bm.free()
    me.update()

    obj = bpy.data.objects.new(spec.name, me)
    obj.location = spec.location
    obj.rotation_euler = spec.rotation_euler

    # Material slots: 0=Cover, 1=Spine, 2=Pages
    obj.data.materials.append(cover_mat)
    obj.data.materials.append(spine_mat)
    obj.data.materials.append(page_mat)

    bpy.context.collection.objects.link(obj)
    return obj


# =========================================================
# CREAR LIBRO A PARTIR DE UN SPEC
# =========================================================
#
# Esta sigue siendo la ÚNICA función que sabe traducir un
# BookSpec a geometría real. Ahora intenta construir el libro
# procedural (create_procedural_book); si algo falla, cae de
# vuelta al cubo (create_box) para que un problema en un solo
# libro nunca tumbe toda la generación. El algoritmo de layout
# (generate_shelf_zones) no se toca en ningún caso.

def create_book_from_spec(spec):

    try:

        return create_procedural_book(spec)

    except Exception as exc:

        print(
            f"[Procedural Bookshelf] Fallback a cubo para "
            f"{spec.name}: {exc}"
        )

        book = create_box(
            spec.name,
            spec.location,
            spec.dimensions,
            spec.bevel_width,
            2
        )

        book.rotation_euler = spec.rotation_euler

        return book


def place_books(specs):

    created = []

    for spec in specs:

        created.append(
            create_book_from_spec(spec)
        )

    return created


# =========================================================
# SEEDS DERIVADOS
# =========================================================
#
# Necesitamos varios flujos de aleatoriedad independientes por
# repisa: uno para decidir las ZONAS (cuántas, de qué tipo, qué
# ancho) y uno propio para cada GRUPO que se genera dentro de
# esas zonas. Si todos compartieran el mismo random.seed()
# global, el orden de las llamadas importaría y añadir un tipo
# de zona nuevo correría el riesgo de desincronizar el Seed de
# zonas ya existentes. Por eso cada flujo usa su propia
# instancia random.Random(...), derivada del Seed global de
# forma determinista pero independiente.

def _derive_seed(base_seed, *parts):

    value = base_seed

    for part in parts:

        value = value * 1000003 + part

    return value


# =========================================================
# NÚCLEO COMPARTIDO: LLENAR UNA LÍNEA HORIZONTAL DE LIBROS
# =========================================================
#
# Esta función contiene la física que ya teníamos (dimensiones,
# clamps, huella rotada, pivote en la base) pero ya no decide
# POR SÍ MISMA si un libro se inclina o no — eso lo decide quien
# la llama, mediante `tilt_mode`:
#
#   "mixed"  -> cada libro tiene una probabilidad `tilt` de
#               inclinarse, en cualquier dirección (comportamiento
#               de un grupo vertical con variación individual).
#   "forced" -> TODOS los libros de esta línea se inclinan, en la
#               misma dirección (`lean_direction`), con un ángulo
#               siempre visible (nunca casi cero). Así es como un
#               leaning_group se ve como un grupo coherente
#               recostado, no como libros verticales con ruido.
#
# El resto (avance en X, límites, nombres) es idéntico para
# ambos casos.

def _generate_book_line(
    rng,
    available_width,
    x_offset,
    shelf_z,
    depth,
    shelf_height,
    density,
    variation,
    tilt,
    thickness,
    name_prefix,
    tilt_mode="mixed",
    lean_direction=1,
    safety_margin=0.01,
    tilt_jitter_rad=0.0
):

    specs = []

    available_height = shelf_height - thickness - safety_margin

    if available_height <= 0:

        return specs

    available_depth = depth - safety_margin

    if available_depth <= 0:

        return specs

    x = -available_width / 2

    book_index = 0

    while x < available_width / 2:

        # -------------------------------------------------
        # DIMENSIONES RANDOM
        # -------------------------------------------------

        book_width = rng.uniform(
            0.035,
            0.075
        )

        book_height = rng.uniform(
            available_height * 0.65,
            available_height * 0.95
        )

        book_depth = rng.uniform(
            available_depth * 0.65,
            available_depth * 0.90
        )

        book_width *= rng.uniform(
            1.0 - variation,
            1.0 + variation
        )

        book_height *= rng.uniform(
            1.0 - variation,
            1.0 + variation
        )

        # Clamp final: garantía dura, independiente de variation

        book_height = min(book_height, available_height)
        book_depth = min(book_depth, available_depth)

        # -------------------------------------------------
        # INCLINACIÓN FÍSICA (Problema 2)
        # -------------------------------------------------
        #
        # rotation_y inclina el libro alrededor del eje
        # horizontal (Y de Blender) — el efecto "/" que se
        # pedía. El ángulo máximo escala con el parámetro Tilt.

        max_angle = tilt * MAX_TILT_ANGLE

        rotation_y = 0.0

        if tilt_mode == "forced":

            # Grupo inclinado: siempre hay ángulo, siempre en
            # la misma dirección, y nunca casi cero — si no, el
            # grupo no se ve como una composición intencional.

            if max_angle > 0:

                base_angle = lean_direction * rng.uniform(
                    max_angle * 0.5,
                    max_angle
                )
                # Modulación determinística por repisa y grupo limitada a [-2°, +2°]
                rotation_y = base_angle + (lean_direction * tilt_jitter_rad)

        else:

            if rng.random() < tilt:

                rotation_y = rng.uniform(
                    -max_angle,
                    max_angle
                )

        half_width = book_width / 2
        half_height = book_height / 2

        cos_r = abs(math.cos(rotation_y))
        sin_r = abs(math.sin(rotation_y))

        # -------------------------------------------------
        # HUELLA EFECTIVA TRAS ROTAR (Problema 3)
        # -------------------------------------------------

        effective_half_width = (
            half_width * cos_r
            + half_height * sin_r
        )

        effective_half_height = (
            half_width * sin_r
            + half_height * cos_r
        )

        if effective_half_height > available_height / 2:

            if cos_r > 0:

                half_height = max(
                    0.0,
                    (
                        available_height / 2
                        - half_width * sin_r
                    )
                ) / cos_r

                book_height = half_height * 2

                effective_half_height = (
                    half_width * sin_r
                    + half_height * cos_r
                )

        effective_width = effective_half_width * 2

        if x + effective_width > available_width / 2:

            break

        # -------------------------------------------------
        # POSICIÓN (pivote en la base, ver Problema 2)
        # -------------------------------------------------

        z = (
            shelf_z
            + thickness / 2
            + effective_half_height
        )

        max_y_offset = max(
            0.0,
            (available_depth - book_depth) / 2
        )

        y = rng.uniform(
            -max_y_offset,
            max_y_offset
        )

        # -------------------------------------------------
        # SPEC (sin crear geometría todavía)
        # -------------------------------------------------

        specs.append(
            BookSpec(
                name=f"{name_prefix}_{book_index:02d}",
                location=(
                    x_offset + x + effective_half_width,
                    y,
                    z
                ),
                dimensions=(
                    book_width,
                    book_depth,
                    book_height
                ),
                rotation_euler=(0.0, rotation_y, 0.0),
                bevel_width=0.0015,
                orientation=(
                    "vertical" if rotation_y == 0.0
                    else "leaning_right" if rotation_y > 0.0
                    else "leaning_left"
                )
            )
        )

        # Separación intra-grupo (≈ 2.5 mm entre libros compactos)
        gap = rng.uniform(
            0.002,
            0.003
        )

        x += effective_width + gap

        book_index += 1

    return specs


# =========================================================
# GRUPO VERTICAL
# =========================================================
#
# Envoltorio delgado sobre _generate_book_line: cada libro
# tiene una probabilidad `tilt` de inclinarse individualmente,
# en cualquier dirección — es el comportamiento que ya
# validamos en el paso anterior.

def generate_vertical_group_books(
    rng,
    available_width,
    x_offset,
    shelf_z,
    depth,
    shelf_height,
    density,
    variation,
    tilt,
    thickness,
    name_prefix,
    safety_margin=0.01
):

    if density <= 0.0:

        return []

    effective_width = max(0.035, available_width * density)

    return _generate_book_line(
        rng=rng,
        available_width=effective_width,
        x_offset=x_offset,
        shelf_z=shelf_z,
        depth=depth,
        shelf_height=shelf_height,
        density=1.0,
        variation=variation,
        tilt=tilt,
        thickness=thickness,
        name_prefix=name_prefix,
        tilt_mode="mixed",
        safety_margin=safety_margin
    )


def generate_leaning_group_books(
    rng,
    available_width,
    x_offset,
    shelf_z,
    depth,
    shelf_height,
    density,
    variation,
    tilt,
    thickness,
    name_prefix,
    lean_direction,
    safety_margin=0.01,
    tilt_jitter_rad=0.0
):

    if density <= 0.0:

        return []

    effective_width = max(0.04, available_width * density)

    return _generate_book_line(
        rng=rng,
        available_width=effective_width,
        x_offset=x_offset,
        shelf_z=shelf_z,
        depth=depth,
        shelf_height=shelf_height,
        density=1.0,
        variation=variation,
        tilt=tilt,
        thickness=thickness,
        name_prefix=name_prefix,
        tilt_mode="forced",
        lean_direction=lean_direction,
        safety_margin=safety_margin,
        tilt_jitter_rad=tilt_jitter_rad
    )


def generate_horizontal_stack_books(
    rng,
    available_width,
    x_offset,
    shelf_z,
    depth,
    shelf_height,
    density,
    variation,
    thickness,
    name_prefix,
    safety_margin=0.01,
    min_books_override=None
):

    if density <= 0.0:

        return []

    specs = []

    available_height = shelf_height - thickness - safety_margin

    if available_height <= 0:

        return specs

    available_depth = depth - safety_margin

    if available_depth <= 0:

        return specs

    effective_width = max(HORIZONTAL_BOOK_MIN_LENGTH, available_width * density)

    min_books = 1 if density < 0.6 else 2
    if min_books_override is not None:
        min_books = max(min_books, min_books_override)

    max_books = max(min_books, min(5, round(1 + 4 * density)))
    num_books = rng.randint(min_books, max_books)

    raw_books = []

    for i in range(num_books):

        length = rng.uniform(
            HORIZONTAL_BOOK_MIN_LENGTH,
            HORIZONTAL_BOOK_MAX_LENGTH
        )

        length *= rng.uniform(
            1.0 - variation,
            1.0 + variation
        )

        length = min(
            length,
            HORIZONTAL_BOOK_MAX_LENGTH,
            effective_width
        )

        spine = rng.uniform(0.025, 0.05)

        spine *= rng.uniform(
            1.0 - variation,
            1.0 + variation
        )

        book_depth = rng.uniform(
            available_depth * 0.65,
            available_depth * 0.90
        )

        book_depth = min(book_depth, available_depth)

        raw_books.append((length, spine, book_depth))

    total_spine = sum(spine for _, spine, _ in raw_books)

    if total_spine > available_height:

        scale = available_height / total_spine

        raw_books = [
            (length, spine * scale, book_depth)
            for length, spine, book_depth in raw_books
        ]

    z_cursor = shelf_z + thickness / 2

    for i, (length, spine, book_depth) in enumerate(raw_books):

        max_y_offset = max(
            0.0,
            (available_depth - book_depth) / 2
        )

        y = rng.uniform(
            -max_y_offset,
            max_y_offset
        )

        z = z_cursor + spine / 2

        specs.append(
            BookSpec(
                name=f"{name_prefix}_{i:02d}",
                location=(
                    x_offset,
                    y,
                    z
                ),
                dimensions=(
                    length,
                    book_depth,
                    spine
                ),
                rotation_euler=(0.0, 0.0, 0.0),
                bevel_width=0.0015,
                orientation="horizontal"
            )
        )

        z_cursor += spine

    return specs


# =========================================================
# ZONAS: DECIDIR QUÉ TIPO DE GRUPO OCUPA CADA TRAMO
# =========================================================
#
# Ahora sí divide la repisa en varios tramos (zonas), cada uno
# con su propio tipo: vertical_group, leaning_group o
# horizontal_stack. Los pesos son el punto de partida que
# pediste (60-75% / 10-20% / 10-20%) — quedan como constantes
# fáciles de ajustar o exponer en la UI más adelante.

VERTICAL_GROUP_WEIGHT = 0.65
LEANING_GROUP_WEIGHT = 0.17
HORIZONTAL_STACK_WEIGHT = 0.18

MIN_ZONE_WIDTH = 0.15


def generate_shelf_zones(
    width,
    shelf_z,
    depth,
    shelf_height,
    density,
    variation,
    tilt,
    seed,
    shelf_index,
    thickness,
    safety_margin=0.01
):

    if density <= 0.0:

        return []

    available_width = width - thickness * 2

    zone_seed = _derive_seed(seed, shelf_index, 999)

    zone_rng = random.Random(zone_seed)

    zones = []

    x_cursor = -available_width / 2

    zone_index = 0

    while (available_width / 2 - x_cursor) >= MIN_ZONE_WIDTH:

        remaining = available_width / 2 - x_cursor

        zone_width = min(
            remaining,
            zone_rng.uniform(0.20, 0.45) * available_width
        )

        if zone_width < MIN_ZONE_WIDTH:

            break

        zone_center = x_cursor + zone_width / 2

        roll = zone_rng.random()

        if roll < HORIZONTAL_STACK_WEIGHT:

            group_type = "horizontal_stack"

        elif roll < HORIZONTAL_STACK_WEIGHT + LEANING_GROUP_WEIGHT:

            group_type = "leaning_group"

        else:

            group_type = "vertical_group"

        type_tag = {
            "vertical_group": 1,
            "leaning_group": 2,
            "horizontal_stack": 3
        }[group_type]

        group_seed = _derive_seed(
            seed,
            shelf_index,
            zone_index,
            type_tag
        )

        group_rng = random.Random(group_seed)

        name_prefix = f"PB_Book_{shelf_index:02d}_{zone_index:02d}"

        if group_type == "leaning_group":

            lean_direction = zone_rng.choice([-1, 1])

            books = generate_leaning_group_books(
                rng=group_rng,
                available_width=zone_width,
                x_offset=zone_center,
                shelf_z=shelf_z,
                depth=depth,
                shelf_height=shelf_height,
                density=density,
                variation=variation,
                tilt=tilt,
                thickness=thickness,
                name_prefix=name_prefix,
                lean_direction=lean_direction,
                safety_margin=safety_margin
            )

        elif group_type == "horizontal_stack":

            books = generate_horizontal_stack_books(
                rng=group_rng,
                available_width=zone_width,
                x_offset=zone_center,
                shelf_z=shelf_z,
                depth=depth,
                shelf_height=shelf_height,
                density=density,
                variation=variation,
                thickness=thickness,
                name_prefix=name_prefix,
                safety_margin=safety_margin
            )

        else:

            books = generate_vertical_group_books(
                rng=group_rng,
                available_width=zone_width,
                x_offset=zone_center,
                shelf_z=shelf_z,
                depth=depth,
                shelf_height=shelf_height,
                density=density,
                variation=variation,
                tilt=tilt,
                thickness=thickness,
                name_prefix=name_prefix,
                safety_margin=safety_margin
            )

        if books:

            zones.append(
                GroupSpec(
                    group_type=group_type,
                    x_start=zone_center - zone_width / 2,
                    x_end=zone_center + zone_width / 2,
                    books=books
                )
            )

        # Espacio entre zonas: escala con Density para que a Density=1.0
        # las zonas queden compactas sin huecos arbitrarios, y a menor
        # densidad se abran espacios libres naturales entre grupos.

        max_zone_gap = 0.02 + 0.12 * (1.0 - density)
        zone_gap = zone_rng.uniform(0.0, max_zone_gap)

        x_cursor += zone_width + zone_gap

        zone_index += 1

    return zones


# =========================================================
# CONSTRUCTORES DE PLANES Y TRADUCTOR DE PLANES (Fase 1)
# =========================================================

def build_group_plan(
    group_type: str,
    x_start: float,
    x_end: float,
    density: float,
    role: str = "support",
    mass_anchor: float = 0.5,
    lean_direction: int = 1,
    internal_role: str = "primary"
) -> GroupPlan:

    min_books = 2 if group_type == "horizontal_stack" else 1

    return GroupPlan(
        group_type=group_type,
        x_start=x_start,
        x_end=x_end,
        role=role,
        mass_budget=density,
        mass_anchor=mass_anchor,
        lean_direction=lean_direction,
        min_books=min_books,
        internal_role=internal_role
    )


def build_zone_plan(
    zone_index: int,
    x_start: float,
    x_end: float,
    zone_type: str,
    group_plan: Optional[GroupPlan] = None
) -> ZonePlan:

    return ZonePlan(
        zone_index=zone_index,
        x_start=x_start,
        x_end=x_end,
        zone_type=zone_type,
        group=group_plan
    )


def build_shelf_macro_intents(
    shelves_count: int,
    density: float,
    seed: int
) -> tuple:

    macro_rng = random.Random(_derive_seed(seed, 9000))

    patterns = ["hero_central", "zigzag", "asymmetric_pyramid", "frame_diagonal"]

    macro_pattern = macro_rng.choice(patterns)

    role_templates = {
        "hero_central": ["anchor", "quiet", "focal_primary", "support", "focal_secondary"],
        "zigzag": ["anchor", "focal_secondary", "quiet", "focal_primary", "support"],
        "asymmetric_pyramid": ["anchor", "focal_primary", "support", "focal_secondary", "quiet"],
        "frame_diagonal": ["anchor", "quiet", "focal_primary", "focal_secondary", "support"]
    }

    roles = list(role_templates.get(macro_pattern, role_templates["hero_central"]))

    if len(roles) < shelves_count:

        roles.extend(["support"] * (shelves_count - len(roles)))

    elif len(roles) > shelves_count:

        roles = roles[:shelves_count]

    if macro_rng.random() < 0.35 and shelves_count == 5:

        roles[1], roles[3] = roles[3], roles[1]

    anchor_templates = {
        "hero_central": [0.18, 0.82, 0.35, 0.72, 0.26],
        "zigzag": [0.82, 0.22, 0.76, 0.28, 0.85],
        "asymmetric_pyramid": [0.15, 0.38, 0.62, 0.84, 0.20],
        "frame_diagonal": [0.12, 0.85, 0.38, 0.18, 0.88]
    }

    base_anchors = anchor_templates.get(macro_pattern, [0.5] * shelves_count)

    intents = []

    for i in range(shelves_count):

        role = roles[i]

        # Mapeo continuo de shelf_mass_ratio según el rol y la densidad global
        # Banderas aprobadas para Density = 0.50: quiet ~ 0.25, support ~ 0.50, focal_sec ~ 0.58, anchor ~ 0.62, focal_pri ~ 0.70
        # Banderas aprobadas para Density = 1.00: quiet ~ 0.50, support ~ 0.80, focal_sec ~ 0.86, anchor ~ 0.90, focal_pri ~ 0.95
        mass_params = {
            "quiet": (0.05, 0.45),
            "support": (0.20, 0.60),
            "focal_secondary": (0.30, 0.56),
            "anchor": (0.35, 0.55),
            "focal_primary": (0.40, 0.55)
        }.get(role, (0.20, 0.60))

        base_m = mass_params[0] + density * mass_params[1]

        noise_mass = macro_rng.uniform(-0.03, 0.03)

        shelf_mass_ratio = min(0.98, max(0.10, base_m + noise_mass))

        if density <= 0.55 and role == "quiet":

            shelf_mass_ratio = max(0.29, shelf_mass_ratio)

        base_anchor = base_anchors[i] if i < len(base_anchors) else 0.5

        noise_anchor = macro_rng.uniform(-0.08, 0.08)

        target_anchor = min(0.95, max(0.05, base_anchor + noise_anchor))

        if role == "quiet" or shelf_mass_ratio < 0.25:

            group_options = [1, 2] if macro_rng.random() < 0.3 else [1]

        elif role == "focal_primary" and shelf_mass_ratio > 0.40:

            group_options = [2, 3]

        else:

            group_options = [1, 2, 3]

        target_group_count = macro_rng.choice(group_options)

        if role == "focal_primary":

            accent_kind = macro_rng.choice(["leaning", "stack", "leaning"])

        elif role == "focal_secondary":

            accent_kind = macro_rng.choice(["leaning", "stack", "none"])

        elif role == "anchor":

            accent_kind = macro_rng.choice(["stack", "none"])

        else:

            accent_kind = "none"

        accent_noise = macro_rng.uniform(-0.06, 0.06)

        accent_anchor = min(0.95, max(0.05, target_anchor + accent_noise))

        intents.append(
            ShelfMacroIntent(
                shelf_index=i,
                role=role,
                shelf_mass_ratio=round(shelf_mass_ratio, 2),
                target_anchor=round(target_anchor, 2),
                target_group_count=target_group_count,
                accent_kind=accent_kind,
                accent_anchor=round(accent_anchor, 2)
            )
        )

    return macro_pattern, intents

def build_shelf_plan(
    shelf_index: int,
    z_location: float,
    width: float,
    shelf_height: float,
    density: float,
    seed: int,
    thickness: float,
    macro_intent: Optional[ShelfMacroIntent] = None
) -> ShelfPlan:

    available_width = width - thickness * 2

    zone_seed = _derive_seed(seed, shelf_index, 999)

    zone_rng = random.Random(zone_seed)

    shelf_intent_name = macro_intent.role if macro_intent else "standard_shelf"

    shelf_plan = ShelfPlan(
        shelf_index=shelf_index,
        z_location=z_location,
        available_width=available_width,
        available_height=shelf_height,
        intent=shelf_intent_name,
        macro_intent=macro_intent
    )

    x_cursor = -available_width / 2

    zone_idx = 0

    target_groups = macro_intent.target_group_count if macro_intent else 2

    shelf_mass_ratio = macro_intent.shelf_mass_ratio if macro_intent else density

    target_anchor = macro_intent.target_anchor if macro_intent else 0.5

    accent_kind = macro_intent.accent_kind if macro_intent else "none"

    # 1. Márgenes Exteriores Protegidos
    base_margin = 0.02 + 0.05 * (1.0 - shelf_mass_ratio)

    margin_left = min(0.08, max(0.02, base_margin))

    margin_right = margin_left

    sum_margins = margin_left + margin_right

    # 2. Funciones Jerárquicas por N (Pesos de Masa)
    # primary = 1.40, secondary = 0.80, accent = 0.45
    if target_groups == 1:

        internal_roles = ["primary"]

        hierarchy_weights = [1.25]

        mass_weights = [1.40]

    elif target_groups == 2:

        if accent_kind != "none":

            internal_roles = ["primary", "accent"]

            hierarchy_weights = [1.25, 0.55]

            mass_weights = [1.40, 0.45]

        else:

            internal_roles = ["primary", "secondary"]

            hierarchy_weights = [1.25, 0.80]

            mass_weights = [1.40, 0.80]

    else:

        internal_roles = ["accent", "primary", "secondary"]

        hierarchy_weights = [0.55, 1.25, 0.80]

        mass_weights = [0.45, 1.40, 0.80]

    # 3. Presupuesto Global de Masa de Repisa (con factor de calibración eta_calib = 0.90)
    ETA_CALIB = 0.90

    W_mass_shelf_total = available_width * shelf_mass_ratio * ETA_CALIB

    sum_mass_weights = sum(mass_weights)

    planned_mass_widths_raw = [
        W_mass_shelf_total * (w / sum_mass_weights) for w in mass_weights
    ]

    # Factor de expansión de envelope dinámico y gaps según la densidad global del usuario
    ref_density = density

    if ref_density <= 0.55:

        env_factor = 1.35

    elif ref_density <= 0.80:

        env_factor = 1.25

    else:

        env_factor = 1.15

    envelopes_raw = [mw * env_factor for mw in planned_mass_widths_raw]

    # Derivación de sobre para horizontal_stack basada en su ancho físico real (+ 25% de holgura)
    for g_i in range(target_groups):

        i_role = internal_roles[g_i]

        if target_groups == 1:

            is_stack = (accent_kind == "stack")

        else:

            is_stack = (i_role == "accent" and accent_kind == "stack")

        if is_stack:

            stack_phys_w = 0.38

            stack_env_w = stack_phys_w * 1.25

            planned_mass_widths_raw[g_i] = stack_phys_w

            envelopes_raw[g_i] = stack_env_w

    sum_envelopes_raw = sum(envelopes_raw)

    # 4. Gaps Arquitectónicos por Densidad con Desfasamiento Determinista Alternado (Opción A)
    num_gaps = max(0, target_groups - 1)

    gap_widths = []

    for g_k in range(num_gaps):

        role_a = internal_roles[g_k]

        role_b = internal_roles[g_k + 1]

        roles_pair = {role_a, role_b}

        if ref_density <= 0.55:

            if "primary" in roles_pair and "accent" in roles_pair:

                gap_w_base = 0.240

            elif "primary" in roles_pair and "secondary" in roles_pair:

                gap_w_base = 0.280

            else:

                gap_w_base = 0.260

        elif ref_density <= 0.80:

            if "primary" in roles_pair and "accent" in roles_pair:

                gap_w_base = 0.140

            elif "primary" in roles_pair and "secondary" in roles_pair:

                gap_w_base = 0.180

            else:

                gap_w_base = 0.160

        else:

            if "primary" in roles_pair and "accent" in roles_pair:

                gap_w_base = 0.130

            elif "primary" in roles_pair and "secondary" in roles_pair:

                gap_w_base = 0.160

            else:

                gap_w_base = 0.145

        # Desfasamiento determinista alternado por repisa y gap: gap_jitter_{s,k} = (-1) ** (s + k) * uniform(0.010, 0.015)
        gap_seed = _derive_seed(seed, shelf_index, 5000 + g_k * 71)

        gap_rng = random.Random(gap_seed)

        sign = (-1) ** (shelf_index + g_k)

        mag = gap_rng.uniform(0.010, 0.015)

        gap_jitter = sign * mag

        if ref_density <= 0.55:

            clamped_gap = max(0.180, min(0.380, gap_w_base + gap_jitter))

        elif ref_density <= 0.80:

            clamped_gap = max(0.120, min(0.250, gap_w_base + gap_jitter))

        else:

            clamped_gap = max(0.120, min(0.180, gap_w_base + gap_jitter))

        gap_widths.append(clamped_gap)

    sum_gaps = sum(gap_widths)

    # 5. Evaluación de Factibilidad y Alpha
    w_req_raw = sum_margins + sum_envelopes_raw + sum_gaps

    if w_req_raw > available_width:

        w_env_allowed = max(0.01, available_width - sum_margins - sum_gaps)

        alpha = w_env_allowed / sum_envelopes_raw

        planned_mass_widths = [mw * alpha for mw in planned_mass_widths_raw]

        group_envelopes = [env * alpha for env in envelopes_raw]

        outer_negative_space = 0.0

    else:

        alpha = 1.0000

        planned_mass_widths = planned_mass_widths_raw

        group_envelopes = envelopes_raw

        outer_negative_space = available_width - w_req_raw

    # 6. Distribución de Negative Space por target_anchor y Construcción Secuencial de Zonas
    outer_neg_left = outer_negative_space * target_anchor
    outer_neg_right = outer_negative_space * (1.0 - target_anchor)

    margin_zone_l = build_zone_plan(
        zone_index=zone_idx,
        x_start=x_cursor,
        x_end=x_cursor + margin_left,
        zone_type="MARGIN"
    )

    shelf_plan.zones.append(margin_zone_l)

    x_cursor += margin_left

    zone_idx += 1

    if outer_neg_left > 0.0005:

        outer_zone_l = build_zone_plan(
            zone_index=zone_idx,
            x_start=x_cursor,
            x_end=x_cursor + outer_neg_left,
            zone_type="OUTER_NEGATIVE_SPACE"
        )

        shelf_plan.zones.append(outer_zone_l)

        x_cursor += outer_neg_left

        zone_idx += 1

    mean_h_w = sum(hierarchy_weights) / len(hierarchy_weights)

    for g_i in range(target_groups):

        env_w = group_envelopes[g_i]

        mass_w = planned_mass_widths[g_i]

        i_role = internal_roles[g_i]

        i_weight = hierarchy_weights[g_i]

        norm_factor = i_weight / mean_h_w

        group_mass_budget = min(0.98, max(0.10, mass_w / env_w))

        if target_groups == 1:

            if accent_kind == "leaning":

                group_type = "leaning_group"

            elif accent_kind == "stack":

                group_type = "horizontal_stack"

            else:

                group_type = "vertical_group"

        else:

            if i_role == "accent":

                group_type = "leaning_group" if accent_kind == "leaning" else ("horizontal_stack" if accent_kind == "stack" else "leaning_group")

            else:

                group_type = "vertical_group"

        if i_role == "primary":

            group_anchor = target_anchor

        elif i_role == "accent":

            group_anchor = macro_intent.accent_anchor if macro_intent else target_anchor

        else:

            p_anchor = target_anchor

            a_anchor = macro_intent.accent_anchor if (macro_intent and "accent" in internal_roles) else target_anchor

            group_anchor = min(0.80, max(0.20, 1.0 - (p_anchor + a_anchor) / 2.0))

        lean_direction = zone_rng.choice([-1, 1])

        group_plan = build_group_plan(
            group_type=group_type,
            x_start=x_cursor,
            x_end=x_cursor + env_w,
            density=group_mass_budget,
            role=shelf_intent_name,
            mass_anchor=group_anchor,
            lean_direction=lean_direction,
            internal_role=i_role
        )

        active_zone = build_zone_plan(
            zone_index=zone_idx,
            x_start=x_cursor,
            x_end=x_cursor + env_w,
            zone_type="ACTIVE_GROUP",
            group_plan=group_plan
        )

        shelf_plan.zones.append(active_zone)

        x_cursor += env_w

        zone_idx += 1

        if g_i < num_gaps:

            gap_w = gap_widths[g_i]

            gap_zone = build_zone_plan(
                zone_index=zone_idx,
                x_start=x_cursor,
                x_end=x_cursor + gap_w,
                zone_type="NEGATIVE_SPACE"
            )

            shelf_plan.zones.append(gap_zone)

            x_cursor += gap_w

            zone_idx += 1

    if outer_neg_right > 0.0005:

        outer_zone_r = build_zone_plan(
            zone_index=zone_idx,
            x_start=x_cursor,
            x_end=x_cursor + outer_neg_right,
            zone_type="OUTER_NEGATIVE_SPACE"
        )

        shelf_plan.zones.append(outer_zone_r)

        x_cursor += outer_neg_right

        zone_idx += 1

    margin_zone_r = build_zone_plan(
        zone_index=zone_idx,
        x_start=x_cursor,
        x_end=available_width / 2,
        zone_type="MARGIN"
    )

    shelf_plan.zones.append(margin_zone_r)

    return shelf_plan


def build_composition_plan(
    width: float,
    height: float,
    depth: float,
    shelves: int,
    density: float,
    variation: float,
    tilt: float,
    seed: int,
    thickness: float = 0.06
) -> CompositionPlan:

    macro_pattern, macro_intents = build_shelf_macro_intents(
        shelves_count=shelves,
        density=density,
        seed=seed
    )

    spacing = height / shelves

    comp_plan = CompositionPlan(
        total_width=width,
        total_height=height,
        total_depth=depth,
        shelves_count=shelves,
        density=density,
        variation=variation,
        tilt=tilt,
        seed=seed,
        macro_pattern=macro_pattern,
        macro_intents=macro_intents
    )

    for shelf_index in range(shelves):

        shelf_z = shelf_index * spacing

        intent_for_shelf = macro_intents[shelf_index] if shelf_index < len(macro_intents) else None

        s_plan = build_shelf_plan(
            shelf_index=shelf_index,
            z_location=shelf_z,
            width=width,
            shelf_height=spacing,
            density=density,
            seed=seed,
            thickness=thickness,
            macro_intent=intent_for_shelf
        )

        comp_plan.shelves.append(s_plan)

    return comp_plan


def dump_composition_plan(plan: CompositionPlan) -> str:

    lines = []

    lines.append(
        f"CompositionPlan ("
        f"Width={plan.total_width:.2f}, "
        f"Height={plan.total_height:.2f}, "
        f"Shelves={plan.shelves_count}, "
        f"Density={plan.density:.2f}, "
        f"Seed={plan.seed}, "
        f"Pattern={plan.macro_pattern})"
    )

    for shelf in plan.shelves:

        mi = shelf.macro_intent

        intent_str = f"role={shelf.intent}"

        if mi:

            intent_str += (
                f", mass_ratio={mi.shelf_mass_ratio:.2f}, "
                f"t_anchor={mi.target_anchor:.2f}, "
                f"t_groups={mi.target_group_count}, "
                f"accent={mi.accent_kind}@{mi.accent_anchor:.2f}"
            )

        lines.append(
            f"  Shelf {shelf.shelf_index} "
            f"(Z={shelf.z_location:.2f}m | {intent_str}):"
        )

        for zone in shelf.zones:

            if zone.zone_type == "ACTIVE_GROUP" and zone.group:

                grp = zone.group

                zone_w = zone.x_end - zone.x_start

                occ_w = zone_w * grp.mass_budget

                lines.append(
                    f"    Zone {zone.zone_index}: ACTIVE_GROUP "
                    f"[{zone.x_start:+.3f}m to {zone.x_end:+.3f}m] "
                    f"(zone_width={zone_w:.3f}m)"
                )

                lines.append(
                    f"      Group: type={grp.group_type}, "
                    f"role={grp.role}/{grp.internal_role}, "
                    f"lean_dir={grp.lean_direction}, "
                    f"mass_budget={grp.mass_budget:.2f}, "
                    f"mass_anchor={grp.mass_anchor:.2f} "
                    f"(occupied={occ_w:.3f}m, empty={zone_w - occ_w:.3f}m)"
                )

            else:

                lines.append(
                    f"    Zone {zone.zone_index}: {zone.zone_type.lower()} "
                    f"[{zone.x_start:+.3f}m to {zone.x_end:+.3f}m]"
                )

    output = "\n".join(lines)

    print(output)

    return output


def generate_specs_from_group_plan(
    group_plan: GroupPlan,
    shelf_z: float,
    depth: float,
    shelf_height: float,
    density: float,
    variation: float,
    tilt: float,
    thickness: float,
    seed: int,
    shelf_index: int,
    zone_index: int,
    safety_margin: float = 0.01
) -> List[BookSpec]:

    if group_plan.group_type == "empty" or group_plan.mass_budget <= 0.0:

        return []

    zone_width = group_plan.x_end - group_plan.x_start

    occupied_width = zone_width * group_plan.mass_budget

    available_travel = max(0.0, zone_width - occupied_width)

    x_start_mass = group_plan.x_start + available_travel * group_plan.mass_anchor

    x_offset = x_start_mass + occupied_width / 2

    type_tag = {
        "vertical_group": 1,
        "leaning_group": 2,
        "horizontal_stack": 3
    }.get(group_plan.group_type, 1)

    group_seed = _derive_seed(
        seed,
        shelf_index,
        zone_index,
        type_tag
    )

    group_rng = random.Random(group_seed)

    name_prefix = f"PB_Book_{shelf_index:02d}_{zone_index:02d}"

    if group_plan.group_type == "leaning_group":

        tilt_jitter_seed = _derive_seed(seed, shelf_index, zone_index * 137 + 7777)

        tilt_jitter_rng = random.Random(tilt_jitter_seed)

        sign = (-1) ** (shelf_index + zone_index)

        jitter_deg = sign * tilt_jitter_rng.uniform(1.5, 2.0)

        tilt_jitter_rad = math.radians(jitter_deg)

        return generate_leaning_group_books(
            rng=group_rng,
            available_width=zone_width,
            x_offset=x_offset,
            shelf_z=shelf_z,
            depth=depth,
            shelf_height=shelf_height,
            density=group_plan.mass_budget,
            variation=variation,
            tilt=tilt,
            thickness=thickness,
            name_prefix=name_prefix,
            lean_direction=group_plan.lean_direction,
            safety_margin=safety_margin,
            tilt_jitter_rad=tilt_jitter_rad
        )

    elif group_plan.group_type == "horizontal_stack":

        min_books_ovr = 3 if (group_plan.role == "anchor" and group_plan.mass_budget <= 0.85) else None

        return generate_horizontal_stack_books(
            rng=group_rng,
            available_width=zone_width,
            x_offset=x_offset,
            shelf_z=shelf_z,
            depth=depth,
            shelf_height=shelf_height,
            density=group_plan.mass_budget,
            variation=variation,
            thickness=thickness,
            name_prefix=name_prefix,
            safety_margin=safety_margin,
            min_books_override=min_books_ovr
        )

    else:

        return generate_vertical_group_books(
            rng=group_rng,
            available_width=zone_width,
            x_offset=x_offset,
            shelf_z=shelf_z,
            depth=depth,
            shelf_height=shelf_height,
            density=group_plan.mass_budget,
            variation=variation,
            tilt=tilt,
            thickness=thickness,
            name_prefix=name_prefix,
            safety_margin=safety_margin
        )


def generate_specs_from_composition_plan(
    composition_plan: CompositionPlan,
    depth: float,
    thickness: float,
    safety_margin: float = 0.01
) -> List[BookSpec]:

    all_specs = []

    for shelf_plan in composition_plan.shelves:

        for zone_plan in shelf_plan.zones:

            if zone_plan.zone_type == "ACTIVE_GROUP" and zone_plan.group is not None:

                specs = generate_specs_from_group_plan(
                    group_plan=zone_plan.group,
                    shelf_z=shelf_plan.z_location,
                    depth=depth,
                    shelf_height=shelf_plan.available_height,
                    density=composition_plan.density,
                    variation=composition_plan.variation,
                    tilt=composition_plan.tilt,
                    thickness=thickness,
                    seed=composition_plan.seed,
                    shelf_index=shelf_plan.shelf_index,
                    zone_index=zone_plan.zone_index,
                    safety_margin=safety_margin
                )

                all_specs.extend(specs)

    return all_specs


# =========================================================
# VALIDACIÓN (Fase 4)
# =========================================================
#
# Esta es la red de seguridad: recorre los BookSpec YA
# GENERADOS y confirma que nada se sale del volumen del
# librero ni se superpone con otro libro. Es deliberadamente
# independiente de los generadores — no confía en que cada
# generador (vertical/leaning/stack) se comportó bien, lo
# COMPRUEBA desde afuera, con los datos finales.
#
# Por ahora solo detecta y reporta (no corrige ni regenera).
# Corregir automáticamente es una decisión de diseño más
# delicada — mejor confirmar primero que el detector es
# confiable antes de dejarlo tocar la generación.

def compute_world_aabb(spec):

    hw = spec.dimensions[0] / 2
    hd = spec.dimensions[1] / 2
    hh = spec.dimensions[2] / 2

    # Todas las rotaciones que generamos son (0, ry, 0) — solo
    # eje Y. Si en el futuro se usan otros ejes, esta función
    # necesita generalizarse; por ahora es válida para el 100%
    # de los BookSpec que produce este archivo.

    ry = spec.rotation_euler[1]

    cos_r = abs(math.cos(ry))
    sin_r = abs(math.sin(ry))

    ehx = hw * cos_r + hh * sin_r
    ehz = hw * sin_r + hh * cos_r
    ehy = hd

    cx, cy, cz = spec.location

    return (
        cx - ehx, cx + ehx,
        cy - ehy, cy + ehy,
        cz - ehz, cz + ehz
    )


def _aabbs_overlap(a, b, epsilon=0.0005):

    return (
        a[0] < b[1] - epsilon and b[0] < a[1] - epsilon and
        a[2] < b[3] - epsilon and b[2] < a[3] - epsilon and
        a[4] < b[5] - epsilon and b[4] < a[5] - epsilon
    )


def validate_all_books(all_specs, width, height, depth, thickness, back_thickness=0.0):

    problems = []

    inner_x = width / 2 - thickness
    inner_y = depth / 2
    min_y_limit = -inner_y + back_thickness - 0.001

    aabbs = {}

    for spec in all_specs:

        aabb = compute_world_aabb(spec)

        aabbs[spec.name] = aabb

        min_x, max_x, min_y, max_y, min_z, max_z = aabb

        if min_x < -inner_x - 0.001 or max_x > inner_x + 0.001:

            problems.append(
                f"{spec.name}: se sale del ancho del librero "
                f"(x: {min_x:.4f} a {max_x:.4f}, límite ±{inner_x:.4f})"
            )

        if min_y < min_y_limit or max_y > inner_y + 0.001:

            problems.append(
                f"{spec.name}: se sale de la profundidad "
                f"(y: {min_y:.4f} a {max_y:.4f}, límite {min_y_limit:.4f} a {inner_y:.4f})"
            )

        if min_z < -0.001 or max_z > height + 0.001:

            problems.append(
                f"{spec.name}: se sale de la altura del librero "
                f"(z: {min_z:.4f} a {max_z:.4f}, límite 0 a {height:.4f})"
            )

    # -------------------------------------------------
    # OVERLAPS: comparación por pares. O(n²) — aceptable para
    # las cantidades actuales; si en Fase 12 (optimización)
    # esto se vuelve un cuello de botella, se puede acelerar
    # agrupando primero por repisa (los libros de repisas
    # distintas nunca pueden superponerse en Z).
    # -------------------------------------------------

    names = list(aabbs.keys())

    for i in range(len(names)):

        for j in range(i + 1, len(names)):

            if _aabbs_overlap(aabbs[names[i]], aabbs[names[j]]):

                problems.append(
                    f"{names[i]} se superpone con {names[j]}"
                )

    return problems


# ==============================================================================
# PHASE 6: MINIMAL PROCEDURAL DECORATIVE PROPS & CURATED ART
# ==============================================================================

ART_DIR = os.path.join(_WORKSPACE_DIR, "assets", "textures", "art")

PHOTO_LIBRARY = [
    "photo_arch_colonnade.jpg",
    "photo_travertine_stair.jpg",
    "photo_botanical_minimal.jpg",
    "photo_facade_angles.jpg",
]

ART_LIBRARY = [
    "art_geometric_bauhaus.jpg",
    "art_relief_curves.jpg",
    "art_colorfield_olive.jpg",
    "art_wabisabi_sumi.jpg",
]


# ------------------------------------------------------------------------------
# PROPSPEC DATA MODEL
# ------------------------------------------------------------------------------

@dataclass
class PropSpec:
    name: str
    prop_type: str        # Archetype key (1 of 12)
    category: str         # "BOOKEND", "STANDALONE_VOID", "ART_OBJECT", "CLOCK"
    location: Tuple[float, float, float]
    rotation: Tuple[float, float, float]
    dimensions: Tuple[float, float, float]
    material_key: str     # "MATTE_BONE", "TERRACOTTA", "HONED_STONE", "PATINATED_BRONZE"
    shelf_index: int
    content_key: Optional[str] = None  # Filename of curated photo or artwork
    anchor_book_name: Optional[str] = None
    clearance_bounds: Tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0) # (x_min, x_max, y_min, y_max)


# ------------------------------------------------------------------------------
# PURE BMESH PROCEDURAL GEOMETRY BUILDERS (12 ARCHETYPES)
# ------------------------------------------------------------------------------

def create_lathe_mesh(name: str, profile_pts: List[Tuple[float, float]], segments: int = 48) -> bpy.types.Mesh:
    """Sweeps a 2D profile (r, z) around the Z axis to create a clean manifold solid of revolution."""
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()

    ring_verts = []
    for r, z in profile_pts:
        if r < 1e-5:
            v = bm.verts.new((0.0, 0.0, z))
            ring_verts.append([v])
        else:
            ring = []
            for i in range(segments):
                theta = 2.0 * math.pi * i / segments
                x = r * math.cos(theta)
                y = r * math.sin(theta)
                ring.append(bm.verts.new((x, y, z)))
            ring_verts.append(ring)

    for i in range(len(profile_pts) - 1):
        r1, r2 = ring_verts[i], ring_verts[i + 1]
        n1, n2 = len(r1), len(r2)
        if n1 == 1 and n2 > 1:
            pole = r1[0]
            for j in range(segments):
                bm.faces.new([pole, r2[(j + 1) % segments], r2[j]])
        elif n1 > 1 and n2 == 1:
            pole = r2[0]
            for j in range(segments):
                bm.faces.new([r1[j], r1[(j + 1) % segments], pole])
        elif n1 > 1 and n2 > 1:
            for j in range(segments):
                v1 = r1[j]
                v2 = r1[(j + 1) % segments]
                v3 = r2[(j + 1) % segments]
                v4 = r2[j]
                bm.faces.new([v1, v2, v3, v4])

    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    for f in bm.faces:
        f.smooth = True

    bm.to_mesh(me)
    bm.free()
    me.update()
    return me


def build_vase_cylinder(name: str, height: float = 0.20, radius: float = 0.042) -> bpy.types.Mesh:
    """
    1. Minimalist Scandinavian architectural ceramic vessel:
    - Recessed shadow plinth base
    - Low architectural waist transition
    - Subtle upward column taper
    - Crisp collar reveal groove
    - Refined square-edged rim band and deep interior cavity
    """
    r_plinth = radius * 0.78
    r_body_low = radius * 1.02
    r_body_mid = radius * 0.96
    r_body_top = radius * 0.88
    r_collar = radius * 0.84
    r_rim = radius * 0.94
    r_cav = radius * 0.72
    h_cav = height * 0.55

    profile = [
        (0.0, 0.0),
        (r_plinth, 0.0),
        (r_plinth, 0.012),             # Recessed shadow plinth
        (r_body_low, 0.022),           # Gentle waist flare
        (r_body_low, 0.045),           # Lower body shoulder
        (r_body_mid, height * 0.50),   # Gentle upward taper
        (r_body_top, height * 0.82),   # Slender upper column
        (r_collar, height * 0.86),     # Architectural collar groove
        (r_rim, height * 0.90),        # Rim collar expansion
        (r_rim, height),               # Crisp top lip
        (r_cav, height),               # Inner rim edge
        (r_cav * 0.94, height - 0.012),
        (r_cav * 0.88, height - h_cav),# Interior cavity floor
        (0.0, height - h_cav),
    ]
    return create_lathe_mesh(name, profile, segments=36)


def build_vase_bottle(name: str, height: float = 0.23, max_radius: float = 0.048) -> bpy.types.Mesh:
    """
    2. Scandinavian stoneware apothecary bottle:
    - Grounded foot ring
    - Low sensual teardrop belly (low center of gravity)
    - Graceful continuous concave inflection into slender neck
    - Crisp flared lip bead and interior bore
    """
    r_foot = max_radius * 0.62
    r_neck = max_radius * 0.28
    r_bead = max_radius * 0.36
    r_cav = r_neck * 0.60

    profile = [
        (0.0, 0.0),
        (r_foot, 0.0),
        (r_foot, 0.008),               # Crisp foot ring
        (max_radius * 0.88, height * 0.08),
        (max_radius, height * 0.22),   # Maximum belly width (grounded)
        (max_radius * 0.92, height * 0.38),
        (max_radius * 0.65, height * 0.55),
        (max_radius * 0.40, height * 0.68),
        (r_neck, height * 0.78),       # Slender neck start
        (r_neck * 0.96, height * 0.94),
        (r_bead, height * 0.98),       # Flared lip bead
        (r_bead * 0.92, height),
        (r_cav, height),
        (r_cav * 0.85, height * 0.75), # Interior bore
        (0.0, height * 0.72),
    ]
    return create_lathe_mesh(name, profile, segments=36)


def build_vase_amphora(name: str, height: float = 0.18, max_radius: float = 0.052) -> bpy.types.Mesh:
    """
    3. Modernist architectural pedestal urn / amphora:
    - Grounded pedestal foot
    - Elegant waisted stem
    - Generous ovoid body
    - Architectural neck and flared funnel rim
    """
    r_foot = max_radius * 0.62
    r_stem = max_radius * 0.38
    r_shoulder = max_radius
    r_neck = max_radius * 0.42
    r_rim = max_radius * 0.64
    r_cav = r_rim * 0.68

    profile = [
        (0.0, 0.0),
        (r_foot, 0.0),
        (r_foot, 0.012),               # Pedestal disc foot
        (r_stem, 0.024),               # Waisted stem
        (r_foot * 0.85, 0.040),        # Lower body expansion
        (r_shoulder * 0.92, height * 0.35),
        (r_shoulder, height * 0.48),   # High shoulder
        (r_shoulder * 0.88, height * 0.65),
        (r_neck, height * 0.78),       # Architectural neck
        (r_rim, height * 0.96),        # Flared funnel rim
        (r_rim, height),
        (r_cav, height),
        (r_cav * 0.80, height * 0.82), # Interior cavity
        (0.0, height * 0.80),
    ]
    return create_lathe_mesh(name, profile, segments=36)


def build_bowl_footed(name: str, height: float = 0.065, radius: float = 0.075) -> bpy.types.Mesh:
    """
    4. Architectural pedestal coupe bowl:
    - Substantial stepped cylindrical foot
    - Sweeping circular coupe flare
    - Refined flat rim and smooth interior depression
    """
    r_foot = radius * 0.40
    r_stem = radius * 0.35
    t_wall = 0.0055

    profile = [
        (0.0, 0.0),
        (r_foot, 0.0),
        (r_foot, height * 0.20),       # Pedestal foot
        (r_stem, height * 0.26),       # Stepped shadow reveal
        (radius * 0.55, height * 0.42),# Coupe flare
        (radius * 0.88, height * 0.75),
        (radius, height),              # Outer rim
        (radius - t_wall, height),     # Rim thickness
        (radius * 0.82, height * 0.78),# Inner contour
        (radius * 0.45, height * 0.45),
        (0.0, height * 0.32),          # Bowl interior floor
    ]
    return create_lathe_mesh(name, profile, segments=36)


def build_tray_oblong(name: str, width: float = 0.17, depth: float = 0.09, height: float = 0.022) -> bpy.types.Mesh:
    """5. Architectural pill-shaped valet tray with chamfered inner depression."""
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()

    hw = width / 2.0
    hd = depth / 2.0
    r_corner = hd * 0.85
    w_straight = max(0.005, hw - r_corner)
    segs_corner = 8

    outer_2d = []
    # Right semi-circle
    for s in range(segs_corner + 1):
        ang = -math.pi / 2.0 + math.pi * (s / segs_corner)
        outer_2d.append((w_straight + r_corner * math.cos(ang), r_corner * math.sin(ang)))
    # Left semi-circle
    for s in range(segs_corner + 1):
        ang = math.pi / 2.0 + math.pi * (s / segs_corner)
        outer_2d.append((-w_straight + r_corner * math.cos(ang), r_corner * math.sin(ang)))

    n = len(outer_2d)
    v_bot = [bm.verts.new((x, y, 0.0)) for x, y in outer_2d]
    v_rim = [bm.verts.new((x, y, height)) for x, y in outer_2d]

    bm.faces.new(list(reversed(v_bot)))
    for i in range(n):
        i_next = (i + 1) % n
        bm.faces.new([v_bot[i], v_bot[i_next], v_rim[i_next], v_rim[i]])

    scale_in = 0.84
    h_cav = height * 0.42
    v_cav_rim = [bm.verts.new((x * scale_in, y * scale_in, height)) for x, y in outer_2d]
    v_cav_bot = [bm.verts.new((x * (scale_in * 0.94), y * (scale_in * 0.94), h_cav)) for x, y in outer_2d]

    for i in range(n):
        i_next = (i + 1) % n
        bm.faces.new([v_rim[i], v_rim[i_next], v_cav_rim[i_next], v_cav_rim[i]])
        bm.faces.new([v_cav_rim[i], v_cav_rim[i_next], v_cav_bot[i_next], v_cav_bot[i]])

    bm.faces.new(v_cav_bot)

    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    for f in bm.faces:
        f.smooth = True

    bm.to_mesh(me)
    bm.free()
    me.update()
    return me


def build_bookend_wedge(name: str, width: float = 0.055, depth: float = 0.12, height: float = 0.14) -> bpy.types.Mesh:
    """
    6. Architectural monolithic wedge bookend:
    - Strictly flush vertical book contact face (x = -width / 2)
    - Substantial base plinth reveal (vertical kick at right side)
    - Truncated top plateau (flat architectural summit)
    - Multi-segment bevel transitions on all exterior corners
    """
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()

    hd = depth / 2.0
    hw = width / 2.0
    h_kick = height * 0.14       # 14% base plinth vertical kick (no knife edge!)
    w_plateau = width * 0.32     # 32% flat top plateau width

    # 5-sided architectural profile points in front plane (y = -hd)
    pts_front = [
        (-hw, -hd, 0.0),                  # 0: bottom-left (flush book corner)
        ( hw, -hd, 0.0),                  # 1: bottom-right (base)
        ( hw, -hd, h_kick),               # 2: base plinth kick
        (-hw + w_plateau, -hd, height),   # 3: top plateau right edge
        (-hw, -hd, height),               # 4: top-left (flush book summit)
    ]
    pts_back = [(x, hd, z) for x, y, z in pts_front]

    vf = [bm.verts.new(p) for p in pts_front]
    vb = [bm.verts.new(p) for p in pts_back]

    # Front and back pentagon faces
    bm.faces.new(vf)
    bm.faces.new(list(reversed(vb)))

    # Perimeter quads
    n = len(pts_front)
    for i in range(n):
        i_next = (i + 1) % n
        bm.faces.new([vf[i], vf[i_next], vb[i_next], vb[i]])

    bmesh.ops.bevel(bm, geom=bm.edges[:], offset=0.0028, segments=2, profile=0.5, affect='EDGES')
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(me)
    bm.free()
    me.update()
    return me


def build_bookend_arch(name: str, width: float = 0.052, depth: float = 0.11, height: float = 0.15) -> bpy.types.Mesh:
    """
    7. Monumental architectural portal arch bookend:
    - Strictly flush vertical book contact face (x = -width / 2)
    - Substantial base reveal kick at bottom
    - Sweeping monumental arch curve with flat top plateau
    - Clean bevel transitions
    """
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()

    hd = depth / 2.0
    hw = width / 2.0
    h_base = height * 0.12
    w_top = width * 0.28
    segs_arch = 16

    pts_front = [
        (-hw, -hd, 0.0),
        ( hw, -hd, 0.0),
        ( hw, -hd, h_base),
    ]

    r_arch_x = width - w_top
    r_arch_z = height - h_base
    for i in range(segs_arch + 1):
        ang = (math.pi * 0.5) * (i / segs_arch)
        px = hw - r_arch_x * (1.0 - math.cos(ang))
        pz = h_base + r_arch_z * math.sin(ang)
        pts_front.append((px, -hd, pz))

    pts_front.append((-hw, -hd, height))

    pts_back = [(x, hd, z) for x, y, z in pts_front]

    vf = [bm.verts.new(p) for p in pts_front]
    vb = [bm.verts.new(p) for p in pts_back]

    bm.faces.new(vf)
    bm.faces.new(list(reversed(vb)))

    n = len(pts_front)
    for i in range(n):
        i_next = (i + 1) % n
        bm.faces.new([vf[i], vf[i_next], vb[i_next], vb[i]])

    bmesh.ops.bevel(bm, geom=bm.edges[:], offset=0.0022, segments=2, profile=0.5, affect='EDGES')
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(me)
    bm.free()
    me.update()
    return me


def build_bookend_steps(name: str, width: float = 0.065, depth: float = 0.11, height: float = 0.13) -> bpy.types.Mesh:
    """
    8. Modernist stepped architectural block bookend:
    - Strictly flush vertical book contact face (x = -width / 2)
    - Asymmetrical golden-ratio stepped tiers (heavy base, refined intermediate, monumental summit)
    - Generous multi-segment beveling on all exterior edges
    """
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()

    hd = depth / 2.0
    hw = width / 2.0

    h1 = height * 0.28
    h2 = height * 0.64
    h3 = height

    w1 = hw
    w2 = hw - width * 0.34
    w3 = hw - width * 0.68

    pts_front = [
        (-hw, -hd, 0.0),
        ( w1, -hd, 0.0),
        ( w1, -hd, h1),
        ( w2, -hd, h1),
        ( w2, -hd, h2),
        ( w3, -hd, h2),
        ( w3, -hd, h3),
        (-hw, -hd, h3),
    ]
    pts_back = [(x, hd, z) for x, y, z in pts_front]

    vf = [bm.verts.new(p) for p in pts_front]
    vb = [bm.verts.new(p) for p in pts_back]

    bm.faces.new(vf)
    bm.faces.new(list(reversed(vb)))

    n = len(pts_front)
    for i in range(n):
        i_next = (i + 1) % n
        bm.faces.new([vf[i], vf[i_next], vb[i_next], vb[i]])

    bmesh.ops.bevel(bm, geom=bm.edges[:], offset=0.0025, segments=2, profile=0.5, affect='EDGES')
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(me)
    bm.free()
    me.update()
    return me


def build_picture_frame(name: str, width: float = 0.14, height: float = 0.18, depth: float = 0.016, tilt_deg: float = 4.5) -> bpy.types.Mesh:
    """
    9. Architectural picture frame with mitered profile and recessed art print face with UV mapping.
    Material Slot 0: Frame moulding & back
    Material Slot 1: Art photograph print face
    """
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()

    hw = width / 2.0
    hh = height
    d = depth
    w_molding = 0.008
    d_recess = 0.005

    outer_pts = [
        (-hw, -d/2, 0.0), (hw, -d/2, 0.0), (hw, d/2, 0.0), (-hw, d/2, 0.0),
        (-hw, -d/2, hh),  (hw, -d/2, hh),  (hw, d/2, hh),  (-hw, d/2, hh),
    ]
    vo = [bm.verts.new(p) for p in outer_pts]

    # Outer faces (slot 0)
    f_bot = bm.faces.new([vo[3], vo[2], vo[1], vo[0]])
    f_top = bm.faces.new([vo[4], vo[5], vo[6], vo[7]])
    f_lft = bm.faces.new([vo[0], vo[4], vo[7], vo[3]])
    f_rgt = bm.faces.new([vo[1], vo[2], vo[6], vo[5]])
    f_bak = bm.faces.new([vo[2], vo[3], vo[7], vo[6]])

    for f in [f_bot, f_top, f_lft, f_rgt, f_bak]:
        f.material_index = 0

    hw_in = hw - w_molding
    hh_in_bot = w_molding
    hh_in_top = hh - w_molding
    y_front = -d / 2.0
    y_inner = y_front + d_recess

    vi_front = [
        bm.verts.new((-hw_in, y_front, hh_in_bot)),
        bm.verts.new((hw_in, y_front, hh_in_bot)),
        bm.verts.new((hw_in, y_front, hh_in_top)),
        bm.verts.new((-hw_in, y_front, hh_in_top)),
    ]

    f_s1 = bm.faces.new([vo[0], vo[1], vi_front[1], vi_front[0]])
    f_s2 = bm.faces.new([vo[1], vo[5], vi_front[2], vi_front[1]])
    f_s3 = bm.faces.new([vo[5], vo[4], vi_front[3], vi_front[2]])
    f_s4 = bm.faces.new([vo[4], vo[0], vi_front[0], vi_front[3]])
    for f in [f_s1, f_s2, f_s3, f_s4]:
        f.material_index = 0

    # Inset canvas/artwork plane (slot 1)
    vi_recess = [
        bm.verts.new((-hw_in, y_inner, hh_in_bot)),
        bm.verts.new((hw_in, y_inner, hh_in_bot)),
        bm.verts.new((hw_in, y_inner, hh_in_top)),
        bm.verts.new((-hw_in, y_inner, hh_in_top)),
    ]
    f_r1 = bm.faces.new([vi_front[0], vi_front[1], vi_recess[1], vi_recess[0]])
    f_r2 = bm.faces.new([vi_front[1], vi_front[2], vi_recess[2], vi_recess[1]])
    f_r3 = bm.faces.new([vi_front[2], vi_front[3], vi_recess[3], vi_recess[2]])
    f_r4 = bm.faces.new([vi_front[3], vi_front[0], vi_recess[0], vi_recess[3]])
    for f in [f_r1, f_r2, f_r3, f_r4]:
        f.material_index = 0

    f_art = bm.faces.new(vi_recess)
    f_art.material_index = 1

    # Exact planar UV mapping for the art face
    uv_layer = bm.loops.layers.uv.get("UVMap") or bm.loops.layers.uv.new("UVMap")
    for loop in f_art.loops:
        if loop.vert == vi_recess[0]:
            loop[uv_layer].uv = (0.0, 0.0)
        elif loop.vert == vi_recess[1]:
            loop[uv_layer].uv = (1.0, 0.0)
        elif loop.vert == vi_recess[2]:
            loop[uv_layer].uv = (1.0, 1.0)
        elif loop.vert == vi_recess[3]:
            loop[uv_layer].uv = (0.0, 1.0)

    if abs(tilt_deg) > 0.01:
        rad = math.radians(tilt_deg)
        bmesh.ops.rotate(bm, cent=(0.0, 0.0, 0.0), matrix=mathutils.Matrix.Rotation(rad, 4, 'X'), verts=bm.verts)

    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(me)
    bm.free()
    me.update()
    return me


def build_art_panel(name: str, width: float = 0.15, height: float = 0.20, depth: float = 0.022) -> bpy.types.Mesh:
    """
    10. Minimalist framed relief canvas panel with recessed artwork face and UV mapping.
    Material Slot 0: Floating outer frame / border
    Material Slot 1: Fine art canvas plane
    """
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()

    hw = width / 2.0
    hd = depth / 2.0
    w_molding = 0.008
    d_inset = -0.004

    bmesh.ops.create_cube(bm, size=1.0)
    bmesh.ops.scale(bm, vec=(width, depth, height), verts=bm.verts)
    bmesh.ops.translate(bm, vec=(0.0, 0.0, height / 2.0), verts=bm.verts)
    for f in bm.faces:
        f.material_index = 0

    front_faces = [f for f in bm.faces if f.normal.y < -0.9]
    res = bmesh.ops.inset_individual(bm, faces=front_faces, thickness=w_molding, depth=d_inset)
    center_face = front_faces[0]
    center_face.material_index = 1
    for f in res['faces']:
        f.material_index = 0

    uv_layer = bm.loops.layers.uv.get("UVMap") or bm.loops.layers.uv.new("UVMap")
    for l in center_face.loops:
        u = (l.vert.co.x + hw - w_molding) / (width - 2.0 * w_molding)
        v = (l.vert.co.z - w_molding) / (height - 2.0 * w_molding)
        l[uv_layer].uv = (max(0.0, min(1.0, u)), max(0.0, min(1.0, v)))

    # Bevel outer frame edges
    outer_edges = [e for e in bm.edges if all(f.material_index == 0 for f in e.link_faces)]
    if outer_edges:
        bmesh.ops.bevel(bm, geom=outer_edges, offset=0.0015, segments=2, profile=0.5, affect='EDGES')

    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(me)
    bm.free()
    me.update()
    return me


def build_art_sculpture(name: str, width: float = 0.09, depth: float = 0.09, height: float = 0.16) -> bpy.types.Mesh:
    """
    11. Architectural geometric monument:
    - Stepped honed stone plinth with recessed shadow reveal base (slot 0)
    - Beveled plinth edges
    - Balanced patinated bronze sphere nestled on top (slot 1)
    """
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()

    h_plinth = height * 0.32
    h_sub = 0.010
    w_sub = width * 0.88
    d_sub = depth * 0.88

    # 1. Recessed sub-plinth (shadow base)
    bmesh.ops.create_cube(bm, size=1.0)
    bmesh.ops.scale(bm, vec=(w_sub, d_sub, h_sub), verts=bm.verts[:8])
    bmesh.ops.translate(bm, vec=(0.0, 0.0, h_sub / 2.0), verts=bm.verts[:8])
    for f in bm.faces[:6]:
        f.material_index = 0

    # 2. Main stone plinth block
    bmesh.ops.create_cube(bm, size=1.0)
    v_main = bm.verts[8:16]
    h_main = h_plinth - h_sub
    bmesh.ops.scale(bm, vec=(width, depth, h_main), verts=v_main)
    bmesh.ops.translate(bm, vec=(0.0, 0.0, h_sub + h_main / 2.0), verts=v_main)
    for f in bm.faces[6:12]:
        f.material_index = 0

    # 3. Bronze sphere nestled on top
    r_sphere = (height - h_plinth) * 0.50
    z_sphere = h_plinth + r_sphere * 0.95

    bmesh.ops.create_uvsphere(bm, u_segments=24, v_segments=16, radius=r_sphere)
    v_sphere = bm.verts[16:]
    bmesh.ops.translate(bm, vec=(0.0, 0.0, z_sphere), verts=v_sphere)
    for f in bm.faces[12:]:
        f.material_index = 1
        f.smooth = True

    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(me)
    bm.free()
    me.update()
    return me


def build_table_clock(name: str, width: float = 0.088, depth: float = 0.036, height: float = 0.096) -> bpy.types.Mesh:
    """
    12. Architectural minimalist table clock:
    - Cylindrical drum casing standing on stable pedestal base (slot 0: PATINATED_BRONZE or HONED_STONE)
    - Open front bezel with recessed circular dial cavity (slot 1: MATTE_BONE)
    - 4 subtle hour markers at 12, 3, 6, 9 (slot 0)
    - Center pinion and slender minute/hour hands pinned at 10:10 (slot 0)
    """
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()

    r_drum = width / 2.0
    hd = depth / 2.0
    z_center = height - r_drum
    segs = 32

    # 1. Base pedestal foot (slot 0)
    w_base = width * 0.72
    h_base = 0.014
    bmesh.ops.create_cube(bm, size=1.0)
    bmesh.ops.scale(bm, vec=(w_base, depth * 0.95, h_base), verts=bm.verts[:8])
    bmesh.ops.translate(bm, vec=(0.0, 0.0, h_base / 2.0), verts=bm.verts[:8])
    for f in bm.faces[:6]:
        f.material_index = 0

    # 2. Cylindrical drum case
    v_front_outer = []
    v_back = []
    for i in range(segs):
        theta = 2.0 * math.pi * i / segs
        x = r_drum * math.cos(theta)
        z = z_center + r_drum * math.sin(theta)
        v_front_outer.append(bm.verts.new((x, -hd, z)))
        v_back.append(bm.verts.new((x, hd, z)))

    # Back cap face
    f_back = bm.faces.new(list(reversed(v_back)))
    f_back.material_index = 0

    # Drum outer barrel quads
    for i in range(segs):
        i_next = (i + 1) % segs
        f_b = bm.faces.new([v_front_outer[i], v_front_outer[i_next], v_back[i_next], v_back[i]])
        f_b.material_index = 0
        f_b.smooth = True

    # Bezel rim (front face ring)
    r_bezel = r_drum * 0.82
    v_bezel_inner = []
    for i in range(segs):
        theta = 2.0 * math.pi * i / segs
        x = r_bezel * math.cos(theta)
        z = z_center + r_bezel * math.sin(theta)
        v_bezel_inner.append(bm.verts.new((x, -hd, z)))

    for i in range(segs):
        i_next = (i + 1) % segs
        f_rim = bm.faces.new([v_front_outer[i_next], v_front_outer[i], v_bezel_inner[i], v_bezel_inner[i_next]])
        f_rim.material_index = 0

    # Recessed inner cavity wall to dial
    y_dial = -hd + 0.005
    v_dial = []
    for i in range(segs):
        theta = 2.0 * math.pi * i / segs
        x = r_bezel * math.cos(theta)
        z = z_center + r_bezel * math.sin(theta)
        v_dial.append(bm.verts.new((x, y_dial, z)))

    for i in range(segs):
        i_next = (i + 1) % segs
        f_wall = bm.faces.new([v_bezel_inner[i], v_bezel_inner[i_next], v_dial[i_next], v_dial[i]])
        f_wall.material_index = 0
        f_wall.smooth = True

    # Dial face (slot 1: MATTE_BONE)
    f_dial = bm.faces.new(list(reversed(v_dial)))
    f_dial.material_index = 1

    # 3. Hour markers (12, 3, 6, 9) (slot 0)
    marker_r = r_bezel * 0.85
    marker_angles = [math.pi / 2.0, 0.0, -math.pi / 2.0, math.pi]
    for ang in marker_angles:
        mx = marker_r * math.cos(ang)
        mz = z_center + marker_r * math.sin(ang)
        bmesh.ops.create_cube(bm, size=1.0)
        m_verts = bm.verts[-8:]
        bmesh.ops.scale(bm, vec=(0.0018, 0.0015, 0.0035), verts=m_verts)
        bmesh.ops.translate(bm, vec=(mx, y_dial - 0.0008, mz), verts=m_verts)
        for f in bm.faces[-6:]:
            f.material_index = 0

    # 4. Center Pinion (slot 0)
    bmesh.ops.create_cube(bm, size=1.0)
    p_verts = bm.verts[-8:]
    bmesh.ops.scale(bm, vec=(0.004, 0.004, 0.004), verts=p_verts)
    bmesh.ops.translate(bm, vec=(0.0, y_dial - 0.002, z_center), verts=p_verts)
    for f in bm.faces[-6:]:
        f.material_index = 0

    # 5. Hour hand (pointing ~10 o'clock: angle 150 deg) (slot 0)
    L_h = r_bezel * 0.55
    bmesh.ops.create_cube(bm, size=1.0)
    h_verts = bm.verts[-8:]
    bmesh.ops.scale(bm, vec=(0.0022, 0.0012, L_h), verts=h_verts)
    bmesh.ops.translate(bm, vec=(0.0, 0.0, L_h / 2.0), verts=h_verts)
    rot_h = mathutils.Matrix.Rotation(-math.radians(60), 4, 'Y')
    bmesh.ops.rotate(bm, cent=(0.0, 0.0, 0.0), matrix=rot_h, verts=h_verts)
    bmesh.ops.translate(bm, vec=(0.0, y_dial - 0.0018, z_center), verts=h_verts)
    for f in bm.faces[-6:]:
        f.material_index = 0

    # 6. Minute hand (pointing ~2 o'clock: angle 30 deg) (slot 0)
    L_m = r_bezel * 0.80
    bmesh.ops.create_cube(bm, size=1.0)
    m_verts = bm.verts[-8:]
    bmesh.ops.scale(bm, vec=(0.0018, 0.0012, L_m), verts=m_verts)
    bmesh.ops.translate(bm, vec=(0.0, 0.0, L_m / 2.0), verts=m_verts)
    rot_m = mathutils.Matrix.Rotation(math.radians(60), 4, 'Y')
    bmesh.ops.rotate(bm, cent=(0.0, 0.0, 0.0), matrix=rot_m, verts=m_verts)
    bmesh.ops.translate(bm, vec=(0.0, y_dial - 0.0026, z_center), verts=m_verts)
    for f in bm.faces[-6:]:
        f.material_index = 0

    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(me)
    bm.free()
    me.update()
    return me


def generate_prop_mesh(prop_type: str, name: str, dims: Tuple[float, float, float]) -> bpy.types.Mesh:
    """Dispatches to the appropriate pure BMesh geometry builder across all 12 archetypes."""
    w, d, h = dims
    if prop_type == "VASE_CYLINDER":
        return build_vase_cylinder(name, height=h, radius=w / 2.0)
    elif prop_type == "VASE_BOTTLE":
        return build_vase_bottle(name, height=h, max_radius=w / 2.0)
    elif prop_type == "VASE_AMPHORA":
        return build_vase_amphora(name, height=h, max_radius=w / 2.0)
    elif prop_type == "BOWL_FOOTED":
        return build_bowl_footed(name, height=h, radius=w / 2.0)
    elif prop_type == "TRAY_OBLONG":
        return build_tray_oblong(name, width=w, depth=d, height=h)
    elif prop_type in ("BOOKEND_WEDGE", "BOOKEND_L"):
        return build_bookend_wedge(name, width=w, depth=d, height=h)
    elif prop_type == "BOOKEND_ARCH":
        return build_bookend_arch(name, width=w, depth=d, height=h)
    elif prop_type == "BOOKEND_STEPS":
        return build_bookend_steps(name, width=w, depth=d, height=h)
    elif prop_type == "PICTURE_FRAME":
        return build_picture_frame(name, width=w, height=h, depth=d, tilt_deg=4.5)
    elif prop_type == "ART_PANEL":
        return build_art_panel(name, width=w, height=h, depth=d)
    elif prop_type == "ART_SCULPTURE":
        return build_art_sculpture(name, width=w, depth=d, height=h)
    elif prop_type == "TABLE_CLOCK":
        return build_table_clock(name, width=w, depth=d, height=h)
    else:
        raise ValueError(f"Unknown prop archetype: {prop_type}")


# ------------------------------------------------------------------------------
# RESTRAINED PHYSICAL MATERIAL PALETTE FACTORY
# ------------------------------------------------------------------------------

PROP_PALETTES = {
    "MATTE_BONE": {
        "color": (0.91, 0.88, 0.82, 1.0),   # Warm French porcelain / archival cream
        "roughness": 0.38,
        "specular": 0.45,
        "metallic": 0.0,
    },
    "TERRACOTTA": {
        "color": (0.58, 0.26, 0.14, 1.0),   # Earthen burnt clay
        "roughness": 0.75,
        "specular": 0.18,
        "metallic": 0.0,
    },
    "HONED_STONE": {
        "color": (0.68, 0.67, 0.65, 1.0),   # Honed limestone / travertine
        "roughness": 0.62,
        "specular": 0.22,
        "metallic": 0.0,
    },
    "PATINATED_BRONZE": {
        "color": (0.28, 0.24, 0.18, 1.0),   # Antique bronze alloy
        "roughness": 0.35,
        "specular": 0.55,
        "metallic": 0.90,
    },
    "DARK_FRAME": {
        "color": (0.08, 0.07, 0.06, 1.0),   # Anodized charcoal frame
        "roughness": 0.45,
        "specular": 0.35,
        "metallic": 0.20,
    },
}

def get_or_create_prop_material(key: str) -> bpy.types.Material:
    """Returns a cached Principled BSDF material with rich physical porcelain, metal patina, stone, or clay response."""
    mat_name = f"PB_Prop_Mat_{key}"
    existing = bpy.data.materials.get(mat_name)
    if existing:
        return existing

    cfg = PROP_PALETTES.get(key, PROP_PALETTES["MATTE_BONE"])
    mat = bpy.data.materials.new(name=mat_name)
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    bsdf = nodes.get("Principled BSDF")

    if bsdf:
        bsdf.inputs["Base Color"].default_value = cfg["color"]
        bsdf.inputs["Roughness"].default_value = cfg["roughness"]
        if "Specular IOR Level" in bsdf.inputs:
            bsdf.inputs["Specular IOR Level"].default_value = cfg["specular"]
        elif "Specular" in bsdf.inputs:
            bsdf.inputs["Specular"].default_value = cfg["specular"]
        bsdf.inputs["Metallic"].default_value = cfg["metallic"]

        if key == "MATTE_BONE":
            # Real French porcelain: soft translucent body + smooth glazed outer coat
            bsdf.inputs["Base Color"].default_value = (0.92, 0.89, 0.83, 1.0)
            bsdf.inputs["Roughness"].default_value = 0.26
            if "Subsurface Weight" in bsdf.inputs:
                bsdf.inputs["Subsurface Weight"].default_value = 0.22
            elif "Subsurface" in bsdf.inputs:
                bsdf.inputs["Subsurface"].default_value = 0.22

            if "Subsurface Radius" in bsdf.inputs:
                bsdf.inputs["Subsurface Radius"].default_value = (0.12, 0.09, 0.07)
            if "Subsurface Color" in bsdf.inputs:
                bsdf.inputs["Subsurface Color"].default_value = (0.95, 0.91, 0.84, 1.0)

            if "Coat Weight" in bsdf.inputs:
                bsdf.inputs["Coat Weight"].default_value = 0.45
            elif "Coat" in bsdf.inputs:
                bsdf.inputs["Coat"].default_value = 0.45
            if "Coat Roughness" in bsdf.inputs:
                bsdf.inputs["Coat Roughness"].default_value = 0.03

            tex_coord = nodes.new("ShaderNodeTexCoord")
            try:
                noise = nodes.new("ShaderNodeTexNoise")
            except Exception:
                noise = nodes.new("ShaderNodeNoiseTexture")
            if "Scale" in noise.inputs:
                noise.inputs["Scale"].default_value = 160.0
            if "Detail" in noise.inputs:
                noise.inputs["Detail"].default_value = 3.0

            bump = nodes.new("ShaderNodeBump")
            bump.inputs["Strength"].default_value = 0.02
            bump.inputs["Distance"].default_value = 0.003
            links.new(tex_coord.outputs["Object"], noise.inputs["Vector"])
            fac_out = noise.outputs.get("Fac") or noise.outputs.get("Factor") or noise.outputs[0]
            links.new(fac_out, bump.inputs["Height"])
            links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])

        elif key == "PATINATED_BRONZE":
            # Dual-tone antique bronze metal with verdigris / oxidized patina in crevices
            bsdf.inputs["Base Color"].default_value = (0.24, 0.20, 0.15, 1.0)
            bsdf.inputs["Metallic"].default_value = 0.88
            bsdf.inputs["Roughness"].default_value = 0.32
            if "Specular IOR Level" in bsdf.inputs:
                bsdf.inputs["Specular IOR Level"].default_value = 0.60

            tex_coord = nodes.new("ShaderNodeTexCoord")
            try:
                noise = nodes.new("ShaderNodeTexNoise")
            except Exception:
                noise = nodes.new("ShaderNodeNoiseTexture")
            if "Scale" in noise.inputs:
                noise.inputs["Scale"].default_value = 45.0
            if "Detail" in noise.inputs:
                noise.inputs["Detail"].default_value = 5.0

            color_ramp = nodes.new("ShaderNodeValToRGB")
            color_ramp.color_ramp.elements[0].position = 0.35
            color_ramp.color_ramp.elements[0].color = (0.14, 0.17, 0.13, 1.0)  # Dark patina verdigris
            color_ramp.color_ramp.elements[1].position = 0.65
            color_ramp.color_ramp.elements[1].color = (0.42, 0.32, 0.20, 1.0)  # Polished bronze metal

            links.new(tex_coord.outputs["Object"], noise.inputs["Vector"])
            fac_out = noise.outputs.get("Fac") or noise.outputs.get("Factor") or noise.outputs[0]
            links.new(fac_out, color_ramp.inputs["Fac"])
            links.new(color_ramp.outputs["Color"], bsdf.inputs["Base Color"])

            bump = nodes.new("ShaderNodeBump")
            bump.inputs["Strength"].default_value = 0.06
            bump.inputs["Distance"].default_value = 0.004
            links.new(fac_out, bump.inputs["Height"])
            links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])

        elif key in ("HONED_STONE", "TERRACOTTA"):
            tex_coord = nodes.new("ShaderNodeTexCoord")
            try:
                noise = nodes.new("ShaderNodeTexNoise")
            except Exception:
                noise = nodes.new("ShaderNodeNoiseTexture")
            if "Scale" in noise.inputs:
                noise.inputs["Scale"].default_value = 120.0
            if "Detail" in noise.inputs:
                noise.inputs["Detail"].default_value = 4.0

            bump = nodes.new("ShaderNodeBump")
            bump.inputs["Strength"].default_value = 0.07 if key == "TERRACOTTA" else 0.05
            bump.inputs["Distance"].default_value = 0.005

            links.new(tex_coord.outputs["Object"], noise.inputs["Vector"])
            fac_out = noise.outputs.get("Fac") or noise.outputs.get("Factor") or noise.outputs[0]
            links.new(fac_out, bump.inputs["Height"])
            links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])

    return mat


def get_or_create_art_material(image_filename: str) -> bpy.types.Material:
    """Returns a cached Principled BSDF material mapping the curated real artwork/photo."""
    if not image_filename:
        image_filename = PHOTO_LIBRARY[0]

    clean_key = os.path.splitext(image_filename)[0]
    mat_name = f"PB_Prop_Art_{clean_key}"
    existing = bpy.data.materials.get(mat_name)
    if existing:
        return existing

    full_path = os.path.join(ART_DIR, image_filename)
    if not os.path.exists(full_path):
        # Fallback to first existing photo library asset if path is missing or invalid
        fallback_filename = PHOTO_LIBRARY[0]
        full_path = os.path.join(ART_DIR, fallback_filename)

    mat = bpy.data.materials.new(name=mat_name)
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links

    bsdf = nodes.get("Principled BSDF")
    tex_node = nodes.new("ShaderNodeTexImage")

    if os.path.exists(full_path):
        img = bpy.data.images.load(full_path, check_existing=True)
        tex_node.image = img
    else:
        print(f"WARNING: Image file not found at {full_path}")

    tex_coord = nodes.new("ShaderNodeTexCoord")
    links.new(tex_coord.outputs["UV"], tex_node.inputs["Vector"])
    links.new(tex_node.outputs["Color"], bsdf.inputs["Base Color"])

    bsdf.inputs["Roughness"].default_value = 0.84
    if "Specular IOR Level" in bsdf.inputs:
        bsdf.inputs["Specular IOR Level"].default_value = 0.08
    elif "Specular" in bsdf.inputs:
        bsdf.inputs["Specular"].default_value = 0.08
    bsdf.inputs["Metallic"].default_value = 0.0

    return mat


# ------------------------------------------------------------------------------
# CONDITION-DRIVEN PLACEMENT & VISUAL HIERARCHY ENGINE
# ------------------------------------------------------------------------------

def solve_prop_placements(composition_plan, density: float = 0.35, seed: int = 42, thickness: float = 0.06) -> List[PropSpec]:
    """
    Budget-driven Whole-Bookshelf Prop Placement Engine (0.0 to 1.0 Density Control).
    
    Density budget mapping:
    - 0.0: strictly 0 props
    - 0.2 - 0.3: 1 prop (Primary Focal)
    - 0.35 - 0.4: 2 props (Primary Focal + Counter-Mass)
    - 0.6: 3-4 props (Focal + Counter-Mass + Secondary Accents)
    - 0.8: 5-6 props (Focal + Counter-Mass + Multiple shelf voids)
    - 1.0: maximum reasonable decorative budget across eligible voids
    """
    if density <= 1e-4:
        return []

    props: List[PropSpec] = []

    # 1. Collect candidate voids from negative space zones (min width 0.15m)
    candidate_voids = []
    for s_idx, s_plan in enumerate(composition_plan.shelves):
        if s_idx == 0:
            continue
        shelf_z = getattr(s_plan, 'z_location', getattr(s_plan, 'z', 0.0))
        role = getattr(s_plan.macro_intent, 'role', getattr(s_plan, 'role', 'standard'))
        num_zones = len(s_plan.zones)
        for z_idx, zone in enumerate(s_plan.zones):
            z_type = getattr(zone, 'zone_type', getattr(zone, 'type', '')).upper()
            if z_type in ('NEGATIVE_SPACE', 'OUTER_NEGATIVE_SPACE'):
                w_void = getattr(zone, 'width', abs(zone.x_end - zone.x_start))
                if w_void >= 0.15:
                    has_b_left = (z_idx > 0 and getattr(s_plan.zones[z_idx - 1], 'zone_type', getattr(s_plan.zones[z_idx - 1], 'type', '')).upper() in ('BOOKS', 'STACK'))
                    has_b_right = (z_idx < num_zones - 1 and getattr(s_plan.zones[z_idx + 1], 'zone_type', getattr(s_plan.zones[z_idx + 1], 'type', '')).upper() in ('BOOKS', 'STACK'))
                    candidate_voids.append({
                        "shelf_index": s_idx,
                        "shelf_z": shelf_z,
                        "zone_idx": z_idx,
                        "x_center": (zone.x_start + zone.x_end) / 2.0,
                        "x_start": zone.x_start,
                        "x_end": zone.x_end,
                        "width": w_void,
                        "role": role,
                        "has_books_left": has_b_left,
                        "has_books_right": has_b_right
                    })

    if not candidate_voids:
        return []

    # 2. Determine target prop count budget (uncapped, scales with available candidate voids)
    num_candidates = len(candidate_voids)
    if density <= 0.05:
        target_count = 0
    elif density <= 0.30:
        target_count = 1
    elif density <= 0.45:
        target_count = 2
    elif density <= 0.75:
        target_count = max(2, min(num_candidates, int(round(num_candidates * 0.60))))
    else:  # High density (0.75 - 1.0)
        target_count = max(2, min(num_candidates, int(round(num_candidates * 0.85))))

    if target_count <= 0:
        return []

    shelf_surface_offset = thickness / 2.0 + 0.0005

    # 3. Master Library of 13 Prop Archetypes
    # Decorative (non-bookend) objects (9 distinct models):
    decorative_archetypes = [
        ("ART_PANEL", "ART", (0.240, 0.025, 0.280), "DARK_FRAME", "art_relief_curves.jpg"),
        ("PICTURE_FRAME", "ART", (0.160, 0.020, 0.200), "DARK_FRAME", "photo_arch_colonnade.jpg"),
        ("VASE_AMPHORA", "VESSEL", (0.130, 0.130, 0.220), "HONED_STONE", None),
        ("VASE_BOTTLE", "VESSEL", (0.100, 0.100, 0.240), "TERRACOTTA", None),
        ("VASE_CYLINDER", "VESSEL", (0.090, 0.090, 0.210), "MATTE_BONE", None),
        ("BOWL_FOOTED", "VESSEL", (0.130, 0.130, 0.080), "PATINATED_BRONZE", None),
        ("TRAY_OBLONG", "VESSEL", (0.170, 0.090, 0.025), "TERRACOTTA", None),
        ("ART_SCULPTURE", "OBJECT", (0.120, 0.120, 0.200), "HONED_STONE", None),
        ("TABLE_CLOCK", "OBJECT", (0.110, 0.060, 0.120), "DARK_FRAME", None),
    ]

    # Contextual book-support bookends (4 distinct models - ONLY used when adjacent to books):
    bookend_archetypes = [
        ("BOOKEND_L", "BOOKEND", (0.120, 0.100, 0.160), "HONED_STONE", None),
        ("BOOKEND_WEDGE", "BOOKEND", (0.120, 0.100, 0.160), "PATINATED_BRONZE", None),
        ("BOOKEND_ARCH", "BOOKEND", (0.110, 0.100, 0.170), "HONED_STONE", None),
        ("BOOKEND_STEPS", "BOOKEND", (0.130, 0.100, 0.150), "PATINATED_BRONZE", None),
    ]

    # Select primary focal void (shelf 2 left void or best available)
    focal_void = next((v for v in candidate_voids if v["shelf_index"] == 2 and v["x_center"] < 0), candidate_voids[0])
    cm_void = next((v for v in candidate_voids if v["shelf_index"] == 1 and v["x_center"] > 0), None)
    if not cm_void and len(candidate_voids) > 1:
        cm_void = [v for v in candidate_voids if v != focal_void][0]

    ordered_voids = [focal_void]
    if cm_void and cm_void not in ordered_voids:
        ordered_voids.append(cm_void)

    # Sort remaining voids by width (descending) to prioritize wider empty spaces across all shelves
    remaining_voids = [v for v in candidate_voids if v not in ordered_voids]
    remaining_voids.sort(key=lambda v: v["width"], reverse=True)
    ordered_voids.extend(remaining_voids)

    used_voids = ordered_voids[:target_count]
    used_archetype_names = set()
    used_artworks = set()

    for idx, void_info in enumerate(used_voids):
        s_idx = void_info["shelf_index"]
        x_c = void_info["x_center"]
        z_loc = void_info["shelf_z"] + shelf_surface_offset
        w_avail = void_info["width"]
        has_books_near = void_info.get("has_books_left") or void_info.get("has_books_right")

        # Choose archetype based on zone size, variety, and contextual book proximity
        if has_books_near and (idx % 3 == 0):
            # Contextual bookend selection: ONLY when adjacent to a real book stack
            pool = bookend_archetypes
        else:
            # Decorative vessels, objects, clocks, art (never floating bookends alone)
            pool = decorative_archetypes

        # Strict whole-bookshelf uniqueness filter: prioritize genuinely unused model archetypes first
        unused_pool = [a for a in pool if a[0] not in used_archetype_names]

        if unused_pool:
            archetype = unused_pool[0]
        else:
            # Fallback to unused decorative pool if bookends are exhausted
            unused_dec = [a for a in decorative_archetypes if a[0] not in used_archetype_names]
            if unused_dec:
                archetype = unused_dec[0]
            else:
                # Absolute last resort if all 13 unique model archetypes across the bookshelf are exhausted
                archetype = pool[idx % len(pool)]

        used_archetype_names.add(archetype[0])
        p_type, p_cat, f_dims, p_mat, p_content = archetype

        # Assign unique artwork image to PICTURE_FRAME and ART_PANEL
        if p_type in ("PICTURE_FRAME", "ART_PANEL"):
            art_library_combined = PHOTO_LIBRARY + ART_LIBRARY
            unused_art = [img for img in art_library_combined if img not in used_artworks]
            if unused_art:
                p_content = unused_art[0]
            else:
                p_content = art_library_combined[idx % len(art_library_combined)]
            used_artworks.add(p_content)

        if f_dims[0] > w_avail - 0.02:
            scale_factor = (w_avail - 0.02) / f_dims[0]
            if scale_factor < 0.5:
                continue
            f_dims = (f_dims[0] * scale_factor, f_dims[1] * scale_factor, f_dims[2] * scale_factor)

        # Calculate actual position relative to real book stack boundary (with 2mm clearance)
        x_loc = x_c
        rot_y = 0.0
        if p_cat == "BOOKEND" or p_type.startswith("BOOKEND_"):
            if void_info.get("has_books_left"):
                x_loc = void_info["x_start"] + f_dims[0] / 2.0 + 0.002
            elif void_info.get("has_books_right"):
                x_loc = void_info["x_end"] - f_dims[0] / 2.0 - 0.002

        props.append(PropSpec(
            name=f"PB_Prop_{s_idx:02d}_{idx:02d}_{p_type}",
            prop_type=p_type,
            category=p_cat,
            location=(x_loc, 0.0, z_loc),
            rotation=(0.0, 0.0, rot_y),
            dimensions=f_dims,
            material_key=p_mat,
            shelf_index=s_idx,
            content_key=p_content,
            clearance_bounds=(x_loc - f_dims[0]/2, x_loc + f_dims[0]/2, -f_dims[1]/2, f_dims[1]/2)
        ))

    return props


def place_props(prop_specs: List[PropSpec]) -> List[bpy.types.Object]:
    """Instantiates and links all generated PropSpec objects into the active collection."""
    placed_objects = []
    for p in prop_specs:
        me = generate_prop_mesh(p.prop_type, p.name, p.dimensions)
        obj = bpy.data.objects.new(p.name, me)
        obj.location = p.location
        obj.rotation_euler = p.rotation

        # Slot 0 material
        obj.data.materials.append(get_or_create_prop_material(p.material_key))

        # Slot 1 material for art / dial / accent
        if p.content_key:
            obj.data.materials.append(get_or_create_art_material(p.content_key))
        elif p.prop_type == "TABLE_CLOCK":
            obj.data.materials.append(get_or_create_prop_material("MATTE_BONE"))
            obj.data.materials.append(_get_or_create_glass_material())
        elif p.prop_type == "ART_SCULPTURE":
            obj.data.materials.append(get_or_create_prop_material("PATINATED_BRONZE"))

        bpy.context.collection.objects.link(obj)
        placed_objects.append(obj)

    return placed_objects


def solve_shelf_coverage(shelves: int, has_doors: bool, door_shelves_covered: int) -> int:
    """Calculates the number of lower shelf compartments enclosed by cabinet doors."""
    if not has_doors:
        return 0
    return max(1, min(shelves, door_shelves_covered))


# =========================================================
# GENERAR LIBRERO
# =========================================================

def generate_bookshelf(
    width,
    height,
    depth,
    shelves,
    bevel_width,
    bevel_segments,
    density,
    variation,
    tilt,
    seed,
    back_style="SOLID",
    back_thickness=0.015,
    has_plinth=True,
    plinth_height=0.10,
    has_crown=True,
    crown_height=0.08,
    has_front_trim=True,
    stile_width=0.06,
    has_doors=False,
    door_shelves_covered=1,
    door_style="RAISED_PANEL",
    door_count=2,
    door_thickness=0.018,
    door_gap=0.002,
    door_angle=0.0,
    has_handles=True,
    handle_style="KNOB",
    handle_material="BRASS",
    handle_height_offset=0.0,
    furniture_finish="OAK_NATURAL",
    prop_density=0.35,
    door_count_mode="AUTO"
):

    # -----------------------------------------------------
    # LIMPIAR
    # -----------------------------------------------------

    for obj in list(bpy.data.objects):
        if obj.name.startswith("PB_") or obj.name == "Cube":
            bpy.data.objects.remove(
                obj,
                do_unlink=True
            )

    problems = []
    thickness = 0.06

    # -----------------------------------------------------
    # ESTRUCTURA BASE Y COBERTURA DE REPISAS (Fase 4A/4C)
    # -----------------------------------------------------

    shelves_covered = solve_shelf_coverage(
        shelves=shelves,
        has_doors=has_doors,
        door_shelves_covered=door_shelves_covered
    )

    # -----------------------------------------------------
    # PUERTAS (Fase 4C)
    # -----------------------------------------------------

    if has_doors:
        create_doors(
            width=width,
            height=height,
            depth=depth,
            shelves=shelves,
            thickness=thickness,
            stile_width=stile_width,
            plinth_height=plinth_height,
            door_shelves_covered=door_shelves_covered,
            door_style=door_style,
            door_count=door_count,
            door_count_mode=door_count_mode,
            door_thickness=door_thickness,
            door_gap=door_gap,
            door_angle=door_angle,
            has_handles=has_handles,
            handle_style=handle_style,
            handle_material=handle_material,
            bevel_width=bevel_width,
            bevel_segments=bevel_segments,
            furniture_finish=furniture_finish
        )

    # -----------------------------------------------------
    # LATERALES
    # -----------------------------------------------------

    side_height = height + thickness

    left_panel = create_box(
        "PB_Left",
        (
            -width / 2 + thickness / 2,
            0,
            height / 2
        ),
        (
            thickness,
            depth,
            side_height
        ),
        bevel_width,
        bevel_segments
    )
    apply_continuous_side_panel_uvs(left_panel)
    _assign_material(left_panel, _get_or_create_structure_material(furniture_finish, grain_orientation="VERTICAL", component_role="SIDE_PANEL_LEFT"))

    right_panel = create_box(
        "PB_Right",
        (
            width / 2 - thickness / 2,
            0,
            height / 2
        ),
        (
            thickness,
            depth,
            side_height
        ),
        bevel_width,
        bevel_segments
    )
    apply_continuous_side_panel_uvs(right_panel)
    _assign_material(right_panel, _get_or_create_structure_material(furniture_finish, grain_orientation="VERTICAL", component_role="SIDE_PANEL_RIGHT"))

    # -----------------------------------------------------
    # REPISAS
    # -----------------------------------------------------

    shelf_width = width - thickness * 2
    spacing = height / shelves

    for i in range(shelves + 1):
        z = i * spacing
        shelf_obj = create_box(
            f"PB_Shelf_{i:02d}",
            (
                0,
                0,
                z
            ),
            (
                shelf_width,
                depth,
                thickness
            ),
            bevel_width,
            bevel_segments
        )
        apply_box_meter_uvs(shelf_obj, "HORIZONTAL")
        _assign_material(shelf_obj, _get_or_create_structure_material(furniture_finish, grain_orientation="HORIZONTAL", component_role="SHELF", component_index=i))

    # -----------------------------------------------------
    # BACK PANEL, PLINTH, CROWN, FRONT TRIM
    # -----------------------------------------------------
    if back_style != "OPEN":
        create_back_panel(
            width=width,
            height=height,
            depth=depth,
            thickness=thickness,
            back_style=back_style,
            back_thickness=back_thickness,
            bevel_width=bevel_width,
            bevel_segments=bevel_segments,
            furniture_finish=furniture_finish
        )

    if has_plinth:
        create_plinth(
            width=width,
            depth=depth,
            thickness=thickness,
            plinth_height=plinth_height,
            bevel_width=bevel_width,
            bevel_segments=bevel_segments,
            furniture_finish=furniture_finish
        )

    if has_crown:
        create_crown(
            width=width,
            height=height,
            depth=depth,
            thickness=thickness,
            crown_height=crown_height,
            bevel_width=bevel_width,
            bevel_segments=bevel_segments,
            furniture_finish=furniture_finish
        )

    if has_front_trim:
        create_face_frame(
            width=width,
            height=height,
            depth=depth,
            shelves=shelves,
            thickness=thickness,
            stile_width=stile_width,
            bevel_width=bevel_width,
            bevel_segments=bevel_segments,
            furniture_finish=furniture_finish
        )

    # -----------------------------------------------------
    # LIBROS (Fase 1: Basado en CompositionPlan)
    # -----------------------------------------------------

    composition_plan = build_composition_plan(
        width=width,
        height=height,
        depth=depth,
        shelves=shelves,
        density=density,
        variation=variation,
        tilt=tilt,
        seed=seed,
        thickness=thickness
    )

    dump_composition_plan(composition_plan)

    all_specs = generate_specs_from_composition_plan(
        composition_plan=composition_plan,
        depth=depth,
        thickness=thickness
    )

    effective_back_thickness = back_thickness if back_style != "OPEN" else 0.0

    problems = validate_all_books(
        all_specs,
        width,
        height,
        depth,
        thickness,
        back_thickness=effective_back_thickness
    )

    place_books(all_specs)

    # -----------------------------------------------------
    # DECORATIVE PROPS (Phase 6)
    # -----------------------------------------------------
    if prop_density > 0.0:
        prop_specs = solve_prop_placements(composition_plan=composition_plan, density=prop_density, seed=seed, thickness=thickness)
        place_props(prop_specs)

    return problems


# =========================================================
# OPERADOR
# =========================================================

class PROCEDURALBOOKSHELF_OT_generate(
    bpy.types.Operator
):

    bl_idname = "procedural_bookshelf.generate"

    bl_label = "Generate Bookshelf"

    def execute(self, context):
        door_count_param = 0 if getattr(context.scene, "pb_door_count_mode", 'AUTO') == 'AUTO' else context.scene.pb_door_count

        problems = generate_bookshelf(
            context.scene.pb_width,
            context.scene.pb_height,
            context.scene.pb_depth,
            context.scene.pb_shelves,
            context.scene.pb_bevel_width,
            context.scene.pb_bevel_segments,
            context.scene.pb_density,
            context.scene.pb_variation,
            context.scene.pb_tilt,
            context.scene.pb_seed,
            context.scene.pb_back_panel_style,
            context.scene.pb_back_panel_thickness,
            context.scene.pb_has_plinth,
            context.scene.pb_plinth_height,
            context.scene.pb_has_crown,
            context.scene.pb_crown_height,
            context.scene.pb_has_front_trim,
            context.scene.pb_stile_width,
            context.scene.pb_has_doors,
            context.scene.pb_door_shelves_covered,
            context.scene.pb_door_style,
            door_count_param,
            context.scene.pb_door_thickness,
            context.scene.pb_door_gap,
            context.scene.pb_door_angle,
            context.scene.pb_has_handles,
            context.scene.pb_handle_style,
            context.scene.pb_handle_material,
            furniture_finish=getattr(context.scene, "pb_furniture_finish", "WALNUT_DARK"),
            prop_density=getattr(context.scene, "pb_prop_density", 0.35),
            door_count_mode=getattr(context.scene, "pb_door_count_mode", "AUTO")
        )

        if problems:

            print(
                f"[Procedural Bookshelf] "
                f"{len(problems)} problema(s) de validación:"
            )

            for problem in problems:

                print(f"  - {problem}")

            self.report(
                {'WARNING'},
                f"Generado con {len(problems)} problema(s) de "
                f"validación — ver consola para detalle"
            )

        else:

            self.report(
                {'INFO'},
                "Generado sin problemas de validación"
            )

        return {'FINISHED'}


# =========================================================
# UPDATE CALLBACKS
# =========================================================

def _on_width_updated(self, context):
    try:
        w = context.scene.pb_width
        stile_w = context.scene.pb_stile_width if getattr(context.scene, "pb_has_front_trim", True) else 0.02
        usable_w = max(0.20, w - 2 * stile_w)
        max_doors = max(1, int(usable_w / 0.38))
        if context.scene.pb_door_count > max_doors:
            context.scene.pb_door_count = max_doors
    except Exception:
        pass


def _on_shelves_updated(self, context):
    try:
        s = context.scene.pb_shelves
        if context.scene.pb_door_shelves_covered > s:
            context.scene.pb_door_shelves_covered = max(1, s)
    except Exception:
        pass


# =========================================================
# PANEL
# =========================================================

class PROCEDURALBOOKSHELF_PT_panel(
    bpy.types.Panel
):

    bl_label = "Procedural Bookshelf"
    bl_idname = "PROCEDURALBOOKSHELF_PT_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Procedural'

    def draw(self, context):
        layout = self.layout

        # 1. Bookshelf Dimensions
        layout.label(text="Bookshelf Dimensions", icon='SHADING_BBOX')
        layout.prop(context.scene, "pb_width")
        layout.prop(context.scene, "pb_height")
        layout.prop(context.scene, "pb_depth")
        layout.prop(context.scene, "pb_shelves")

        layout.separator()

        # 2. Back Panel
        layout.label(text="Back Panel", icon='MOD_SOLIDIFY')
        layout.prop(context.scene, "pb_back_panel_style")
        if context.scene.pb_back_panel_style != 'OPEN':
            layout.prop(context.scene, "pb_back_panel_thickness")

        layout.separator()

        # 3. Structural Trim
        layout.label(text="Structural Trim", icon='MOD_BEVEL')
        layout.prop(context.scene, "pb_has_plinth")
        if context.scene.pb_has_plinth:
            layout.prop(context.scene, "pb_plinth_height")

        layout.prop(context.scene, "pb_has_crown")
        if context.scene.pb_has_crown:
            layout.prop(context.scene, "pb_crown_height")

        layout.prop(context.scene, "pb_has_front_trim")
        if context.scene.pb_has_front_trim:
            layout.prop(context.scene, "pb_stile_width")

        layout.separator()

        # 4. Cabinet Doors
        layout.label(text="Cabinet Doors", icon='OUTLINER_OB_MESH')
        layout.prop(context.scene, "pb_has_doors")

        if context.scene.pb_has_doors:
            box = layout.box()
            box.prop(context.scene, "pb_door_shelves_covered")
            box.prop(context.scene, "pb_door_count_mode")

            mode = getattr(context.scene, "pb_door_count_mode", 'AUTO')
            if mode == 'MANUAL':
                box.prop(context.scene, "pb_door_count", text="Requested Doors")

            # Calculate door grid for UI display
            grid = calculate_door_grid(
                context.scene.pb_height,
                context.scene.pb_width,
                context.scene.pb_door_shelves_covered,
                context.scene.pb_shelves,
                mode,
                context.scene.pb_door_count,
                context.scene.pb_stile_width if context.scene.pb_has_front_trim else 0.02
            )

            box.label(text=f"Calculated Doors: {grid['total_leaves']}", icon='INFO')
            box.label(text=f"Calculated Layout: {grid['rows']} × {grid['cols']}", icon='MOD_ARRAY')
            box.label(text=f"Leaf Height: {grid['leaf_height']:.2f} m", icon='SNAP_VOLUME')

            box.prop(context.scene, "pb_door_style")
            box.prop(context.scene, "pb_door_thickness")
            box.prop(context.scene, "pb_door_gap")
            box.prop(context.scene, "pb_door_angle")

            # 5. Cabinet Hardware
            box.prop(context.scene, "pb_has_handles")
            if context.scene.pb_has_handles:
                hw_box = box.box()
                hw_box.label(text="Hardware Settings", icon='TOOL_SETTINGS')
                hw_box.prop(context.scene, "pb_handle_style")
                hw_box.prop(context.scene, "pb_handle_material")

        layout.separator()

        # 6. Geometry
        layout.label(text="Geometry", icon='MESH_CUBE')
        layout.prop(context.scene, "pb_bevel_width")
        layout.prop(context.scene, "pb_bevel_segments")

        layout.separator()

        # 7. Books
        layout.label(text="Books", icon='BOOKMARKS')
        layout.prop(context.scene, "pb_density")
        layout.prop(context.scene, "pb_variation")
        layout.prop(context.scene, "pb_tilt")
        layout.prop(context.scene, "pb_seed")

        layout.separator()

        # 8. Furniture Material
        layout.label(text="Furniture Material", icon='MATERIAL')
        layout.prop(context.scene, "pb_furniture_finish")

        layout.separator()

        # 9. Decorative Props
        layout.label(text="Decorative Props (Phase 6)", icon='COLLECTION_NEW')
        layout.prop(context.scene, "pb_prop_density")

        layout.separator()

        layout.operator("procedural_bookshelf.generate", icon='CUBE')


# =========================================================
# CLASSES
# =========================================================

classes = (
    PROCEDURALBOOKSHELF_OT_generate,
    PROCEDURALBOOKSHELF_PT_panel,
)


# =========================================================
# REGISTER
# =========================================================

def register():
    for cls in classes:
        bpy.utils.register_class(cls)

    bpy.types.Scene.pb_width = bpy.props.FloatProperty(
        name="Overall Width",
        description="Total outer width of the bookshelf carcass in meters",
        default=2.4,
        min=0.5,
        max=20.0,
        unit='LENGTH',
        update=_on_width_updated
    )

    bpy.types.Scene.pb_height = bpy.props.FloatProperty(
        name="Overall Height",
        description="Total outer height of the bookshelf carcass in meters",
        default=2.2,
        min=0.5,
        max=10.0,
        unit='LENGTH'
    )

    bpy.types.Scene.pb_depth = bpy.props.FloatProperty(
        name="Overall Depth",
        description="Total depth of side panels and shelves in meters",
        default=0.35,
        min=0.1,
        max=2.0,
        unit='LENGTH'
    )

    bpy.types.Scene.pb_shelves = bpy.props.IntProperty(
        name="Shelf Count",
        description="Number of horizontal shelf compartments",
        default=5,
        min=1,
        max=20,
        update=_on_shelves_updated
    )

    bpy.types.Scene.pb_bevel_width = bpy.props.FloatProperty(
        name="Bevel Width",
        description="Bevel width applied to structural timber edges",
        default=0.003,
        min=0.0,
        max=0.05,
        unit='LENGTH'
    )

    bpy.types.Scene.pb_bevel_segments = bpy.props.IntProperty(
        name="Bevel Segments",
        description="Number of polygon segments for edge beveling",
        default=2,
        min=1,
        max=6
    )

    bpy.types.Scene.pb_density = bpy.props.FloatProperty(
        name="Book Density",
        description="Target volume filling ratio for book placement (0.0 to 1.0)",
        default=0.75,
        min=0.0,
        max=1.0
    )

    bpy.types.Scene.pb_variation = bpy.props.FloatProperty(
        name="Book Variation",
        description="Random variance factor for book dimensions and colors",
        default=0.20,
        min=0.0,
        max=0.50
    )

    bpy.types.Scene.pb_tilt = bpy.props.FloatProperty(
        name="Maximum Book Tilt",
        description="Maximum tilt angle factor for leaning books",
        default=0.25,
        min=0.0,
        max=1.0
    )

    bpy.types.Scene.pb_seed = bpy.props.IntProperty(
        name="Random Seed",
        description="Deterministic seed for reproducible procedural generation",
        default=1234,
        min=0,
        max=999999
    )

    bpy.types.Scene.pb_back_panel_style = bpy.props.EnumProperty(
        name="Style",
        description="Style of rear backing panel (Solid Panel or Open Back)",
        items=[
            ('SOLID', "Solid Panel", "Flat solid rear backing panel"),
            ('OPEN', "Open Back", "No rear panel")
        ],
        default='SOLID'
    )

    bpy.types.Scene.pb_back_panel_thickness = bpy.props.FloatProperty(
        name="Back Thickness",
        description="Thickness of backing panel board",
        default=0.005,
        min=0.002,
        max=0.05,
        unit='LENGTH'
    )

    bpy.types.Scene.pb_has_plinth = bpy.props.BoolProperty(
        name="Plinth / Base",
        description="Enable lower architectural kickboard / base plinth",
        default=True
    )

    bpy.types.Scene.pb_plinth_height = bpy.props.FloatProperty(
        name="Plinth Height",
        description="Height of bottom base plinth",
        default=0.10,
        min=0.04,
        max=0.25,
        unit='LENGTH'
    )

    bpy.types.Scene.pb_has_crown = bpy.props.BoolProperty(
        name="Crown Moulding",
        description="Enable top architectural cornice / crown moulding cap",
        default=True
    )

    bpy.types.Scene.pb_crown_height = bpy.props.FloatProperty(
        name="Crown Height",
        description="Height of top crown moulding cap",
        default=0.08,
        min=0.04,
        max=0.20,
        unit='LENGTH'
    )

    bpy.types.Scene.pb_has_front_trim = bpy.props.BoolProperty(
        name="Front Face Trim",
        description="Enable vertical stiles and horizontal rail face trim",
        default=True
    )

    bpy.types.Scene.pb_stile_width = bpy.props.FloatProperty(
        name="Stile Width",
        description="Width of vertical front face stiles",
        default=0.06,
        min=0.02,
        max=0.12,
        unit='LENGTH'
    )

    bpy.types.Scene.pb_has_doors = bpy.props.BoolProperty(
        name="Cabinet Doors",
        description="Enable lower enclosed cabinet doors",
        default=False
    )

    bpy.types.Scene.pb_door_shelves_covered = bpy.props.IntProperty(
        name="Shelves Covered",
        description="Number of lower shelf compartments enclosed by cabinet doors. Cannot exceed total Shelf Count.",
        default=1,
        min=1,
        max=10,
        update=_on_shelves_updated
    )

    bpy.types.Scene.pb_door_style = bpy.props.EnumProperty(
        name="Door Style",
        description="Cabinet door style (Flat, Raised Panel, or Glass)",
        items=[
            ('FLAT', "Flat Panel", "Slab door panel"),
            ('RAISED_PANEL', "Raised Panel", "Framed door with raised center field"),
            ('GLASS', "Glass Panel", "Framed door with glass insert")
        ],
        default='RAISED_PANEL'
    )

    bpy.types.Scene.pb_door_count_mode = bpy.props.EnumProperty(
        name="Door Count Mode",
        description="Door count selection mode: Auto (calculated from width) or Manual",
        items=[
            ('AUTO', "Auto", "Automatically calculate optimal door count based on width"),
            ('MANUAL', "Manual", "Manually specify door count (bounded by minimum width)")
        ],
        default='AUTO'
    )

    bpy.types.Scene.pb_door_count = bpy.props.IntProperty(
        name="Door Count",
        description="Number of cabinet doors in Manual mode. Automatically clamped by minimum door width constraint (0.40m)",
        default=2,
        min=1,
        max=20
    )

    bpy.types.Scene.pb_door_thickness = bpy.props.FloatProperty(
        name="Door Thickness",
        description="Thickness of cabinet door leaves",
        default=0.018,
        min=0.010,
        max=0.040,
        unit='LENGTH'
    )

    bpy.types.Scene.pb_door_gap = bpy.props.FloatProperty(
        name="Door Gap",
        description="Perimeter reveal gap between doors and frame",
        default=0.002,
        min=0.001,
        max=0.010,
        unit='LENGTH'
    )

    bpy.types.Scene.pb_door_angle = bpy.props.FloatProperty(
        name="Door Angle",
        description="Opening rotation angle for cabinet doors in radians",
        default=0.0,
        min=0.0,
        max=math.radians(135.0),
        subtype='ANGLE'
    )

    bpy.types.Scene.pb_has_handles = bpy.props.BoolProperty(
        name="Cabinet Handles",
        description="Enable door handles and hardware",
        default=True
    )

    bpy.types.Scene.pb_handle_style = bpy.props.EnumProperty(
        name="Handle Style",
        description="Cabinet hardware handle style (Knob, Pull Bar, or Drop Ring)",
        items=[
            ('KNOB', "Knob", "Spherical / cylindrical knob"),
            ('PULL_BAR', "Pull Bar", "Horizontal bar pull"),
            ('DROP_RING', "Drop Ring", "Teardrop ring pull")
        ],
        default='KNOB'
    )

    bpy.types.Scene.pb_handle_material = bpy.props.EnumProperty(
        name="Handle Finish",
        description="Hardware metal finish (Brass, Aged Bronze, or Chrome)",
        items=[
            ('BRASS', "Brass", "Satin warm brass"),
            ('AGED_BRONZE', "Aged Bronze", "Dark patinated bronze"),
            ('CHROME', "Chrome", "High polish chrome"),
            ('SILVER', "Silver", "Satin silver metal"),
            ('BLACK', "Black", "Matt black metal")
        ],
        default='BRASS'
    )

    bpy.types.Scene.pb_furniture_finish = bpy.props.EnumProperty(
        name="Furniture Material",
        description="Wood texture finish for structural carcass and doors",
        items=[
            ('WALNUT_DARK', "Walnut Dark", "Rich dark walnut finish"),
            ('OAK_NATURAL', "Oak Natural", "Natural light oak finish"),
            ('TEAK_MID', "Teak Mid", "Mid-tone warm teak finish")
        ],
        default='WALNUT_DARK'
    )

    bpy.types.Scene.pb_prop_density = bpy.props.FloatProperty(
        name="Decorative Density",
        description="Decorative budget (0.0=none, 0.35=hero focal+vessel, 1.0=full balance)",
        default=0.35,
        min=0.0,
        max=1.0
    )


# =========================================================
# UNREGISTER
# =========================================================

def unregister():
    del bpy.types.Scene.pb_width
    del bpy.types.Scene.pb_height
    del bpy.types.Scene.pb_depth
    del bpy.types.Scene.pb_shelves

    del bpy.types.Scene.pb_bevel_width
    del bpy.types.Scene.pb_bevel_segments

    del bpy.types.Scene.pb_density
    del bpy.types.Scene.pb_variation
    del bpy.types.Scene.pb_tilt
    del bpy.types.Scene.pb_seed

    del bpy.types.Scene.pb_back_panel_style
    del bpy.types.Scene.pb_back_panel_thickness

    del bpy.types.Scene.pb_has_plinth
    del bpy.types.Scene.pb_plinth_height
    del bpy.types.Scene.pb_has_crown
    del bpy.types.Scene.pb_crown_height
    del bpy.types.Scene.pb_has_front_trim
    del bpy.types.Scene.pb_stile_width

    del bpy.types.Scene.pb_has_doors
    del bpy.types.Scene.pb_door_shelves_covered
    del bpy.types.Scene.pb_door_style
    del bpy.types.Scene.pb_door_count_mode
    del bpy.types.Scene.pb_door_count
    del bpy.types.Scene.pb_door_thickness
    del bpy.types.Scene.pb_door_gap
    del bpy.types.Scene.pb_door_angle
    del bpy.types.Scene.pb_has_handles
    del bpy.types.Scene.pb_handle_style
    del bpy.types.Scene.pb_handle_material
    del bpy.types.Scene.pb_furniture_finish
    del bpy.types.Scene.pb_prop_density

    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)



# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":

    register()

