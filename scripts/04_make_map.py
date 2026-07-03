#!/usr/bin/env python3
"""生成交互地图: 13 个市级单文件 HTML + 1 个全省总图。

用法:  python3 04_make_map.py [city ...]   # 缺省: 全部 13 市 + 全省总图

市级图  output/{city}/{city}.html: 全覆盖分类(1km, 带占比弹窗) + 优选试飞块(2km, 带标签)
全省图  output/jiangsu_all.html: 各市覆盖层按主类溶解(控制体积) + 全部优选块
另导出  output/{city}/blocks_selected.kml
"""
import json
import os
import sys
from pathlib import Path

from shapely.geometry import mapping, shape
from shapely.ops import unary_union

BASE = Path(__file__).resolve().parent.parent
OUT = BASE / "output"

CITY_NAMES = {
    "nanjing": "南京市", "suzhou": "苏州市", "wuxi": "无锡市", "changzhou": "常州市",
    "zhenjiang": "镇江市", "yangzhou": "扬州市", "taizhou": "泰州市", "nantong": "南通市",
    "yancheng": "盐城市", "huaian": "淮安市", "suqian": "宿迁市", "xuzhou": "徐州市",
    "lianyungang": "连云港市",
}

SCENE_COLORS = {
    "水域": "#1f78d1",
    "林区": "#1a9641",
    "密集城区": "#d7191c",
    "农田": "#e8a600",
    "郊区": "#9b59b6",
    "城镇": "#ff7043",
    "草地": "#a6d96a",
    "湿地": "#00c5cc",
    "裸地": "#b0a08a",
}

FOOTER = ("适飞空域数据源: jfsc.cn 江苏低空飞行服务(公示KML) | 土地覆盖: ESA WorldCover 2021 (10m) | "
          "实际飞行需经江苏低空飞行服务平台登记报备, 临时限飞区以当日公告为准; 地物现状建议飞前用卫星图复核。")


def load_amap_key():
    key = os.environ.get("AMAP_KEY", "").strip()
    key_file = BASE / "data" / "amap_key.txt"
    if not key and key_file.exists():
        key = key_file.read_text(encoding="utf-8").strip()
    if not key:
        print("警告: 未配置高德key (环境变量 AMAP_KEY 或 data/amap_key.txt), 地图中的地名搜索将不可用")
    return key


AMAP_KEY = load_amap_key()


def round_coords(o):
    if isinstance(o, list):
        return ([round(v, 5) for v in o] if o and isinstance(o[0], float)
                else [round_coords(x) for x in o])
    return o


def round_fc(fc):
    for f in fc["features"]:
        f["geometry"]["coordinates"] = round_coords(f["geometry"]["coordinates"])
    return fc


def primary_color(scene):
    return SCENE_COLORS.get(scene, SCENE_COLORS.get(scene.split("+")[0], "#666"))


def build_kml(sel, title):
    pm = []
    for f in sel["features"]:
        p = f["properties"]
        coords = f["geometry"]["coordinates"][0]
        ring = " ".join(f"{lon},{lat},0" for lon, lat in coords)
        color = primary_color(p["scene"]).lstrip("#")
        abgr = "80" + color[4:6] + color[2:4] + color[0:2]
        pm.append(f"""  <Placemark>
    <name>{p['scene']}-{p['rank']} ({p['id']})</name>
    <description>中心: {p['center_lon']},{p['center_lat']} 林{p['pct_tree']}% 农{p['pct_crop']}% 建{p['pct_built']}% 水{p['pct_water']}%</description>
    <Style><LineStyle><color>ff{abgr[2:]}</color><width>2</width></LineStyle><PolyStyle><color>{abgr}</color></PolyStyle></Style>
    <Polygon><outerBoundaryIs><LinearRing><coordinates>{ring}</coordinates></LinearRing></outerBoundaryIs></Polygon>
  </Placemark>""")
    return ('<?xml version="1.0" encoding="utf-8"?>\n<kml xmlns="http://www.opengis.net/kml/2.2">\n'
            f'<Document><name>{title}</name>\n' + "\n".join(pm) + "\n</Document>\n</kml>\n")


def html_shell(title, body_js, search_city="江苏"):
    leaflet_js = (BASE / "data" / "vendor" / "leaflet.js").read_text(encoding="utf-8")
    leaflet_css = (BASE / "data" / "vendor" / "leaflet.css").read_text(encoding="utf-8")
    return f"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>{leaflet_css}</style>
