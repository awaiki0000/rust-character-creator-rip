import bpy
import os
import re
import json
import bpy.utils.previews
import mathutils
from bpy.types import Operator, Panel, PropertyGroup
from bpy.props import StringProperty, EnumProperty, BoolProperty


CATEGORIES = [
    "Head",
    "Hair",
    "Beard",
    "Head Armor",
    "Neck Armor",
    "Chest",
    "Chest Armor",
    "Legs",
    "Leg Armor",
    "Hands",
    "Hand Armor",
    "Feet",
    "Full Body",
    "Right Hand",
    "Left Hand",
]

GENDER_TOKENS = ("Female", "Male")
RACE_TOKENS = ("Light", "Dark")

CHAR_COLLECTION_NAME = "Characters"
LIBRARY_ITEMS_DIRNAME = "library"


def library_items_dir():
    return os.path.join(os.path.dirname(LIBRARY_PATH), LIBRARY_ITEMS_DIRNAME)


def library_available():
    return os.path.isdir(library_items_dir()) or library_file_available()
HAND_SLOTS = ("Right Hand", "Left Hand")
LIBRARY_CATEGORY_ALIASES = {"Right Hand": "Weapons", "Left Hand": "Weapons"}
FINGER_TOKENS = ("index", "middle", "ring", "little", "pinky", "thumb")


def is_finger_bone(name, prefix):
    return name.startswith(prefix) and any(t in name for t in FINGER_TOKENS)

LIBRARY_FILENAME = "Rust_RIG.blend"
ADDON_DIR = os.path.dirname(os.path.abspath(__file__))
LIBRARY_PATH = os.path.join(ADDON_DIR, "assets", LIBRARY_FILENAME)
CATALOG_PATH = os.path.join(ADDON_DIR, "assets", "catalog.json")

_enum_cache = {}

_catalog_cache = None


def slug(category):
    return category.replace(" ", "_")


def strip_tokens(name, tokens):
    for t in tokens:
        name = re.sub(rf"\b{t}\b", "", name)
    return re.sub(r"\s+", " ", name).strip()


def library_file_available():
    return os.path.isfile(LIBRARY_PATH)


def catalog_available():
    return os.path.isfile(CATALOG_PATH)


def load_catalog():
    global _catalog_cache
    if _catalog_cache is not None:
        return _catalog_cache
    if not catalog_available():
        _catalog_cache = []
        return _catalog_cache
    try:
        with open(CATALOG_PATH, "r", encoding="utf-8") as f:
            _catalog_cache = json.load(f)
    except Exception:
        _catalog_cache = []
    return _catalog_cache


def invalidate_catalog_cache():
    global _catalog_cache
    _catalog_cache = None


def gather_category_items(gender, race, category):
    found = {}
    for entry in load_catalog():
        if entry["category"] != LIBRARY_CATEGORY_ALIASES.get(category, category):
            continue
        if entry["group"] not in ("Neutral", "Items", gender):
            continue
        name = entry["object_name"]
        item_race = None
        for rt in RACE_TOKENS:
            if re.search(rf"\b{rt}\b", name):
                item_race = rt
                break
        if item_race is not None and item_race != race:
            continue
        disp = strip_tokens(name, GENDER_TOKENS + RACE_TOKENS)
        if category in HAND_SLOTS and disp.endswith(" L"):
            continue
        found[disp] = (entry["object_name"], entry["mesh_names"])
    return sorted(found.items(), key=lambda kv: kv[0])


def find_armature_by_display(gender, race, category, display_name):
    for disp, (obj_name, mesh_names) in gather_category_items(gender, race, category):
        if disp == display_name:
            return obj_name, mesh_names
    return None, None


CACHE_COLL_NAME = "RUSTCHAR_LibCache"


def _get_lib_cache():
    coll = bpy.data.collections.get(CACHE_COLL_NAME)
    if coll is None:
        coll = bpy.data.collections.new(CACHE_COLL_NAME)
        bpy.context.scene.collection.children.link(coll)
        for vl in bpy.context.scene.view_layers:
            lc = vl.layer_collection.children.get(CACHE_COLL_NAME)
            if lc:
                lc.exclude = True
    return coll


def duplicate_item(object_name, mesh_names, target_collection):
    cache = _get_lib_cache()
    cached_arm = None
    for o in cache.objects:
        if o.type == 'ARMATURE' and o.get("lib_src") == object_name:
            cached_arm = o
            break
    if cached_arm is None:
        arm, meshes = _append_item_from_library(object_name, mesh_names, cache)
        if arm is None:
            return arm, meshes
        arm["lib_src"] = object_name
        cached_arm = arm
    cached_meshes = [o for o in bpy.data.objects
                     if o.parent == cached_arm and o.type == 'MESH']
    new_arm = cached_arm.copy()
    new_arm.data = cached_arm.data.copy()
    if "lib_src" in new_arm:
        del new_arm["lib_src"]
    target_collection.objects.link(new_arm)
    new_meshes = []
    for m in cached_meshes:
        nm = m.copy()
        nm.data = m.data.copy()
        nm.parent = new_arm
        for md in nm.modifiers:
            if md.type == 'ARMATURE' and md.object == cached_arm:
                md.object = new_arm
        target_collection.objects.link(nm)
        new_meshes.append(nm)
    return new_arm, new_meshes


def _append_item_from_library(object_name, mesh_names, target_collection):
    wanted = set([object_name] + list(mesh_names))
    src_path = LIBRARY_PATH
    for _e in load_catalog():
        if _e["object_name"] == object_name:
            if _e.get("file"):
                _cand = os.path.join(library_items_dir(), _e["file"])
                if os.path.isfile(_cand):
                    src_path = _cand
            break
    with bpy.data.libraries.load(src_path, link=False) as (data_from, data_to):
        if src_path != LIBRARY_PATH:
            data_to.objects = list(data_from.objects)
        else:
            data_to.objects = [n for n in data_from.objects if n in wanted]

    new_armature = None
    new_meshes = []
    for obj in data_to.objects:
        if obj is None:
            continue
        target_collection.objects.link(obj)
        if obj.type == 'ARMATURE':
            new_armature = obj
        else:
            new_meshes.append(obj)

    if new_armature is not None:
        new_armature.data = new_armature.data.copy()
        new_armature.show_in_front = True
        new_armature.data.display_type = 'WIRE'

    return new_armature, new_meshes


def remove_armature_object(armature_obj):
    if armature_obj is None:
        return
    arm_data = armature_obj.data
    bpy.data.objects.remove(armature_obj)
    if arm_data is not None and arm_data.users == 0:
        bpy.data.armatures.remove(arm_data)


def _snap_via_operators(mesh_objs, target_armature):
    win = bpy.context.window_manager.windows[0]
    area = next((a for a in win.screen.areas if a.type == 'VIEW_3D'), None)
    if area is None:
        raise RuntimeError("No VIEW_3D area available for context override")
    region = next((r for r in area.regions if r.type == 'WINDOW'), None)

    with bpy.context.temp_override(window=win, area=area, region=region):
        bpy.ops.object.select_all(action='DESELECT')
        for mesh_obj in mesh_objs:
            mesh_obj.select_set(True)
        bpy.context.view_layer.objects.active = mesh_objs[0]
        r1 = bpy.ops.object.parent_clear(type='CLEAR_KEEP_TRANSFORM')
        if r1 != {'FINISHED'}:
            raise RuntimeError(f"parent_clear returned {r1}")

        bpy.ops.object.select_all(action='DESELECT')
        for mesh_obj in mesh_objs:
            mesh_obj.select_set(True)
        target_armature.select_set(True)
        bpy.context.view_layer.objects.active = target_armature
        r2 = bpy.ops.object.parent_set(type='ARMATURE', keep_transform=True)
        if r2 != {'FINISHED'}:
            raise RuntimeError(f"parent_set returned {r2}")

    import mathutils
    for mesh_obj in mesh_objs:
        mesh_obj.matrix_parent_inverse = mathutils.Matrix.Identity(4)


def _snap_via_matrices(mesh_objs, target_armature):
    import mathutils
    for mesh_obj in mesh_objs:
        mesh_obj.parent = None
        mesh_obj.parent = target_armature
        mesh_obj.matrix_parent_inverse = mathutils.Matrix.Identity(4)


def snap_meshes_to_armature(mesh_objs, target_armature):
    if not mesh_objs:
        return

    for mesh_obj in mesh_objs:
        for mod in list(mesh_obj.modifiers):
            if mod.type == 'ARMATURE':
                mesh_obj.modifiers.remove(mod)

    try:
        _snap_via_operators(mesh_objs, target_armature)
    except Exception:
        _snap_via_matrices(mesh_objs, target_armature)

    for mesh_obj in mesh_objs:
        mod = next((m for m in mesh_obj.modifiers if m.type == 'ARMATURE'), None)
        if mod is None:
            mod = mesh_obj.modifiers.new(name="Armature", type='ARMATURE')
        mod.object = target_armature
        mod.use_vertex_groups = True


