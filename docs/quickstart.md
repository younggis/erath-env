# 启动与操作手册

本产品是**本地三维地球天气工作台**：全球预报图层 + 实时事件/空间天气 + 机场观测。
默认 `live` 模式接入真实上游；`fixture` 模式全离线演示。
区域模拟（WPS/WRF）、卫星云图图层（Himawari/GOES）及对应 UI 入口已移除。

## 1. Windows 11 本机（不依赖 Docker，验证最快）

1. Python 3.11+，安装依赖：`python -m pip install -e .`（需 fastapi/uvicorn/pydantic/httpx/numpy/pytest，
   解码需 eccodes；可选 satpy/rasterio）。
2. 进入 `backend/` 后启动 API（同时托管已构建的前端静态文件）：

   ```powershell
   cd backend
   python -m earthsim.cli doctor                 # catalog 应为 ok
   python -m earthsim.cli fixtures install       # 生成并登记演示资产
   python -m earthsim.cli fixtures verify        # 校验所有资产长度与 SHA-256
   $env:EARTHSIM_DATA_MODE='fixture'             # 离线演示；改为 'live' 接入真实数据
   python -m uvicorn earthsim.api.app:app --host 127.0.0.1 --port 8080
   ```

3. 浏览器打开 <http://localhost:8080>，右上角显示「● 演示」（fixture）或「● 在线」（live）。
4. 前端热更新开发：`cd apps/web; npm install; npm run dev`，访问 5173，`/api` 自动代理到 8080；
   生产构建 `npm run build` 写入 `apps/web/dist`，由 FastAPI 同源托管。

> Windows 无 `/data` 时数据自动写入仓库下 `.local-data/`（不会写入 C:\）。

## 2. Docker Desktop / WSL 2

推荐在 WSL Linux 家目录克隆仓库，大文件与 SQLite 留在 Linux 本地卷。

```bash
cp .env.example .env          # 默认 EARTHSIM_DATA_MODE=live
docker compose config
docker compose up -d --build
docker compose ps
docker compose logs -f ingest-worker
curl -fsS http://localhost:8080/api/v1/health
```

- `api` 只绑定宿主机 `127.0.0.1:8080`，与前端静态文件同源。
- `ingest-worker` 随 api 默认启动；各源定时并发采集，慢源不阻塞其它源，同源在途任务去重。
- 修改 `.env` 后 `docker compose up -d` 重建受影响容器；数据卷 `earth_data` 保留。

## 3. 模式、刷新与数据源

- `fixture`：全离线，图层标「演示」，可断网回放最近完整批次。
- `live`：后台定时采集；可在左侧面板点「刷新 GFS / 刷新站点 / 刷新体积云」，或用 CLI：

  ```bash
  python -m earthsim.cli sources probe
  python -m earthsim.cli sources refresh --source noaa_gfs
  python -m earthsim.cli sources refresh --source awc_metar
  python -m earthsim.cli sources refresh --source gfs_volume
  python -m earthsim.cli sources refresh --source ecmwf_ifs
  python -m earthsim.cli sources refresh --source realtime_all
  ```

- 429/503 使用有界退避与 Retry-After；批次不完整只写候选，活动快照不切换。
- 新鲜度：`GET /api/v1/data-status` 给出每源 state（live/stale/missing）、fresh、age_minutes；
  界面左侧「实时数据源」列出各数据集状态与时间戳，并汇总实时事件（Kp、太阳风、Bz）。
- 实时事件开关：极光、太阳风、地震、航班、气旋、CME，数据每 60s 自动刷新。

## 4. 常见诊断

| 表现 | 处理 |
|---|---|
| 地球在、天气无数据 | 检查 `.env` 模式与 `fixtures install` 是否执行；看 `/api/v1/sources` 与活动快照 |
| GFS 最近周期 404 | `sources probe` 看候选周期；回退上一完整批次；检查 lead hour 与路径 |
| 上游 429/503 | 看 source details 的 Retry-After 与在途任务数，不要并发重复刷新 |
| 站点为空/过期 | 核对 ICAO、报告时刻与 204；看保留的最近一条历史观测 |
| 颜色/位置/风向异常 | 用已知样点与反经线核对；点查返回气象风来向，粒子箭头表示吹往方向 |
| 区域场被拉伸到全球 | 区域场（HRRR）走独立 bbox 贴片路径；确认 frame manifest 带正确 bbox |
| 实时事件不显示 | 看 `/api/v1/realtime/summary` 与对应源 freshness；确认 60s 轮询执行 |
| 3D 体积云不显示 | 需 WebGL2；确认左侧开关与云密度；该图层是 RH 代理，不是真实云水 |

## 5. 导出与清理

- 点位数值：在地球上点选任意位置，右侧「点位详情」显示图层值、单位与有效时刻；
  也可 `GET /api/v1/sample?frame_id=...&lon=...&lat=...`。
- 资产（格网二进制、PNG、体数据）通过 `/api/v1/assets/{asset_id}` 交付，带 ETag 与 immutable 缓存头。
- 清理前先 `python -m earthsim.cli catalog cleanup --dry-run`；活动批次与读取中的快照受保护。

## 6. 升级与备份

迁移由 `migrations` 表按版本顺序在启动时执行；升级保留数据卷。备份前停止写入或做一致性快照，
恢复后确认迁移版本与目录一致。

## 7. 验证命令

```bash
# 后端（backend/ 目录，fixture 模式）
$env:EARTHSIM_DATA_MODE='fixture'; python -m pytest -q     # 20 passed

# 前端
cd apps/web
npm test -- --run       # 3 passed
npm run build           # vue-tsc + vite
```

逐条验收与证据见 [acceptance.md](acceptance.md)；数据来源见 [data-sources.md](data-sources.md)。
