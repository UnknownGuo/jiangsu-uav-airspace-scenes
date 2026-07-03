#!/bin/bash
# 下载数据：江苏适飞空域 KML + ESA WorldCover 2021 土地覆盖瓦片（江苏全省覆盖 5 张 3°×3° 瓦片）
set -e
DATA_DIR="$(dirname "$0")/../data"
cd "$DATA_DIR"

[ -f shifeikongyu.kml ] || curl -fL "https://www.jfsc.cn/data/shifeikongyu.kml" -o shifeikongyu.kml

for TILE in N30E117 N30E120 N33E114 N33E117 N33E120; do
  WC_TIF="ESA_WorldCover_10m_2021_v200_${TILE}_Map.tif"
  curl -fL -C - "https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/$WC_TIF" -o "$WC_TIF" || true
done

ls -lh