POSES = {
 "pose 1": {
  "pelvis": {
   "loc": [
    -0.0,
    0.34502,
    -0.13699
   ],
   "rot": [
    0.98175,
    0.19018,
    0.0,
    -0.0
   ]
  },
  "l_hip": {
   "rot": [
    0.97428,
    0.0626,
    0.06232,
    -0.20731
   ]
  },
  "l_knee": {
   "rot": [
    0.67083,
    0.69274,
    0.14625,
    0.2207
   ]
  },
  "l_foot": {
   "rot": [
    0.98184,
    0.01773,
    0.18183,
    0.05111
   ]
  },
  "l_toe": {
   "rot": [
    0.75121,
    -0.08046,
    0.02092,
    0.65481
   ]
  },
  "r_hip": {
   "rot": [
    0.86519,
    0.47701,
    0.14447,
    -0.05506
   ]
  },
  "r_knee": {
   "rot": [
    0.78281,
    -0.59218,
    -0.19082,
    0.01088
   ]
  },
  "r_foot": {
   "rot": [
    0.98525,
    -0.16683,
    0.03132,
    0.0216
   ]
  },
  "spine1": {
   "rot": [
    0.91666,
    0.26784,
    0.29478,
    0.0333
   ]
  },
  "spine2": {
   "rot": [
    0.99939,
    0.03191,
    0.00055,
    0.01436
   ]
  },
  "spine3": {
   "rot": [
    0.96153,
    0.07446,
    -0.26151,
    0.03912
   ]
  },
  "l_upperarm": {
   "rot": [
    0.97021,
    -0.08218,
    -0.17136,
    -0.15025
   ]
  },
  "l_forearm": {
   "rot": [
    0.85127,
    -0.33313,
    0.23453,
    -0.33069
   ]
  },
  "l_index1": {
   "rot": [
    0.98216,
    -0.13644,
    -0.08854,
    -0.09442
   ]
  },
  "l_index2": {
   "rot": [
    0.9976,
    0.06507,
    0.00412,
    -0.0233
   ]
  },
  "l_index3": {
   "rot": [
    0.9966,
    0.08097,
    0.0,
    -0.01546
   ]
  },
  "l_middle_meta": {
   "rot": [
    0.99989,
    0.00308,
    0.01306,
    -0.00666
   ]
  },
  "l_middle1": {
   "rot": [
    0.99294,
    -0.11183,
    0.01052,
    0.03804
   ]
  },
  "l_middle2": {
   "rot": [
    0.99417,
    0.10741,
    -0.00421,
    -0.00799
   ]
  },
  "l_middle3": {
   "rot": [
    0.99731,
    0.07295,
    -0.00177,
    -0.00758
   ]
  },
  "l_pinky_meta": {
   "rot": [
    0.9922,
    -0.00443,
    0.10836,
    0.06151
   ]
  },
  "l_little1": {
   "rot": [
    0.9832,
    -0.14573,
    -0.07071,
    0.08414
   ]
  },
  "l_little2": {
   "rot": [
    0.99496,
    -0.06532,
    -0.01416,
    0.0747
   ]
  },
  "l_little3": {
   "rot": [
    0.97763,
    -0.1203,
    0.15533,
    -0.07504
   ]
  },
  "l_ring_meta": {
   "rot": [
    0.99778,
    -0.06256,
    0.00636,
    0.02182
   ]
  },
  "l_ring1": {
   "rot": [
    0.9955,
    0.09092,
    -0.01201,
    0.02376
   ]
  },
  "l_ring2": {
   "rot": [
    0.97911,
    -0.2025,
    -0.00742,
    0.01684
   ]
  },
  "l_ring3": {
   "rot": [
    0.99277,
    -0.12,
    -0.00057,
    0.00114
   ]
  },
  "neck": {
   "rot": [
    0.96725,
    0.0246,
    -0.22373,
    0.11738
   ]
  },
  "head": {
   "rot": [
    0.97413,
    -0.20697,
    0.08296,
    0.03672
   ]
  },
  "r_forearm": {
   "rot": [
    0.94562,
    -0.04336,
    -0.13339,
    -0.29347
   ]
  },
  "r_index1": {
   "rot": [
    0.74335,
    -0.6074,
    0.27734,
    -0.03974
   ]
  },
  "r_index2": {
   "rot": [
    0.93934,
    -0.32239,
    -0.0011,
    -0.11706
   ]
  },
  "r_index3": {
   "rot": [
    0.96399,
    -0.25477,
    0.00416,
    -0.07613
   ]
  },
  "r_middle1": {
   "rot": [
    0.76193,
    -0.64159,
    0.07245,
    0.05066
   ]
  },
  "r_middle2": {
   "rot": [
    0.98247,
    -0.18181,
    0.00571,
    -0.04088
   ]
  },
  "r_middle3": {
   "rot": [
    0.9948,
    -0.09927,
    0.0008,
    -0.02288
   ]
  },
  "r_little1": {
   "rot": [
    0.77645,
    -0.62482,
    -0.0662,
    0.04835
   ]
  },
  "r_ring_meta": {
   "rot": [
    0.999,
    -0.04304,
    0.00884,
    0.00826
   ]
  },
  "r_ring1": {
   "rot": [
    0.8091,
    -0.58538,
    7e-05,
    0.05176
   ]
  },
  "r_ring2": {
   "rot": [
    0.98959,
    -0.14321,
    -0.00157,
    -0.01445
   ]
  },
  "r_ring3": {
   "rot": [
    0.99562,
    -0.09339,
    0.00061,
    -0.00393
   ]
  },
  "r_thumb1": {
   "rot": [
    0.96821,
    0.15388,
    -0.02099,
    -0.1961
   ]
  },
  "r_thumb3": {
   "rot": [
    0.94491,
    -0.23844,
    -0.20042,
    0.10064
   ]
  }
 },
 "pose 2": {
  "l_foot": {
   "rot": [
    0.95998,
    -0.28005,
    -0.0,
    -0.0
   ]
  },
  "r_hip": {
   "rot": [
    0.98283,
    -0.02126,
    0.18331,
    0.00112
   ]
  },
  "r_foot": {
   "rot": [
    0.99825,
    -0.05916,
    -0.0,
    0.0
   ]
  },
  "spine1": {
   "rot": [
    0.99885,
    -0.01699,
    0.03403,
    0.02905
   ]
  },
  "spine2": {
   "rot": [
    0.9977,
    -0.04051,
    0.05431,
    0.00363
   ]
  },
  "spine3": {
   "rot": [
    0.99787,
    0.06174,
    -0.00095,
    0.02096
   ]
  },
  "clavicle.L": {
   "loc": [
    -0.00111,
    0.00027,
    -0.0006
   ],
   "rot": [
    0.99926,
    -0.01031,
    0.02138,
    0.03018
   ]
  },
  "upperarm.L": {
   "loc": [
    0.00567,
    -0.01226,
    0.01015
   ],
   "rot": [
    0.87467,
    -0.13626,
    0.28223,
    -0.36977
   ]
  },
  "l_forearm": {
   "rot": [
    0.82303,
    -0.26584,
    0.30823,
    -0.39617
   ]
  },
  "l_forearm_twist_01": {
   "rot": [
    0.74669,
    -0.04958,
    -0.6631,
    -0.01726
   ]
  },
  "l_hand": {
   "rot": [
    0.50743,
    0.14649,
    -0.83942,
    0.12815
   ]
  },
  "l_index1": {
   "rot": [
    0.99144,
    0.12223,
    0.00564,
    -0.04566
   ]
  },
  "l_index2": {
   "rot": [
    0.97328,
    -0.22879,
    0.00112,
    0.01954
   ]
  },
  "l_index3": {
   "rot": [
    0.98561,
    -0.16854,
    0.00025,
    0.01262
   ]
  },
  "l_middle1": {
   "rot": [
    0.99696,
    0.05865,
    -0.02994,
    0.04165
   ]
  },
  "l_middle2": {
   "rot": [
    0.97532,
    -0.21838,
    -0.03261,
    0.0014
   ]
  },
  "l_middle3": {
   "rot": [
    0.98698,
    -0.16049,
    -0.00824,
    -0.00744
   ]
  },
  "l_pinky_meta": {
   "rot": [
    0.99278,
    -0.0895,
    -0.0188,
    0.07757
   ]
  },
  "l_little1": {
   "rot": [
    0.98648,
    0.07447,
    -0.13775,
    0.04826
   ]
  },
  "l_little2": {
   "rot": [
    0.89844,
    -0.43904,
    -0.00556,
    0.0028
   ]
  },
  "l_little3": {
   "rot": [
    0.97173,
    -0.23578,
    -0.00227,
    -0.01196
   ]
  },
  "l_ring_meta": {
   "rot": [
    0.99926,
    -0.01197,
    -0.03514,
    0.01
   ]
  },
  "l_ring1": {
   "rot": [
    0.99573,
    0.05263,
    -0.0139,
    0.07462
   ]
  },
  "l_ring2": {
   "rot": [
    0.9417,
    -0.33018,
    -0.05653,
    0.03147
   ]
  },
  "l_ring3": {
   "rot": [
    0.98553,
    -0.169,
    -0.01249,
    0.00374
   ]
  },
  "l_thumb2": {
   "rot": [
    0.99633,
    0.02278,
    -0.02565,
    0.07846
   ]
  },
  "l_thumb3": {
   "rot": [
    0.99734,
    0.01223,
    0.06699,
    -0.02587
   ]
  },
  "neck": {
   "rot": [
    0.99872,
    -0.00317,
    0.04919,
    -0.01108
   ]
  },
  "head": {
   "rot": [
    0.99788,
    0.06342,
    -0.00646,
    -0.01312
   ]
  },
  "clavicle.R": {
   "loc": [
    0.0011,
    -0.00035,
    -0.00059
   ],
   "rot": [
    0.9994,
    -0.02053,
    -0.01486,
    -0.02339
   ]
  },
  "upperarm.R": {
   "loc": [
    -0.00575,
    0.01104,
    0.01143
   ],
   "rot": [
    0.93013,
    0.2084,
    -0.17516,
    -0.24645
   ]
  },
  "r_forearm": {
   "rot": [
    0.79342,
    0.44962,
    -0.07657,
    -0.40308
   ]
  },
  "r_hand": {
   "rot": [
    0.9508,
    -0.18131,
    0.22049,
    -0.12035
   ]
  },
  "r_index_meta": {
   "rot": [
    0.97742,
    -0.06311,
    0.19724,
    -0.04198
   ]
  },
  "r_index1": {
   "rot": [
    0.98801,
    -0.0602,
    -0.00436,
    -0.14211
   ]
  },
  "r_index2": {
   "rot": [
    0.99837,
    -0.05676,
    -0.00018,
    -0.00509
   ]
  },
  "r_index3": {
   "rot": [
    0.99819,
    -0.05995,
    -0.0,
    -0.00481
   ]
  },
  "r_middle_meta": {
   "rot": [
    0.99564,
    -0.08191,
    0.04434,
    -0.00459
   ]
  },
  "r_middle1": {
   "rot": [
    0.99501,
    -0.09458,
    -0.00979,
    -0.03024
   ]
  },
  "r_middle2": {
   "rot": [
    0.99848,
    0.05377,
    -0.00068,
    -0.01241
   ]
  },
  "r_middle3": {
   "rot": [
    0.99918,
    0.04036,
    1e-05,
    -0.00433
   ]
  },
  "r_pinky_meta": {
   "rot": [
    0.99101,
    -0.04457,
    -0.10721,
    0.06644
   ]
  },
  "r_little1": {
   "rot": [
    0.99085,
    0.06424,
    0.00169,
    0.1187
   ]
  },
  "r_little2": {
   "rot": [
    0.95289,
    0.30282,
    0.00555,
    0.01635
   ]
  },
  "r_little3": {
   "rot": [
    0.99513,
    0.09829,
    0.00025,
    -0.00798
   ]
  },
  "r_ring_meta": {
   "rot": [
    0.9979,
    -0.05478,
    0.03281,
    0.01067
   ]
  },
  "r_ring1": {
   "rot": [
    0.99893,
    -0.0423,
    0.00954,
    0.01626
   ]
  },
  "r_ring2": {
   "rot": [
    0.98738,
    0.15753,
    0.00036,
    0.01625
   ]
  },
  "r_ring3": {
   "rot": [
    0.99439,
    0.10558,
    -0.00107,
    0.00561
   ]
  }
 },
 "pose 3": {
  "l_hip": {
   "rot": [
    0.9965,
    0.00964,
    -0.08307,
    0.00051
   ]
  },
  "l_foot": {
   "rot": [
    0.91515,
    -0.40311,
    -0.0,
    -0.0
   ]
  },
  "r_hip": {
   "rot": [
    0.98283,
    -0.02126,
    0.18331,
    0.00112
   ]
  },
  "r_foot": {
   "rot": [
    0.99825,
    -0.05916,
    -0.0,
    0.0
   ]
  },
  "spine1": {
   "rot": [
    0.99885,
    -0.01699,
    0.03403,
    0.02905
   ]
  },
  "spine2": {
   "rot": [
    0.9977,
    -0.04051,
    0.05431,
    0.00363
   ]
  },
  "spine3": {
   "rot": [
    0.99787,
    0.06174,
    -0.00095,
    0.02096
   ]
  },
  "clavicle.L": {
   "loc": [
    -0.00111,
    0.00027,
    -0.0006
   ],
   "rot": [
    0.99926,
    -0.01031,
    0.02138,
    0.03018
   ]
  },
  "l_forearm": {
   "rot": [
    0.93834,
    0.30027,
    0.02302,
    -0.16975
   ]
  },
  "l_forearm_twist_01": {
   "rot": [
    0.74669,
    -0.04958,
    -0.6631,
    -0.01726
   ]
  },
  "l_hand": {
   "rot": [
    0.50743,
    0.14649,
    -0.83942,
    0.12815
   ]
  },
  "l_index1": {
   "rot": [
    0.9837,
    -0.07399,
    -0.14835,
    -0.0696
   ]
  },
  "l_index2": {
   "rot": [
    0.99556,
    0.09387,
    0.00712,
    -0.00278
   ]
  },
  "l_index3": {
   "rot": [
    0.98989,
    0.13032,
    0.05153,
    -0.02193
   ]
  },
  "l_middle_meta": {
   "rot": [
    0.99943,
    -0.00965,
    0.03245,
    -0.00082
   ]
  },
  "l_middle1": {
   "rot": [
    0.99559,
    -0.05822,
    -0.04211,
    0.06023
   ]
  },
  "l_middle2": {
   "rot": [
    0.99547,
    0.08894,
    -0.02755,
    -0.01934
   ]
  },
  "l_middle3": {
   "rot": [
    0.99959,
    0.01018,
    -0.01711,
    0.02076
   ]
  },
  "l_pinky_meta": {
   "rot": [
    0.99278,
    -0.0895,
    -0.0188,
    0.07757
   ]
  },
  "l_little1": {
   "rot": [
    0.97449,
    -0.04809,
    -0.15814,
    0.15184
   ]
  },
  "l_little2": {
   "rot": [
    0.95256,
    -0.25638,
    -0.08302,
    -0.14144
   ]
  },
  "l_little3": {
   "rot": [
    0.99271,
    -0.05235,
    -0.06472,
    -0.08712
   ]
  },
  "l_ring_meta": {
   "rot": [
    0.99926,
    -0.01197,
    -0.03514,
    0.01
   ]
  },
  "l_ring1": {
   "loc": [
    -0.00525,
    -0.0002,
    0.00024
   ],
   "rot": [
    0.99058,
    -0.11672,
    -0.05704,
    0.04333
   ]
  },
  "l_ring2": {
   "rot": [
    0.99839,
    -0.02008,
    -0.05311,
    0.00185
   ]
  },
  "l_ring3": {
   "rot": [
    0.99789,
    -0.06276,
    -0.01,
    0.0133
   ]
  },
  "l_thumb1": {
   "rot": [
    0.97875,
    -0.03944,
    0.13966,
    0.14486
   ]
  },
  "l_thumb3": {
   "rot": [
    0.99396,
    0.09295,
    0.00058,
    -0.0583
   ]
  },
  "neck": {
   "rot": [
    0.99078,
    -0.0018,
    0.13544,
    -0.00031
   ]
  },
  "head": {
   "rot": [
    0.94897,
    0.29712,
    0.0289,
    0.10171
   ]
  },
  "clavicle.R": {
   "loc": [
    0.0011,
    -0.00035,
    -0.00059
   ],
   "rot": [
    0.99847,
    -0.02885,
    -0.04637,
    -0.00847
   ]
  },
  "upperarm.R": {
   "loc": [
    -0.00575,
    0.01104,
    0.01143
   ],
   "rot": [
    0.91309,
    -0.02123,
    -0.21744,
    -0.34428
   ]
  },
  "r_forearm": {
   "rot": [
    0.64248,
    -0.71109,
    0.02284,
    -0.28469
   ]
  },
  "r_hand": {
   "rot": [
    0.9502,
    -0.1811,
    0.21882,
    -0.12821
   ]
  },
  "r_index_meta": {
   "rot": [
    0.97742,
    -0.06311,
    0.19724,
    -0.04198
   ]
  },
  "r_index1": {
   "rot": [
    0.99479,
    0.04486,
    0.04045,
    -0.08208
   ]
  },
  "r_index2": {
   "rot": [
    0.98108,
    -0.18935,
    0.02398,
    0.03256
   ]
  },
  "r_index3": {
   "rot": [
    0.98181,
    -0.14773,
    0.11907,
    -0.00665
   ]
  },
  "r_middle_meta": {
   "loc": [
    -4e-05,
    0.00107,
    -6e-05
   ],
   "rot": [
    0.99754,
    -0.00695,
    0.04874,
    -0.04989
   ]
  },
  "r_middle1": {
   "loc": [
    -0.00029,
    0.001,
    -0.00449
   ],
   "rot": [
    0.81892,
    -0.563,
    -0.09738,
    -0.05396
   ]
  },
  "r_middle2": {
   "rot": [
    0.95633,
    -0.2896,
    -0.00218,
    -0.03957
   ]
  },
  "r_middle3": {
   "rot": [
    0.99441,
    -0.10455,
    0.01348,
    -0.00511
   ]
  },
  "r_pinky_meta": {
   "loc": [
    0.00026,
    -0.00102,
    -0.00017
   ],
   "rot": [
    0.99546,
    0.0309,
    -0.08567,
    0.02751
   ]
  },
  "r_little1": {
   "loc": [
    0.001,
    -0.00165,
    0.00424
   ],
   "rot": [
    0.90894,
    -0.38304,
    -0.1536,
    0.05926
   ]
  },
  "r_little2": {
   "rot": [
    0.98385,
    -0.12914,
    0.12269,
    0.01785
   ]
  },
  "r_little3": {
   "rot": [
    0.99914,
    -0.01402,
    -0.00982,
    -0.03773
   ]
  },
  "r_ring_meta": {
   "rot": [
    0.99839,
    0.02449,
    0.04462,
    -0.02499
   ]
  },
  "r_ring1": {
   "loc": [
    -0.00098,
    0.00253,
    -0.00041
   ],
   "rot": [
    0.84238,
    -0.52431,
    -0.09965,
    -0.07466
   ]
  },
  "r_ring2": {
   "rot": [
    0.98153,
    -0.1867,
    -0.0105,
    -0.04039
   ]
  },
  "r_ring3": {
   "rot": [
    0.99997,
    0.00282,
    -0.00078,
    -0.00764
   ]
  },
  "r_thumb1": {
   "rot": [
    0.90086,
    -0.29168,
    -0.31748,
    -0.0508
   ]
  },
  "r_thumb2": {
   "rot": [
    0.99912,
    0.00845,
    -0.03281,
    -0.02466
   ]
  },
  "r_thumb3": {
   "rot": [
    0.91801,
    -0.36113,
    -0.16343,
    -0.01149
   ]
  }
 },
 "pose 4": {
  "l_foot": {
   "rot": [
    0.86151,
    -0.50773,
    -0.0,
    -0.0
   ]
  },
  "r_hip": {
   "rot": [
    0.99977,
    -0.00248,
    0.02142,
    0.00013
   ]
  },
  "r_foot": {
   "rot": [
    0.97987,
    -0.19962,
    -0.0,
    0.0
   ]
  },
  "spine1": {
   "rot": [
    0.99926,
    0.01948,
    -0.01756,
    -0.02801
   ]
  },
  "clavicle.L": {
   "loc": [
    -0.00089,
    0.00014,
    0.00059
   ],
   "rot": [
    0.98573,
    -0.05016,
    0.12118,
    -0.10552
   ]
  },
  "upperarm.L": {
   "loc": [
    -0.00976,
    -0.02701,
    0.01153
   ],
   "rot": [
    0.98376,
    -0.04359,
    0.16012,
    -0.06836
   ]
  },
  "l_forearm": {
   "rot": [
    0.91902,
    0.33276,
    0.04302,
    -0.20694
   ]
  },
  "l_forearm_twist_01": {
   "rot": [
    0.74669,
    -0.04958,
    -0.6631,
    -0.01726
   ]
  },
  "l_hand": {
   "rot": [
    0.19043,
    -0.11003,
    -0.95303,
    0.20824
   ]
  },
  "l_index_meta": {
   "rot": [
    0.97206,
    0.23403,
    0.0113,
    -0.01392
   ]
  },
  "l_index1": {
   "rot": [
    0.94457,
    0.28874,
    -0.08797,
    -0.12912
   ]
  },
  "l_index2": {
   "rot": [
    0.99896,
    0.03991,
    0.00387,
    -0.02189
   ]
  },
  "l_index3": {
   "rot": [
    0.99961,
    0.02561,
    0.00016,
    -0.01139
   ]
  },
  "l_middle_meta": {
   "rot": [
    0.97347,
    0.21326,
    0.07278,
    -0.03975
   ]
  },
  "l_middle1": {
   "rot": [
    0.95546,
    0.27536,
    0.10575,
    0.00965
   ]
  },
  "l_middle2": {
   "rot": [
    0.99966,
    -0.0229,
    0.0019,
    -0.01225
   ]
  },
  "l_middle3": {
   "rot": [
    0.99988,
    -0.0138,
    -0.0001,
    -0.00652
   ]
  },
  "l_pinky_meta": {
   "rot": [
    0.99783,
    -0.05519,
    0.03359,
    0.01248
   ]
  },
  "l_little1": {
   "rot": [
    0.92763,
    0.31025,
    -0.0881,
    -0.18837
   ]
  },
  "l_little2": {
   "rot": [
    0.89895,
    -0.23956,
    0.30758,
    -0.19973
   ]
  },
  "l_little3": {
   "rot": [
    0.98039,
    -0.19085,
    0.04349,
    -0.02296
   ]
  },
  "l_ring_meta": {
   "rot": [
    0.9852,
    0.15821,
    0.01216,
    -0.06489
   ]
  },
  "l_ring1": {
   "rot": [
    0.97064,
    0.15893,
    0.18035,
    0.00854
   ]
  },
  "l_ring2": {
   "rot": [
    0.99989,
    0.01027,
    -0.00077,
    -0.01086
   ]
  },
  "l_ring3": {
   "rot": [
    0.99781,
    -0.06135,
    0.0232,
    -0.00869
   ]
  },
  "l_thumb1": {
   "rot": [
    0.96684,
    0.09103,
    0.11573,
    0.20865
   ]
  },
  "l_thumb2": {
   "rot": [
    0.96459,
    -0.07507,
    0.23523,
    0.09271
   ]
  },
  "l_thumb3": {
   "rot": [
    0.9963,
    0.00339,
    -0.0044,
    0.08577
   ]
  },
  "neck": {
   "rot": [
    0.99829,
    0.01763,
    0.05488,
    -0.00991
   ]
  },
  "head": {
   "rot": [
    0.97032,
    0.23216,
    -0.05884,
    0.03349
   ]
  },
  "clavicle.R": {
   "loc": [
    0.00088,
    -0.00019,
    0.00059
   ],
   "rot": [
    0.95649,
    -0.08773,
    -0.17192,
    -0.21882
   ]
  },
  "upperarm.R": {
   "rot": [
    0.79457,
    0.04941,
    -0.60472,
    -0.02288
   ]
  },
  "r_forearm": {
   "rot": [
    0.65747,
    -0.62153,
    -0.22142,
    -0.36389
   ]
  },
  "r_hand": {
   "rot": [
    0.79462,
    -0.16432,
    0.58244,
    0.04838
   ]
  },
  "r_index_meta": {
   "rot": [
    0.97742,
    -0.06311,
    0.19724,
    -0.04198
   ]
  },
  "r_index1": {
   "rot": [
    0.99479,
    0.04486,
    0.04045,
    -0.08208
   ]
  },
  "r_index2": {
   "rot": [
    0.98108,
    -0.18935,
    0.02398,
    0.03256
   ]
  },
  "r_index3": {
   "rot": [
    0.98181,
    -0.14773,
    0.11907,
    -0.00665
   ]
  },
  "r_middle_meta": {
   "loc": [
    -4e-05,
    0.00107,
    -6e-05
   ],
   "rot": [
    0.99754,
    -0.00695,
    0.04874,
    -0.04989
   ]
  },
  "r_middle1": {
   "loc": [
    -0.00029,
    0.001,
    -0.00449
   ],
   "rot": [
    0.81892,
    -0.563,
    -0.09738,
    -0.05396
   ]
  },
  "r_middle2": {
   "rot": [
    0.95633,
    -0.2896,
    -0.00218,
    -0.03957
   ]
  },
  "r_middle3": {
   "rot": [
    0.99441,
    -0.10455,
    0.01348,
    -0.00511
   ]
  },
  "r_pinky_meta": {
   "loc": [
    0.00026,
    -0.00102,
    -0.00017
   ],
   "rot": [
    0.99546,
    0.0309,
    -0.08567,
    0.02751
   ]
  },
  "r_little1": {
   "loc": [
    0.001,
    -0.00165,
    0.00424
   ],
   "rot": [
    0.90894,
    -0.38304,
    -0.1536,
    0.05926
   ]
  },
  "r_little2": {
   "rot": [
    0.98385,
    -0.12914,
    0.12269,
    0.01785
   ]
  },
  "r_little3": {
   "rot": [
    0.99914,
    -0.01402,
    -0.00982,
    -0.03773
   ]
  },
  "r_ring_meta": {
   "rot": [
    0.99839,
    0.02449,
    0.04462,
    -0.02499
   ]
  },
  "r_ring1": {
   "loc": [
    -0.00098,
    0.00253,
    -0.00041
   ],
   "rot": [
    0.84238,
    -0.52431,
    -0.09965,
    -0.07466
   ]
  },
  "r_ring2": {
   "rot": [
    0.98153,
    -0.1867,
    -0.0105,
    -0.04039
   ]
  },
  "r_ring3": {
   "rot": [
    0.99997,
    0.00282,
    -0.00078,
    -0.00764
   ]
  },
  "r_thumb1": {
   "rot": [
    0.90086,
    -0.29168,
    -0.31748,
    -0.0508
   ]
  },
  "r_thumb2": {
   "rot": [
    0.99912,
    0.00845,
    -0.03281,
    -0.02466
   ]
  },
  "r_thumb3": {
   "rot": [
    0.91801,
    -0.36113,
    -0.16343,
    -0.01149
   ]
  }
 },
 "pose 5": {
  "l_hip": {
   "rot": [
    0.99378,
    -0.06295,
    -0.09062,
    0.01477
   ]
  },
  "l_knee": {
   "rot": [
    0.99779,
    0.06362,
    0.00552,
    -0.01818
   ]
  },
  "r_hip": {
   "rot": [
    0.997,
    0.07075,
    0.0298,
    0.00987
   ]
  },
  "r_knee": {
   "rot": [
    0.99779,
    -0.06528,
    -0.00654,
    -0.01024
   ]
  },
  "r_foot": {
   "rot": [
    0.97987,
    -0.19962,
    -0.0,
    0.0
   ]
  },
  "spine1": {
   "rot": [
    0.99503,
    0.01624,
    0.0933,
    -0.03082
   ]
  },
  "spine3": {
   "rot": [
    0.99855,
    0.05378,
    -0.0,
    0.0
   ]
  },
  "clavicle.L": {
   "rot": [
    0.9836,
    0.13185,
    -0.05298,
    -0.11108
   ]
  },
  "upperarm.L": {
   "rot": [
    0.9553,
    -0.11382,
    -0.02355,
    0.27185
   ]
  },
  "l_forearm": {
   "rot": [
    0.93532,
    -0.18567,
    0.27846,
    0.11475
   ]
  },
  "l_hand": {
   "rot": [
    0.9538,
    0.25661,
    0.08105,
    0.13357
   ]
  },
  "l_index_meta": {
   "loc": [
    0.00368,
    -0.00042,
    -0.00732
   ],
   "rot": [
    0.98379,
    0.1473,
    -0.09438,
    0.03935
   ]
  },
  "l_index1": {
   "rot": [
    0.86479,
    0.47624,
    0.03026,
    0.15625
   ]
  },
  "l_index2": {
   "rot": [
    0.85947,
    0.49603,
    0.01223,
    0.12297
   ]
  },
  "l_index3": {
   "rot": [
    0.95756,
    0.25066,
    -0.13408,
    0.04768
   ]
  },
  "l_middle_meta": {
   "loc": [
    0.00183,
    0.00011,
    -0.00236
   ],
   "rot": [
    0.97673,
    0.16313,
    -0.13286,
    0.04173
   ]
  },
  "l_middle1": {
   "rot": [
    0.88099,
    0.46789,
    0.05599,
    0.04236
   ]
  },
  "l_middle2": {
   "rot": [
    0.89207,
    0.45136,
    0.00816,
    -0.02026
   ]
  },
  "l_middle3": {
   "rot": [
    0.95961,
    0.28074,
    0.01406,
    -0.01161
   ]
  },
  "l_pinky_meta": {
   "loc": [
    -0.00108,
    0.0015,
    0.00799
   ],
   "rot": [
    0.96803,
    0.15825,
    -0.17246,
    0.09012
   ]
  },
  "l_little1": {
   "rot": [
    0.96254,
    0.25438,
    0.08616,
    -0.03731
   ]
  },
  "l_little2": {
   "rot": [
    0.95901,
    0.23267,
    -0.05831,
    -0.15087
   ]
  },
  "l_little3": {
   "rot": [
    0.93768,
    0.34296,
    0.03495,
    -0.04385
   ]
  },
  "l_ring_meta": {
   "loc": [
    0.00047,
    0.00028,
    0.00279
   ],
   "rot": [
    0.96887,
    0.18678,
    -0.156,
    0.0454
   ]
  },
  "l_ring1": {
   "rot": [
    0.92788,
    0.36394,
    0.07801,
    0.0222
   ]
  },
  "l_ring2": {
   "rot": [
    0.94018,
    0.33338,
    -0.00629,
    -0.06992
   ]
  },
  "l_ring3": {
   "rot": [
    0.93411,
    0.35383,
    -0.04559,
    0.01294
   ]
  },
  "l_thumb1": {
   "rot": [
    0.94875,
    -0.08632,
    0.29055,
    -0.0894
   ]
  },
  "l_thumb3": {
   "rot": [
    0.90682,
    0.41585,
    0.01786,
    -0.06653
   ]
  },
  "neck": {
   "rot": [
    0.94988,
    0.15098,
    -0.26321,
    0.07513
   ]
  },
  "head": {
   "rot": [
    0.99475,
    0.00087,
    -0.00629,
    0.10214
   ]
  },
  "upperarm.R": {
   "rot": [
    0.99692,
    0.05824,
    0.04393,
    -0.02872
   ]
  },
  "r_forearm": {
   "rot": [
    0.98605,
    -0.023,
    0.1618,
    -0.03166
   ]
  },
  "r_hand": {
   "rot": [
    0.96511,
    -0.25567,
    0.03797,
    0.04178
   ]
  },
  "r_index_meta": {
   "rot": [
    0.97742,
    -0.06311,
    0.19724,
    -0.04198
   ]
  },
  "r_index1": {
   "rot": [
    0.98754,
    0.09111,
    0.00276,
    -0.12829
   ]
  },
  "r_index2": {
   "rot": [
    0.93227,
    -0.36168,
    -0.00693,
    0.00094
   ]
  },
  "r_index3": {
   "rot": [
    0.94907,
    -0.29179,
    0.10845,
    -0.04859
   ]
  },
  "r_middle_meta": {
   "loc": [
    -4e-05,
    0.00107,
    -6e-05
   ],
   "rot": [
    0.99754,
    -0.00695,
    0.04874,
    -0.04989
   ]
  },
  "r_middle1": {
   "loc": [
    -0.00029,
    0.001,
    -0.00449
   ],
   "rot": [
    0.83489,
    -0.53904,
    -0.08914,
    -0.06669
   ]
  },
  "r_middle2": {
   "rot": [
    0.95633,
    -0.2896,
    -0.00218,
    -0.03957
   ]
  },
  "r_middle3": {
   "rot": [
    0.99441,
    -0.10455,
    0.01348,
    -0.00511
   ]
  },
  "r_pinky_meta": {
   "loc": [
    0.00026,
    -0.00102,
    -0.00017
   ],
   "rot": [
    0.99546,
    0.0309,
    -0.08567,
    0.02751
   ]
  },
  "r_little1": {
   "loc": [
    0.001,
    -0.00165,
    0.00424
   ],
   "rot": [
    0.90894,
    -0.38304,
    -0.1536,
    0.05926
   ]
  },
  "r_little2": {
   "rot": [
    0.98385,
    -0.12914,
    0.12269,
    0.01785
   ]
  },
  "r_little3": {
   "rot": [
    0.99914,
    -0.01402,
    -0.00982,
    -0.03773
   ]
  },
  "r_ring_meta": {
   "rot": [
    0.99839,
    0.02449,
    0.04462,
    -0.02499
   ]
  },
  "r_ring1": {
   "loc": [
    -0.00098,
    0.00253,
    -0.00041
   ],
   "rot": [
    0.84238,
    -0.52431,
    -0.09965,
    -0.07466
   ]
  },
  "r_ring2": {
   "rot": [
    0.98153,
    -0.1867,
    -0.0105,
    -0.04039
   ]
  },
  "r_ring3": {
   "rot": [
    0.99997,
    0.00282,
    -0.00078,
    -0.00764
   ]
  },
  "r_thumb1": {
   "rot": [
    0.90086,
    -0.29168,
    -0.31748,
    -0.0508
   ]
  },
  "r_thumb2": {
   "rot": [
    0.99912,
    0.00845,
    -0.03281,
    -0.02466
   ]
  },
  "r_thumb3": {
   "rot": [
    0.91801,
    -0.36113,
    -0.16343,
    -0.01149
   ]
  }
 }
}

