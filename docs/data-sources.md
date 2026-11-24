# 数据来源与验证记录

核对日期 2026-11-24。本文记录每个当前接入来源的实际访问结果、样本标识、字段、许可与复跑命令。
凡未在本机实测的项明确标为「待验证」，不以设计意图代替实测。

> 卫星云图（Himawari-9 / GOES-19）与区域数值模拟（WPS/WRF）已按用户要求移除，
> 不再是数据来源；相关适配器、数据集与磁盘数据均已删除。

## 通用复跑方式

```bash
# 仓库根目录（Windows 本机）
python scripts/probe_live.py            # 上游连通性与实际 HTTP 状态
python -m earthsim.cli sources probe    # 经适配器的探测
python -m earthsim.cli sources refresh --source noaa_gfs
python -m earthsim.cli sources refresh --source awc_metar
python -m earthsim.cli fixtures install && python -m earthsim.cli fixtures verify
```

`EARTHSIM_DATA_MODE=fixture` 时不访问网络；`live` 时才由 API/CLI/worker 触发采集。

## 1. NOAA GFS 0.25°（核心全球预报）

- 官方入口：<https://nomads.ncep.noaa.gov/>；产品清单：<https://www.nco.ncep.noaa.gov/pmb/products/gfs/nomads/>；公开镜像：<https://registry.opendata.aws/noaa-gfs-pds/>
- 实测：NOMADS GRIB Filter 对 00/06/12/18Z 候选起报返回 200，`application/octet-stream`；适配器用 NOMADS GET 探测（早期 S3 HEAD 在本机不可靠）。
- 请求示例：`dir=/gfs.YYYYMMDD/CC/atmos`，`file=gfs.tCCz.pgrb2.0p25.f003`，`lev_10_m_above_ground=on`，`var_UGRD=on`，`var_VGRD=on`。
- 字段契约：`wind10`(10u/10v)、`temp2m`(2t)、`rh2m`(2r)、`dewpoint2m`(2d)、`mslp`(prmsl)、
  `visibility_sfc`(vis)、`precip`(tp，单位 mm)、`cape`、`cin`、`gh500`/`vvel500`(gh/w @500hPa)、
  `snow_depth`(sde，9999 为缺测哨兵)、`surface_pressure`(sp)。
  `cloud_total` **不再从 TCDC 提取**——NOMADS 对 `var_TCDC` 返回地表气温（paramId 130），
  会误标；仅当显式的 `tcc`@atmosphere 消息出现时才发布。
- 下载按字段组拆为两个 staged 文件：`filter.grib2`（core 约 13MB：风/温/湿/露点/气压/能见度/降水/CAPE/500hPa 高度与垂直速度）与 `filter-extra.grib2`（extra 约 2MB：雪深/地面气压/CIN）——组合所有字段的单次请求在本机/上游会挂起，拆分后各自可下载。
- 实测 `sources refresh --source noaa_gfs`（设 `EARTHSIM_GFS_MAX_LEAD_HOURS=3`）在 18Z 起报批次上取得 0–3h 共 24 帧并发布；点查示例：东京 (139.7°E,35.5°N) f001 `wind10.u=4.1063 m/s`、`temp2m=291.6557 K → 18.51 °C`。
- 坐标修复：GRIB 原生北→南、经度 0–360；解码时 `np.flipud` 并滚转为 −180–180，发布网格元数据统一 `lon0=-180, lat0=-90`（详见 acceptance.md）。历史上曾被旧进程用错误方向重新发布 53 帧，已重启服务并原地修复。
- 状态：**真实解码与发布已验证**；完整 0–36h 逐小时批次按默认配置在目标机可复跑。

## 1b. ECMWF IFS 开放数据（已验证）

