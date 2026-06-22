#!/usr/bin/env python3
import json, os, math, argparse
from collections import defaultdict

EPS = 1e-6

def to_key(v, step):
    # округление к сетке
    return int(round(v / step))

def gcd_list(nums):
    g = 0
    for n in nums:
        n = abs(n)
        if n == 0:
            continue
        g = math.gcd(g, n)
    return g

def infer_step_from_values(values):
    # values: list[float]
    # находит шаг как GCD расстояний между уникальными координатами
    uniq = sorted(set(round(v, 6) for v in values))
    diffs = []
    for i in range(1, len(uniq)):
        d = uniq[i] - uniq[i-1]
        if d > EPS:
            diffs.append(d)
    if not diffs:
        return 1/16
    # превращаем в “кратности” относительно 1/16 довольно грубо:
    # затем находим gcd по целочисленным дельтам в базе 1/16.
    base = 1/16
    ints = [max(1, int(round(d / base))) for d in diffs]
    g = gcd_list(ints)
    step = base / max(1, g)
    return step

def pick_face(faces):
    # предполагаем ровно 1 face-ключ на element
    for k in faces.keys():
        return k
    return None

def face_axis(face):
    # fixed axis coordinate:
    # north/south => z fixed, varying x,y
    # east/west   => x fixed, varying z,y
    # up/down     => y fixed, varying x,z
    if face in ("north", "south"):
        return "z"
    if face in ("east", "west"):
        return "x"
    if face in ("up", "down"):
        return "y"
    return None

def face_sign(face):
    # direction to set thickness side
    # (для правильного to/from по толщине не принципиально как в твоём случае,
    # но мы оставим как “активная сторона” face)
    if face in ("north", "west", "down"):
        return -1
    return 1
def merge_3d(elements):
    groups = {}

    for el in elements:
        face = next(iter(el["faces"]))
        texture = el["faces"][face]["texture"]

        key = (
            face,
            texture,
            tuple(el["from"][1:]),
            tuple(el["to"][1:])
        )

        if face in ("west", "east"):
            key = (
                face,
                texture,
                el["from"][1],
                el["from"][2],
                el["to"][1],
                el["to"][2]
            )

        elif face in ("north", "south"):
            key = (
                face,
                texture,
                el["from"][0],
                el["from"][1],
                el["to"][0],
                el["to"][1]
            )

        elif face in ("up", "down"):
            key = (
                face,
                texture,
                el["from"][0],
                el["from"][2],
                el["to"][0],
                el["to"][2]
            )

        groups.setdefault(key, []).append(el)

    merged = []

    for els in groups.values():

        face = next(iter(els[0]["faces"]))

        if face in ("west", "east"):
            axis = 0
        elif face in ("up", "down"):
            axis = 1
        else:
            axis = 2

        els.sort(key=lambda e: e["from"][axis])

        cur = els[0]

        for nxt in els[1:]:

            if abs(cur["to"][axis] - nxt["from"][axis]) < 1e-6:
                cur["to"][axis] = nxt["to"][axis]
            else:
                merged.append(cur)
                cur = nxt

        merged.append(cur)

    return merged
def quantize_interval(a, b, step):
    return (to_key(a, step), to_key(b, step))