POSE_THUMB_DIR = os.path.join(ADDON_DIR, "assets", "pose_thumbs")

_pose_previews = None


def get_pose_previews():
    global _pose_previews
    if _pose_previews is None:
        _pose_previews = bpy.utils.previews.new()
        for name in POSES:
            fn = os.path.join(POSE_THUMB_DIR, name.replace(" ", "_") + ".png")
            if os.path.isfile(fn):
                _pose_previews.load(name, fn, 'IMAGE')
    return _pose_previews


def free_pose_previews():
    global _pose_previews
    if _pose_previews is not None:
        bpy.utils.previews.remove(_pose_previews)
        _pose_previews = None


def pose_enum_items(self, context):
    pcoll = get_pose_previews()
    items = []
    for i, name in enumerate(POSES):
        if name in pcoll:
            items.append((name, name.title(), "", pcoll[name].icon_id, i))
        else:
            items.append((name, name.title(), "", 'POSE_HLT', i))
    _enum_cache["poses"] = items
    return items

_SIDE_PREFIX_RE = re.compile(r"^(l|r)_(.+)$")
_SIDE_SUFFIX_RE = re.compile(r"^(.+)\.(L|R)$")


def pose_bone_alias(name):
    m = _SIDE_PREFIX_RE.match(name)
    if m:
        return f"{m.group(2)}.{m.group(1).upper()}"
    m = _SIDE_SUFFIX_RE.match(name)
    if m:
        return f"{m.group(2).lower()}_{m.group(1)}"
    return None


