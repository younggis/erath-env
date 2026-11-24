# 地球环境模拟器 · 实施指南

**版本** 2.0　**核对日期** 2026-11-24　**交付对象** Codex 开发代理及项目维护者
**目标设备** Windows 11 个人电脑（可选用 Docker Desktop + WSL 2，也可本机直接运行）。
**产品形式** 本地 Web 应用：浏览器访问本机服务，同时提供可复现的命令行入口。

> 本指南描述**当前实际产品**：接入真实全球数值预报与实时事件的三维地球天气工作台。
> 早期设想过的区域物理模拟（WPS/WRF）、卫星云图图层（Himawari / GOES）与对应的
> 「看现在 / 算这个区域 / 区域模拟」入口已按用户要求移除，不再属于本产品范围。

---

## 1. 产品定义

在一个三维地球里查看**全球数值预报**与**实时地球事件**：全球风、温、湿、压、云、降水、
3D 体积云、机场观测，以及地震、航班、热带气旋、日冕物质抛射、极光和太阳风。
用户进入应用即可看到最近可用的真实数据；可旋转、缩放地球，点选任意位置查询数值，
切换预报图层并用时间轴回放。断网或离线演示时使用 `fixture` 模式。

### 1.1 当前界面与交互

| 入口 | 当前状态 | 说明 |
|---|---|---|
| 顶部导航「看预报」 | 唯一导航项 | 选中第一个可用的预报图层；无「看现在」「算这个区域」 |
| 左侧「数据图层」 | 30 个预报图层（按常用度排序） | 单一「全球预报」分组，由 `src/layerOrder.ts` 统一排序：近地常用天气（风/气温/气压/降水/湿度/露点/能见度/体积云）→ 高空诊断 → 高分辨率区域 → 海洋 → IFS → GEFS；未列入的新图层保持原顺序置于末尾。另含渲染控制、实时事件、视觉特效、数据源面板 |
| 中部三维地球 | 主视图 | 旋转、缩放、点选取值；定位栏支持经纬度搜索与常用位置保存 |
| 底部时间轴 | 播放/倍率/轨道/缺帧提示 | 无模式切换器（观测/区域模拟已移除）；来源标注「全球预报 / 演示」 |
| 右侧「点位详情」 | 唯一详情面板 | 点选位置的图层值、单位、有效时刻、来源；无「区域模拟」tab |

当前图层（`GET /api/v1/layers`，live 模式实测 30 个，全部 `kind=forecast`）：

| 类别 | 图层 ID | 来源 |
|---|---|---|
| GFS 10m / 2m 基本场 | `wind10`、`temp2m`、`rh2m`、`dewpoint2m`、`mslp`、`cloud_total`、`visibility_sfc` | NOAA GFS 0.25° |
| GFS 扩展场 | `precip`、`snow_depth`、`surface_pressure`、`cape`、`cin`、`gh500`、`vvel500`、`wind500` | NOAA GFS 0.25° |
| 全球海浪 | `wave_height`、`wave_period`、`wave_direction`、`wave_drift`（波向换算的可视化矢量） | NOAA GFS-Wave 0.25° |
| 全球日海温 | `sst`（约两周发布滞后） | NOAA OISST v2.1 0.5° |
| GEFS 集合不确定性 | `gefs_wind10_mean`、`gefs_wind10_spread`、`gefs_temp2m_mean`、`gefs_temp2m_spread`、`gefs_wind_prob` | NOAA GEFS 0.5° `geavg`/`gespr` |
| 高分辨率区域场 | `hrrr_wind10` | NOAA HRRR CONUS 3 km |
| 3D 体积云 | `cloud_volume` | GFS 6 层相对湿度（代理量） |
| ECMWF IFS 对比场 | `ifs_2t`、`ifs_2d`、`ifs_msl`、`ifs_10u`、`ifs_10v`、`ifs_tcc`、`ifs_lcc`、`ifs_mcc`、`ifs_hcc`、`ifs_sd`、`ifs_tcwv`、`ifs_ssrd`、`ifs_100u`、`ifs_100v` | ECMWF IFS Open Data 0.25° |

> 注：图层是否可见取决于当前数据根目录里已发布的快照；在 live 模式会过滤掉 `fixture` 来源。
> `terrain`（DEM）作为独立地形渲染层，不出现在图层列表中。

### 1.2 实时事件与空间天气（非格网图层）

左侧「⚡ 实时事件 / 空间天气」分组提供 9 个开关，数据每 60s 刷新，均为真实上游数据：

