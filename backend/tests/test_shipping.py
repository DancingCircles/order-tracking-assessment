from copy import deepcopy
from decimal import Decimal

import pytest

from app.shipping import apply_shipping


def order(carrier='startrack', quantity=2, dimensions=None, postcode='3065'):
    return {'shipping': {'postcode': postcode},
            'shipments': [{'id': 'parcel', 'carrier': carrier, 'label': 'Parcel'}],
            'items': [{'shipment_id': 'parcel', 'quantity': quantity, 'issues': [],
                       'dimensions': dimensions or {'weight': '500g', 'length': '100mm', 'width': '100mm', 'height': '100mm'}}],
            'summary': {'subtotal_ex_gst': '40.00', 'gst': '4.00', 'shipment_fee': '0.00', 'total': '44.00'}}


def test_weight_packaging_rounding_and_interstate_total():
    original = order()
    result = apply_shipping(original)
    # 2 x .5kg + .2kg packaging => round up to 1.5kg; (8+2*1.5)*1.25 = 13.75.
    assert result['summary']['shipment_fee'] == '13.75'
    assert result['summary']['total'] == '57.75'
    assert result['shipping_estimate']['shipments'][0]['chargeable_weight_kg'] == '1.500'
    assert original['summary']['shipment_fee'] == '0.00'


def test_volume_controls_chargeable_weight_and_units_are_equivalent():
    large = order(quantity=1, dimensions={'weight': '0.1kg', 'volume': '0.02m³'}, postcode='2111')
    # .02m3 * 1.2 packaging * 250kg/m3 = 6kg => 8 + 2*6 = 20.
    result = apply_shipping(large)
    assert result['summary']['shipment_fee'] == '20.00'
    equivalent = deepcopy(large)
    equivalent['items'][0]['dimensions'] = {'weight': '100g', 'length': '20cm', 'width': '20cm', 'height': '50cm'}
    assert apply_shipping(equivalent)['summary'] == result['summary']


@pytest.mark.parametrize('dimensions', [{'weight': 'NaNkg', 'volume': '1m³'}, {'weight': '-1kg', 'volume': '1m³'}, {'weight': '1kg'}, {'volume': '1m³'}, {'weight': '1kg', 'volume': '0m³'}])
def test_incomplete_dimensions_fall_back_without_hiding_reason(dimensions):
    result = apply_shipping(order(dimensions=dimensions))
    assert result['summary']['shipment_fee'] == '0.00'
    row = result['shipping_estimate']['shipments'][0]
    assert row['availability'] == 'unavailable'
    assert row['reason']


def test_tnt_tracking_gate_and_order_level_aggregation():
    original = order()
    original['shipments'].append({'id': 'tnt-parcel', 'carrier': 'tnt', 'label': 'TNT parcel'})
    original['items'].append({**deepcopy(original['items'][0]), 'shipment_id': 'tnt-parcel'})
    failed = apply_shipping(original, [{'id': 'tnt-parcel', 'availability': 'unavailable'}])
    assert failed['summary']['shipment_fee'] == '13.75'
    assert failed['shipping_estimate']['availability'] == 'partial'
    assert failed['shipping_estimate']['shipments'][1]['fee'] == '0.00'
    available = apply_shipping(original, [{'id': 'tnt-parcel', 'availability': 'available'}])
    assert available['summary']['shipment_fee'] == '27.50'
    assert available['summary']['total'] == '71.50'
    assert available['shipping_estimate']['availability'] == 'estimated'
    assert Decimal(available['summary']['shipment_fee']) == sum(Decimal(s['fee']) for s in available['shipping_estimate']['shipments'])


@pytest.mark.parametrize('postcode', ['', 'bad', '0000', None])
def test_bad_postcode_has_explicit_zero_fee(postcode):
    result = apply_shipping(order(postcode=postcode))
    assert result['summary']['shipment_fee'] == '0.00'
    assert result['shipping_estimate']['availability'] == 'unavailable'


def test_invalid_order_keeps_amounts_unavailable():
    invalid = order()
    invalid['summary'] = None
    assert apply_shipping(invalid)['summary'] is None


def test_extreme_dimensions_do_not_break_order_response():
    result = apply_shipping(order(dimensions={'weight': '1kg', 'length': '1000000000000mm', 'width': '1000000000000mm', 'height': '1000000000000mm'}))
    assert result['summary']['total'] == '44.00'
    assert result['shipping_estimate']['shipments'][0]['availability'] == 'unavailable'