def reset_rig_to_rest(rig):
    for pb in rig.pose.bones:
        pb.location = (0.0, 0.0, 0.0)
        pb.rotation_quaternion = (1.0, 0.0, 0.0, 0.0)
        pb.rotation_euler = (0.0, 0.0, 0.0)
        pb.rotation_axis_angle = (0.0, 0.0, 1.0, 0.0)
        pb.scale = (1.0, 1.0, 1.0)


def apply_pose_to_rig(rig, pose_name):
    data = POSES.get(pose_name)
    if data is None:
        return -1
    reset_rig_to_rest(rig)
    applied = 0
    for bone_name, tf in data.items():
        pb = rig.pose.bones.get(bone_name)
        if pb is None:
            alias = pose_bone_alias(bone_name)
            pb = rig.pose.bones.get(alias) if alias else None
        if pb is None:
            continue
        mode = tf.get("rot_mode", "QUATERNION")
        pb.rotation_mode = mode
        if "loc" in tf:
            pb.location = tf["loc"]
        if "scale" in tf:
            pb.scale = tf["scale"]
        rot = tf.get("rot")
        if rot is not None:
            if mode == "QUATERNION":
                pb.rotation_quaternion = rot
            elif mode == "AXIS_ANGLE":
                pb.rotation_axis_angle = rot
            else:
                pb.rotation_euler = rot
        applied += 1
    return applied


