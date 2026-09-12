# 轮对超声环形读数判读台

这是一个从零实现的 React + FastAPI 联调项目，用于复核轮对超声检测仪导出的 360 条环形采样。核心目标是避免跨越 0° 的同一处损伤被拆成两段后重复计数。

## 判读规则

- 输入必须包含恰好 **360 条采样**。
- `samples[*].angle` 必须是互不重复的整数，且范围为 `0..359`。
- `samples[*].amplitude` 是非负有限数字，单位毫米。
- `threshold` 由用户提供，必须是非负有限数字。
- 幅值 **大于或等于** 阈值即为缺陷点。
- 相邻整数角度属于同一连续区段；`359°` 与 `0°` 也相邻。
- 非全圆区段的起点是沿顺时针方向在缺口后遇到的首个缺陷角；例如 `358,359,0,1` 的起点是 `358`，终点是 `1`。
- 区段跨度按包含的采样点数计算。
- 峰值取段内最大幅值；峰值并列时取最小角度。
- 当 360 点全部超限时，唯一结果固定为：起点 `0`、终点 `359`、跨度 `360`。

页面默认载入跨零度样例：`357°..359°` 与 `0°..2°` 均超限。计算结果只有一个连续区段，起点 `357°`、终点 `2°`、跨度 `6`，可从原始读数逐项复算。

## 技术栈

- Python 3.12
- FastAPI
- React + TypeScript
- Vite
- pytest / httpx
- Docker Compose

## 一键真实联调验收

```bash
WEB_PORT=8080 API_PORT=8000 docker compose run --build verify
```

`verify` 是一次性验收服务：它等待 API 与 Web 健康检查通过后，在 Compose 网络内执行单元/接口测试与真实 HTTP 联调，结束后退出，不作为长期服务运行。

也可以先构建并启动：

```bash
docker compose up --build api web
```

然后打开：

- Web：`http://localhost:${WEB_PORT:-8080}`
- API：`http://localhost:${API_PORT:-8000}`
- OpenAPI 文档：`http://localhost:${API_PORT:-8000}/docs`

宿主端口可由环境变量覆盖：

```bash
WEB_PORT=18080 API_PORT=18000 docker compose up --build
```

## API

### `POST /api/readings/analyze`

请求：

```json
{
  "threshold": 2.5,
  "samples": [
    { "angle": 0, "amplitude": 4.8 },
    { "angle": 1, "amplitude": 3.2 }
  ]
}
```

成功响应中的每个区段：

```json
{
  "startAngle": 357,
  "endAngle": 2,
  "span": 6,
  "peakAngle": 0,
  "peakAmplitude": 4.8,
  "angles": [357, 358, 359, 0, 1, 2]
}
```

非法输入返回 HTTP 422，例如：

```json
{
  "errors": [
    { "field": "samples[12].angle", "message": "角度 7 重复，0 至 359 每个角度只能出现一次" },
    { "field": "samples[30].amplitude", "message": "amplitude 必须是非负数" }
  ]
}
```

后端会定位缺失、重复、越界、非整数、非法幅值和非法阈值字段；前端收到校验错误时会清空本次结果和图形高亮。

## 本地开发

创建 Python 虚拟环境：

```bash
python3.12 -m venv .venv
. .venv/bin/activate
pip install -r backend/requirements.txt
pip install -r requirements.txt
uvicorn app.main:app --reload --app-dir backend
```

启动前端：

```bash
npm install
npm run dev
```

Vite 将 `/api` 代理到 `http://localhost:8000`；也可用 `VITE_API_PROXY_TARGET` 覆盖。

运行测试：

```bash
pytest -q
npm run typecheck
npm run build
```

默认 pytest 会执行核心算法和 FastAPI 测试；跨容器的实时验收测试由 Compose 的 `verify` 服务设置 `VERIFY_LIVE=1` 后运行。

## 项目结构

```text
backend/            FastAPI 与环形分段核心算法
src/                React 页面与 360° SVG 采样环
tests/              核心边界、接口和实时联调验收测试
docker-compose.yml  api、web 与一次性 verify 服务
verify.Dockerfile   Python 3.12 验收镜像
web.Dockerfile      Node/Vite Web 镜像
```
