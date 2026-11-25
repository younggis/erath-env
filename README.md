# 地球环境模拟器 · Earth Environment Simulator

本地运行的三维地球天气工作台：全球风、温、湿、压、云、降水、全球海浪、全球日海温、CAMS 沙尘/AOD/PM2.5、3D 体积云和机场观测，并实时显示地震/航班/气旋/极光/太阳风/CME，以及 GDACS 全球灾害、NASA EONET 自然事件和 FIRMS 全球火点；可点查任意位置数值。项目只接入真实数据（NOAA GFS、ECMWF IFS、NOAA HRRR、AWC METAR 等）；界面显示每个数据源的新鲜度，无可用数据时明确标注。区域物理模拟（WPS/WRF）与卫星云图图层已移除。

目标环境：Windows 11 + Docker Desktop（WSL 2 后端）+ 本机浏览器；不依赖 Docker 也可在 Windows 本机直接运行 API/CLI。

---

## 1. 快速开始

### 1.1 不装 Docker（本机验证最快）

```bash
# Python 3.11+，需要 fastapi / uvicorn / pydantic / httpx / numpy / pytest
python -m pip install -e . --no-deps        # 若依赖已存在
python -m earthsim.cli doctor

# 启动 API（同时托管已构建的前端静态文件）
cd backend
python -m uvicorn earthsim.api.app:app --host 127.0.0.1 --port 8080
```

浏览器打开 <http://localhost:8080>。首次进入即可看到风场与时间轴，界面右上角显示「● 在线」；若尚未采集数据，先运行下方 sources refresh。

### 1.2 Docker Compose（完整形态）

在 WSL 2 的 Linux 发行版里克隆本仓库后：

```bash
cp .env.example .env
docker compose config
docker compose up -d --build

curl -fsS http://localhost:8080/api/v1/health
docker compose exec api python -m earthsim.cli doctor
```

启动真实数据采集：

```bash
docker compose exec ingest-worker python -m earthsim.cli sources probe
docker compose exec ingest-worker python -m earthsim.cli sources refresh --source noaa_gfs
docker compose exec ingest-worker python -m earthsim.cli sources refresh --source awc_metar
docker compose exec ingest-worker python -m earthsim.cli sources refresh --source gfs_volume
docker compose exec ingest-worker python -m earthsim.cli sources refresh --source noaa_wave
docker compose exec ingest-worker python -m earthsim.cli sources refresh --source noaa_oisst
docker compose exec ingest-worker python -m earthsim.cli sources refresh --source cams
docker compose exec ingest-worker python -m earthsim.cli sources refresh --source noaa_gefs
docker compose exec ingest-worker python -m earthsim.cli sources refresh --source gdacs
docker compose exec ingest-worker python -m earthsim.cli sources refresh --source eonet
# FIRMS 火点需先设置免费 MAP_KEY：EARTHSIM_FIRMS_MAP_KEY=<key>
```

### 1.3 前端开发（热更新）

```bash
cd apps/web
npm install
npm run dev          # http://127.0.0.1:5173，/api 代理到 127.0.0.1:8080
npm run build        # 产物写入 apps/web/dist，由 FastAPI 同源托管
npm test             # Vitest
```

---

## 2. 仓库结构

```text
apps/web/          Vue 3 + TypeScript + Three.js 前端（地球、粒子、时间轴、详情面板）
backend/earthsim/  FastAPI、SQLite 目录、采集适配、格网采样、实时事件
  api/             路由、响应模型、静态托管
  catalog/         WAL 迁移、目录与发布事务
  fields/          格网、单位、风与时间约定
  ingest/          GFS / IFS / HRRR / 体积云 / METAR / DEM / 实时事件
  cli.py           doctor/sources/catalog
  worker.py        定时采集
config/            defaults.toml
deploy/            Dockerfile.app
docs/              数据来源、验收矩阵、操作说明
scripts/           连通性探测与验证辅助脚本
compose.yaml / .env.example
```

数据根目录（容器内 `/data`；Windows 本机回退到仓库下 `.local-data`）：

