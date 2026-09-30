from copy import deepcopy
from decimal import Decimal
from pathlib import Path

from hypothesis import given, strategies as st
import pytest

from app.orders import build_orders, calculate_line, OrderRepository, summarize

DATA = Path(__file__).resolve().parents[2] / 'data'


def test_real_sample_grouping_prices_and_totals():
    first, second = OrderRepository(DATA).read()
    assert first['order_no'] == 'PO-20251130-00072'
    assert second['order_no'] == 'PO-20251203-00046'
    assert len(first['items']) == 5
    assert len(second['items']) == 4
    assert [item['quantity'] for item in first['items']] == [3, 1, 1, 4, 6]
    assert [item['rrp'] for item in first['items']] == ['99.00', '199.00', '199.00', '149.00', '140.00']
    assert {item['shipment_id'] for item in first['items']} == {'track-1'}
    assert {item['shipment_id'] for item in second['items']} == {'track-2', 'track-3'}
    assert len(first['shipments']) == 1
    assert len(second['shipments']) == 2
    assert first['summary'] == {'subtotal_ex_gst': '1937.28', 'gst': '193.73', 'shipment_fee': '0.00', 'total': '2131.01'}
    assert second['summary'] == {'subtotal_ex_gst': '1504.55', 'gst': '150.46', 'shipment_fee': '0.00', 'total': '1655.01'}


def minimal_orders():
    return [{'order_no': 'NEW-A', 'shipments': [{'id': 'new-shipment'}],
             'items': [{'sku': 'NEW-SKU', 'quantity': 2, 'shipment_id': 'new-shipment'}]},
            {'order_no': 'NEW-B', 'shipments': [{'id': 'different-shipment'}],
             'items': [{'sku': 'NEW-SKU', 'quantity': 1, 'shipment_id': 'different-shipment'}]}]


@pytest.mark.parametrize('quantity', [0, -1, 1.5, True, '2', None])
def test_bad_quantities_block_only_affected_order(quantity):
    orders = minimal_orders()
    orders[0]['items'][0]['quantity'] = quantity
    first, second = build_orders(orders, [{'sku': 'NEW-SKU', 'name': 'New product', 'rrp': '22.00'}])
    assert first['summary'] is None
    assert first['items'][0]['issues'] == ['数量必须为正整数']
    assert second['summary']['total'] == '22.00'


@pytest.mark.parametrize('price', ['bad', '-1', 'NaN', 'Infinity', None, 22.0])
def test_invalid_price_is_not_silently_zero(price):
    result = build_orders(minimal_orders(), [{'sku': 'NEW-SKU', 'rrp': price}])[0]
    assert result['summary'] is None
    assert result['issues']
    assert result['items'][0]['rrp'] is None


def test_missing_sku_and_shipment_are_visible():
    orders = minimal_orders()
    orders[0]['items'][0]['sku'] = 'MISSING'
    orders[1]['items'][0]['shipment_id'] = 'MISSING'
    first, second = build_orders(orders, [{'sku': 'NEW-SKU', 'rrp': '22.00'}])
    assert first['summary'] is None
    assert first['items'][0]['issues'] == ['SKU 未匹配到商品资料']
    assert second['summary'] is None
    assert second['items'][0]['issues'] == ['商品关联的物流记录不存在']


@given(quantity=st.integers(min_value=1, max_value=10000), cents=st.integers(min_value=0, max_value=1000000))
def test_valid_amounts_and_order_independence(quantity, cents):
    price = str(Decimal(cents).scaleb(-2))
    orders = minimal_orders()
    before = deepcopy(orders)
    products = [{'sku': 'NEW-SKU', 'rrp': price}]
    baseline = build_orders(orders, products)
    orders[0]['items'][0]['quantity'] = quantity
    changed = build_orders(orders, products)
    assert baseline[1] == changed[1]
    assert before[0]['items'][0]['quantity'] == 2
    line = changed[0]['items'][0]
    summary = changed[0]['summary']
    assert Decimal(line['line_subtotal_ex_gst']).is_finite()
    assert summary['subtotal_ex_gst'] == line['line_subtotal_ex_gst']
    assert Decimal(summary['total']) == Decimal(summary['subtotal_ex_gst']) + Decimal(summary['gst']) + Decimal(summary['shipment_fee'])


@given(rows=st.lists(st.tuples(st.integers(0, 100000), st.integers(1, 100)), min_size=1, max_size=8))
def test_line_order_does_not_change_summary(rows):
    lines = [Decimal(calculate_line(str(Decimal(cents).scaleb(-2)), quantity)['line_subtotal_ex_gst']) for cents, quantity in rows]
    assert summarize(lines) == summarize(list(reversed(lines)))


@given(value=st.one_of(st.none(), st.booleans(), st.text(), st.floats(allow_nan=True, allow_infinity=True), st.integers(max_value=0)))
def test_boundary_rejects_invalid_quantities(value):
    with pytest.raises(ValueError, match='数量必须为正整数'):
        calculate_line('22.00', value)
