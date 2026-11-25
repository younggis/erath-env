# 验收矩阵与实测证据

核对日期 2026-11-24。本产品为**全球预报 + 实时事件的三维地球天气工作台**。
早期设想的区域物理模拟（WPS/WRF）与卫星云图图层（Himawari / GOES）已按要求移除，
相关验收项不再适用，本章节只记录当前功能的验证状态。
历史 bug 修复记录保留在文末，供回归参考。

## 1. 当前验收矩阵

| 编号 | 验收项 | 状态 | 证据 |
|---|---|---|---|
| AC-01 | 全新环境启动 | 通过 | Quick Start 可执行；`GET /api/v1/health` 返回 ok；浏览器显示「● 在线」+ 风场 + 时间轴 + 定位栏（`docs/shots/01-home.png`） |
| AC-02 | 获取真实 GFS | 通过 | 真实批次解码发布；东京点查 u=4.11 m/s、temp2m 291.66K→18.51°C；字段扩展至 12+ 类 |
| AC-03 | 批次更新与回退 | 通过 | 不完整候选不切活动快照；旧 init 不覆盖新批次；补齐后单事务切换（`tests/test_catalog.py`） |
| AC-04 | 点位查询与地球格网 | 通过 | `tests/test_fields.py` + 前端 `earth.test.ts`；已知样点数值在容差内；跨 180° 连续；缺测点提示正确 |
| AC-05 | 持久缓存与回放 | 通过 | 资产校验与 SHA-256 一致；已发布批次可回放；前端 LRU 淘汰；CLI cleanup 保护活动批次 |
| AC-06 | 图层与数据源标注 | 通过 | 20 个 forecast 图层；来源新鲜度（live/stale/missing + age）在左侧显示 |
| EXT-01 | ECMWF IFS 模式对比 | 通过 | 95MB 已下载解码发布；15 个 surface 字段在线验证；云量分数→% 修正、f000 全零累积字段跳过 |
| EXT-02 | 3D 体积云 | 通过 | GFS 6 层 RH → 360×181×6 体数据；WebGL2 raymarching；4 时效；密度滑块生效；诚实标注「非真实云水」（`volume-cloud.png`） |
| EXT-03 | HRRR 高分辨率 LOD | 通过 | 3km CONUS 区域场重建经纬度并以 bbox 贴片叠加；放大到美国显示「◆ 高分辨率数据 3 km」（`coord-hrrr-us.png`、`diag-lod-hrrr.png`） |
| EXT-04 | 实时事件 / 空间天气 | 通过 | 6 源全部 200 可达并解码发布：地震 / 航班 / 气旋 / CME / 极光 / 太阳风；前端开关 + 60s 刷新（`diag-realtime-events.png`） |
| EXT-05 | 机场观测 METAR | 通过 | AWC 真实 JSON 归一化；约 60 个机场；VRB / 静风 / 删失能见度 / 缺字段处理；站点端点过滤非站点事件 |
| EXT-06 | 真实昼夜与地球视觉 | 通过 | 太阳方向按真实 UTC 每帧计算；春分/夏至/冬至直射点验证通过；NASA Black Marble 夜间灯光；Esri 高清瓦片贴地 z14 ≈ 7.8 m/像素（`07-county-zoom.png`） |
| EXT-07 | 全球灾害事件与轨迹 | 通过 | GDACS/EONET/FIRMS 适配器 + 去重入库；实测 `gdacs=6`、`eonet=29`、`firms=0`（未配 MAP_KEY）；前端 3 个开关与事件详情生效；浏览器无 JS 错误（`disasters-check.png`） |
| EXT-08 | 渲染基础与画质档 | 通过 | EffectComposer 4× MSAA；关闭 Bloom 仍正常出图（`bloom-off-check.png`）；3 秒 FPS EMA + 26/45fps 迟滞自动降/升画质，7 项画质策略单测通过 |
| EXT-09 | GFS-Wave 全球海浪 | 通过 | NOMADS 0.25° 三层字段 1.8MB/时效实测下载解码；发布 4 图层 × 4 时效；波高驱动海面高光/泡沫，波向驱动粒子；浏览器验证 24 图层、无 JS 错误（`wave-ocean-check.png`） |
| EXT-10 | 体积云与大气质感 | 通过 | 体积云加入蓝噪声抖动、自适应步数、向光自阴影、HG 前向散射；大气边缘加入臭氧与 Mie 前向散射；浏览器切换 `cloud_volume` 验证无 JS 错误（`cloud-v2-check.png`） |
| EXT-11 | OISST 全球日海温 | 通过 | NCEI ERDDAP 1MB NetCDF3 实测下载解码；滚转经度、掩膜哨兵并发布 `sst` 图层；浏览器验证（当时 25 图层，现为 30）、观测时刻 2026-11-07、无 JS 错误（`oisst-check.png`）；上游约两周滞后已标注 |
| EXT-12 | CAMS 全球大气成分 | 部分（上游限流） | 适配器、5° 采样、格网解码、3 图层注册与缓存机制通过单元测试；本机 Open-Meteo IP 配额触发 429，真实发布待配额恢复/目标机复跑；明确标注为 CAMS 0.4° 的 5° 降采样 |
| EXT-13 | GEFS 集合不确定性 | 通过 | `geavg`/`gespr` 0.5° 子集实测下载解码；5 图层 × 3 时效发布；概率图层明确为高斯近似；浏览器验证 30 图层、无 JS 错误（`gefs-prob-check.png`） |
| EXT-14 | GPU 风场粒子 | 通过 | WebGL2 + `EXT_color_buffer_float` ping-pong 状态纹理，CPU 不再逐帧遍历粒子；GLSL 短拖尾粒子按风速着色；开关切换 CPU/GPU 互斥可见；浏览器实测 `supported=true`、默认 16000 粒子 160+ FPS、双帧画面差分确认粒子持续运动、关闭后回退 CPU（上限 8000），无 JS 错误（`gpu-wind-check.png`、`motion-diff.png`） |
| EXT-15 | 风场拖尾光带 | 通过 | 粒子状态累积到半分辨率 ping-pong 缓冲形成连续光带；背面粒子顶点剔除、相机移动时快速衰减；浏览器实测开关正常、160+ FPS、无 JS 错误（`trails-check.png`） |
| EXT-16 | 晨昏光照与电影调色 | 通过 | 晨昏金色光带+夜面对比增强；`OutputPass` 前插入暗角/轻色差/微颗粒 pass，开关实测画面差异正常；修复 `pow(负数,2.0)` 未定义行为；无 JS 错误（`cinematic-check.png`） |
| EXT-17 | 地点预报卡 | 通过 | 拾取点按当前图层全部时效并发调用 `/api/v1/sample`，详情面板绘制折线与数值表；浏览器实测 4 时效、数值与 API 一致、无 JS 错误（`forecast-card.png`） |
| AC-07 | 性能与体验 | 部分（依机器） | API P95 9.9 ms；HUD 显示 FPS/粒子/draw calls（96–116 FPS @3000 粒子）；首屏/内存目标需目标机按规格实测 |