```text
catalog/catalog.sqlite3
raw/gfs/<init>/<lead>/filter.grib2 ; raw/ifs/<init>/… ; raw/gfs-volume/<init>/…
raw/metar/<fetch>.json ; raw/topography/…
derived/<snapshot>/<frame>.bin|.png
tmp/
```

---

## 3. 当前功能与验证状态

| 能力 | 状态 | 说明 |
|---|---|---|
| 数据纵向切片（M1） | ✅ 已验证 | 真实数据接入 → 目录发布 → 地球/风粒子 → 时间轴 → 点查 |
| GFS 采集（M2） | ✅ 真实解码与发布已验证（ecCodes 2.50.1；字段扩展后 f000 9→12+ 帧） | 图层已扩展至 10+ 类：10m风、2m温/湿/露点、海平面气压、能见度、降水、CAPE/CIN、雪深、地面气压、500hPa位势高度/垂直速度；其余字段可从同一 GRIB Filter 按需扩展 |
| ECMWF IFS 接入（扩展） | ✅ 95MB 数据已下载解码发布，15 个 surface 字段在线验证通过 | 云分层/100m风/整层水汽/辐射等模式对比字段 |
| GFS-Wave 全球海浪（扩展） | ✅ NOMADS 0.25° 波高/周期/波向 4 时效真实解码发布；浏览器可视化验证通过 | 新增 4 图层（有效波高、峰值周期、平均波向、传播矢量）；海面 shader 用真实波高增强高光/泡沫，粒子流由波向换算，已明确标注为可视化矢量 |
| NOAA OISST 全球日海温（扩展） | ✅ ERDDAP 按日+2×2 降采样取 1MB NetCDF3，全球 0.5° 真实解码发布并浏览器验证 | `sst` 图层；上游 AVHRR-only 分析约滞后两周，界面标注观测时刻 |
| CAMS 全球大气成分（扩展） | ⚠️ 适配器与单元测试通过；本机 Open-Meteo IP 配额耗尽返回 429，真实发布待配额恢复 | AOD / 沙尘 / PM2.5，零值透明；明确标注为 CAMS 0.4° 的 5° 降采样可视化 |
| GEFS 集合不确定性（扩展） | ✅ `geavg`/`gespr` 0.5° 实测下载发布，5 图层 × 3 时效，浏览器验证通过 | 均值/离散度图层 + 风>10m/s 概率（高斯近似，非成员计数概率） |
| 3D 体积云（扩展） | ✅ 6 层 RH → 体数据 raymarching，4 时效时间轴已验证 | 基于多层湿度的云密度代理（非真实云水） |
| GPU 粒子流场（扩展） | ✅ WebGL2 ping-pong 浮点纹理，默认 16000 粒子（可调至 30000），浏览器实测 160+ FPS、无 JS 错误 | 粒子状态存于 GPU 纹理，CPU 不逐帧遍历；`EXT_color_buffer_float` 不可用时自动回退 CPU（上限 8000）；LayerPanel 可切换 |
| 风场拖尾光带（扩展） | ✅ 粒子状态累积到半分辨率 ping-pong 缓冲，形成流动的青色光带；浏览器实测无 JS 错误（`trails-check.png`） | 背面粒子在顶点着色器剔除，避免穿透地球；相机移动时快速衰减防拖影；LayerPanel 可开关 |
| 晨昏光照与电影调色（扩展） | ✅ 增强晨昏金色光带与夜面对比；后期加入暗角/轻色差/微颗粒；浏览器实测无 JS 错误（`cinematic-check.png`） | 调色在 `OutputPass` 之前的线性空间进行，不重复色调映射；顺带修复 `pow(负数,2.0)` 未定义行为；均可开关 |
| 地点预报卡（扩展） | ✅ 点击地球并发拉取当前图层全部时效的点查结果，右侧详情面板绘制数值曲线；浏览器实测 4 时效、无 JS 错误（`forecast-card.png`） | 直接使用 `/api/v1/sample`，数据来自当前图层真实格网；切换图层时自动清空 |
| METAR 接入（M2） | ✅ 真实 JSON 已取得并归一化（AWC 200，含 VRB/删失能见度处理） | 站点标记与点查使用真实观测 |

