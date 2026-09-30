# 订单详情与物流查询

一个面向澳大利亚业务场景的前后端小型应用。它将订单行与本地 SKU 数据匹配，按 RRP 含 GST 的规则计算每笔订单金额，展示 Australia Post / StarTrack 测试环境及 TNT 国内查询结果，并根据 SKU 重量和体积估算运费。

## 需求版本依据

本项目以 `IT_Coding_Assessment_Update_v2.html`（2026 年 9 月 28 日的评审草稿）作为实现依据；原始 `2026-06-IT-Interview-in-person.pdf` 用于背景对照，`courier_testing_account.pdf` 用于快递测试账户参考。HTML 仍标记为草稿，不代表已获正式批准。

原始 PDF 的第二笔订单头为 `PO-20251202-00046`，但商品行使用 `PO-20251203-00046`；新版 HTML 已统一为后者，本项目采用后者。原始 PDF 同时说明 SKU 价格包含 GST，又要求直接汇总价格后加计 10% GST，存在重复加税的口径矛盾；新版明确 RRP 含 GST、Subtotal 不含 GST，因此本项目先除以 1.10，再计算未税行小计、Subtotal 和 GST。

## 已实现内容

- 两笔订单独立处理；第二笔订单含 StarTrack 与 TNT 两条物流记录。
- 九个真实 SKU 查询结果已保存为 `data/sku-query-result.json`，并标准化为 `data/products.json`。
- React + TypeScript + Vite 前端，使用 Tailwind CSS 与 shadcn/ui 的 Tabs、Card、Table、Badge、Alert、Button、Skeleton、Separator 组件。
- Python + FastAPI 服务，提供 `GET /api/orders` 及 `GET /api/orders/{order_no}/tracking`。
- RRP 为含 GST 价格：未税单价 = RRP / 1.10；每个未税行小计以 `ROUND_HALF_UP` 舍入至两位，Subtotal 为已舍入行小计之和，GST = Subtotal × 10%，Total = Subtotal + GST + Shipment Fee。
- Australia Post / StarTrack 仅从服务端访问测试环境；TNT 通过官方澳大利亚国内查询网页的表单和历史记录接入，展示实际返回的状态、更新时间和事件。
- 以物流分组汇总 SKU 重量和体积，计算订单运费估算并更新 Total；明细展示实际重量、体积重量、计费重量及失败原因。TNT 查询不可用时该段费用按新版要求为 A$0.00。
- 商品区域使用 `lucide-react` 的开源 Pill 图标作中性占位，不使用品牌商品图片或外部图片热链。

## 运行方式

需要 Python 3.12+ 与 Node.js 24+。

后端：

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
Copy-Item .env.example .env
# 在 .env 填入测试环境变量；未填写时应用仍可运行，物流会显示不可用。
.\.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

前端：

```powershell
cd frontend
npm install
npm run dev
```

在浏览器打开 Vite 显示的本地地址。开发服务器将 `/api` 代理给 `http://127.0.0.1:8000`。

## 数据来源和输入结构

SKU 查询网站实际表名为 `product_list`，SKU 字段为 `SKU`。`data/sku-query-result.json` 是本次查询得到的原始响应，`backend/import_skus.py` 负责将其转换为 `products.json`。

### `orders.json` 契约

文件顶层必须是订单数组。每笔订单必须包含 `order_no`（唯一非空字符串）、`order_date`（`YYYY-MM-DD` 日期字符串）、`status`、`company`、`customer`、`phone`、`email`、`shipping`、`items` 与 `shipments`。`shipping` 必须包含非空的 `address` 和 `postcode`。

```json
{
  "order_no": "PO-20251203-00046",
  "order_date": "2025-12-03",
  "status": "In Transit",
  "company": "Example Dispensary",
  "customer": "Example Customer",
  "phone": "0400 000 000",
  "email": "customer@example.au",
  "shipping": { "address": "1 Example Street, Sydney NSW 2000", "postcode": "2000" },
  "shipments": [
    { "id": "track-1", "label": "Track 1", "carrier": "startrack", "tracking_no": "2FWZ50000000" }
  ],
  "items": [
    { "sku": "EXAMPLE-SKU", "quantity": 2, "shipment_id": "track-1" }
  ]
}
```

