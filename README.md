# 订单详情与物流查询

一个面向澳大利亚业务场景的前后端小型应用。它将订单行与本地 SKU 数据匹配，按 RRP 含 GST 的规则计算每笔订单金额，并展示 Australia Post / StarTrack 测试环境的物流结果。

## 已实现内容

- 两笔订单独立处理；第二笔订单含 StarTrack 与 TNT 两条物流记录。
- 九个真实 SKU 查询结果已保存为 `data/sku-query-result.json`，并标准化为 `data/products.json`。
- React + TypeScript + Vite 前端，使用 Tailwind CSS 与 shadcn/ui 的 Tabs、Card、Table、Badge、Alert、Button、Skeleton、Separator 组件。
- Python + FastAPI 服务，提供 `GET /api/orders` 及 `GET /api/orders/{order_no}/tracking`。
- RRP 为含 GST 价格：未税单价 = RRP / 1.10；每个未税行小计以 `ROUND_HALF_UP` 舍入至两位，Subtotal 为已舍入行小计之和，GST = Subtotal × 10%，Total = Subtotal + GST + Shipment Fee。
- Australia Post / StarTrack 仅从服务端访问测试环境。TNT 是可选加分项，本期明确展示未实现状态；全部 Shipment Fee 显示 A$0.00。
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

每个商品行的 `sku` 必须是字符串，`quantity` 必须是正整数，`shipment_id` 必须精确匹配同一订单中某个 `shipments[].id`。每条物流记录的 `id`、`carrier`、`tracking_no` 必须为非空字符串，`id` 在订单内唯一；`label` 用于界面显示。`carrier` 支持 `startrack`、`auspost` 和 `tnt`：前两者走 Australia Post 测试环境，`tnt` 明确返回“未实现”。

### `products.json` 契约

文件顶层必须是商品数组。每项至少包含唯一的字符串 `sku`、用于展示的 `name` 或 `description`，以及 `rrp`。`rrp` **必须是十进制字符串**，例如 `"99.00"`，表示含 GST 的澳元 RRP；不得写成 JSON 数字，避免浮点误差。`dimensions` 是来源提供的可选重量、尺寸与体积资料，供后续运费估算使用。

输入错误不会静默变成零金额：缺失 SKU、无效 RRP、非正整数数量或缺失物流关联会保留问题说明，并使该订单的金额汇总显示为无法计算；其他订单仍可处理。

### 金额对账与舍入

系统以逐行税前金额为权威计算基础：先以完整精度计算 `RRP / 1.10 × quantity`，每行用 `ROUND_HALF_UP` 舍入到分，再汇总 Subtotal，并对 `Subtotal × 10%` 用同一规则计算 GST。因此所有展示的行小计可直接加总为 Subtotal，且 `Total = Subtotal + GST + Shipment Fee`。

由于含税 RRP 是逐项输入的价格，从其汇总值反推含税总额时，可能与上述逐行税前舍入后的 Total 相差最多 A$0.01。本样本两笔订单分别是 A$2,131.00 对 A$2,131.01、A$1,655.00 对 A$1,655.01；这属于已声明的舍入结果，并非额外收费。订单日期只表示日历日期，页面不为它附加时区或具体时刻；物流事件时间才转换为悉尼时区展示。

## 物流与安全

所有密钥只从 `backend/.env` 读取，`.env` 已被忽略；仓库仅提供变量名在 `.env.example`。前端不会接触密钥。

测试环境响应可能是模拟事件，页面始终标记为“Test environment result”，不将其描述为真实包裹状态。`verification/tracking-check.json` 记录了实际读取测试环境的脱敏结果。测试环境返回的演示事件时间可能早于样本订单日期，因此与输入订单状态分开显示。

运费估算没有实现。若后续开发，应以起点 2111、目的地邮编、每个 SKU 的重量/体积与物流分组计算各段费用后再汇总订单；当前按文档允许显示 A$0.00。

## 测试与验证

```powershell
cd backend
.\.venv\Scripts\python -m pytest -q

cd ..\frontend
npm run build
```

测试覆盖 GST 规则、舍入、订单隔离、商品及物流关联、数据错误、API 契约、真实测试环境响应的脱敏 fixture、HTTP 失败、超时与 TNT 降级。默认 pytest 禁止外网连接；真实物流探测仅通过 `backend/probe_tracking.py` 显式执行。

## 素材许可

界面图标来自 [Lucide](https://lucide.dev)，遵循 ISC License。组件由 [shadcn/ui](https://ui.shadcn.com) 生成并保存在 `frontend/src/components/ui`，可随项目维护。

## 面试说明要点

1. 产品资料通过 SKU 数据映射，订单逻辑不按固定订单号或 SKU 写分支。
2. RRP 已含 GST，所以先除以 1.10，再计算订单未税小计与 GST，避免重复加税。
3. 订单状态是输入数据；物流状态是可选测试环境接口结果，二者不混用。
4. 凭据留在服务端环境变量；失败、限流或无记录会变成清晰的页面状态，不会影响金额或伪造物流信息。