逐条 AC-01…AC-07 与 EXT-01…EXT-17 状态与证据见 [docs/acceptance.md](docs/acceptance.md)；数据来源与验证记录见 [docs/data-sources.md](docs/data-sources.md)。

---

## 4. 命令与测试

```bash
# 后端（仓库根目录）
python -m pytest -q                       # 单元/集成测试（自带最小测试数据）
python -m earthsim.cli doctor
python -m earthsim.cli catalog stats
python -m earthsim.cli sources refresh --source noaa_gfs
python -m earthsim.cli sources refresh --source realtime_all

# 前端
cd apps/web && npm test && npm run build
```

所有长任务通过 CLI 或 API 提交；API 列表均稳定排序并设上限，资产通过 opaque ID 交付且带 ETag/immutable 缓存头。

---

## 5. 关键约定

- 坐标 EPSG:4326，参数顺序 `lon,lat`；经度规范到 [-180,180)，全球格网可环绕。
- 时间统一 ISO-8601 UTC 到秒；`init_time`/`valid_time`/`lead_hours` 相互校验。
- 存储单位 SI（K、Pa、m/s、m、%、kg/kg）；显示端转换为 °C、hPa、km。
- 缺测 JSON 用 null、二进制用 NaN、影像用透明；0 与缺测严格区分。
- 风：粒子显示风吹往方向 (u,v)，文字显示气象来向 `(atan2(-u,-v)…)`。
- 视觉特效（Shadertoy 风格）：程序化星空/星云、地球昼夜分界、海洋高光、大气散射、太阳镜头光晕、脉动经纬网、Bloom 辉光。
- 真实昼夜：夜间灯光用 NASA Black Marble 真实纹理（非噪声马赛克）；太阳方向由 NOAA 天文算法按真实 UTC 每帧计算，晨昏线/海洋高光/昼夜分界真实反映地球状态。左侧可勾选是否跟随实时 UTC（取消则跟随图层数据时刻），并显示当前太阳直射点。
- 高清卫星底图：左侧「高清卫星瓦片 (Esri)」开关启用动态 LOD 瓦片（双层 context+detail）。相机可贴近地表（minDistance≈2.006），贴地时中心达 z14 ≈ 7.8 m/像素，可见城市街区、道路、码头（见 `docs/shots/07-county-zoom.png`）。瓦片来自 NOAA Esri World Imagery，署名 Esri, Maxar, Earthstar Geographics；并发限流 3、内存缓存、边缘渐变。
- 发布：候选批次先落盘校验，完整后在单事务里更新活动快照；失败保留上一批可用数据。
- 数据：只访问真实上游，启动时后台补采缺失/过期数据，UI 只显示真实图层；无演示/模拟模式。
- 实时性：`GET /api/v1/data-status` 给出每源 state（live/stale/missing）、fresh、age_minutes 和时间戳；采集失败保留上一批可用数据。实时源含 GFS（NOMADS，约 4–5h 内新批次）、GFS-Wave 全球海浪、METAR（AWC，约 30min）、体积云、IFS，以及地震/航班/极光/太阳风/气旋/CME/GDACS/EONET/FIRMS 等事件数据。
- 全球灾害：GDACS 与 EONET 按灾害类型和 250 km/72h 阈值去重，避免同一事件重复渲染；FIRMS 需设置免费 `EARTHSIM_FIRMS_MAP_KEY`，未配置时显示清晰诊断且 EONET 野火仍可用。

---

## 6. 安全与清理

默认只绑定 `127.0.0.1:8080`。导出写入用户指定目录；外部文件名经安全规范化。清理命令先列出目标与预计释放空间：

```bash
python -m earthsim.cli catalog cleanup --dry-run
```

活动批次、读取中的快照、运行中输入和用户锁定案例受保护；清理顺序为先过期暂存、再过期可重建产物。备份前应停止写入或做一致性快照，恢复时按 `migrations` 版本推进。

详见 [docs/quickstart.md](docs/quickstart.md)、[docs/data-sources.md](docs/data-sources.md)、[docs/acceptance.md](docs/acceptance.md)。
