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

## 可选基线补偿

现场复核时探头与轮辋耦合会形成稳定的角度底噪。检修员可随采样一并提交 `baseline` 数组做逐点补偿：

- `baseline` 为可选字段；一旦提交，必须恰好包含 **360 条**，`baseline[*].angle` 为 `0..359` 内互不重复的整数，`baseline[*].value` 为非负有限数字。
- 校验层按角度把基线与采样配对；核心算法以 `max(0, 原幅值 - 基线)` 参与阈值比较、跨零合段和峰值判定。减法按提交字面值做**精确十进制运算**（不以二进制浮点或粗粒度舍入处理），因此即使校正值仅高出阈值不到 `1e-9` 也会形成区段，而真正低于阈值的微小差值不会误报。
- 提交基线后，响应附带 `baselineApplied: true`、逐点 `points`（原幅值、基线、校正幅值），区段额外返回 `peakRawAmplitude` 与 `peakBaseline`，`peakAmplitude` 为校正峰值。
- 不提交 `baseline` 的旧载荷完全按原算法返回原有字段（`baselineApplied: false`，无 `points`）。
- 基线缺失角度、重复角度或非法数值会定位到 `baseline` / `baseline[i].angle` / `baseline[i].value` 字段并返回 422，前端清空本次结果与高亮。

页面默认载入带基线的跨零度样例：`357°..359°` 与 `0°..2°` 的校正幅值均超限。计算结果只有一个连续区段，起点 `357°`、终点 `2°`、跨度 `6`，峰值角 `0°` 的原幅值 `5.1`、基线 `0.3`、校正幅值 `4.8`，可从响应的逐点 `points` 逐项复算。

## 零位角度偏移

现场复核发现编码器零位与轮辋标记错位时，检修员可在判读页的“零位角度偏移”字段填写**整数角度偏移**（`angleOffset`，范围 `-359..359`，留空即不校正），随原始采样与可选基线一次提交，使采样环、区段起止角和峰值角统一落到现场标记坐标。

- 补偿顺序固定为“**先配对基线、计算校正幅值，再整体旋转角度**”：基线始终按原始（来源）角度与采样配对，不会跟随展示坐标错配；随后以 `展示角 = (来源角 + 偏移) mod 360` 做零至三百五十九度环形归一化，再进入现有分段算法。
- 跨零合段、峰值取值与“峰值并列取最小角”规则保持原语义，只是在展示坐标上执行；因此跨零缺陷可在偏移后变为普通连续区段（如来源 `357..2` 在 `+5` 偏移后成为 `2..7`），全圆结果仍固定为 `0..359`。
- 提交非零偏移后，区段的 `startAngle` / `endAngle` / `peakAngle` / `angles` 均为展示角，并额外返回 `sourceStartAngle` / `sourceEndAngle` / `sourcePeakAngle` / `sourceAngles` 映射回来源角；顶层回显 `angleOffset`。带基线时逐点 `points` 同样以展示角 `angle` 按 0°–359° 顺序排列并附 `sourceAngle`，可逐项复算“基线按来源角配对”。
- 偏移不是整数或超出 `-359..359` 时，422 错误只定位到 `angleOffset` 字段，页面清空结果与高亮。
- 省略 `angleOffset`（或显式传 `0` / `null`）的旧请求与当前版本完全一致：不返回任何 `source*` / `angleOffset` 字段，区段数据逐字段相等。
- 页面上修改偏移后旧结果与环形高亮**立即隐藏**，直到重新提交成功才恢复；结果表与采样环使用展示角，点击区段可在峰值明细与弧/点提示中查看峰值来源角。

## 声程校准

现场更换探头或耦合剂后，检修员需要先用已知厚度的参考试块校准声程。判读台顶部的“声程校准”入口打开独立的校准记录模块（不复用缺陷区段或基线补偿对象）：

- 校准记录包含 `name`（非空记录名称）、`tolerance`（允许残差，正有限数，单位 µs）和 `points`（**3 至 8 个**测点）。
- `points[*].thickness` 为试块厚度（mm），`points[*].travelTime` 为往返时间（µs），两者都必须是**正有限数**，且所有厚度**互不相同**。
- 核心按**普通最小二乘**拟合直线 `t = slope·d + zeroOffset`；拟合声速为 `2 / slope`（往返双程），零点偏移为拟合截距。
- 每个测点返回预测时间与残差；`max|残差| ≤ tolerance` 评定为**合格**，否则为**不合格**；提交评定前记录为**未评定**。
- 测点不足或超量、厚度重复、退化斜率（斜率非正有限数，无法对应物理声速）、非法容差都会定位到具体字段并返回 422，前端随即清空旧曲线与结论，记录回到未评定。
- 结果区突出最大绝对残差点（明细行与拟合曲线同步高亮），并给出逐点预测/残差明细，检修员可从返回明细复算结论。

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

请求（`baseline`、`angleOffset` 均可选）：

```json
{
  "threshold": 2.5,
  "angleOffset": 5,
  "samples": [
    { "angle": 0, "amplitude": 5.1 },
    { "angle": 1, "amplitude": 5.18 }
  ],
  "baseline": [
    { "angle": 0, "value": 0.3 },
    { "angle": 1, "value": 0.38 }
  ]
}
```