def find_weapon_entry(display):
    for entry in load_catalog():
        if entry["category"] != "Weapons":
            continue
        if strip_tokens(entry["object_name"], GENDER_TOKENS + RACE_TOKENS) == display:
            return entry
    return None


def get_weapon_grip(display):
    entry = find_weapon_entry(display)
    return entry.get("grip") if entry else None


def resolve_hand_item(gender, race, category, display):
    if category == "Left Hand":
        alt = find_weapon_entry(display + " L")
        if alt is not None:
            return display + " L", alt["object_name"], alt["mesh_names"], False
    obj_name, mesh_names = find_armature_by_display(gender, race, category, display)
    return display, obj_name, mesh_names, category == "Left Hand"


def _reflect_about_own_plane(rig, meshes, bone_name):
    import numpy as np
    pts = []
    for m in meshes:
        pts.extend(tuple(v.co) for v in m.data.vertices)
    if len(pts) < 3:
        return
    a = np.array(pts, dtype=np.float64)
    center = a.mean(axis=0)
    cov = np.cov((a - center).T)
    evals, evecs = np.linalg.eigh(cov)
    n = mathutils.Vector(evecs[:, 0])
    if evals[1] > 0 and evals[0] / evals[1] > 0.75:
        alt = mathutils.Vector(evecs[:, 1])
        if abs(alt.z) < abs(n.z):
            n = alt
    n.normalize()
    c = mathutils.Vector(center)
    R3 = mathutils.Matrix.Identity(3)
    for i in range(3):
        for j in range(3):
            R3[i][j] -= 2.0 * n[i] * n[j]
    T = (mathutils.Matrix.Translation(c)
         @ R3.to_4x4()
         @ mathutils.Matrix.Translation(-c))
    for m in meshes:
        for v in m.data.vertices:
            v.co = T @ v.co
        m.data.flip_normals()