<style>
  html,body{{margin:0;height:100%;font-family:"PingFang SC","Microsoft YaHei",sans-serif}}
  #map{{height:100%}}
  .block-label{{background:none;border:none;box-shadow:none;font-weight:700;font-size:12px;
    color:#fff;text-shadow:0 0 3px #000,0 0 3px #000;white-space:nowrap}}
  .city-label{{background:none;border:none;box-shadow:none;font-weight:700;font-size:14px;
    color:#ffe;text-shadow:0 0 4px #000,0 0 4px #000;white-space:nowrap}}
  .legend{{background:#fff;padding:8px 12px;border-radius:6px;box-shadow:0 1px 5px rgba(0,0,0,.4);line-height:1.7}}
  .geosearch{{background:#fff;padding:6px;border-radius:6px;box-shadow:0 1px 5px rgba(0,0,0,.4);width:220px}}
  .geosearch input{{width:100%;box-sizing:border-box;border:1px solid #ccc;border-radius:4px;padding:4px 6px;font-size:13px}}
  .geosearch .results{{max-height:220px;overflow-y:auto;font-size:12px}}
  .geosearch .results .item{{padding:4px 2px;border-top:1px solid #eee;cursor:pointer}}
  .geosearch .results .item:hover{{background:#f0f6ff}}
  .geosearch .results .hint{{padding:4px 2px;color:#888}}
  .search-pin{{background:none;border:none}}
  .legend i{{display:inline-block;width:14px;height:14px;margin-right:6px;vertical-align:-2px;border-radius:2px}}
  .footer{{position:absolute;bottom:0;left:0;right:0;z-index:1000;background:rgba(255,255,255,.9);
    font-size:11px;color:#444;padding:3px 10px}}
  .popup-table td{{padding:0 6px 0 0}}
</style>
</head>
<body>
<div id="map"></div>
<div class="footer">{FOOTER}</div>
<script>{leaflet_js}</script>
<script>
const SCENE_COLORS = {json.dumps(SCENE_COLORS, ensure_ascii=False)};
const sat = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{{z}}/{{y}}/{{x}}',
  {{maxZoom: 19, attribution: 'Esri World Imagery'}});
const osm = L.tileLayer('https://tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png',
  {{maxZoom: 19, attribution: 'OpenStreetMap'}});
const map = L.map('map', {{layers: [sat], preferCanvas: true}});
function color(scene) {{
  return SCENE_COLORS[scene] || SCENE_COLORS[scene.split('+')[0]] || '#666';
}}
function pctRows(p) {{
  return `林 ${{p.pct_tree}}% | 草 ${{p.pct_grass}}% | 农 ${{p.pct_crop}}%<br>
    建 ${{p.pct_built}}% | 水 ${{p.pct_water}}% | 湿 ${{p.pct_wetland}}%`;
}}
function addLegend(extra) {{
  const legend = L.control({{position: 'bottomright'}});
  legend.onAdd = () => {{
    const div = L.DomUtil.create('div', 'legend');
    div.innerHTML = '<b>场景类别</b>（叠加类按主类着色）<br>' + Object.entries(SCENE_COLORS)
      .map(([k, v]) => `<i style="background:${{v}}"></i>${{k}}`).join('<br>') + (extra || '');
    return div;
  }};
  legend.addTo(map);
}}
// 地名搜索定位: 高德 inputtips 实时补全; 返回 GCJ-02, 纠偏为 WGS-84 后打标 (底图与数据均 WGS-84)
const AMAP_KEY = {json.dumps(AMAP_KEY)};
const SEARCH_CITY = {json.dumps(search_city, ensure_ascii=False)};

// GCJ-02 -> WGS-84 逆偏移 (业界通用近似算法, 误差约 1-2 m)
function gcjTransform(x, y, isLat) {{
  let r = isLat ? -100 + 2*x + 3*y + 0.2*y*y + 0.1*x*y + 0.2*Math.sqrt(Math.abs(x))
                : 300 + x + 2*y + 0.1*x*x + 0.1*x*y + 0.1*Math.sqrt(Math.abs(x));
  const u = isLat ? y : x;
  r += (20*Math.sin(6*x*Math.PI) + 20*Math.sin(2*x*Math.PI)) * 2/3;
  r += (20*Math.sin(u*Math.PI) + 40*Math.sin(u/3*Math.PI)) * 2/3;
  r += isLat ? (160*Math.sin(u/12*Math.PI) + 320*Math.sin(u*Math.PI/30)) * 2/3
             : (150*Math.sin(u/12*Math.PI) + 300*Math.sin(u/30*Math.PI)) * 2/3;
  return r;
}}
function gcj2wgs(lon, lat) {{
  if (lon < 72.004 || lon > 137.8347 || lat < 0.8293 || lat > 55.8271) return [lon, lat];
  const a = 6378245.0, ee = 0.00669342162296594323;
  const dLat0 = gcjTransform(lon - 105, lat - 35, true);
  const dLon0 = gcjTransform(lon - 105, lat - 35, false);
  const radLat = lat / 180 * Math.PI;
  const magic = 1 - ee * Math.sin(radLat) * Math.sin(radLat);
  const dLat = (dLat0 * 180) / ((a * (1 - ee)) / (magic * Math.sqrt(magic)) * Math.PI);
  const dLon = (dLon0 * 180) / (a / Math.sqrt(magic) * Math.cos(radLat) * Math.PI);
  return [lon - dLon, lat - dLat];
}}

const pinIcon = L.divIcon({{className: 'search-pin', iconSize: [30, 42],
  iconAnchor: [15, 42], popupAnchor: [0, -40],
  html: '<svg width="30" height="42" viewBox="0 0 30 42"><path d="M15 1C7.3 1 1 7.3 1 15c0 10.5 14 26 14 26s14-15.5 14-26C29 7.3 22.7 1 15 1z" fill="#e63946" stroke="#fff" stroke-width="2"/><circle cx="15" cy="15" r="5.5" fill="#fff"/></svg>'}});

let searchMarker = null;
const searchCtl = L.control({{position: 'topleft'}});
searchCtl.onAdd = () => {{
  const div = L.DomUtil.create('div', 'geosearch');
  div.innerHTML = '<input type="text" placeholder="搜索地名, 实时匹配"><div class="results"></div>';
  L.DomEvent.disableClickPropagation(div);
  L.DomEvent.disableScrollPropagation(div);
  const input = div.querySelector('input');
  const results = div.querySelector('.results');
  if (!AMAP_KEY) {{
    input.disabled = true;
    input.placeholder = '未配置高德key, 搜索不可用';
    return div;
  }}
  let timer = null, aborter = null, tips = [];

  function locate(tip) {{
    results.innerHTML = '';
    const [glon, glat] = tip.location.split(',').map(Number);
    const [lon, lat] = gcj2wgs(glon, glat);
    const dist = typeof tip.district === 'string' ? tip.district : '';
    if (searchMarker) map.removeLayer(searchMarker);
    searchMarker = L.marker([lat, lon], {{icon: pinIcon}}).addTo(map)
      .bindPopup(`<b>${{tip.name}}</b><br>${{dist}}<br>${{lat.toFixed(5)}}°N, ${{lon.toFixed(5)}}°E`)
      .openPopup();
    map.setView([lat, lon], Math.max(map.getZoom(), 14));
  }}

  async function query(kw) {{
    if (aborter) aborter.abort();
    aborter = new AbortController();
    try {{
      const url = 'https://restapi.amap.com/v3/assistant/inputtips?key=' + AMAP_KEY
        + '&datatype=all&city=' + encodeURIComponent(SEARCH_CITY)
        + '&keywords=' + encodeURIComponent(kw);
      const rsp = await (await fetch(url, {{signal: aborter.signal}})).json();
      if (rsp.status !== '1') {{
        results.innerHTML = `<div class="hint">搜索失败: ${{rsp.info || '未知错误'}}</div>`;
        return;
      }}
      tips = (rsp.tips || []).filter(t => typeof t.location === 'string' && t.location.includes(','));
      if (!tips.length) {{ results.innerHTML = '<div class="hint">未找到结果</div>'; return; }}
      results.innerHTML = '';
      tips.forEach(t => {{
        const d = document.createElement('div');
        d.className = 'item';
        d.textContent = t.name + (typeof t.district === 'string' && t.district ? ' · ' + t.district : '');
        d.onclick = () => locate(t);
        results.appendChild(d);
      }});
    }} catch (err) {{
      if (err.name !== 'AbortError') results.innerHTML = '<div class="hint">搜索失败, 请检查网络</div>';
    }}
  }}

  input.addEventListener('input', () => {{
    clearTimeout(timer);
    const kw = input.value.trim();
    if (!kw) {{ results.innerHTML = ''; tips = []; return; }}
    timer = setTimeout(() => query(kw), 250);
  }});
  input.addEventListener('keydown', e => {{
    if (e.key === 'Escape') results.innerHTML = '';
    else if (e.key === 'Enter' && tips.length) locate(tips[0]);
  }});
  return div;
}};
searchCtl.addTo(map);
{body_js}
</script>
</body>
</html>
"""


def make_city_map(city):
    zh = CITY_NAMES[city]
    cdir = OUT / city
    airspace = json.loads((OUT / "airspace" / f"{city}.geojson").read_text(encoding="utf-8"))
    sel = json.loads((cdir / "blocks_selected.geojson").read_text(encoding="utf-8"))
    allb = json.loads((cdir / "blocks_all.geojson").read_text(encoding="utf-8"))
    cover = round_fc(json.loads((cdir / "coverage_1km.geojson").read_text(encoding="utf-8")))

    g = shape(airspace["features"][0]["geometry"]).simplify(0.0001, preserve_topology=True)
    airspace["features"][0]["geometry"] = mapping(g)

    (cdir / "blocks_selected.kml").write_text(build_kml(sel, f"{zh}无人机试飞块"), encoding="utf-8")

    body = f"""
const AIRSPACE = {json.dumps(airspace, ensure_ascii=False)};
const BLOCKS_SEL = {json.dumps(sel, ensure_ascii=False)};
const BLOCKS_ALL = {json.dumps(allb, ensure_ascii=False)};
const COVERAGE = {json.dumps(cover, ensure_ascii=False)};

const airspaceLayer = L.geoJSON(AIRSPACE, {{
  style: {{color: '#00e5e5', weight: 1.5, fillColor: '#00e5e5', fillOpacity: 0.06}}
}}).addTo(map);

const coverLayer = L.geoJSON(COVERAGE, {{
  style: f => ({{color: '#ffffff', weight: 0.4, opacity: 0.35,
                 fillColor: color(f.properties.scene), fillOpacity: 0.55}}),
  onEachFeature: (f, l) => {{
    const p = f.properties;
    l.bindPopup(`<b>${{p.scene}}</b>（${{p.area_km2}} km²）<br>` + pctRows(p));
  }}
}}).addTo(map);

const allLayer = L.geoJSON(BLOCKS_ALL, {{
  style: f => {{
    const lab = f.properties.labels;
    return {{color: lab ? color(lab.split('/')[0]) : '#999', weight: 1,
             fillOpacity: lab ? 0.15 : 0.02, dashArray: '3'}};
  }},
  onEachFeature: (f, l) => {{
    const p = f.properties;
    l.bindPopup(`<b>${{p.id}}</b> ${{p.labels || '(未达标)'}}<br>` + pctRows(p));
  }}
}});

const labelGroup = L.layerGroup();
const selLayer = L.geoJSON(BLOCKS_SEL, {{
  style: f => ({{color: color(f.properties.scene), weight: 3,
                 fillColor: color(f.properties.scene), fillOpacity: 0.35}}),
  onEachFeature: (f, l) => {{
    const p = f.properties;
    l.bindPopup(`<b>${{p.scene}} #${{p.rank}}</b>（${{p.id}}）<br>
      中心: ${{p.center_lat.toFixed(5)}}°N, ${{p.center_lon.toFixed(5)}}°E<br>
      尺寸: 2 km × 2 km<br>` + pctRows(p));
    const c = l.getBounds().getCenter();
    L.marker(c, {{icon: L.divIcon({{className: 'block-label',
      html: `${{p.scene}}#${{p.rank}}`, iconSize: null}}), interactive: false}}).addTo(labelGroup);
  }}
}}).addTo(map);
labelGroup.addTo(map);

L.control.layers(
  {{'卫星影像 (Esri)': sat, '街道图 (OSM)': osm}},
  {{'适飞空域边界': airspaceLayer, '全覆盖分类 (1km)': coverLayer,
    '优选试飞块 (2km)': selLayer, '块标签': labelGroup, '全部2km格网': allLayer}},
  {{collapsed: false}}
).addTo(map);
addLegend('<br><i style="border:1.5px solid #00e5e5;background:none"></i>适飞空域边界');
map.fitBounds(airspaceLayer.getBounds().pad(0.03));
"""
    out = cdir / f"{city}.html"
    out.write_text(html_shell(f"{zh}无人机试飞场景分块图", body, search_city=zh), encoding="utf-8")
    print(f"{out.name}: {out.stat().st_size/1e6:.1f} MB")


def make_province_map(cities):
    dissolved_feats = []
    sel_feats = []
    boundary_feats = []
    city_centers = []
    for city in cities:
        zh = CITY_NAMES[city]
        cover = json.loads((OUT / city / "coverage_1km.geojson").read_text(encoding="utf-8"))
        by_scene = {}
        for f in cover["features"]:
            by_scene.setdefault(f["properties"]["scene"].split("+")[0], []).append(
                shape(f["geometry"]))
        for scene, geoms in by_scene.items():
            merged = unary_union(geoms).simplify(0.0005, preserve_topology=True)
            dissolved_feats.append({
                "type": "Feature",
                "properties": {"city": zh, "scene": scene,
                               "n_blocks": len(geoms)},
                "geometry": mapping(merged),
            })
        sel = json.loads((OUT / city / "blocks_selected.geojson").read_text(encoding="utf-8"))
        for f in sel["features"]:
            f["properties"]["city"] = zh
            sel_feats.append(f)
        air = json.loads((OUT / "airspace" / f"{city}.geojson").read_text(encoding="utf-8"))
        g = shape(air["features"][0]["geometry"])
        boundary_feats.append({
            "type": "Feature", "properties": {"city": zh},
            "geometry": mapping(g.simplify(0.001, preserve_topology=True)),
        })
        c = g.centroid
        city_centers.append({"city": zh, "lat": round(c.y, 4), "lon": round(c.x, 4)})

    dissolved = round_fc({"type": "FeatureCollection", "features": dissolved_feats})
    boundaries = round_fc({"type": "FeatureCollection", "features": boundary_feats})
    sel_fc = {"type": "FeatureCollection", "features": sel_feats}

    body = f"""
const BOUNDARIES = {json.dumps(boundaries, ensure_ascii=False)};
const DISSOLVED = {json.dumps(dissolved, ensure_ascii=False)};
const BLOCKS_SEL = {json.dumps(sel_fc, ensure_ascii=False)};
const CITY_CENTERS = {json.dumps(city_centers, ensure_ascii=False)};

const boundaryLayer = L.geoJSON(BOUNDARIES, {{
  style: {{color: '#00e5e5', weight: 1.5, fillColor: '#00e5e5', fillOpacity: 0.05}},
  onEachFeature: (f, l) => l.bindPopup(`<b>${{f.properties.city}}</b> 适飞空域`)
}}).addTo(map);

const coverLayer = L.geoJSON(DISSOLVED, {{
  style: f => ({{color: color(f.properties.scene), weight: 0.5, opacity: 0.6,
                 fillColor: color(f.properties.scene), fillOpacity: 0.55}}),
  onEachFeature: (f, l) => {{
    const p = f.properties;
    l.bindPopup(`<b>${{p.city}} · ${{p.scene}}</b><br>约 ${{p.n_blocks}} 个 1km 块<br>
      详细占比见对应市级地图`);
  }}
}}).addTo(map);

const labelGroup = L.layerGroup();
const selLayer = L.geoJSON(BLOCKS_SEL, {{
  style: f => ({{color: '#fff', weight: 2,
                 fillColor: color(f.properties.scene), fillOpacity: 0.8}}),
  onEachFeature: (f, l) => {{
    const p = f.properties;
    l.bindPopup(`<b>${{p.city}} ${{p.scene}} #${{p.rank}}</b>（${{p.id}}）<br>
      中心: ${{p.center_lat.toFixed(5)}}°N, ${{p.center_lon.toFixed(5)}}°E | 2km × 2km<br>` + pctRows(p));
  }}
}}).addTo(map);
CITY_CENTERS.forEach(c => {{
  L.marker([c.lat, c.lon], {{icon: L.divIcon({{className: 'city-label',
    html: c.city, iconSize: null}}), interactive: false}}).addTo(labelGroup);
}});
labelGroup.addTo(map);

L.control.layers(
  {{'卫星影像 (Esri)': sat, '街道图 (OSM)': osm}},
  {{'适飞空域边界': boundaryLayer, '场景分类 (按主类溶解)': coverLayer,
    '优选试飞块 (2km)': selLayer, '城市名': labelGroup}},
  {{collapsed: false}}
).addTo(map);
addLegend('<br><i style="border:1.5px solid #00e5e5;background:none"></i>适飞空域边界' +
  '<br><span style="font-size:11px;color:#666">优选块为白边高亮小方块<br>各市 1km 细分见市级地图</span>');
map.fitBounds(boundaryLayer.getBounds().pad(0.03));
"""
    out = OUT / "jiangsu_all.html"
    out.write_text(html_shell("江苏省无人机试飞场景分块总图", body), encoding="utf-8")
    print(f"{out.name}: {out.stat().st_size/1e6:.1f} MB")


def main():
    cities = sys.argv[1:] or sorted(CITY_NAMES)
    for city in cities:
        make_city_map(city)
    if not sys.argv[1:]:
        make_province_map(cities)


if __name__ == "__main__":
    main()
