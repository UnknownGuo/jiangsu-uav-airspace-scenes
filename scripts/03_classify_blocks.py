#!/usr/bin/env python3
"""对江苏 13 个地市的适飞空域做两层分类:
1) 全覆盖层: 1km 格网按适飞区边界裁剪, 每个碎块(≥0.15km²)都标主类别+叠加类别;
2) 优选层: 2km 格网(≥90%在适飞区内)按判据挑选各场景候选试飞块。

用法:  python3 03_classify_blocks.py [city ...]   # 缺省跑全部 13 市

输入:  output/airspace/{city}.geojson, data/ESA_WorldCover_10m_2021_v200_*_Map.tif
输出:  output/{city}/coverage_1km.geojson   全覆盖分类
       output/{city}/blocks_all.geojson     全部合格 2km 格子及占比
       output/{city}/blocks_selected.geojson 入选候选块
       output/{city}/blocks_summary.csv     候选块汇总表
"""
import csv
import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np
import rasterio
from rasterio import features as rfeatures
from rasterio.merge import merge as rio_merge
from rasterio.windows import from_bounds
from pyproj import Transformer
from shapely.geometry import box, mapping, shape
from shapely.ops import transform as shp_transform

BASE = Path(__file__).resolve().parent.parent
AIRSPACE_DIR = BASE / "output" / "airspace"

BLOCK_SIZE_M = 2000
INSIDE_FRAC_MIN = 0.90   # 2km 格子面积至少 90% 落在适飞区内
TOP_N = 5                # 每类候选上限
MIN_SPACING_M = 5000     # 同类候选中心最小间距

COVER_SIZE_M = 1000
COVER_MIN_AREA_M2 = 0.15e6  # 裁剪碎块小于 0.15km² 丢弃

# WorldCover 类别值
WC = {"tree": 10, "shrub": 20, "grass": 30, "crop": 40, "built": 50,
      "bare": 60, "snow": 70, "water": 80, "wetland": 90, "mangrove": 95, "moss": 100}

DOM_NAMES = {"water": "水域", "tree": "林区", "crop": "农田", "built": "城镇",
             "grass": "草地", "wetland": "湿地", "bare": "裸地"}

# 全省统一投影 UTM 50N (跨 120°E 的苏州/南通东部误差 <5m, 对 1-2km 格网可忽略)
to_utm = Transformer.from_crs("EPSG:4326", "EPSG:32650", always_xy=True).transform
to_wgs = Transformer.from_crs("EPSG:32650", "EPSG:4326", always_xy=True).transform


class WorldCoverReader:
    """跨多张 3°×3° 瓦片的分区统计读取器。"""

    def __init__(self):
        self.srcs = [rasterio.open(p) for p in sorted(
            (BASE / "data").glob("ESA_WorldCover_10m_2021_v200_*_Map.tif"))]
        if not self.srcs:
            raise SystemExit("data/ 下没有 WorldCover 瓦片")

    def frac(self, geom_wgs):
        """返回 WGS-84 几何内各类占比, 无像元时返回 None。"""
        b = geom_wgs.bounds
        hits = [s for s in self.srcs
                if not (b[2] <= s.bounds.left or b[0] >= s.bounds.right
                        or b[3] <= s.bounds.bottom or b[1] >= s.bounds.top)]
        if not hits:
            return None
        if len(hits) == 1:
            src = hits[0]
            w = from_bounds(*b, transform=src.transform)
            data = src.read(1, window=w, boundless=True, fill_value=0)
            transform = src.window_transform(w)
        else:
            data, transform = rio_merge(hits, bounds=b, nodata=0)
            data = data[0]
        if data.size == 0:
            return None
        mask = rfeatures.geometry_mask([mapping(geom_wgs)], out_shape=data.shape,
                                       transform=transform, invert=True)
        vals = data[mask]
        vals = vals[vals > 0]
        if vals.size == 0:
            return None
        return {k: float(np.count_nonzero(vals == v)) / vals.size for k, v in WC.items()}

    def close(self):
        for s in self.srcs:
            s.close()


def classify(frac):
    """2km 优选层: 返回该块所有达标的单类标签。"""
    labels = []
    if frac["water"] >= 0.40:
        labels.append("水域")
    if frac["tree"] >= 0.60:
        labels.append("林区")
    if frac["built"] >= 0.60:
        labels.append("密集城区")
    if frac["crop"] >= 0.65:
        labels.append("农田")
    if 0.20 <= frac["built"] <= 0.45 and frac["crop"] + frac["grass"] >= 0.40:
        labels.append("郊区")
    if frac["wetland"] + frac["mangrove"] >= 0.35:
        labels.append("湿地")
    return labels


