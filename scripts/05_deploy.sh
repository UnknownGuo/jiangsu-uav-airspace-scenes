#!/usr/bin/env bash
# 组装静态站点并部署到 Cloudflare Pages (首次使用需: npx wrangler login)
set -euo pipefail
cd "$(dirname "$0")/.."

CITIES="nanjing suzhou wuxi changzhou zhenjiang yangzhou taizhou nantong yancheng huaian suqian xuzhou lianyungang"
SITE=output/site
PROJECT=jiangsu-uav-maps

rm -rf "$SITE"
mkdir -p "$SITE"
cp web/index.html "$SITE/"
cp output/jiangsu_all.html "$SITE/"
for city in $CITIES; do
  cp "output/$city/$city.html" "$SITE/"
  mkdir -p "$SITE/files/$city"
  cp "output/$city/blocks_selected.kml" "output/$city/blocks_summary.csv" "$SITE/files/$city/"
done

echo "站点组装完成: $(du -sh "$SITE" | cut -f1), $(find "$SITE" -type f | wc -l) 个文件"
npx --yes wrangler pages deploy "$SITE" --project-name "$PROJECT"