def greedy_rect(mask, H, W):
    # mask[h][w] True if cell exists
    used = [[False]*W for _ in range(H)]
    rects = []
    for y in range(H):
        for x in range(W):
            if not mask[y][x] or used[y][x]:
                continue
            # find max width
            wmax = x
            while wmax+1 < W and mask[y][wmax+1] and not used[y][wmax+1]:
                wmax += 1
            # then grow height while rows match contiguous segment
            hmax = y
            def row_ok(yy, xx0, xx1):
                for xx in range(xx0, xx1+1):
                    if not mask[yy][xx] or used[yy][xx]:
                        return False
                return True
            while hmax+1 < H and row_ok(hmax+1, x, wmax):
                hmax += 1
            # mark used
            for yy in range(y, hmax+1):
                for xx in range(x, wmax+1):
                    used[yy][xx] = True
            rects.append((x,y,wmax,hmax))
    return rects

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input_json")
    ap.add_argument("-o", "--output", default=None)
    args = ap.parse_args()

    with open(args.input_json, "r", encoding="utf-8") as f:
        data = json.load(f)

    elements = data.get("elements", [])
    # infer step
    coords = []
    for el in elements:
        coords += el["from"]
        coords += el["to"]
    step = infer_step_from_values(coords)

    # group by face -> map from grid cell to (texture,uv)
    # we'll build masks separately per face as 2D grids.
    by_face_cells = defaultdict(list)

    for el in elements:
        if "faces" not in el or not el["faces"]:
            continue
        face = pick_face(el["faces"])
        if face is None:
            continue
        f = el["faces"][face]
        texture = f.get("texture")
        uv = f.get("uv")
        if uv != [0,0,1,1]:
            # для твоего формата можно убрать, но оставим строгую проверку
            # чтобы не “сломать” нетипичные грани
            continue

        x0,y0,z0 = el["from"]
        x1,y1,z1 = el["to"]

        # compute grid coords for the “quad”
        if face_axis(face) == "z":
            # z fixed, x/y vary
            zx = to_key(z0, step)
            xa0, xa1 = quantize_interval(x0, x1, step)
            ya0, ya1 = quantize_interval(y0, y1, step)
            # thickness is the delta in z between z0 and z1 (should be one step)
            # We’ll use the element's actual min/max as a plate
            by_face_cells[face].append((zx, xa0, xa1, ya0, ya1, texture, uv, (x0,y0,z0,x1,y1,z1)))
        elif face_axis(face) == "x":
            xx = to_key(x0, step)
            za0, za1 = quantize_interval(z0, z1, step)
            ya0, ya1 = quantize_interval(y0, y1, step)
            by_face_cells[face].append((xx, za0, za1, ya0, ya1, texture, uv, (x0,y0,z0,x1,y1,z1)))
        elif face_axis(face) == "y":
            yy = to_key(y0, step)
            xa0, xa1 = quantize_interval(x0, x1, step)
            za0, za1 = quantize_interval(z0, z1, step)
            by_face_cells[face].append((yy, xa0, xa1, za0, za1, texture, uv, (x0,y0,z0,x1,y1,z1)))

    new_elements = []
    removed = 0

    # For each face, build a 2D grid per fixed coordinate and greedy merge.
    # Note: we treat each fixed coordinate slice separately.
    for face, cells in by_face_cells.items():
        # organize by fixed coordinate (z or x or y)
        slice_map = defaultdict(list)
        for item in cells:
            fixed = item[0]
            slice_map[fixed].append(item)

        for fixed, scells in slice_map.items():
            # Determine bounds
            xs = []
            ys = []
            for it in scells:
                if face_axis(face) == "z":
                    _, xa0, xa1, ya0, ya1, texture, uv, raw = it
                    xs += [xa0, xa1]
                    ys += [ya0, ya1]
                elif face_axis(face) == "x":
                    _, za0, za1, ya0, ya1, texture, uv, raw = it
                    xs += [za0, za1]
                    ys += [ya0, ya1]
                else:
                    _, xa0, xa1, za0, za1, texture, uv, raw = it
                    xs += [xa0, xa1]
                    ys += [za0, za1]

            # grid spans in “cells”, not vertices: we assume each quad is 1 cell thick in the varying axes.
            # so we convert [a0,a1] to a0..a1-1 cells
            minx = min(xs); maxx = max(xs)
            miny = min(ys); maxy = max(ys)
            W = maxx - minx
            H = maxy - miny
            if W <= 0 or H <= 0:
                continue

            mask = [[False]*W for _ in range(H)]
            tex_map = [[None]*W for _ in range(H)]

            for it in scells:
                if face_axis(face) == "z":
                    _, xa0, xa1, ya0, ya1, texture, uv, raw = it
                    # should be a0..a0+1 etc, but allow larger:
                    # We'll mark all covered unit cells
                    for xx in range(xa0, xa1):
                        for yy in range(ya0, ya1):
                            cx = xx - minx
                            cy = yy - miny
                            mask[cy][cx] = True
                            tex_map[cy][cx] = texture
                elif face_axis(face) == "x":
                    _, za0, za1, ya0, ya1, texture, uv, raw = it
                    for xx in range(za0, za1):
                        for yy in range(ya0, ya1):
                            cx = xx - minx
                            cy = yy - miny
                            mask[cy][cx] = True
                            tex_map[cy][cx] = texture
                else:
                    _, xa0, xa1, za0, za1, texture, uv, raw = it
                    for xx in range(xa0, xa1):
                        for yy in range(za0, za1):
                            cx = xx - minx
                            cy = yy - miny
                            mask[cy][cx] = True
                            tex_map[cy][cx] = texture

            rects = greedy_rect(mask, H, W)

            for x0,y0,x1,y1 in rects:
                xa0 = minx + x0
                ya0 = miny + y0
                xa1 = minx + x1 + 1
                ya1 = miny + y1 + 1

                texture = tex_map[y0][x0]  # from top-left cell

                # Build one plate element
                if face_axis(face) == "z":
                    zfixed = fixed * step
                    x_from = xa0 * step
                    x_to   = xa1 * step
                    y_from = ya0 * step
                    y_to   = ya1 * step
                    # thickness: use 0..step by taking direction
                    dz = step
                    if face == "north":
                        z0 = zfixed; z1 = zfixed + dz
                    else: # south
                        z0 = zfixed - dz; z1 = zfixed
                    el = {
                        "from": [x_from, y_from, z0],
                        "to":   [x_to,   y_to,   z1],
                        "faces": {face: {"uv":[0,0,1,1], "texture": texture}}
                    }
                elif face_axis(face) == "x":
                    xfixed = fixed * step
                    z_from = xa0 * step
                    z_to   = xa1 * step
                    y_from = ya0 * step
                    y_to   = ya1 * step
                    dx = step
                    if face == "west":
                        x0 = xfixed; x1 = xfixed + dx
                    else: # east
                        x0 = xfixed - dx; x1 = xfixed
                    el = {
                        "from": [x0, y_from, z_from],
                        "to":   [x1, y_to,   z_to],
                        "faces": {face: {"uv":[0,0,1,1], "texture": texture}}
                    }
                else: # y fixed
                    yfixed = fixed * step
                    x_from = xa0 * step
                    x_to   = xa1 * step
                    z_from = ya0 * step
                    z_to   = ya1 * step
                    dy = step
                    if face == "down":
                        y0 = yfixed; y1 = yfixed + dy
                    else: # up
                        y0 = yfixed - dy; y1 = yfixed
                    el = {
                        "from": [x_from, y0, z_from],
                        "to":   [x_to,   y1, z_to],
                        "faces": {face: {"uv":[0,0,1,1], "texture": texture}}
                    }

                new_elements.append(el)
                removed += 1

    data["elements"] = new_elements

    out = args.output
    if out is None:
        base, ext = os.path.splitext(args.input_json)
        out = base + "_merged" + ext
    with open(out, "w", encoding="utf-8") as f:
        json.dump(data, f, separators=(",", ":"))

    print("step:", step)
    new_elements = merge_3d(new_elements)
    print("elements before:", len(elements), "after:", len(new_elements))
    print("saved:", out)

if __name__ == "__main__":
    main()