- 入口：[ECMWF Open Data](https://www.ecmwf.int/en/forecasts/datasets/open-data)，CC-BY-4.0。AWS S3 镜像 `ecmwf-forecasts.s3.eu-central-1.amazonaws.com`，路径 `YYYYMMDD/HHz/ifs/0p25/oper/YYYYMMDDHHMMSS-0h-oper-fc.grib2`（00/06/12/18Z，约 98MB/文件）。
- 适配器 `ingest/ifs.py` 用 ecCodes 解码 f000 surface 字段并发布为独立 `ecmwf-ifs` 数据集。
- 发布字段：2m 气温/露点、海平面气压、10m/100m 风分量、总/低/中/高云量、累计降水、雪深、整层水汽、向下短波辐射。
- 处理要点：ECMWF 云量为 0–1 分数，发布时 ×100 转 %；f000 起报时刻累积量（降水/短波辐射）恒为 0，解码阶段跳过全零累积字段。
- 下载：S3 文件较大，采用分块流式下载 + Range 断点续传（写 `.part`），失败保留上一批。
- 状态：**95MB 数据已下载、解码并发布，15 个字段在线验证通过**。可发布图层 ID：
  `ifs_2t`、`ifs_2d`、`ifs_msl`、`ifs_10u`、`ifs_10v`、`ifs_tcc`、`ifs_lcc`、`ifs_mcc`、
  `ifs_hcc`、`ifs_tp`（跳过 f000 全零）、`ifs_sd`、`ifs_tcwv`、`ifs_ssrd`、
  `ifs_100u`、`ifs_100v`；当前 live 清单中按已发布快照展示其中一部分。

## 1c. GFS 3D 体积云（多层湿度代理）

- 适配器 `ingest/volume.py`：一次 GRIB Filter 请求下载 6 个等压面相对湿度
  （1000/925/850/700/600/500 hPa，`r`@isobaricInhPa，约 5MB / 7s），ecCodes 解码后按
  `RH>70%` 映射为云密度，降采样为 `360×181×6` 的 xyz 布局 float32 体数据（约 1.5MB），
  发布为独立数据集 `gfs-volume`。
- 实测 ITCZ 探空剖面（925hPa RH 94% / 500hPa RH 5%）符合「低层湿深层干」结构。
- **诚实声明**：这是基于相对湿度的**可视化代理**，不是真实云水含量；UI 明确标注，无数值色标。
- 渲染 `render/volume.ts`：Three.js `Data3DTexture` + WebGL2 GLSL3 raymarching，带太阳方向明暗；
  左侧「3D 体积云显示」开关与云密度滑块；切换到其它图层自动隐藏。
- 时效：`volume_lead_max_hours=3` 生成 f000–f003 共 4 帧，单时效失败时发布已完成前缀。

## 1d. 实时事件与空间天气

统一适配器 `ingest/realtime.py`，点事件存入 `observations` 表（source_id 区分），场/时间序列写入
`data_root/realtime/*.json`。API：`/api/v1/realtime/events|aurora|solar-wind|summary`。
前端每 60s 轮询，全部为真实上游数据，无合成。

| 数据 | 上游（免费/无需密钥） | 实测 | 视觉 |
|---|---|---|---|
| 地震 | USGS `all_hour.geojson` | 200 / 5–24KB / 1–3s | 扩散冲击波环，按震级着色 |
| 航班 | OpenSky `/states/all` | 200 / 1.3MB / 25s，限流 6000 架 | 航向拖尾，按高度着色 |
| 热带气旋 | NOAA NHC `CurrentStorms.json` | 200（当前无活跃风暴） | 旋转螺旋云系 |
| 日冕物质抛射 | NASA DONKI CME（DEMO_KEY） | 200 / 9KB / 7s | 扩张等离子体云 |
| 极光概率 | NOAA SWPC OVATION | 200 / 918KB / 3s，360×181 网格 | 极区流动绿紫光幕，随 Kp 增强 |
| 太阳风 / Bz / Kp | NOAA SWPC RTSW + IMF | 200 / 3MB / 4.5s | 日照侧粒子流，Bz<0 向极区汇聚 |

实时源 freshness 按源分级：地震/航班 15min、极光/太阳风 30min、气旋 6h、CME 12h。
站点端点显式过滤 `source_id=awc_metar`，避免点事件被当作站点渲染。

## 2. NOAA AWC METAR（机场观测）

- 官方 API：<https://aviationweather.gov/data/api/>；端点 `GET /api/data/metar?ids=...&format=json`。
- 实测：`ids=RJTT,RJCC,RKSI,ZSPD,VHHH,WSSS` 返回 200 / 922 字节 / 2 条报告。样本保存为 `raw/metar/2026-11-20T160746.json`，SHA-256 `7053364f932ada38560fb394bfc70668737b20f75befb411145db1eb7ec8e054`。字段示例：`icaoId=RJCC`、`reportTime=...`、`temp=-1`、`dewp=-7`、`wdir=220`、`wspd=9`、`visib="6+"`、`wxString="-SHSN"`、`lat=42.774`、`lon=141.693`、`elev=19`。
- 归一化：风速节→m/s；`VRB` / 静风 `000` / 数值风向分类型编码；`>10`、`6+`、`9999` 保留下界与 qualifier；缺字段为 null；`obsTime` epoch 与 `reportTime` 均兼容。
- 状态：**真实样本已取得并可解析**；204 无报告与缺测通过测试注入覆盖。站点规模已从 6 个扩展到全球约 60 个主要机场。

## 3. 地球底图与可视化资源

- `apps/web/public/earth-day.jpg`：真实卫星影像 equirectangular 纹理，Three.js 地球底图，离线可用。来源 Solar System Scope（CC BY 4.0）。
- `apps/web/public/earth-night.jpg`：NASA Black Marble 真实夜间灯光纹理（Solar System Scope 派生，CC BY 4.0）。夜面直接使用真实灯光，非程序化噪声。
- 太阳位置：`render/sunpos.ts` 用 NOAA 低精度算法按 UTC 实时计算太阳赤纬和时差，推导太阳直射点，每帧更新 shader `uSunDir`。验证：春分直射 0.0°/-4.1°、夏至 23.44°N、冬至 -23.43°S；与浏览器 UTC 同步。
- **高清卫星瓦片**：`render/tiles.ts` 双层 LOD（context + detail），动态加载 NOAA Esri World Imagery Web-Mercator 瓦片；实测 z8–z18 可用，贴地 z14 ≈ 7.8 m/像素，可见城市街区/道路/码头。并发限 3、内存 LRU、边缘 feather。署名：Esri, Maxar, Earthstar Geographics。
- **数据 LOD**：全球默认 GFS 0.25°（25km）；`ingest/hrrr.py` 接入 NOAA **HRRR CONUS 3km** 区域模式，NOMADS `filter_hrrr_sub.pl` 按区域取 10m U/V 子集（约 1.8MB），ecCodes 解码后用 pyproj Lambert Conformal 重建经纬度，scipy griddata 重采样为 0.05°（约 5km）规则 4326 格网。视角进入 HRRR 域（−102..−74 / 32..52）且缩放足够近时自动叠加 3km 数据场（边缘 feather），右上角提示「◆ 高分辨率数据 3 km」。限制：HRRR 仅覆盖美国本土，其他地区仍为 25km GFS；放大不会凭空产生更细的真实观测。
- **数据显示密度**：实时 GFS 格网 1441×721（约 104 万格点），首屏默认以连续风速色带（palette wind，0–35 m/s）覆盖全球，叠加 8000 条风粒子流线；左侧「数据显示 (色带)」可关闭色带只看底图。站点标记用 shader 脉冲光环，按温度着色（冷青→暖橙）；站点查询取各站最新观测，不再与预报有效时刻配对。
- 风场图层只显示粒子流场，不用不透明纯色场覆盖底图；标量场以 0.5 不透明度叠加。

## 4. Natural Earth 110m 陆地

- 来源：<https://www.naturalearthdata.com/downloads/110m-physical-vectors/110m-land/>（公共领域），GeoJSON 取自 nvkelso/natural-earth-vector 镜像。
- 本地文件：`apps/web/public/land110m.json`（138160 字节），构建时复制到 `dist/`，由 `/land110m.json` 路由交付。作为卫星纹理不可用时的回退底图，并用于 WGS84 经纬到 ECEF 的主轴/UV 约定测试。

## 5. Copernicus DEM GLO-30（局部地形）

- 来源：<https://registry.opendata.aws/copernicus-dem/>、<https://dataspace.copernicus.eu/>
- 适配器实现 `tile_key/tile_url` 与 GeoTIFF 元数据读取（CRS、NoData、像元尺寸、垂直基准 EGM96、角点范围）；本机 rasterio 1.4.3 可用。
- 离线样本：`raw/topography/fixture/fixture-dem-alps.bin` + `.json`（合成山谷，含 NoData 哨兵），SHA-256（bin）`ed167068942d0d39e24896bbef0e661cd5ec8b1e3eb1e22ee58e55bc93c9a314`。
- 状态：真实 DEM 瓦片待在目标机验证；fixture 已闭环（注册为可查询的 `terrain` 帧，前端用独立地形层渲染）。

## 6. M0 固定样本校验和

| sample_id | 路径（相对数据根） | 字节 | SHA-256 |
|---|---|---:|---|
| fixture-gfs-wind10-t03 | derived/fixture-gfs-20261120T0000Z/fixture-wind10-t03.bin | 131768 | `15f9b13a0ac8841a0b741662e4cfdaf1a549b6c69e4eee167cfce7bf17b41d08` |
| fixture-gfs-temp2m-t00 | derived/fixture-gfs-20261120T0000Z/fixture-temp2m-t00.bin | 65884 | `6fd4f621edd03f0ebe1ae6da19c7d8f556240d21af34276bcace82a92b45bdef` |
| fixture-metar-batch | raw/metar/fixture-metar-20261120T0000Z.json | 16880 | `17ff7427070f3eb2f4d9c822ae641e14f0b39879021f732b06ac29cb20027d93` |
| fixture-dem-alps | raw/topography/fixture/fixture-dem-alps.bin | 16384 | `ed167068942d0d39e24896bbef0e661cd5ec8b1e3eb1e22ee58e55bc93c9a314` |
| live-metar-20261120T1607 | raw/metar/2026-11-20T160746.json | 922 | `7053364f932ada38560fb394bfc70668737b20f75befb411145db1eb7ec8e054` |
| live-gfs-wind10-f001 | derived/noaa-gfs-20261120T1800Z/noaa-gfs-20261120T1800Z-wind10-f001.bin | 8311688 | `69192238837a6436c9ad6b9f66aa9fb197add9c3f08f9b21f0924981238214df` |

（`fixture-himawari-b13-00` 已随卫星图层移除。）

所有 fixture 由固定解析函数生成，可通过 `python -m earthsim.cli fixtures install` 完全重建；
`fixtures verify` 校验目录登记的每个资产校验和与长度（当前校验全部通过）。