每个商品行的 `sku` 必须是字符串，`quantity` 必须是正整数，`shipment_id` 必须精确匹配同一订单中某个 `shipments[].id`。每条物流记录的 `id`、`carrier`、`tracking_no` 必须为非空字符串，`id` 在订单内唯一；`label` 用于界面显示。`carrier` 支持 `startrack`、`auspost` 和 `tnt`：前两者走 Australia Post 测试环境，`tnt` 使用 TNT Australia 官方国内查询服务，单号必须为九位数字。

### `products.json` 契约

文件顶层必须是商品数组。每项至少包含唯一的字符串 `sku`、用于展示的 `name` 或 `description`，以及 `rrp`。`rrp` **必须是十进制字符串**，例如 `"99.00"`，表示含 GST 的澳元 RRP；不得写成 JSON 数字，避免浮点误差。`dimensions` 是来源提供的可选重量、尺寸与体积资料，供后续运费估算使用。

输入错误不会静默变成零金额：缺失 SKU、无效 RRP、非正整数数量或缺失物流关联会保留问题说明，并使该订单的金额汇总显示为无法计算；其他订单仍可处理。

### 金额对账与舍入

系统以逐行税前金额为权威计算基础：先以完整精度计算 `RRP / 1.10 × quantity`，每行用 `ROUND_HALF_UP` 舍入到分，再汇总 Subtotal，并对 `Subtotal × 10%` 用同一规则计算 GST。因此所有展示的行小计可直接加总为 Subtotal，且 `Total = Subtotal + GST + Shipment Fee`。

由于含税 RRP 是逐项输入的价格，其汇总值可能与上述逐行税前舍入后重建的含税商品金额存在差异。本次样本差异均为 A$0.01，其他订单的差异可能随行数累积，并不以 A$0.01 为上限。本样本两笔订单分别是 A$2,131.00 对 A$2,131.01、A$1,655.00 对 A$1,655.01；以上比较的是不含 Shipment Fee 的商品金额，这属于已声明的舍入结果，并非额外收费。对账时应先从 Total 中扣除 Shipment Fee，再比较含税商品金额。订单日期只表示日历日期，页面不为它附加时区或具体时刻；带明确时区偏移的物流事件时间才转换为悉尼时区；TNT 无偏移时间按下文说明保留快递当地时间。

## 物流与安全

Australia Post 密钥只从 `backend/.env` 读取，`.env` 已被忽略；仓库仅在 `.env.example` 提供变量名。前端不会接触密钥。TNT 国内公开查询不需要账户凭据，不会使用或转发所给 Weblinking/UAT 密码；`TNT_TRACKING_ENABLED` 默认启用（空值也启用），设为 `0`、`false` 或 `no` 可停用 TNT 外网查询。

测试环境响应可能是模拟事件，页面始终标记为“Test environment result”，不将其描述为真实包裹状态。`verification/tracking-check.json` 记录了实际读取快递服务的脱敏结果，并用每条结果的 source 区分来源。测试环境返回的演示事件时间可能早于样本订单日期，因此与输入订单状态分开显示。

### TNT 国内查询实现与限制