def secondary_label(frac, primary):
    name_map = {"water": "水域", "tree": "林区", "built": "密集城区",
                "crop": "农田", "wetland": "湿地", "grass": "草地"}
    cands = [(v, name_map[k]) for k, v in frac.items()
             if k in name_map and name_map[k] != primary and v >= 0.25]
    if not cands:
        return None
    return max(cands)[1]


def coverage_scene(frac):
    """全覆盖层: 每块必得一个主类别, 第二类占比>=25%时追加叠加标签。"""
    if frac["built"] >= 0.60:
        primary, primary_key = "密集城区", "built"
    elif 0.20 <= frac["built"] <= 0.45 and frac["crop"] + frac["grass"] >= 0.40:
        return "郊区"  # 郊区本身即混合场景, 不再叠加
    else:
        primary_key = max(DOM_NAMES, key=lambda k: frac[k])
        primary = DOM_NAMES[primary_key]
    others = [k for k in DOM_NAMES if k != primary_key and frac[k] >= 0.25]
    if others:
        sec = max(others, key=lambda k: frac[k])
        return f"{primary}+{DOM_NAMES[sec]}"
    return primary


def frac_props(frac):
    return {f"pct_{k}": round(frac[k] * 100, 1)
            for k in ["tree", "grass", "crop", "built", "water", "wetland", "bare"]}


def build_coverage(airspace_utm, reader):
    minx, miny, maxx, maxy = airspace_utm.bounds
    xs = np.arange(np.floor(minx / COVER_SIZE_M) * COVER_SIZE_M, maxx, COVER_SIZE_M)
    ys = np.arange(np.floor(miny / COVER_SIZE_M) * COVER_SIZE_M, maxy, COVER_SIZE_M)
    feats = []
    for x in xs:
        for y in ys:
            cell = box(x, y, x + COVER_SIZE_M, y + COVER_SIZE_M)
            inter = airspace_utm.intersection(cell)
            if inter.is_empty or inter.area < COVER_MIN_AREA_M2:
                continue
            geom_wgs = shp_transform(to_wgs, inter)
            frac = reader.frac(geom_wgs)
            if frac is None:
                continue
            feats.append({
                "type": "Feature",
                "properties": {"scene": coverage_scene(frac),
                               "area_km2": round(inter.area / 1e6, 2), **frac_props(frac)},
                "geometry": mapping(geom_wgs),
            })
    return {"type": "FeatureCollection", "features": feats}


def build_selection(airspace_utm, reader):
    minx, miny, maxx, maxy = airspace_utm.bounds
    xs = np.arange(np.floor(minx / BLOCK_SIZE_M) * BLOCK_SIZE_M, maxx, BLOCK_SIZE_M)
    ys = np.arange(np.floor(miny / BLOCK_SIZE_M) * BLOCK_SIZE_M, maxy, BLOCK_SIZE_M)
    cell_area = BLOCK_SIZE_M ** 2
    blocks = []
    i = 0
    for x in xs:
        for y in ys:
            cell = box(x, y, x + BLOCK_SIZE_M, y + BLOCK_SIZE_M)
            inter = airspace_utm.intersection(cell)
            if inter.area / cell_area < INSIDE_FRAC_MIN:
                continue
            cell_wgs = shp_transform(to_wgs, cell)
            frac = reader.frac(cell_wgs)
            if frac is None:
                continue
            lon, lat = to_wgs(cell.centroid.x, cell.centroid.y)
            blocks.append({"id": f"B{i:04d}", "geom_utm": cell, "geom_wgs": cell_wgs,
                           "lon": lon, "lat": lat, "frac": frac, "labels": classify(frac)})
            i += 1

    labeled = [b for b in blocks if b["labels"]]
    cnt = Counter(l for b in labeled for l in b["labels"])

    # 密集城区兜底: 若无块达 0.60, 降阈值到 0.45
    if cnt.get("密集城区", 0) == 0:
        for b in blocks:
            if b["frac"]["built"] >= 0.45 and "密集城区" not in b["labels"]:
                b["labels"].append("密集城区")
        labeled = [b for b in blocks if b["labels"]]
        cnt = Counter(l for b in labeled for l in b["labels"])

    score_key = {"水域": "water", "林区": "tree", "密集城区": "built",
                 "农田": "crop", "湿地": "wetland", "郊区": None}
    selected = []
    for label in sorted(cnt):
        pool = [b for b in labeled if label in b["labels"]]
        if score_key.get(label):
            pool.sort(key=lambda b: b["frac"][score_key[label]], reverse=True)
        else:
            pool.sort(key=lambda b: min(b["frac"]["built"], b["frac"]["crop"] + b["frac"]["grass"]), reverse=True)
        picked = []
        for b in pool:
            c = b["geom_utm"].centroid
            if all(c.distance(p["geom_utm"].centroid) >= MIN_SPACING_M for p in picked):
                picked.append(b)
            if len(picked) >= TOP_N:
                break
        for rank, b in enumerate(picked, 1):
            sec = secondary_label(b["frac"], label)
            scene = f"{label}+{sec}" if sec else label
            selected.append({**b, "primary": label, "scene": scene, "rank": rank})

    # 常见叠加组合单独挑选（min(两类占比归一) 打分）
    combos = {
        "林区+水域": lambda f: min(f["tree"] / 0.35, f["water"] / 0.25),
        "农田+水域": lambda f: min(f["crop"] / 0.45, f["water"] / 0.15),
    }
    chosen_ids = {b["id"] for b in selected}
    for combo, score in combos.items():
        pool = [b for b in blocks if score(b["frac"]) >= 1.0 and b["id"] not in chosen_ids]
        pool.sort(key=lambda b: score(b["frac"]), reverse=True)
        picked = []
        for b in pool:
            c = b["geom_utm"].centroid
            if all(c.distance(p["geom_utm"].centroid) >= MIN_SPACING_M for p in picked):
                picked.append(b)
            if len(picked) >= 3:
                break
        for rank, b in enumerate(picked, 1):
            selected.append({**b, "primary": combo.split("+")[0], "scene": combo, "rank": rank})

    return blocks, selected, cnt