| 开关 | 数据 | 上游 |
|---|---|---|
| 极光光幕 | OVATION 极光概率 1° 网格 | NOAA SWPC |
| 太阳风粒子流 | 风速/密度/Bz/Kp | NOAA SWPC RTSW + IMF |
| 实时地震冲击波 | 小时地震点 | USGS |
| 实时航班流 | 航空器状态（限流 6000 架） | OpenSky |
| 热带气旋 | 当前风暴 | NOAA NHC |
| 日冕物质抛射 CME | 近 5 日 CME 事件 | NASA DONKI |
| 全球灾害预警 | 全球地震/气旋/洪水/火山/干旱/野火 | GDACS |
| 全球自然事件 | 策划的自然事件与来源链接 | NASA EONET |
| FIRMS 全球火点 | VIIRS 24h 热异常点（需免费 MAP_KEY） | NASA FIRMS |
| 全球气旋轨迹 | GDACS timeline 观测/预报点 | GDACS |

GDACS 与 EONET/FIRMS 同类事件按 250 km / 72h 去重，避免同一事件重复绘制。
机场观测（AWC METAR）作为可点选站点单独呈现，约 60 个全球主要机场。

### 1.3 术语与显示口径

| 类型 | 含义 | 界面标签 |
|---|---|---|
| forecast | 上游预报模型的指定有效时刻 | 全球预报 |
| fixture | 用于测试和离线演示的样本 | 演示 |
| observation | 站点观测与带出处的观测衍生产品 | 站点详情 |

- 卫星资料与区域数值模拟不属于当前产品；无「观测」时间轴模式。
- 云量、降水、雪深等按各自单位与图例显示；3D 体积云基于相对湿度代理，
  **不是真实云水含量**，界面已明确标注。
- 地面能见度为要素预报值；站点能见度来自 METAR 报告，二者分别标注。

---

## 2. 技术架构与项目目录

### 2.1 技术决策

| 层 | 选择 | 实施细节 |
|---|---|---|
| 前端 | Vue 3、TypeScript、Vite、Three.js | Vue 管理 UI 状态，Three.js 独立渲染循环；生产由同源 FastAPI 托管静态文件 |
| API | Python 3.11、FastAPI、Pydantic v2 | 目录查询、格网采样、文件交付、后台刷新任务、新鲜度状态 |
| 数据处理 | ecCodes、cfgrib/xarray、NumPy、pyproj、scipy | 按 GRIB 消息分组解码，重建格点经纬度；HRRR Lambert Conformal → 4326 规则格网 |
| 本地存储 | SQLite WAL + 文件 | SQLite 保存目录、索引、资产与观测；原始 GRIB、派生格网/PNG/体数据存文件系统 |
| 运行 | Docker Compose 或本机进程 | 静态前端与 API 同源；采集 worker 独立进程；默认只绑定 127.0.0.1 |
| 测试 | pytest、Vitest、Playwright | 固定样本常规验证；真实上游冒烟单独执行 |

依赖版本以 `backend/pyproject.toml` 与锁文件为准。M0 阶段已验证 ecCodes 2.50.1
可解码 GFS / IFS / HRRR / 体积云 GRIB。