已移除且不再适用：原 AC-07～AC-11（模拟提交、成果查看、作业恢复、观测验证、复跑）、
卫星帧配准验收项。

## 2. 验证命令与结果（2026-11-24）

```bash
# 后端（backend/ 目录）
python -m pytest -q

# 前端
cd apps/web
npm test -- --run       # 19 passed
npm run build           # 通过（vue-tsc + vite）

# 资产
python -m earthsim.cli catalog stats                       # 目录统计
```

在线 API 实测：

- `GET /api/v1/health` → `status=ok`。
- `GET /api/v1/layers` → 30 个图层，全部 `kind=forecast`，无 WRF / 卫星图层。
- `GET /api/v1/sources` → 18 个 source_id：`awc_metar`、`cams`、`ecmwf_ifs`、`eonet`、
  `gdacs`、`gfs_volume`、`nasa_cme`、`nasa_firms`、`nhc_storm`、`noaa_aurora`、`noaa_gefs`、
  `noaa_gfs`、`noaa_hrrr`、`noaa_oisst`、`noaa_solar_wind`、`noaa_wave`、`opensky`、`usgs_quake`。
- `GET /api/v1/simulation/presets` → 404（确认区域模拟端点已移除）。

浏览器实测（Playwright，无 JS 错误）：

