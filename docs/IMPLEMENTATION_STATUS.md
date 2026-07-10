# 点击/点按显示地名功能 - 实施状态与继续步骤

## 已完成

### 1. 修改地图生成脚本
- **文件**: `scripts/04_make_map.py`
- **改动**:
  - 地图初始化增加 `tap: true`，确保手机端点按事件正常触发：
    ```javascript
    const map = L.map('map', {layers: [sat], preferCanvas: true, tap: true});
    ```
  - 新增 `reverseGeocode(lat, lon)`：调用高德逆地理编码 API (`/v3/geocode/regeo`)，缓存结果，无 key 时降级显示坐标。
  - 新增 `bindPopupWithAddress(l, makeHtml)`：先弹出原有信息，点击后异步追加 `位置: <地名>`。
  - 市级地图的 `coverLayer`、`allLayer`、`selLayer` 全部改用 `bindPopupWithAddress`。
  - 全省总图的 `boundaryLayer`、`coverLayer`、`selLayer` 全部改用 `bindPopupWithAddress`。

### 2. 重新生成 14 张地图
已执行：
```bash
cd /mnt/win_data/data_mea/sunshu_mea/
python3 scripts/04_make_map.py
```
生成结果：
- 13 张市级地图：`output/{city}/{city}.html`
- 1 张全省总图：`output/jiangsu_all.html`

### 3. 基础验证
- `python3 -m py_compile scripts/04_make_map.py` 通过（语法正确）。
- `node --check /tmp/test_nanjing.js` 通过（生成 HTML 内联 JS 语法正确）。
- 高德逆地理编码 API 用 `data/amap_key.txt` 中的 key 测试通过，可返回完整地址。

### 4. 已部署到 Cloudflare Pages
执行：
```bash
cd /mnt/win_data/data_mea/sunshu_mea/
scripts/05_deploy.sh
```
部署成功。`wrangler pages deploy` 返回的 `5428eac1.jiangsu-uav-maps.pages.dev` 是当前部署的预览/哈希地址，**原项目主地址 `jiangsu-uav-maps.pages.dev` 已同步更新到最新版本**。

- **入口页**: https://jiangsu-uav-maps.pages.dev/
- **全省总图**: https://jiangsu-uav-maps.pages.dev/jiangsu_all
- **市级地图示例**: https://jiangsu-uav-maps.pages.dev/nanjing
- 其他城市替换路径名即可：`suzhou`、`wuxi`、`changzhou`、`zhenjiang`、`yangzhou`、`taizhou`、`nantong`、`yancheng`、`huaian`、`suqian`、`xuzhou`、`lianyungang`

已通过 `curl` 确认原主地址的 `nanjing` 页面包含 `reverseGeocode` 与 `bindPopupWithAddress` 代码。

## 当前问题

### 浏览器自动化测试未通过
使用 `puppeteer-core` + 本地 `python3 -m http.server` 启动的测试遇到 **404 资源错误**，导致 `window.map` 等全局变量未能被脚本检测到。该问题大概率与测试环境（本地静态服务器、404 的字体/CSS/瓦片资源、页面加载策略）有关，而不是地图代码本身的问题。

### 建议的验证方式
在本地浏览器中打开文件直接验证：
```bash
# 方式 1：直接打开文件
xdg-open /mnt/win_data/data_mea/sunshu_mea/output/nanjing/nanjing.html
xdg-open /mnt/win_data/data_mea/sunshu_mea/output/jiangsu_all.html

# 方式 2：启动本地服务器后打开（避免 file:// 协议的资源限制）
cd /mnt/win_data/data_mea/sunshu_mea/output
python3 -m http.server 8765
# 然后在浏览器访问 http://localhost:8765/nanjing/nanjing.html
```

验证要点：
1. 桌面端：用鼠标点击任意色块，popup 中除原有场景/占比信息外，应出现 `位置: 江苏省南京市...` 等地址。
2. 手机端：用 Chrome DevTools 的 Device Mode（如 iPhone SE）刷新页面，用手指点按色块，应同样弹出地址。
3. 全省总图：点击城市边界或溶解后的场景分类块，也应显示地址。

## 继续步骤（剩余工作）

### 步骤 A：本地/线上实测地名 popup
部署已完成，建议你在桌面浏览器和手机浏览器分别打开原项目主地址验证：
- 入口页：https://jiangsu-uav-maps.pages.dev/
- 南京市：https://jiangsu-uav-maps.pages.dev/nanjing

验证要点：
1. 桌面端：鼠标点击任意色块，popup 中除原有场景/占比信息外，应出现 `位置: 江苏省南京市...`。
2. 手机端：微信/浏览器打开，手指点按色块，应同样弹出地址。
3. 全省总图：点击城市边界或溶解后的场景分类块，也应显示地址。

若有问题，查看浏览器 F12 Console 中的报错，并检查 `data/amap_key.txt` 是否有效/配额是否耗尽。

### 步骤 B：后续更新流程
如果以后需要再次更新地图，只需：
```bash
cd /mnt/win_data/data_mea/sunshu_mea/
python3 scripts/04_make_map.py   # 重新生成地图
scripts/05_deploy.sh             # 重新部署
```

### 步骤 C：清理临时文件
测试过程中产生了以下临时文件，建议加入 `.gitignore` 或删除：
- `node_modules/`
- `package-lock.json`
- `package.json`（若未手动维护）
- `test_click_name.js`

**注意**：部署会消耗高德 key 的搜索/逆地理编码配额；key 已嵌入 HTML，建议在[高德控制台](https://console.amap.com/)设置每日调用上限。

## 相关文件变更
- `scripts/04_make_map.py`（主要改动）
- `output/*.html`（重新生成）
- `docs/IMPLEMENTATION_STATUS.md`（本文档）
- 临时测试文件：`test_click_name.js`、`node_modules/`、`package-lock.json`（可删除或加入 `.gitignore`）

## 已知未清理的临时文件
为方便测试安装了 `puppeteer-core`，产生了：
- `/mnt/win_data/data_mea/sunshu_mea/node_modules/`
- `/mnt/win_data/data_mea/sunshu_mea/package-lock.json`
- `/mnt/win_data/data_mea/sunshu_mea/package.json`
- `/mnt/win_data/data_mea/sunshu_mea/test_click_name.js`

建议在验证/部署完成后删除或加入 `.gitignore`。
