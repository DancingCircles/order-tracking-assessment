from decimal import Decimal

import pytest

from app.orders import calculate_line, summarize


@pytest.mark.parametrize('rrp,quantity,unit,line', [
    ('22.00', 2, '20.00', '40.00'),
    ('33.00', 1, '30.00', '30.00'),
    ('1.00', 3, '0.91', '2.73'),
    ('0.00', 4, '0.00', '0.00'),
])
def test_inclusive_rrp_is_not_taxed_twice(rrp, quantity, unit, line):
    result = calculate_line(rrp, quantity)
    assert result['ex_gst_unit_price'] == unit
    assert result['line_subtotal_ex_gst'] == line


@pytest.mark.parametrize('lines,expected', [
    (['40.00'], {'subtotal_ex_gst': '40.00', 'gst': '4.00', 'shipment_fee': '0.00', 'total': '44.00'}),
    (['40.00', '30.00'], {'subtotal_ex_gst': '70.00', 'gst': '7.00', 'shipment_fee': '0.00', 'total': '77.00'}),
    (['2.73'], {'subtotal_ex_gst': '2.73', 'gst': '0.27', 'shipment_fee': '0.00', 'total': '3.00'}),
])
def test_summary_has_independent_expected_amounts(lines, expected):
    assert summarize([Decimal(value) for value in lines]) == expected