- 顶部导航仅「看预报」；右侧无 tab（只「点位详情」）；时间轴无模式切换器。
- 左侧「全球预报」分组 30 个图层；实时事件、体积云、视觉特效、GPU 粒子流开关齐全。
- 快速切换图层与实时事件开关，数据加载与 toast 提示正常。

## 3. 坐标与数据正确性修复（历史记录，需回归保持）

1. **纬度上下颠倒**：GFS/IFS 的 GRIB 原生为北→南（第 0 行=90°N），项目契约与球面纹理为南→北（第 0 行=−90°）。解码增加 `np.flipud`。
2. **经度 180° 偏移**：GRIB 0–360 滚转为 −180–180 后网格元数据仍声明 `lon0=0`。统一改为 `lon0=-180`；IFS 去掉多余的 roll。
3. **区域场被拉伸到全球**：HRRR 497×349 美国区域网格走独立 `setRegionField()` bbox 贴片路径。
   `GET /api/v1/frames/{id}` 必须把 frame 的 bbox 归一化注入 manifest，否则前端会回退全球范围导致严重错位。
4. **旧进程污染**：修复后仍在运行的旧 uvicorn 进程用旧方向发布新批次，已重启服务并对新发布的 53 帧再次原地修复。
5. **雪深哨兵**：`snow_depth` 的 9999 是缺测值，曾显示 10000m 亮斑，现掩膜为 NaN。
6. **全零累积字段**：`ifs_tp`/`ifs_ssrd` 在 f000 恒为 0，发布后为空图层，解码阶段跳过。
7. **降水单位与色标**：APCP 实为 kg/m²（=mm），改为 mm 声明；因 99% < 6mm 的分布，色标改为对数（log floor 0.05mm）+ 显示范围 0–12mm，ITCZ 雨带等清晰可见。
8. **零值透明治理**：`precip`、`snow`、`cloud`、`wind`、`vvel` 等「0=无物」量加 alpha 渐变，避免无值区遮盖底图；`cloudwater` 本就透明；全幅背景场（温度/湿度/气压/位势高度/CAPE）保持全幅显示。
9. **wind 透明度滑块失效**：硬编码 opacity 改为统一 `store.state.layerOpacity`，滑块对所有图层生效。
10. **图层切换不刷新**：`activeLayerId` watch 立即清空旧图层并显示 loading；用显式 `frameDataRev` 计数器替代不可靠的 cache.size watch；居中 toast（spinner→✓→淡出）。快速连切与切回缓存图层均正确。
11. **worker 从未运行**：信号处理器 `def _stop` 覆盖布尔标志导致 `while not _stop` 恒假，已改名 `_handle_stop`；后台采集正常运行。
12. **慢源阻塞快源**：改为线程池 fire-and-forget + `_inflight` 去重，慢源不阻塞调度循环。
13. **实时源 freshness 阈值**：按源分级（地震/航班 15min、极光/太阳风 30min、气旋 6h、CME 12h）。
14. **体积云单帧**：新增 `volume_lead_max_hours=3`，生成 f000–f003 共 4 帧。
15. **站点端点污染**：显式过滤 `source_id=awc_metar`，避免点事件被当作站点渲染。
16. **时区 bug**：`mark_success/mark_failure` 改用带时区 UTC 时间，避免 naive UTC 被当本地时间偏移 8h。

## 4. 遗留与边界（诚实声明）

1. 真实 Copernicus DEM 瓦片未在本机下载验证；适配器与单元测试已覆盖，真实瓦片待目标机。
2. 性能目标（首屏 ≤3s、中位帧率 ≥30 FPS、点查 P95 ≤150ms）需在目标机按实际规格实测；无硬件加速时应自动降级。
3. HRRR 仅覆盖美国本土；其他地区仍为 25km GFS。放大不会凭空产生更细的真实观测。
4. 3D 体积云是多层相对湿度的可视化代理，**不是真实云水含量**，不做定量解释。
5. 卫星资料与区域数值模拟已移除，相关历史截图/记录不代表当前功能。