def run_city(city, reader):
    gj = json.loads((AIRSPACE_DIR / f"{city}.geojson").read_text(encoding="utf-8"))
    airspace_utm = shp_transform(to_utm, shape(gj["features"][0]["geometry"]))
    out_dir = BASE / "output" / city
    out_dir.mkdir(parents=True, exist_ok=True)

    coverage = build_coverage(airspace_utm, reader)
    (out_dir / "coverage_1km.geojson").write_text(
        json.dumps(coverage, ensure_ascii=False), encoding="utf-8")
    cover_cnt = Counter(f["properties"]["scene"].split("+")[0]
                        for f in coverage["features"])

    blocks, selected, cnt = build_selection(airspace_utm, reader)

    out_all = {"type": "FeatureCollection", "features": [{
        "type": "Feature",
        "properties": {"id": b["id"], "labels": "/".join(b["labels"]), **frac_props(b["frac"])},
        "geometry": mapping(b["geom_wgs"]),
    } for b in blocks]}
    (out_dir / "blocks_all.geojson").write_text(
        json.dumps(out_all, ensure_ascii=False), encoding="utf-8")

    out_sel = {"type": "FeatureCollection", "features": [{
        "type": "Feature",
        "properties": {"id": b["id"], "primary": b["primary"], "scene": b["scene"],
                       "rank": b["rank"], "center_lon": round(b["lon"], 6),
                       "center_lat": round(b["lat"], 6), **frac_props(b["frac"])},
        "geometry": mapping(b["geom_wgs"]),
    } for b in selected]}
    (out_dir / "blocks_selected.geojson").write_text(
        json.dumps(out_sel, ensure_ascii=False), encoding="utf-8")

    with open(out_dir / "blocks_summary.csv", "w", newline="", encoding="utf-8-sig") as f:
        wtr = csv.writer(f)
        wtr.writerow(["块ID", "场景", "序号", "中心经度", "中心纬度",
                      "林地%", "草地%", "农田%", "建成区%", "水体%", "湿地%"])
        for b in sorted(selected, key=lambda b: (b["primary"], b["rank"])):
            fp = frac_props(b["frac"])
            wtr.writerow([b["id"], b["scene"], b["rank"],
                          round(b["lon"], 6), round(b["lat"], 6),
                          fp["pct_tree"], fp["pct_grass"], fp["pct_crop"],
                          fp["pct_built"], fp["pct_water"], fp["pct_wetland"]])

    print(f"{city}: 覆盖层 {len(coverage['features'])} 块 {dict(cover_cnt.most_common())}, "
          f"2km 合格 {len(blocks)}, 优选 {len(selected)}")


def main():
    cities = sys.argv[1:] or sorted(p.stem for p in AIRSPACE_DIR.glob("*.geojson"))
    reader = WorldCoverReader()
    for city in cities:
        run_city(city, reader)
    reader.close()


if __name__ == "__main__":
    main()