`angleOffset` 为整数角度偏移（`-359..359`）。服务端先按来源角度配对基线并以 `max(0, 原幅值 - 基线)` 计算校正幅值，再以 `(来源角 + angleOffset) mod 360` 旋转后分段。非零偏移时，区段在常规字段外额外返回展示角到来源角的映射：

```json
{
  "startAngle": 2,
  "endAngle": 7,
  "span": 6,
  "peakAngle": 2,
  "peakAmplitude": 4.8,
  "angles": [2, 3, 4, 5, 6, 7],
  "sourceStartAngle": 357,
  "sourceEndAngle": 2,
  "sourcePeakAngle": 357,
  "sourceAngles": [357, 358, 359, 0, 1, 2]
}
```

顶层在非零偏移时回显 `angleOffset`；带基线的 `points` 每项追加 `sourceAngle`，其 `angle` 为展示角。省略偏移（或 `0` / `null`）时响应不含任何 `source*` 与 `angleOffset` 字段。

成功响应中的每个区段（提交基线时附带峰值三元组）：

```json
{
  "startAngle": 357,
  "endAngle": 2,
  "span": 6,
  "peakAngle": 0,
  "peakAmplitude": 4.8,
  "peakRawAmplitude": 5.1,
  "peakBaseline": 0.3,
  "angles": [357, 358, 359, 0, 1, 2]
}
```

响应顶层同时返回 `baselineApplied` 与逐点 `points`：

```json
{
  "angle": 0,
  "amplitude": 5.1,
  "baseline": 0.3,
  "correctedAmplitude": 4.8
}
```

非法输入返回 HTTP 422，例如：

```json
{
  "errors": [
    { "field": "samples[12].angle", "message": "角度 7 重复，0 至 359 每个角度只能出现一次" },
    { "field": "samples[30].amplitude", "message": "amplitude 必须是非负数" },
    { "field": "baseline[8].value", "message": "value 必须是非负数" }
  ]
}
```

后端会定位缺失、重复、越界、非整数、非法幅值、非法阈值、非法偏移和非法基线字段；前端收到校验错误时会清空本次结果和图形高亮。

### `POST /api/calibrations/evaluate`

请求：

```json
{
  "name": "探头更换后参考试块校准",
  "tolerance": 0.1,
  "points": [
    { "thickness": 25, "travelTime": 9.1 },
    { "thickness": 50, "travelTime": 17.6 },
    { "thickness": 75, "travelTime": 26.1 },
    { "thickness": 100, "travelTime": 34.6 },
    { "thickness": 125, "travelTime": 43.1 }
  ]
}
```

成功响应（`status` 为 `pass` / `fail`，未提交评定时前端显示 `unevaluated`）：

```json
{
  "name": "探头更换后参考试块校准",
  "pointCount": 5,
  "tolerance": 0.1,
  "slope": 0.34,
  "zeroOffset": 0.6,
  "soundVelocity": 5.8824,
  "maxAbsResidual": 0.0,
  "maxResidualIndex": 0,
  "status": "pass",
  "points": [
    {
      "thickness": 25,
      "travelTime": 9.1,
      "predictedTime": 9.1,
      "residual": 0.0,
      "withinTolerance": true
    }
  ]
}
```

非法输入返回 HTTP 422，字段定位与判读接口一致，例如：

```json
{
  "errors": [
    { "field": "points", "message": "points 必须包含 3 至 8 个测点，当前为 2 个" },
    { "field": "points[0].thickness", "message": "厚度 25 重复，每个测点的厚度必须互异" },
    { "field": "tolerance", "message": "允许残差必须是正数" }
  ]
}
```

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

Vite 默认只放行 localhost 的 Host 头。Compose 网络内通过服务名访问（`http://web:5173`）时，`vite.config.ts` 已在 `server.allowedHosts` 中放行 `web`；其他主机名可用逗号分隔的 `VITE_ALLOWED_HOSTS` 追加，否则 Vite 会返回 403。

运行测试：

```bash
pytest -q
npm run typecheck
npm run build
```

默认 pytest 会执行核心算法和 FastAPI 测试；跨容器的实时验收测试由 Compose 的 `verify` 服务设置 `VERIFY_LIVE=1` 后运行。

运行 Playwright 端到端流程（本地会自动拉起 uvicorn 与 vite，需要 `npx playwright install chromium` 一次）：

```bash
npm run test:e2e
```

也可以在 Compose 网络内对 `api` + `web` 跑一次性的浏览器验收：

```bash
WEB_PORT=8080 API_PORT=8000 docker compose run --build e2e
```

## 项目结构

```text
backend/            FastAPI、环形分段核心算法与声程校准模块
src/                React 页面、360° SVG 采样环与校准拟合图
tests/              核心边界、接口和实时联调验收测试
e2e/                Playwright 声程校准流程与零位偏移验收（录入、提交、跨零段旋转、非法字段反馈）
docker-compose.yml  api、web、一次性 verify 与 e2e 服务
verify.Dockerfile   Python 3.12 验收镜像
e2e.Dockerfile      Playwright 浏览器验收镜像
web.Dockerfile      Node/Vite Web 镜像
```