官方澳大利亚网站将国内查询链接指向 [TNT Domestic Track & Trace](https://www.tntexpress.com.au/interaction/trackntrace.aspx)。后端读取查询表单的隐藏字段，提交单号，再进入该单号的 `View Details` 历史记录。它是官方公开网页的服务端 HTML 适配，**不是经过认证的 Weblinking/XML API**。资料中的 RTT/UAT 账户用于不同接口；由于未提供国内 Weblinking 端点和完整协议，本项目不将这些密码发送到国际 ExpressConnect 或未经核实的端点。

样本 `305506914` 的里程碑页面提示没有里程碑数据，但历史页实际返回 6 条事件，最新为 `We've delivered your shipment`，时间 `04/12/2025 13:00`，地点 `Melbourne - Airport`。`verification/tnt-check.json` 保存实际接入的脱敏结果，测试 fixture 仅保留历史事件片段并移除签收人。TNT 历史时间未带时区偏移，页面标为 carrier local time，保留快递返回的当地钟表时间，不推断为悉尼时区。

仅允许 HTTPS 且跳转到 `www.tntexpress.com.au` 的三个已核实查询/历史页面；不会执行登录、订阅通知或预约发货操作。HTTP 错误、超时、无记录、单号不匹配及网页结构变化均降级为明确的 unavailable，不读取空时间线中的静态 DELIVERED 标签充当物流状态。公开网页结构可能变化，届时需要维护适配器；真实网络成功不由离线测试保证。

### 运费估算规则与假设

此功能为需求允许的本地公式估算，**不是快递官方报价**；不接入 RTT 报价，不预约运输，也不产生实际费用。

1. 起点固定为 Ryde NSW **2111**，目的地读取该订单的四位邮编。同一订单按 `shipment_id` 分组，每组假设合成一个包裹，禁止跨收件人合并。
2. 重量支持 `g` / `kg`；尺寸支持 `mm` / `cm` / `m`。体积优先用完整长宽高相乘；长宽高不完整时读取 `volume`（`mm³` / `cm³` / `m³`，也支持 `3` 写法）。商品重量及体积均乘数量。原始 `Volumetric_GrossWeight` 换算规则不明，因此不直接使用。
3. 每组实际重量增加 **0.2 kg** 包装重量，体积增加 **20%** 包装余量。体积重量 = 包装后体积（m³）× **250 kg/m³**；这是本项目声明的估算假设。
4. 计费重量 = `max(包装后实际重量, 体积重量)`，向上取整至 **0.5 kg**。
5. 每组费用 = `(A$8.00 + A$2.00 × 计费重量kg) × 邮编区域系数`。目的地邮编与 2111 同为 `2` 开头时系数为 **1**，其他为 **1.25**。这是粗略邮编前缀分区，不能代表真实距离、行政州界或快递费率。
6. 费用以 `ROUND_HALF_UP` 舍入到分；所有组费用加总为订单 Shipment Fee。费率按含 GST 口径定义，不再额外对运费加一次 GST，商品 GST 计算保持原规则，Total = Subtotal + 商品 GST + Shipment Fee。
7. 缺失或无效重量/尺寸、邮编、商品及不支持的物流公司导致该组 A$0.00，并展示具体原因；部分组成功时明确标记 partial estimate。TNT 查询尚未结束时暂为 A$0.00；成功后重算并同步更新页面，查询失败时按新版要求保持该段 A$0.00。StarTrack 的本地估算不依赖测试环境是否可查到包裹。

本次样本：订单 1 的 Track 1 为 A$13.75，订单总额 A$2,144.76；订单 2 的 Track 2 为 A$13.75，TNT 查询成功后的 Track 3 为 A$12.50，运费合计 A$26.25、总额 A$1,681.26。TNT 失败时订单 2 运费 A$13.75、总额 A$1,668.76。订单列表接口先返回无需外网查询的估算；物流接口返回当前查询结果与重新计算的汇总，前端一起更新，金额不会把以前的运费重复相加。

## 测试与验证

```powershell
cd backend
.\.venv\Scripts\python -m pytest -q

cd ..\frontend
npm run build
```

测试覆盖 GST 规则、舍入、订单隔离、商品及物流关联、数据错误、API 契约、真实测试环境响应的脱敏 fixture、HTTP 失败、超时、TNT 国内历史解析/安全跳转/结构变化、运费单位换算/体积计费/分组汇总及 TNT 成功或失败后的金额联动。默认 pytest 禁止外网连接；真实物流探测可通过 `backend/probe_tracking.py` 显式执行；正常运行页面的物流查询也会访问实际快递服务。

## 素材许可

界面图标来自 [Lucide](https://lucide.dev)，遵循 ISC License。组件由 [shadcn/ui](https://ui.shadcn.com) 生成并保存在 `frontend/src/components/ui`，可随项目维护。

## 面试说明要点

1. 产品资料通过 SKU 数据映射，订单逻辑不按固定订单号或 SKU 写分支。
2. RRP 已含 GST，所以先除以 1.10，再计算订单未税小计与 GST，避免重复加税。
3. 订单状态是输入数据；Australia Post 物流来自测试环境，TNT 物流来自官方国内公开查询，二者均与输入订单状态分开显示。
4. 凭据留在服务端环境变量；失败、限流或无记录会变成清晰的页面状态，不会影响金额或伪造物流信息。
