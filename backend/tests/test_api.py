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
        assert body['orders'][0]['summary']['total'] == '2131.01'
        assert body['orders'][1]['summary']['total'] == '1655.01'
        tracking = client.get('/api/orders/PO-20251203-00046/tracking')
        assert tracking.status_code == 200
        rows = tracking.json()['tracking']
        assert [row['availability'] for row in rows] == ['unavailable', 'not_implemented']
        assert [row['tracking_no'] for row in rows] == ['2FWZ50008645', '305506914']
        assert client.get('/api/orders/unknown/tracking').status_code == 404
        assert 'AUSPOST_API_SECRET' not in response.text + tracking.text


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
