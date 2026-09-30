import json
from pathlib import Path

import asyncio
import httpx

from app.main import create_app
from app.tracking import TrackingService, TrackingSettings

DATA = Path(__file__).resolve().parents[2] / 'data'


class TestClient:
    """In-process HTTP contract client; no external network or extra runner."""
    __test__ = False

    def __init__(self, app):
        self.app = app

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def get(self, path):
        async def request():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url='http://test') as client:
                return await client.get(path)
        return asyncio.run(request())


def test_order_endpoint_smoke_and_tracking_fallback():
    with TestClient(create_app(DATA, TrackingService(TrackingSettings()))) as client:
        response = client.get('/api/orders')
        assert response.status_code == 200
        body = response.json()
        assert body['currency'] == 'AUD'
        assert body['origin_postcode'] == '2111'
        assert len(body['orders']) == 2
        assert body['orders'][0]['summary']['shipment_fee'] == '13.75'
        assert body['orders'][0]['summary']['total'] == '2144.76'
        assert body['orders'][1]['summary']['shipment_fee'] == '13.75'
        assert body['orders'][1]['summary']['total'] == '1668.76'
        tracking = client.get('/api/orders/PO-20251203-00046/tracking')
        assert tracking.status_code == 200
        rows = tracking.json()['tracking']
        assert [row['availability'] for row in rows] == ['unavailable', 'unavailable']
        assert [row['tracking_no'] for row in rows] == ['2FWZ50008645', '305506914']
        assert client.get('/api/orders/unknown/tracking').status_code == 404
        assert 'AUSPOST_API_SECRET' not in response.text + tracking.text
        assert tracking.json()['summary']['shipment_fee'] == '13.75'
        assert tracking.json()['shipping_estimate']['availability'] == 'partial'


def write_data(directory, orders, products):
    (directory / 'orders.json').write_text(json.dumps(orders), encoding='utf-8')
    (directory / 'products.json').write_text(json.dumps(products), encoding='utf-8')


def test_empty_orders(tmp_path):
    write_data(tmp_path, [], [])
    response = TestClient(create_app(tmp_path)).get('/api/orders')
    assert response.status_code == 200
    assert response.json()['orders'] == []


def test_missing_and_corrupt_data(tmp_path):
    client = TestClient(create_app(tmp_path))
    response = client.get('/api/orders')
    assert response.status_code == 503
    assert response.json()['detail'] == '订单或商品数据文件不可用，请检查输入结构'
    (tmp_path / 'orders.json').write_text('{broken', encoding='utf-8')
    (tmp_path / 'products.json').write_text('[]', encoding='utf-8')
    assert client.get('/api/orders').status_code == 503


def test_tnt_result_updates_shipping_and_failure_removes_only_tnt_fee():
    from app.tnt import TntService
    from test_tnt import domestic_transport

    service = TrackingService(TrackingSettings(), tnt_service=TntService(domestic_transport()))
    client = TestClient(create_app(DATA, service))
    before = client.get('/api/orders').json()['orders'][1]
    assert before['summary']['shipment_fee'] == '13.75'
    successful = client.get('/api/orders/PO-20251203-00046/tracking').json()
    assert successful['tracking'][1]['availability'] == 'available'
    assert successful['summary'] == {'subtotal_ex_gst': '1504.55', 'gst': '150.46', 'shipment_fee': '26.25', 'total': '1681.26'}
    assert [row['fee'] for row in successful['shipping_estimate']['shipments']] == ['13.75', '12.50']
    service.tnt = TntService(httpx.MockTransport(lambda _: httpx.Response(503)))
    failed = client.get('/api/orders/PO-20251203-00046/tracking').json()
    assert failed['tracking'][1]['availability'] == 'unavailable'
    assert failed['summary']['shipment_fee'] == '13.75'
    assert failed['summary']['total'] == '1668.76'