~~~mermaid
flowchart TD
    S[真实上游 GFS / IFS / HRRR / METAR / 实时事件] --> W[ingest 适配器]
    W --> V[校验 + 派生格网]
    V --> DB[(SQLite 目录 + 文件系统)]
    DB --> API[FastAPI /api/v1]
    API --> UI[Vue 左侧图层 + 三维地球 + 时间轴 + 详情]
    API --> RT[realtime/* 与 data-status]
    RT --> UI
~~~

采集 worker 默认单实例、各源并发 fire-and-forget，同源在途任务去重；API 与 worker
分进程运行，通过同一数据卷/目录与目录库交换数据。

### 2.2 目录结构（当前）

~~~text
earth-environment-simulator/
  apps/web/
    src/
      api.ts, store.ts          接口与集中状态
      palettes.ts               色板与显示范围
      components/               App / LayerPanel / GlobeView / Timeline / DetailPanel / LocationBar
      render/                   Three.js 渲染（scene、earth、FieldLayer、WindLayer、
                                volume、stations、terrain、tiles、sunpos、shaders、postfx）
    public/                     earth-day.jpg / earth-night.jpg / land110m.json
    e2e/                        Playwright 用例
    dist/                       构建产物（由 FastAPI 同源托管）
  backend/
    pyproject.toml, uv.lock
    earthsim/
      api/                      FastAPI 路由与响应模型
      catalog/                  SQLite 迁移、目录、发布事务
      fields/                   格网、单位、风与时间约定
      ingest/                   GFS / IFS / HRRR / volume / METAR / realtime / DEM / fixtures / 拓扑任务
      freshness.py              数据源新鲜度评估
      ingest_tasks.py           后台刷新任务与在途合并
      cli.py                    doctor / fixtures / sources / catalog
      worker.py                 定时采集调度
    tests/
  config/defaults.toml
  deploy/Dockerfile.app
  docs/                         quickstart / data-sources / acceptance / shots
  fixtures/                     由 ingest/fixtures.py 程序生成，可重建
  scripts/                      启动、验证与基准脚本
  compose.yaml / .env.example
  README.md
~~~

数据根：容器内 `/data`；Windows 本机（无 `/data`）回退到仓库下 `.local-data/`。
子目录：`catalog/`、`raw/`、`derived/`、`fixtures/`、`tmp/`、`realtime/`。
工作数据挂载在独立卷，源码与原始数据分开管理。

---

## 3. 数据来源与上线验证

| 源 | 数据 | 接入入口/说明 | 当前状态 |
|---|---|---|---|
| NOAA GFS 0.25° | 全球预报 12+ 字段，00/06/12/18Z 起报 | [NOMADS GRIB Filter](https://nomads.ncep.noaa.gov/) | 真实解码与发布已验证 |
| ECMWF IFS Open Data 0.25° | 15 个 surface 字段，模式对比 | AWS S3 镜像，CC-BY-4.0 | 95MB 已下载解码发布，在线验证通过 |
| NOAA HRRR CONUS 3 km | 10m U/V，高分辨率 LOD | NOMADS `filter_hrrr_sub.pl` | 区域格网重建与贴片渲染已验证 |
| NOAA GFS-Wave 0.25° | 有效波高/峰值周期/平均波向 | NOMADS `filter_gfswave.pl` | 1.8MB/时效真实解码，4 图层 × 4 时效发布与浏览器验证通过 |
| NOAA OISST v2.1 | 全球日海温 0.5°（约两周滞后） | NCEI ERDDAP 按日降采样 | 1MB NetCDF3 真实解码，`sst` 图层发布与浏览器验证通过 |
| CAMS 全球大气成分 | AOD / 沙尘 / PM2.5，5° 降采样 | Open-Meteo `cams_global` | 适配器与 fixture 通过；本机 IP 配额触发 429，真实发布待复跑 |
| NOAA GEFS 0.5° | 集合均值/离散度 + 超阈值概率 | NOMADS `geavg`/`gespr` | 1.3MB/时效，5 图层 × 3 时效真实发布；概率为高斯近似 |
| GFS 多层相对湿度 | 6 层 RH → 3D 体积云 | 同 NOMADS，1000–500 hPa | 360×181×6 体数据，4 时效已验证 |
| NOAA AWC METAR | 机场点观测 | `aviationweather.gov/api/data/metar` | 真实 JSON 已归一化 |
| USGS / OpenSky / NHC / NASA DONKI / NOAA SWPC | 地震、航班、气旋、CME、极光、太阳风 | `ingest/realtime.py` | 6 源全部实测可达 |
| GDACS / NASA EONET / NASA FIRMS | 全球灾害预警、自然事件、VIIRS 24h 火点 | `ingest/disasters.py` | GDACS/EONET 实测入库；FIRMS 需免费 MAP_KEY |
| Natural Earth 110m | 陆海回退底图 | 公共领域 | 本地纹理/GeoJSON |
| NASA Black Marble / Esri | 夜间灯光、动态高清瓦片 | CC BY 4.0 / Esri 署名 | 已接入 |

各源的实际 HTTP 状态、样本标识、字段清单、校验和与复跑命令见
[docs/data-sources.md](docs/data-sources.md)。

### 3.1 GFS 适配器要点

1. 按 UTC 生成 00/06/12/18Z 候选起报时间，倒序探测最近可用批次。
2. 使用 NOMADS GRIB Filter，核心字段与额外字段拆成两个请求：
   `filter.grib2`（风/温/湿/露点/海平面气压/能见度/降水/CAPE/500hPa 高度与垂直速度）
   与 `filter-extra.grib2`（雪深/地面气压/CIN）。组合单次请求在本机网络会挂起。
3. 逐消息用 ecCodes 读取 shortName / typeOfLevel / level / 时间 / 格网；按参数与层次配对提取。
   注意 `cloud_total` 只接受 `tcc`@atmosphere——NOMADS 对 `var_TCDC` 实际返回地表气温
   （paramId 130），必须避免误标。
4. 下载写 `.part`，校验 HTTP 状态、文件长度、GRIB 消息数与缺测率，通过后再原子发布。
   支持 429/503/404 的有界重试与 Retry-After；已下载文件复用。
5. GRIB 原生为北→南存储且经度为 0–360；解码时翻转纬度（`np.flipud`）并把经度滚转为
   −180–180，发布格网元数据统一为 `lon0=-180, lat0=-90`（详见 4.1）。

### 3.2 IFS / HRRR / 体积云 / 实时事件要点

- **IFS**：AWS S3 约 98MB/文件，用分块流式下载 + Range 断点续传（写 `.part`）避免内存缓冲；
  解码 f000 surface 字段为独立数据集 `ecmwf-ifs`。ECMWF 云量为 0–1 分数，发布时 ×100 转 %；
  f000 起报时刻累积量（降水/短波辐射）恒为 0，解码阶段跳过全零累积字段。
- **HRRR**：NOMADS 区域子集约 1.8MB，ecCodes 解码 10m U/V，用 pyproj Lambert Conformal
  重建经纬度，scipy griddata 重采样为 0.05°（约 5km）规则 4326 格网；仅为美国本土区域贴片。
- **体积云**：一次请求取 6 层相对湿度（1000/925/850/700/600/500 hPa，约 5MB），
  `RH>70%` 映射为云密度，降采样为 `360×181×6` float32 体数据（xyz 布局，约 1.5MB），
  数据集 `gfs-volume`；`volume_lead_max_hours=3` 生成 f000–f003 共 4 帧。
- **实时事件**：统一适配器 `ingest/realtime.py`，点事件写 `observations` 表（按 source_id 区分），
  场/时间序列写 `data_root/realtime/*.json`；API 为 `/api/v1/realtime/events|aurora|solar-wind|summary`。
  站点查询显式过滤 `source_id=awc_metar`，避免点事件被当作站点渲染。

### 3.3 METAR 接入要点

使用 `GET https://aviationweather.gov/api/data/metar?ids=...&format=json`，后端按站点请求。
风速节→m/s；`VRB`、静风 `000`、数值风向分类型编码；`>10`、`6+`、`9999` 保留下界与 qualifier；
缺字段为 null；`obsTime`（epoch）与 `reportTime` 均兼容。以
source_id + station_id + observed_at + revision 为逻辑键；204 无报告时保留缓存并维护新鲜度。

---

## 4. 数据契约、存储与更新

### 4.1 空间、时间与单位约定

| 项目 | 约定 |
|---|---|
| 接口坐标 | EPSG:4326，参数顺序 lon、lat；经度规范到 [−180°,180°)，纬度 [−90°,90°] |
| 地球 | WGS84 椭球；经纬高程转 ECEF，固定主轴与 UV 约定 |
| 全球格网 | 南→北、`lon0=-180`、`lat0=-90`、西到东升序；解码时核对 GRIB 扫描方式与首尾经度 |
| 区域格网 | HRRR 等为各自 bbox，不套全球纹理路径；前端用独立贴片渲染 |
| 时间 | 持久化与 API 统一 ISO 8601 UTC 到秒；UI 使用浏览器时区，可切 UTC |
| 预报时间 | `init_time` 起报，`valid_time` 目标时刻，`lead_hours` 推导并校验 |
| 单位 | 温度 K（显示 °C）、气压 Pa（显示 hPa）、风 m/s、降水 mm、雪深 m（显示 cm）、云量 % |
| 缺测 | JSON 用 null，二进制用 NaN，影像用透明；0 与缺测严格区分 |
| 特殊哨兵 | `snow_depth` 的 9999 为缺测哨兵，解码阶段掩膜为 NaN |
| 风 | 风速 `hypot(u,v)`；气象来向 `(atan2(-u,-v)×180/π+360) mod 360`；粒子箭头表示吹往方向，文字表示来向 |

标量点查询为同一有效时刻的双线性插值；靠近无效格或覆盖边界时按字段配置用有界最近邻或返回缺测，
并返回实际采样方法。时序 UI 的帧间插值只用同源、同批次、同高度的帧。

### 4.2 数据库与文件

~~~text
/data/
  catalog/catalog.sqlite3
  raw/gfs/<init>/<lead>/filter.grib2[, filter-extra.grib2]
  raw/ifs/<init>/... ; raw/hrrr/... ; raw/gfs-volume/<init>/...
  raw/metar/<fetch>.json ; raw/topography/<provider>/<tile>
  derived/<snapshot>/<frame>.bin|.png|.vol
  realtime/aurora.json ; solar_wind.json ; ...
  fixtures/ ; tmp/
~~~

| 表 | 主键/关键字段 | 说明 |
|---|---|---|
| source_status | source_id、last_attempt_at、last_success_at、last_error_code | 每个采集源一行 |
| datasets | dataset_id、source_id、kind、attribution、license_url | 稳定数据集定义 |
| snapshots | snapshot_id、dataset_id、identity_key、init_time、state、published_at | 批次；同数据集同标识唯一 |
| frames | frame_id、snapshot_id、layer_id、level_*、valid_time、bbox_json、grid_json | 索引 layer_id/valid_time；bbox 注入 manifest |
| assets | asset_id、frame_id、role、relative_path、media_type、sha256、bytes | 不可变资产，ETag = sha256 |
| active_snapshots | dataset_id、snapshot_id、published_at | 每数据集一个默认快照，事务内更新 |
| observations | station_id、source_id、observed_at、revision、lon、lat、values_json | 站点与实时点事件共用 |
| migrations | version、applied_at | 迁移按版本顺序执行 |

上表是最低持久化契约。数值缺测、限定比较符和原始单位须可查询；源配置和产品元数据更新时保留历史版本。

### 4.3 发布、重试与空间上限

1. 下载与转换在同卷临时路径完成，校验内容类型、关键字段、数组尺寸、时间、校验和和可读性。
2. 原子移到不可变正式路径，随后在单事务中写目录并更新 active 指针。
3. 晚到的较旧预报不替换更新的活动批次；补齐同批次生成新版本，不覆盖已发布资产。
4. 失败时保留上一份可用结果，显示最近成功、最近尝试与来源错误；429/连接失败使用有界退避。
5. 缓存清理按引用关系，保护活动批次与读取中的快照；先过期暂存，再过期可重建产物。
6. `GET /api/v1/data-status` 给出每源 state（live/stale/missing）、fresh、age_minutes 与时间戳。
   live 模式按源分级新鲜度阈值（地震/航班 15min、极光/太阳风 30min、气旋 6h、CME 12h）。

| 参数 | 默认值 | 含义 |
|---|---:|---|
| gfs_poll_seconds | 900 | GFS 探测周期 |
| gfs_lead_max_hours | 36 | 默认逐小时时效覆盖 |
| volume_lead_max_hours | 3 | 体积云时效 f000–f003 |
| wave_lead_max_hours | 3 | 海浪时效 f000–f003 |
| metar_poll_seconds | 300 | METAR 更新周期 |
| realtime_poll_seconds | 180 | 实时源采集周期 |
| firms_map_key | 空 | NASA FIRMS 免费 MAP_KEY；留空禁用 FIRMS |
| gfs_stale_after_hours | 13 | GFS 批次老化告警 |
| oisst_stale_after_hours | 480 | OISST 上游约两周滞后，按 20 天判活 |
| cams_stale_after_hours | 24 | CAMS 全球大气成分新鲜度阈值 |
| gefs_lead_max_hours | 6 | GEFS 时效 f000/f003/f006 |
| metar_stale_after_minutes | 120 | METAR 站点老化告警 |
| keep_gfs_cycles | 2 | 保护最近两个完整批次 |
| derived_cache_budget_gib | 12 | 派生缓存预算 |
| min_free_disk_gib | 8 | 低磁盘阈值 |

---

## 5. API 与前后端接口

### 5.1 端点（当前实际实现）

| 方法和路径 | 请求 | 成功结果 |
|---|---|---|
| GET /api/v1/health | 无 | 服务状态、版本、模式、目录路径、时间 |
| GET /api/v1/sources | include_disabled | 各源采集状态与最新结果 |
| GET /api/v1/data-status | 无 | 每个数据集的 live/stale/missing 与新鲜度 |
| POST /api/v1/sources/{source_id}/refresh | 源 ID | 202，启动非阻塞后台刷新（在途任务复用） |
| GET /api/v1/sources/refresh/{task_id} | 任务 ID | 后台刷新任务状态 |
| GET /api/v1/layers | mode、snapshot_id | 图层清单（label、单位、色带、来源、覆盖、帧数） |
| GET /api/v1/layers/{layer_id}/frames | snapshot_id、from、to、level、limit | 有效时间、资产引用、缺帧提示 |
| GET /api/v1/frames/{frame_id} | 无 | 格网/影像 manifest（含注入的 bbox） |
| GET /api/v1/assets/{asset_id} | 条件请求 | 不可变二进制/图片，ETag 与 immutable 缓存头 |
| GET /api/v1/sample | frame_id、lon、lat | 值、显示值与单位、采样方法、实际帧时间、质量标记 |
| GET /api/v1/stations | bbox、at、max_age_minutes、source_id | 站点及有效窗口内最近观测 |
| GET /api/v1/realtime/events | type、bbox、limit、max_age_minutes | USGS/OpenSky/NHC/DONKI 点事件 |
| GET /api/v1/realtime/aurora | 无 | OVATION 极光概率网格 |
| GET /api/v1/realtime/solar-wind | 无 | 风速/密度/Bz/Kp 与 3 小时历史 |
| GET /api/v1/realtime/summary | 无 | 各实时源状态、Kp、太阳风、服务器时间 |
| GET /api/v1/realtime/tracks | 无 | GDACS 全球气旋轨迹（观测/预报点） |

> 已移除的端点：`/api/v1/simulation/*`（不存在，返回 404）；卫星图像图层相关端点/资产亦不再提供。

错误响应统一为 `{"error":{"code","message","request_id","details"}}`。
状态码：200 正常（空值在结果中表达）、202 已接收刷新任务、404 对象不存在、
422 参数校验失败、503 必需数据/设施不可用。

### 5.2 格网资产示例

~~~json
{
  "schema_version": 1,
  "frame_id": "fixture-wind10-t03",
  "snapshot_id": "fixture-gfs-20261120T0000Z",
  "kind": "fixture",
  "source_id": "demo",
  "layer_id": "wind10",
  "init_time": "2026-11-20T00:00:00Z",
  "valid_time": "2026-11-20T03:00:00Z",
  "level": {"type": "height_agl", "value": 10, "unit": "m"},
  "grid": {
    "crs": "EPSG:4326", "nx": 1440, "ny": 721,
    "lon0": -180.0, "lat0": -90.0, "dx": 0.25, "dy": 0.25,
    "wrap_longitude": true, "cell_reference": "sample_point"
  },
  "fields": [{"id": "u", "unit": "m/s"}, {"id": "v", "unit": "m/s"}],
  "encoding": {"dtype": "float32", "byte_order": "little",
               "layout": "y_x_component_interleaved", "missing": "nan"},
  "assets": [{"role": "grid", "href": "/api/v1/assets/fixture-wind10-t03-bin"}]
}
~~~

二进制长度为 nx × ny × components × sizeof(dtype)，索引
`((j × nx + i) × components + k)`，坐标 `(lon0+i×dx, lat0+j×dy)`。
`GET /api/v1/frames/{id}` 保证把 frame 的 bbox 归一化注入 manifest（影像贴片依赖它，
缺 bbox 时前端明确报错而不是回退全球范围）。

### 5.3 渲染与前端实现要点

- **地球与底图**。`earth-day.jpg` 真实卫星影像为底图，`earth-night.jpg`（NASA Black Marble）
  为夜面灯光；太阳方向由 `render/sunpos.ts` 按 NOAA 算法根据真实 UTC 每帧计算，
  昼夜分界/晨昏线/海洋高光真实反映地球状态。左侧可取消「昼夜跟随真实 UTC」让昼夜
  跟随图层数据时刻，并显示当前太阳直射点。可用 Esri World Imagery 动态 LOD 高清瓦片
  （双层 context+detail，贴地可达 z14 ≈ 7.8 m/像素），署名 Esri, Maxar。
- **图层组合**。渲染顺序为地球/瓦片 → 标量色带或高分辨率贴片 → 风粒子/高空风丝带 →
  站点 → 实时事件 → 3D 体积云。左侧控制开关、不透明度、粒子数量、地形夸张、云密度、辉光。
- **风粒子**。CPU 原型起步，对 u/v 插值后沿切平面东/北方向更新粒子；跨 180° 环绕，
  速度、色阶、拖尾独立；无数据时明确隐藏而非伪造。默认走 GPU 路径（`render/gpuWind.ts`）：
  WebGL2 浮点纹理 ping-pong 保存 (lon, lat, age, seed)，全屏 pass 用同一风场纹理逐帧推进，
  米→度换算必须用 `180/π`（写成 `π/180` 会让粒子慢 3000 倍而看似静止）；
  顶点着色器按索引取状态纹理绘制短拖尾，NormalBlending 避免在明亮地表上过曝。
  `EXT_color_buffer_float` 不可用时回退 CPU，CPU 粒子数上限 8000。
- **零值透明**。`precip`、`snow`、`cloud`、`wind`、`vvel` 等「0=无物」的量使用 alpha
  渐变（0 透明→随量增不透明），避免无值区遮盖底图；`cape`/高度/温度/湿度/气压为全幅
  背景场，保持全幅显示（50% opacity 下底图透出）。`cloudwater` 本就透明。
- **3D 体积云**。Three.js `Data3DTexture` + WebGL2 GLSL raymarching，射线在云壳层内步进
  累加密度；蓝噪声抖动起点、按射线长度自适应步数、4 步向光自阴影、HG 前向散射与 Powder
  边缘共同提供层次感；左侧「3D 体积云显示」开关与云密度滑块；切换到其它图层自动隐藏。
  大气壳加入臭氧吸收与 Mie 前向散射，使临边与晨昏过渡更自然。
- **全球海浪与动态海洋**。有效波高归一化后作为地球 shader 的 `uWaveMap`，增强真实海面高光和强浪泡沫；微尺度波纹法线是装饰效果，数据本身是真实 `swh`。选择任一 wave 图层时风粒子源自动切换为 `wave_drift`（由波向换算的可视化传播矢量），无数据时回退 `wind10`。
- **高分辨率 LOD**。开启「自动高分辨率 LOD」后，视角进入 HRRR 域（−102..−74 / 32..52）
  且缩放足够近时叠加 3km 数据场（边缘 feather 过渡），右上角提示「◆ 高分辨率数据 3 km」。
- **图层切换反馈**。切换时立即清空旧图层并显示 loading，加载完成后渲染新帧；
  `frameDataRev` 计数器统一驱动重绘（不依赖缓存 map 的 size watch），并有居中 toast
  提示（spinner → ✓ → 淡出）。拖动时间轴取消旧请求，LRU 限制内存并主动释放 GPU 资源。
- **全球灾害事件**。GDACS/EONET/FIRMS 以点精灵绘制：灾害预警为按等级着色的脉动菱形，
  火点为闪烁火星，GDACS 气旋 timeline 为带流动脉冲的观测/预报轨迹线（`render/tracks.ts`）。
  点击可见事件会在右侧显示来源、观测时刻、预警等级/强度与报告链接。
- **画质与合成**。`PostFX` 使用 `HalfFloatType + 4× MSAA` 离屏目标，关闭 Bloom 时仍正常出图；
  `render/quality.ts` 以 3 秒 FPS EMA 和 26/45fps 迟滞自动调整 DPR、云步数和 Bloom，
  不覆盖用户的粒子数量、云密度与图层可见性设置。页面隐藏时暂停渲染循环。
- **风场拖尾光带**。`render/windTrails.ts` 把 GPU 粒子状态累积到半分辨率 ping-pong 缓冲：
  每帧先衰减上一帧，再以加法混合绘制当前粒子，最后全屏叠加到主画面，形成连续流动光带。
  背面粒子在顶点着色器直接裁掉；相机矩阵变化时把衰减从 0.975 降到 0.5 以避免屏幕空间拖影。
- **晨昏与电影调色**。地球 shader 的晨昏带有宽暖带+细金边（用 `t*t` 替代 `pow(ndl,2.0)`，
  避免负底数未定义行为）；`PostFX` 在 `OutputPass` 之前插入一个线性空间 grade pass，
  做轻暗角/色差/微颗粒，不重复色调映射。两者均有 LayerPanel 开关。
- **地点预报卡**。点击地球触发 `store.queryPoint`，除当前帧点查外还会对当前图层全部时效
  并发请求 `/api/v1/sample`；`DetailPanel.vue` 把结果绘成 SVG 折线与数值表。
  切换图层时清空序列；显示时效数等于图层实际可用时效，不伪造 72h。

### 5.4 交互布局

顶部品牌 + 唯一导航「看预报」+ UTC 时钟 + 「● 在线/演示」状态；左侧数据图层与各类开关；
中部上方定位栏、中间三维地球、底部时间轴；右侧「点位详情」；底部页脚显示状态、坐标系与出处。
普通模式默认从最近可用数据开始。

---

## 6. 本地部署与操作

### 6.1 开发机准备

- Windows 11 可直接运行 Python + Node；Docker 路径需 WSL 2 + Docker Desktop。
- 首轮用具备硬件加速的 Chromium 系浏览器验证 WebGL2（3D 体积云依赖 WebGL2）。
- 安装镜像与首次获取上游数据需要网络；完成后 `fixture` 模式离线可用。
- 数据源连接从后端进行，适配器读取部署环境的代理设置；日志输出源地址、HTTP 状态与失败原因。

### 6.2 Compose 服务与配置

| 服务 | 启动范围 | 职责 |
|---|---|---|
| api | 默认 | FastAPI、静态前端、OpenAPI、目录查询、后台刷新任务；127.0.0.1:8080 |
| ingest-worker | 默认 | 各源定时采集、解码、发布与缓存治理；与 api 共享数据卷 |
| 前端开发服务 | 开发模式 | Vite 热更新，代理 /api 到 FastAPI |

`.env` 建议值（详见 `.env.example` 与 `config/defaults.toml`）：

~~~dotenv
EARTHSIM_DATA_MODE=live
EARTHSIM_HTTP_PORT=8080
EARTHSIM_UI_TIMEZONE=local
EARTHSIM_STORAGE_ROOT=/data
EARTHSIM_GFS_POLL_SECONDS=900
EARTHSIM_GFS_MAX_LEAD_HOURS=36
EARTHSIM_METAR_POLL_SECONDS=300
EARTHSIM_REALTIME_POLL_SECONDS=180
EARTHSIM_DERIVED_CACHE_GIB=12
EARTHSIM_MIN_FREE_DISK_GIB=8
~~~

`live` 为默认（README 与 .env.example）；`fixture` 全离线并标「演示」。
修改 `.env` 后 `docker compose up -d` 重建受影响容器；数据卷 `earth_data` 保留。

### 6.3 命令入口

~~~bash
# 本机（仓库根目录）
cp .env.example .env
python -m earthsim.cli doctor
python -m earthsim.cli fixtures install
python -m earthsim.cli fixtures verify
python -m uvicorn earthsim.api.app:app --host 127.0.0.1 --port 8080   # 在 backend/ 下

# Docker Compose
docker compose config
docker compose up -d --build
curl -fsS http://localhost:8080/api/v1/health
docker compose exec ingest-worker python -m earthsim.cli sources probe
docker compose exec ingest-worker python -m earthsim.cli sources refresh --source noaa_gfs
docker compose exec ingest-worker python -m earthsim.cli sources refresh --source awc_metar
docker compose exec ingest-worker python -m earthsim.cli sources refresh --source gfs_volume
docker compose exec ingest-worker python -m earthsim.cli sources refresh --source ecmwf_ifs
docker compose exec ingest-worker python -m earthsim.cli sources refresh --source realtime_all
docker compose ps
docker compose logs -f ingest-worker

# 前端
cd apps/web && npm install && npm run dev        # 5173，/api 代理到 8080
cd apps/web && npm run build                     # dist 由 FastAPI 同源托管
~~~

`catalog cleanup --dry-run` 先列出清理目标与预计释放空间；活动批次受保护。

### 6.4 操作诊断表

| 表现 | 先看 | 处理信息 |
|---|---|---|
| 地球加载、天气无数据 | 显示模式、sources 状态、活动快照 | fixture 是否已安装；是否等待采集；最近成功时间 |
| GFS 最近周期 404 | 候选周期、目录、lead hour | 未发布或路径错误；退回上一可用批次 |
| 上游 429/503 | 源状态、Retry-After、在途任务数 | 退避时间，合并刷新任务，缓存仍可用 |
| 站点为空/过期 | 站点列表、报告时刻、204 | 核对 ICAO 与报告频率，标出最近历史观测 |
| 颜色/位置/风向异常 | 解码坐标、反经线、UV、点查来向 | 用测试点与已知向量核验 |
| 实时事件不显示 | `/api/v1/realtime/summary`、对应源状态 | 上游可达性与 freshness 阈值；60s 轮询是否执行 |
| 3D 体积云不显示 | WebGL2 支持、云密度开关/滑块、图层帧 | 只为 RH 代理，切回 `cloud_volume` 图层 |

---

## 7. 测试与验证

### 7.1 测试分层

| 层级 | 典型用例 | 通过依据 |
|---|---|---|
| 单元 | UTC 起报边界、格网方向、坐标归一化、单位、矢量方向、样点缺测、能见度下界 | 固定输入得到可重复数值与质量标记 |
| 源契约 | GRIB 样本、METAR JSON、实时事件 JSON、异常响应、过期数据 | 能定位字段、网格、时间；可容错停更 |
| 服务集成 | 替换活动快照、在下载与发布之间重启、限流、缓存清理、重复刷新 | 同一资产只处理一次，活动快照始终可读 |
| E2E | 离线开机、选图层、拖时间、点选取值、图层切换反馈 | 界面、API 和数据源标注一致 |
| 在线冒烟 | 真实 GFS / IFS / HRRR / METAR / 实时事件至少一条样本 | 信息正确、时间可追踪 |

故障注入覆盖：网络超时、响应是 HTML 而非目标文件、下载中断、同批次重复发布、
候选批次部分就绪、断网、进程退出与恢复、低磁盘、异常时间戳、图层切换后色带与时间更新。
日常 CI 使用固定样本；真实上游冒烟显式启动，避免把上游停机混同为代码回归。

### 7.2 当前验证结果（2026-11-24）

- 后端：`EARTHSIM_DATA_MODE=fixture python -m pytest -q` → **36 passed**。
- 前端：`npm test -- --run` → **19 passed**；`npm run build` 通过（vue-tsc + vite）。
- Fixture 校验：`python -m earthsim.cli fixtures verify` → 全部资产校验通过。
- 在线 API：`/api/v1/health` ok，`/api/v1/layers` 返回 20 个 forecast 图层；
  `/api/v1/simulation/*` 返回 404（确认已移除）。
- 浏览器实测：顶部仅「看预报」；右侧无 tab；时间轴无模式按钮；20 个全球预报图层；
  快速切换图层与实时事件开关无 JS 错误。

逐条验收记录与截图见 [docs/acceptance.md](docs/acceptance.md)。

### 7.3 性能目标

- 有缓存时打开页面到可交互地球目标 ≤ 3 秒（冷/热缓存各测一次）。
- 基准机器稳定浏览中位帧率 ≥ 30 FPS；无硬件加速时自动减粒子/降纹理/关高成本效果。
- 本地已缓存点查 P95 ≤ 150 ms。
- 连续切换 50 次时间帧后内存与 GPU 资源稳定；慢网络执行请求取消与可见加载状态。

---

## 8. 给 Codex 的实施与维护要求

本仓库已完成当前产品的实现。后续 Codex 任务应**在现有代码上增量修改**，不要重新引入
已移除的功能（区域模拟 WPS/WRF、卫星云图图层、看现在/算这个区域入口）。

- 先检查当前仓库、运行环境与现有代码，再动手；以可复跑命令验证数据契约，再改上层 UI。
- 保持三层链路正常：① 真实/样本数据 → 采集解码 → 目录发布 → 缓存回放；
  ② 目录 → API → 三维地球、时间轴、点位查询；③ 实时事件/空间天气 → 前端 Shadertoy 风格呈现。
- 任何新数据源都要有独立 source_id、字段清单、单位/坐标口径、freshness 阈值与测试样本；
  任何新图层都要在 `LAYER_INFO` 与 `palettes.ts` 登记单位/色带/显示范围。
- 零值透明、坐标方向（南→北、lon0=-180）、bbox 注入、图层切换清空旧图层等已修复的约束
  必须保持；新增渲染路径需沿用同样的正确性检查。
- 每条验收项提供日志、测试或产物证据；最终交付可运行代码，而不是只给设计或空接口。

### 8.1 交付清单

- 可运行仓库：前后端、依赖锁文件、Compose、Dockerfile.app、Windows/WSL 指南。
- 可复用数据源适配器、时间/空间数据契约、SQLite 迁移与可追溯资产、断网缓存。
- 可交互地球、时间轴、图层与点查；真实数据与演示状态清楚可见。
- 实时事件与空间天气、3D 体积云、高分辨率 LOD 与真实昼夜。
- 自动化测试、联网验证记录、性能基线与重复运行命令。
- 与当前功能一致的 README 与 docs（本文、quickstart、data-sources、acceptance）。