def mirror_meshes_to_left(rig, meshes, keep_chirality):
    mirror = mathutils.Matrix.Scale(-1.0, 4, (1.0, 0.0, 0.0))
    for m in meshes:
        for v in m.data.vertices:
            v.co = mirror @ v.co
        m.data.flip_normals()
        vg = m.vertex_groups.get("r_prop")
        if vg is not None:
            vg.name = "l_prop"
    if keep_chirality:
        _reflect_about_own_plane(rig, meshes, "l_prop")


def apply_grip_to_rig(rig, category, grip):
    want = "r_" if category == "Right Hand" else "l_"
    resolved = {}
    for pass_same in (False, True):
        for bname, rot in grip.items():
            same = bname.startswith(want)
            if same != pass_same:
                continue
            tname = bname if same else want + bname[2:]
            resolved[tname] = (rot, None if same else bname)
    MIR = mathutils.Matrix.Scale(-1.0, 3, (1.0, 0.0, 0.0))
    for tname, (rot, src_name) in resolved.items():
        pb = rig.pose.bones.get(tname)
        if pb is None:
            continue
        q = mathutils.Quaternion(rot)
        if src_name is not None:
            src = rig.data.bones.get(src_name)
            if src is None:
                continue
            K = pb.bone.matrix_local.to_3x3().inverted() @ MIR @ src.matrix_local.to_3x3()
            q = (K @ q.to_matrix() @ K.inverted()).to_quaternion()
        pb.rotation_mode = 'QUATERNION'
        pb.rotation_quaternion = q


def reset_hand_fingers(rig, prefix):
    for pb in rig.pose.bones:
        if is_finger_bone(pb.name, prefix):
            pb.rotation_mode = 'QUATERNION'
            pb.rotation_quaternion = (1.0, 0.0, 0.0, 0.0)


def reapply_grips(rig, props):
    if not props.auto_grip:
        return
    for cat in HAND_SLOTS:
        item = rig.get(f"equipped_{cat}", "")
        if item and item != "None":
            grip = get_weapon_grip(item) or get_weapon_grip(item + " L")
            if grip:
                apply_grip_to_rig(rig, cat, grip)


def postprocess_hand_item(rig, category, display, meshes, needs_mirror, props):
    if category == "Left Hand" and needs_mirror:
        mirror_meshes_to_left(rig, meshes, True)
    if props.auto_grip:
        grip = get_weapon_grip(display) or get_weapon_grip(display + " L")
        if grip:
            apply_grip_to_rig(rig, category, grip)


def get_characters_collection():
    coll = bpy.data.collections.get(CHAR_COLLECTION_NAME)
    if coll is None:
        coll = bpy.data.collections.new(CHAR_COLLECTION_NAME)
        bpy.context.scene.collection.children.link(coll)
    return coll


def get_character_rigs():
    rigs = [o for o in bpy.data.objects if o.type == 'ARMATURE' and "rig_id" in o]
    rigs.sort(key=lambda o: o["rig_id"])
    return rigs


def get_rig_by_id(rig_id):
    for o in get_character_rigs():
        if o["rig_id"] == rig_id:
            return o
    return None


def next_character_id():
    existing = [int(o["rig_id"]) for o in get_character_rigs()]
    return (max(existing) + 1) if existing else 1


def make_build_items(category):
    def items_func(self, context):
        opts = [("None", "None", "")]
        opts += [(disp, disp, "") for disp, _ in gather_category_items(self.gender, self.race, category)]
        _enum_cache[("build", category)] = opts
        return opts
    return items_func


