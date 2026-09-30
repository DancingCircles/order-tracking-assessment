"""Declared assessment estimate, not a carrier quote. All fees are GST-inclusive."""
from copy import deepcopy
from decimal import Decimal, DecimalException, ROUND_CEILING
import re

from .orders import money

ORIGIN_POSTCODE = '2111'


def measurement(value, units):
    if not isinstance(value, str):
        raise ValueError('重量或尺寸缺失')
    match = re.fullmatch(r'\s*(\d+(?:\.\d+)?)\s*([a-zA-Z³3]+)\s*', value)
    if not match or match[2] not in units:
        raise ValueError('重量或尺寸单位无效')
    number = Decimal(match[1])
    if not 0 < number <= Decimal('1000000000000'):
        raise ValueError('重量或尺寸必须为合理的正数')
    return number * units[match[2]]


def unit_volume(dimensions):
    length_units = {'mm': Decimal('0.001'), 'cm': Decimal('0.01'), 'm': Decimal('1')}
    # Physical dimensions are the primary source; supplied volumetric weights
    # use an unspecified conversion and therefore are not trusted for this rule.
    if all(dimensions.get(key) is not None for key in ('length', 'width', 'height')):
        return (measurement(dimensions['length'], length_units)
                * measurement(dimensions['width'], length_units)
                * measurement(dimensions['height'], length_units))
    return measurement(dimensions.get('volume'), {
        'mm³': Decimal('0.000000001'), 'mm3': Decimal('0.000000001'),
        'cm³': Decimal('0.000001'), 'cm3': Decimal('0.000001'),
        'm³': Decimal('1'), 'm3': Decimal('1'),
    })


def apply_shipping(order, tracking_results=()):
    result = deepcopy(order)
    rows = []
    tracking = {row['id']: row for row in tracking_results}
    postcode = order.get('shipping', {}).get('postcode')
    for shipment in order['shipments']:
        row = {'id': shipment['id'], 'label': shipment.get('label', shipment['id']),
               'carrier': shipment.get('carrier'), 'availability': 'unavailable',
               'fee': '0.00', 'reason': None, 'actual_weight_kg': None,
               'volumetric_weight_kg': None, 'chargeable_weight_kg': None}
        try:
            if order['summary'] is None:
                raise ValueError('订单商品数据无效，无法估算运费')
            if shipment.get('carrier') not in ('startrack', 'auspost', 'tnt'):
                raise ValueError('物流公司不受支持')
            if shipment['carrier'] == 'tnt' and tracking.get(shipment['id'], {}).get('availability') != 'available':
                raise ValueError('TNT 查询尚未完成，该段运费暂为 A$0.00' if shipment['id'] not in tracking else 'TNT 查询不可用，按需求该段运费为 A$0.00')
            if not isinstance(postcode, str) or not re.fullmatch(r'\d{4}', postcode) or postcode == '0000':
                raise ValueError('目的地邮编必须为有效的四位字符串')
            items = [line for line in order['items'] if line['shipment_id'] == shipment['id']]
            if not items:
                raise ValueError('该物流记录没有关联商品')
            weight, volume = Decimal('0'), Decimal('0')
            for item in items:
                if item.get('issues') or type(item.get('quantity')) is not int or item['quantity'] <= 0:
                    raise ValueError('商品行无效，无法估算运费')
                dimensions = item.get('dimensions') or {}
                weight += measurement(dimensions.get('weight'), {'g': Decimal('0.001'), 'kg': Decimal('1')}) * item['quantity']
                volume += unit_volume(dimensions) * item['quantity']
            weight += Decimal('0.2')
            volumetric = volume * Decimal('1.2') * Decimal('250')
            chargeable = (max(weight, volumetric) * 2).to_integral_value(rounding=ROUND_CEILING) / 2
            # Deliberately coarse NSW postcode-prefix zone, not geographic distance.
            zone_multiplier = Decimal('1') if postcode[0] == ORIGIN_POSTCODE[0] else Decimal('1.25')
            fee = (Decimal('8') + Decimal('2') * chargeable) * zone_multiplier
            row.update(availability='estimated', fee=money(fee),
                       actual_weight_kg=format(weight, '.3f'),
                       volumetric_weight_kg=format(volumetric, '.3f'),
                       chargeable_weight_kg=format(chargeable, '.3f'))
        except (ValueError, TypeError, AttributeError) as exc:
            row['reason'] = str(exc)
        except DecimalException:
            row['reason'] = '重量、体积或费用超出可处理精度，无法估算'
        rows.append(row)
    count = sum(row['availability'] == 'estimated' for row in rows)
    result['shipping_estimate'] = {
        'availability': 'estimated' if rows and count == len(rows) else 'partial' if count else 'unavailable',
        'origin_postcode': ORIGIN_POSTCODE, 'destination_postcode': postcode,
        'method': 'Local formula estimate · GST-inclusive · not a carrier quote', 'shipments': rows,
    }
    if result['summary'] is not None:
        summary = result['summary']
        fee = sum((Decimal(row['fee']) for row in rows), Decimal('0'))
        summary.update(shipment_fee=money(fee),
                       total=money(Decimal(summary['subtotal_ex_gst']) + Decimal(summary['gst']) + fee))
    return result
