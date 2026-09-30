"""Order enrichment and GST rules; no sample identifiers in business logic."""
import json
from copy import deepcopy
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext
from pathlib import Path

CENT = Decimal('0.01')


class DataUnavailable(ValueError):
    pass


def money(value: Decimal) -> str:
    return format(value.quantize(CENT, rounding=ROUND_HALF_UP), '.2f')


def calculate_line(rrp, quantity):
    if type(quantity) is not int or quantity <= 0:
        raise ValueError('数量必须为正整数')
    if not isinstance(rrp, (str, Decimal)):
        raise ValueError('RRP 必须为十进制字符串')
    try:
        price = Decimal(rrp)
        if not price.is_finite() or price < 0:
            raise ValueError('RRP 必须为有限非负金额')
        with localcontext() as context:
            context.prec = 40
            unit = price / Decimal('1.10')
            return {'rrp': money(price), 'ex_gst_unit_price': money(unit),
                    'line_subtotal_ex_gst': money(unit * quantity)}
    except InvalidOperation as exc:
        raise ValueError('RRP 无效或超出可处理精度') from exc


def summarize(lines):
    with localcontext() as context:
        context.prec = 40
        subtotal = sum(lines, Decimal('0.00'))
        gst = (subtotal * Decimal('0.10')).quantize(CENT, rounding=ROUND_HALF_UP)
        return {'subtotal_ex_gst': money(subtotal), 'gst': money(gst),
                'shipment_fee': '0.00', 'total': money(subtotal + gst)}


def build_orders(orders, products):
    index = {}
    for product in products:
        code = product.get('sku')
        if not isinstance(code, str) or code in index:
            raise DataUnavailable('商品数据包含缺失或重复 SKU')
        index[code] = product
    results = []
    for order in orders:
        result = deepcopy(order)
        issues, amounts, enriched = [], [], []
        shipment_ids = {shipment['id'] for shipment in order['shipments']}
        for item in order['items']:
            line = {**item, 'name': item.get('sku', '未知 SKU'), 'description': '',
                    'rrp': None, 'ex_gst_unit_price': None,
                    'line_subtotal_ex_gst': None, 'issues': []}
            product = index.get(item.get('sku'))
            if product is None:
                line['issues'].append('SKU 未匹配到商品资料')
            else:
                line['name'] = product.get('name') or product.get('description') or item['sku']
                line['description'] = product.get('description', '')
                line['dimensions'] = product.get('dimensions', {})
                try:
                    line.update(calculate_line(product.get('rrp'), item.get('quantity')))
                except ValueError as exc:
                    line['issues'].append(str(exc))
            if item.get('shipment_id') not in shipment_ids:
                line['issues'].append('商品关联的物流记录不存在')
            if line['issues']:
                issues.extend(f"{line['sku']}: {issue}" for issue in line['issues'])
            else:
                amounts.append(Decimal(line['line_subtotal_ex_gst']))
            enriched.append(line)
        if not enriched:
            issues.append('订单没有商品明细，无法计算金额')
        result.update(items=enriched, issues=issues, summary=None if issues else summarize(amounts))
        results.append(result)
    return results


class OrderRepository:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir

    def read(self):
        try:
            orders = json.loads((self.data_dir / 'orders.json').read_text(encoding='utf-8'))
            products = json.loads((self.data_dir / 'products.json').read_text(encoding='utf-8'))
            if not isinstance(orders, list) or not isinstance(products, list):
                raise DataUnavailable('数据文件必须包含 JSON 数组')
            required = {'order_no', 'order_date', 'status', 'company', 'customer', 'phone', 'email', 'shipping', 'items', 'shipments'}
            numbers = set()
            for order in orders:
                if not isinstance(order, dict) or not required <= order.keys():
                    raise DataUnavailable('订单头字段不完整')
                if not isinstance(order['order_no'], str) or order['order_no'] in numbers:
                    raise DataUnavailable('订单号缺失或重复')
                numbers.add(order['order_no'])
                if not isinstance(order['items'], list) or not isinstance(order['shipments'], list):
                    raise DataUnavailable('订单商品和物流必须为数组')
                if not isinstance(order['shipping'], dict) or not {'address', 'postcode'} <= order['shipping'].keys():
                    raise DataUnavailable('收货地址字段不完整')
                for item in order['items']:
                    if not isinstance(item, dict) or not isinstance(item.get('sku'), str):
                        raise DataUnavailable('商品行缺少 SKU')
                ids = set()
                for shipment in order['shipments']:
                    if not isinstance(shipment, dict) or not {'id', 'carrier', 'tracking_no'} <= shipment.keys():
                        raise DataUnavailable('物流字段不完整')
                    if not all(isinstance(shipment[key], str) and shipment[key] for key in ('id', 'carrier', 'tracking_no')):
                        raise DataUnavailable('物流字段必须为非空字符串')
                    if shipment['id'] in ids:
                        raise DataUnavailable('订单包含重复物流标识')
                    ids.add(shipment['id'])
            return build_orders(orders, products)
        except (OSError, json.JSONDecodeError, UnicodeError, TypeError, KeyError, AttributeError) as exc:
            raise DataUnavailable('订单或商品数据文件不可用，请检查输入结构') from exc