def make_edit_items(category):
    def items_func(self, context):
        rig = get_rig_by_id(int(self.active_char_enum)) if self.active_char_enum else None
        if rig is None:
            opts = [("None", "None", "")]
        else:
            gender = rig.get("gender", "Male")
            race = rig.get("race", "Light")
            opts = [("None", "None", "")]
            opts += [(disp, disp, "") for disp, _ in gather_category_items(gender, race, category)]
        _enum_cache[("edit", category)] = opts
        return opts
    return items_func


def make_edit_update(category):
    def update_func(self, context):
        if self.suppress_update:
            return
        value = getattr(self, f"edit_sel_{slug(category)}")
        bpy.ops.rustchar.swap_item(category=category, new_item=value)
    return update_func


def character_enum_items(self, context):
    rigs = get_character_rigs()
    opts = [(str(o["rig_id"]), o.name, "") for o in rigs]
    if not opts:
        opts = [("", "No characters yet", "")]
    _enum_cache["char_list"] = opts
    return opts


def update_active_char(self, context):
    rig = get_rig_by_id(int(self.active_char_enum)) if self.active_char_enum else None
    if rig is None:
        return
    self.suppress_update = True
    try:
        for cat in CATEGORIES:
            val = rig.get(f"equipped_{cat}", "") or "None"
            setattr(self, f"edit_sel_{slug(cat)}", val)
    finally:
        self.suppress_update = False


class RUSTCHAR_Props(PropertyGroup):
    gender: EnumProperty(name="Gender", items=[("Male", "Male", ""), ("Female", "Female", "")], default="Male")
    race: EnumProperty(name="Race", items=[("Light", "Light", ""), ("Dark", "Dark", "")], default="Light")
    active_char_enum: EnumProperty(name="Character", items=character_enum_items, update=update_active_char)
    suppress_update: BoolProperty(default=False)
    pose_enum: EnumProperty(name="Pose", items=pose_enum_items)
    auto_grip: BoolProperty(
        name="Auto Hand Pose", default=True,
        description="Wrap the fingers around equipped weapons using the grip "
                    "authored in the library")


for _cat in CATEGORIES:
    RUSTCHAR_Props.__annotations__[f"sel_{slug(_cat)}"] = EnumProperty(name=_cat, items=make_build_items(_cat))
    RUSTCHAR_Props.__annotations__[f"edit_sel_{slug(_cat)}"] = EnumProperty(
        name=_cat, items=make_edit_items(_cat), update=make_edit_update(_cat)
    )


def read_weapon_grip_from_file(path, object_name):
    try:
        with bpy.data.libraries.load(path, link=True) as (data_from, data_to):
            names = [n for n in data_from.objects if n == object_name]
            data_to.objects = names if names else list(data_from.objects)
    except Exception:
        return None
    grip = {}
    lib = None
    for obj in data_to.objects:
        if obj is None:
            continue
        if lib is None:
            lib = obj.library
        if obj.type != 'ARMATURE' or obj.pose is None:
            continue
        for pb in obj.pose.bones:
            if is_finger_bone(pb.name, "r_") or is_finger_bone(pb.name, "l_"):
                q = pb.matrix_basis.to_quaternion()
                if abs(q.w) < 0.99999:
                    grip[pb.name] = [round(c, 5) for c in q]
        break
    if lib is not None:
        try:
            bpy.data.libraries.remove(lib)
        except Exception:
            pass
    return grip or None


class RUSTCHAR_OT_rebuild_catalog(Operator):
    bl_idname = "rustchar.rebuild_catalog"
    bl_label = "Rebuild Catalog"
    bl_description = (
        "Scan the per-item library folders and bake the item catalog. "
        "Folders define group and category, filenames define items, and "
        "weapon grips are read from each weapon's own file"
    )

    def execute(self, context):
        import time as _time
        lib_dir = library_items_dir()
        if not os.path.isdir(lib_dir):
            self.report({'ERROR'}, "Library folder not found in the addon's assets folder.")
            return {'CANCELLED'}
        t0 = _time.perf_counter()
        catalog = []
        grips = 0
        for dirpath, dirnames, filenames in os.walk(lib_dir):
            if "textures" in dirnames:
                dirnames.remove("textures")
            for fn in sorted(filenames):
                if not fn.endswith(".blend"):
                    continue
                full = os.path.join(dirpath, fn)
                rel = os.path.relpath(full, lib_dir).replace(os.sep, "/")
                parts = rel.split("/")
                if len(parts) != 3:
                    continue
                group, category, base = parts
                entry = {"category": category, "group": group,
                         "object_name": base[:-6], "mesh_names": [],
                         "file": rel}
                if category == "Weapons":
                    grip = read_weapon_grip_from_file(full, base[:-6])
                    if grip:
                        entry["grip"] = grip
                        grips += 1
                catalog.append(entry)
        tmp = CATALOG_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(catalog, f, indent=2)
        os.replace(tmp, CATALOG_PATH)
        invalidate_catalog_cache()
        self.report({'INFO'}, f"Catalog rebuilt: {len(catalog)} items, "
                              f"{grips} grips, {_time.perf_counter() - t0:.2f}s.")
        return {'FINISHED'}

class RUSTCHAR_OT_build_character(Operator):
    bl_idname = "rustchar.build_character"
    bl_label = "Generate Character"
    bl_description = "Build a new character from the current selections"
    bl_options = {'UNDO'}

    def execute(self, context):
        if bpy.data.filepath and os.path.normcase(os.path.normpath(bpy.data.filepath)) == os.path.normcase(os.path.normpath(LIBRARY_PATH)):
            self.report({'ERROR'}, "This is the library file itself - open a working scene to use the character creator.")
            return {'CANCELLED'}
        if not library_available():
            self.report({'ERROR'}, f"{LIBRARY_FILENAME} not found in the addon's assets folder.")
            return {'CANCELLED'}

        props = context.scene.rustchar_props
        gender = props.gender
        race = props.race

        selections = {}
        for cat in CATEGORIES:
            value = getattr(props, f"sel_{slug(cat)}")
            if value and value != "None":
                selections[cat] = value

        if not selections:
            self.report({'ERROR'}, "No items selected.")
            return {'CANCELLED'}

        char_id = next_character_id()
        char_name = f"Character_{char_id:02d}"
        char_collection = bpy.data.collections.new(char_name)
        get_characters_collection().children.link(char_collection)

        duplicated = []
        hand_mirror = {}
        for cat, disp in selections.items():
            if cat in HAND_SLOTS:
                use_disp, obj_name, mesh_names, needs_mirror = resolve_hand_item(gender, race, cat, disp)
                hand_mirror[cat] = needs_mirror
            else:
                obj_name, mesh_names = find_armature_by_display(gender, race, cat, disp)
            if obj_name is None:
                continue
            new_arm, new_meshes = duplicate_item(obj_name, mesh_names, char_collection)
            duplicated.append((cat, disp, new_arm, new_meshes))

        if not duplicated:
            self.report({'ERROR'}, "Could not resolve any selected items.")
            bpy.data.collections.remove(char_collection)
            return {'CANCELLED'}

        target_cat, target_disp, target_armature, target_meshes = max(
            duplicated, key=lambda d: len(d[2].data.bones)
        )

        for cat, disp, arm, meshes in duplicated:
            for m in meshes:
                m["rust_category"] = cat
                m["rust_item"] = disp
            if arm is not target_armature:
                snap_meshes_to_armature(meshes, target_armature)
                remove_armature_object(arm)
            if cat in HAND_SLOTS:
                postprocess_hand_item(target_armature, cat, disp, meshes,
                                      hand_mirror.get(cat, cat == "Left Hand"),
                                      context.scene.rustchar_props)

        target_armature.name = char_name
        target_armature["rig_id"] = char_id
        target_armature["gender"] = gender
        target_armature["race"] = race
        for cat in CATEGORIES:
            target_armature[f"equipped_{cat}"] = selections.get(cat, "")

        target_armature.location.x += (char_id - 1) * 2.0

        context.scene.rustchar_props.active_char_enum = str(char_id)
        self.report({'INFO'}, f"Built {char_name}.")
        return {'FINISHED'}


