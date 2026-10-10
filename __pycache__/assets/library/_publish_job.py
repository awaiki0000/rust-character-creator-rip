
import bpy, os, json, re, time
LIB_DIR = r'C:\Users\Oscar\AppData\Roaming\Blender Foundation\Blender\5.2\extensions\user_default\rust_character_creator\assets\library'
CATALOG = r'C:\Users\Oscar\AppData\Roaming\Blender Foundation\Blender\5.2\extensions\user_default\rust_character_creator\assets\catalog.json'
TEX_DIR = os.path.join(LIB_DIR, 'textures')
os.makedirs(TEX_DIR, exist_ok=True)
ROOTS = ('Neutral', 'Male', 'Female', 'Items')
FINGER = ('index', 'middle', 'ring', 'little', 'pinky', 'thumb')

def is_finger(n, p):
    return n.startswith(p) and any(t in n for t in FINGER)

def sanitize(n):
    return re.sub(r'[^A-Za-z0-9 ._-]', '_', n)

t0 = time.perf_counter()

# externalise packed textures into the shared folder (incremental)
for img in bpy.data.images:
    if img.packed_file is None:
        continue
    base = os.path.basename(img.filepath_raw) if img.filepath_raw else ''
    if not base:
        base = img.name + '.png'
    target = os.path.join(TEX_DIR, base)
    if not os.path.exists(target):
        try:
            with open(target, 'wb') as fh:
                fh.write(img.packed_file.data)
        except Exception:
            continue
    img.filepath = target
    try:
        img.unpack(method='REMOVE')
    except Exception:
        pass

catalog = []
files_written = 0
for rname in ROOTS:
    root = bpy.data.collections.get(rname)
    if root is None:
        continue
    for sub in root.children:
        category = sub.name
        if rname != 'Neutral' and category.startswith(rname + ' '):
            category = category[len(rname) + 1:]
        for obj in sub.objects:
            if obj.type != 'ARMATURE':
                continue
            mesh_names = sorted(o.name for o in sub.objects
                                if o.parent == obj and o.type == 'MESH')
            entry = {'category': category, 'group': rname,
                     'object_name': obj.name, 'mesh_names': mesh_names}
            if category == 'Weapons':
                if obj.pose is not None:
                    grip = {}
                    for pb in obj.pose.bones:
                        if is_finger(pb.name, 'r_') or is_finger(pb.name, 'l_'):
                            q = pb.matrix_basis.to_quaternion()
                            if abs(q.w) < 0.99999:
                                grip[pb.name] = [round(c, 5) for c in q]
                    if grip:
                        entry['grip'] = grip
            objs = set([obj])
            for mn in mesh_names:
                mo = bpy.data.objects.get(mn)
                if mo is not None:
                    objs.add(mo)
            rel_dir = sanitize(rname) + '/' + sanitize(category)
            out_dir = os.path.join(LIB_DIR, sanitize(rname), sanitize(category))
            os.makedirs(out_dir, exist_ok=True)
            fname = sanitize(obj.name) + '.blend'
            bpy.data.libraries.write(os.path.join(out_dir, fname), objs,
                                     path_remap='RELATIVE_ALL',
                                     compress=False, fake_user=False)
            entry['file'] = rel_dir + '/' + fname
            files_written += 1
            catalog.append(entry)

# merge in items that exist only as per-item files in the folder tree
seen = set(e['object_name'] for e in catalog)
for dirpath, dirnames, filenames in os.walk(LIB_DIR):
    if 'textures' in dirnames:
        dirnames.remove('textures')
    for fn in filenames:
        if not fn.endswith('.blend'):
            continue
        rel = os.path.relpath(os.path.join(dirpath, fn), LIB_DIR).replace(os.sep, '/')
        parts = rel.split('/')
        if len(parts) != 3:
            continue
        grp, cat_name, base = parts
        oname = base[:-6]
        if oname in seen:
            continue
        catalog.append({'category': cat_name, 'group': grp,
                        'object_name': oname, 'mesh_names': [],
                        'file': rel})

tmp = CATALOG + '.tmp'
with open(tmp, 'w', encoding='utf-8') as fh:
    json.dump(catalog, fh, indent=2)
os.replace(tmp, CATALOG)
with open(os.path.join(LIB_DIR, '_publish_done.json'), 'w', encoding='utf-8') as fh:
    json.dump({'items': len(catalog), 'files_written': files_written,
               'elapsed_s': round(time.perf_counter() - t0, 1)}, fh)
