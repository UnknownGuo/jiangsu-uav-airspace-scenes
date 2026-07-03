#!/usr/bin/env python3
"""解析江苏适飞空域 KML，提取 13 个地市的多边形，各输出一份 GeoJSON。

输入:  data/shifeikongyu.kml (WGS-84)
输出:  output/airspace/{pinyin}.geojson × 13
"""
import json
import re
from pathlib import Path

from shapely.geometry import MultiPolygon, Polygon, mapping
from shapely.validation import make_valid
from shapely.ops import unary_union

BASE = Path(__file__).resolve().parent.parent
KML_PATH = BASE / "data" / "shifeikongyu.kml"
OUT_DIR = BASE / "output" / "airspace"

CITY_PINYIN = {
    "南京市": "nanjing", "苏州市": "suzhou", "无锡市": "wuxi", "常州市": "changzhou",
    "镇江市": "zhenjiang", "扬州市": "yangzhou", "泰州市": "taizhou", "南通市": "nantong",
    "盐城市": "yancheng", "淮安市": "huaian", "宿迁市": "suqian", "徐州市": "xuzhou",
    "连云港市": "lianyungang",
}


def parse_coord_text(text):
    """KML coordinates 文本 -> [(lon, lat), ...]。格式为 'lon,lat[,alt] lon,lat ...' 或空格分隔对。"""
    pts = []
    for token in text.split():
        parts = token.split(",")
        if len(parts) >= 2:
            pts.append((float(parts[0]), float(parts[1])))
    if not pts:  # 兼容 'lon lat lon lat' 无逗号格式
        nums = [float(x) for x in text.split()]
        pts = list(zip(nums[0::2], nums[1::2]))
    return pts


def parse_city(placemark):
    polygons = []
    for poly_xml in re.findall(r"<Polygon>.*?</Polygon>", placemark, re.S):
        outer = re.search(
            r"<outerBoundaryIs>.*?<coordinates>(.*?)</coordinates>", poly_xml, re.S
        )
        shell = parse_coord_text(outer.group(1))
        holes = [
            parse_coord_text(h)
            for h in re.findall(
                r"<innerBoundaryIs>.*?<coordinates>(.*?)</coordinates>.*?</innerBoundaryIs>",
                poly_xml,
                re.S,
            )
        ]
        if len(shell) >= 4:
            polygons.append(Polygon(shell, holes))
    geom = unary_union([make_valid(p) for p in polygons])
    if isinstance(geom, Polygon):
        geom = MultiPolygon([geom])
    return geom, len(polygons)


def main():
    kml = KML_PATH.read_text(encoding="utf-8")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for p in re.findall(r"<Placemark.*?</Placemark>", kml, re.S):
        m = re.search(r'name="aliasname">([^<]+)<', p)
        city = m.group(1) if m else None
        if city not in CITY_PINYIN:
            print(f"跳过未知 Placemark: {city}")
            continue
        geom, n = parse_city(p)
        fc = {
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "properties": {"city": city, "source": "jfsc.cn shifeikongyu.kml"},
                "geometry": mapping(geom),
            }],
        }
        out = OUT_DIR / f"{CITY_PINYIN[city]}.geojson"
        out.write_text(json.dumps(fc, ensure_ascii=False), encoding="utf-8")
        print(f"{city}: {n} 个多边形, bounds={tuple(round(v,3) for v in geom.bounds)} -> {out.name}")


if __name__ == "__main__":
    main()