class RUSTCHAR_OT_swap_item(Operator):
    bl_idname = "rustchar.swap_item"
    bl_label = "Swap Item"
    bl_description = "Replace the equipped item in this category for the active character"
    bl_options = {'UNDO'}

    category: StringProperty()
    new_item: StringProperty()

    def execute(self, context):
        if bpy.data.filepath and os.path.normcase(os.path.normpath(bpy.data.filepath)) == os.path.normcase(os.path.normpath(LIBRARY_PATH)):
            self.report({'ERROR'}, "This is the library file itself - open a working scene to use the character creator.")
            return {'CANCELLED'}
        if not library_available():
            self.report({'ERROR'}, f"{LIBRARY_FILENAME} not found in the addon's assets folder.")
            return {'CANCELLED'}

        props = context.scene.rustchar_props
        if not props.active_char_enum:
            self.report({'ERROR'}, "No character selected.")
            return {'CANCELLED'}
        rig = get_rig_by_id(int(props.active_char_enum))
        if rig is None:
            self.report({'ERROR'}, "No character selected.")
            return {'CANCELLED'}

        gender = rig.get("gender")
        race = rig.get("race")

        old_meshes = [
            o for o in bpy.data.objects
            if o.parent == rig and o.get("rust_category") == self.category
        ]
        for o in old_meshes:
            bpy.data.objects.remove(o)

        rig[f"equipped_{self.category}"] = ""
        if self.category in HAND_SLOTS and props.auto_grip:
            reset_hand_fingers(rig, "r_" if self.category == "Right Hand" else "l_")

        if self.new_item and self.new_item != "None":
            if self.category in HAND_SLOTS:
                use_disp, obj_name, mesh_names, needs_mirror = resolve_hand_item(
                    gender, race, self.category, self.new_item)
            else:
                obj_name, mesh_names = find_armature_by_display(gender, race, self.category, self.new_item)
                needs_mirror = False
            if obj_name is None:
                self.report({'WARNING'}, f"Could not find '{self.new_item}'.")
                return {'CANCELLED'}
            char_collection = rig.users_collection[0] if rig.users_collection else context.scene.collection
            new_arm, new_meshes = duplicate_item(obj_name, mesh_names, char_collection)
            for m in new_meshes:
                m["rust_category"] = self.category
                m["rust_item"] = self.new_item
            snap_meshes_to_armature(new_meshes, rig)
            remove_armature_object(new_arm)
            if self.category in HAND_SLOTS:
                postprocess_hand_item(rig, self.category, self.new_item, new_meshes, needs_mirror, props)
            rig[f"equipped_{self.category}"] = self.new_item

        return {'FINISHED'}


class RUSTCHAR_OT_apply_pose(Operator):
    bl_idname = "rustchar.apply_pose"
    bl_label = "Apply Pose"
    bl_description = "Apply the selected library pose to the active character"
    bl_options = {'UNDO'}

    def execute(self, context):
        props = context.scene.rustchar_props
        rig = get_rig_by_id(int(props.active_char_enum)) if props.active_char_enum else None
        if rig is None:
            self.report({'ERROR'}, "No character selected.")
            return {'CANCELLED'}
        applied = apply_pose_to_rig(rig, props.pose_enum)
        if applied < 0:
            self.report({'ERROR'}, f"Unknown pose '{props.pose_enum}'.")
            return {'CANCELLED'}
        if applied == 0:
            self.report({'WARNING'}, "No bone names matched this rig.")
        else:
            self.report({'INFO'}, f"Applied '{props.pose_enum}' ({applied} bones).")
        reapply_grips(rig, props)
        return {'FINISHED'}


class RUSTCHAR_OT_rest_pose(Operator):
    bl_idname = "rustchar.rest_pose"
    bl_label = "Rest Pose"
    bl_description = "Reset the active character back to its rest (T) pose"
    bl_options = {'UNDO'}

    def execute(self, context):
        props = context.scene.rustchar_props
        rig = get_rig_by_id(int(props.active_char_enum)) if props.active_char_enum else None
        if rig is None:
            self.report({'ERROR'}, "No character selected.")
            return {'CANCELLED'}
        reset_rig_to_rest(rig)
        self.report({'INFO'}, "Character reset to rest pose.")
        return {'FINISHED'}


def _panels_ready():
    return library_available() and catalog_available()


def get_active_rig(context):
    props = context.scene.rustchar_props
    if not props.active_char_enum:
        return None
    try:
        return get_rig_by_id(int(props.active_char_enum))
    except ValueError:
        return None


class RUSTCHAR_PT_main(Panel):
    bl_label = "Rust Character Creator"
    bl_idname = "RUSTCHAR_PT_main"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Character"

    def draw(self, context):
        layout = self.layout
        if not library_available():
            box = layout.box()
            box.alert = True
            box.label(text="Item library not found!", icon='ERROR')
            box.label(text="Expected 'library' folder in the addon's assets.")
            return
        if not catalog_available():
            box = layout.box()
            box.alert = True
            box.label(text="No item catalog yet.", icon='ERROR')
            box.operator("rustchar.rebuild_catalog", icon='FILE_REFRESH')
            return
        row = layout.row()
        row.label(text=f"{len(load_catalog())} items catalogued", icon='ASSET_MANAGER')
        row.operator("rustchar.rebuild_catalog", text="", icon='FILE_REFRESH')


class RUSTCHAR_PT_build(Panel):
    bl_label = "Build Character"
    bl_idname = "RUSTCHAR_PT_build"
    bl_parent_id = "RUSTCHAR_PT_main"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Character"
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        return _panels_ready()

    def draw(self, context):
        layout = self.layout
        props = context.scene.rustchar_props
        row = layout.row()
        row.prop(props, "gender", expand=True)
        row = layout.row()
        row.prop(props, "race", expand=True)
        layout.separator()
        col = layout.column(align=True)
        for cat in CATEGORIES:
            if cat not in HAND_SLOTS:
                col.prop(props, f"sel_{slug(cat)}", text=cat)
        col = layout.column(align=True)
        for cat in HAND_SLOTS:
            col.prop(props, f"sel_{slug(cat)}", text=cat)
        layout.operator("rustchar.build_character", icon='ARMATURE_DATA')


class RUSTCHAR_PT_edit(Panel):
    bl_label = "Edit Character"
    bl_idname = "RUSTCHAR_PT_edit"
    bl_parent_id = "RUSTCHAR_PT_main"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Character"

    @classmethod
    def poll(cls, context):
        return _panels_ready()

    def draw(self, context):
        layout = self.layout
        props = context.scene.rustchar_props
        layout.prop(props, "active_char_enum", text="Character")
        rig = get_active_rig(context)
        if rig:
            layout.label(text=f"Gender: {rig.get('gender', '?')}   Race: {rig.get('race', '?')}")
        else:
            layout.label(text="No characters yet.", icon='INFO')


class RUSTCHAR_PT_edit_clothing(Panel):
    bl_label = "Clothing"
    bl_idname = "RUSTCHAR_PT_edit_clothing"
    bl_parent_id = "RUSTCHAR_PT_edit"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Character"
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        return _panels_ready() and get_active_rig(context) is not None

    def draw(self, context):
        layout = self.layout
        props = context.scene.rustchar_props
        col = layout.column(align=True)
        for cat in CATEGORIES:
            if cat not in HAND_SLOTS:
                col.prop(props, f"edit_sel_{slug(cat)}", text=cat)


class RUSTCHAR_PT_edit_items(Panel):
    bl_label = "Items"
    bl_idname = "RUSTCHAR_PT_edit_items"
    bl_parent_id = "RUSTCHAR_PT_edit"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Character"
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        return _panels_ready() and get_active_rig(context) is not None

    def draw(self, context):
        layout = self.layout
        props = context.scene.rustchar_props
        col = layout.column(align=True)
        for cat in HAND_SLOTS:
            col.prop(props, f"edit_sel_{slug(cat)}", text=cat)
        layout.prop(props, "auto_grip")


class RUSTCHAR_PT_pose(Panel):
    bl_label = "Pose"
    bl_idname = "RUSTCHAR_PT_pose"
    bl_parent_id = "RUSTCHAR_PT_main"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Character"
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        return _panels_ready()

    def draw(self, context):
        layout = self.layout
        props = context.scene.rustchar_props
        layout.enabled = get_active_rig(context) is not None
        layout.template_icon_view(props, "pose_enum", show_labels=True, scale=6.0, scale_popup=5.0)
        row = layout.row(align=True)
        row.operator("rustchar.apply_pose", icon='CHECKMARK')
        row.operator("rustchar.rest_pose", icon='LOOP_BACK')


classes = (
    RUSTCHAR_Props,
    RUSTCHAR_OT_rebuild_catalog,
    RUSTCHAR_OT_build_character,
    RUSTCHAR_OT_swap_item,
    RUSTCHAR_OT_apply_pose,
    RUSTCHAR_OT_rest_pose,
    RUSTCHAR_PT_main,
    RUSTCHAR_PT_build,
    RUSTCHAR_PT_edit,
    RUSTCHAR_PT_edit_clothing,
    RUSTCHAR_PT_edit_items,
    RUSTCHAR_PT_pose,
)


def register():
    for c in classes:
        bpy.utils.register_class(c)
    bpy.types.Scene.rustchar_props = bpy.props.PointerProperty(type=RUSTCHAR_Props)


def unregister():
    free_pose_previews()
    del bpy.types.Scene.rustchar_props
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
