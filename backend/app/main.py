from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException

from .orders import DataUnavailable, OrderRepository
from .tracking import TrackingService, TrackingSettings
from .shipping import apply_shipping

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / 'backend' / '.env')


def create_app(data_dir=None, tracking_service=None):
    app = FastAPI(title='Order Details & Tracking', version='1.0.0')
    repository = OrderRepository(Path(data_dir) if data_dir is not None else ROOT / 'data')
    tracking = tracking_service or TrackingService(TrackingSettings.from_env())

    def read_orders():
        try:
            return repository.read()
        except DataUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.get('/api/orders')
    def orders():
        # Order data loads without waiting for courier services. TNT's fee stays
        # zero until tracking confirms an available result for that shipment.
        return {'orders': [apply_shipping(order) for order in read_orders()], 'currency': 'AUD', 'origin_postcode': '2111'}

    @app.get('/api/orders/{order_no}/tracking')
    def order_tracking(order_no: str):
        order = next((order for order in read_orders() if order['order_no'] == order_no), None)
        if order is None:
            raise HTTPException(status_code=404, detail='订单不存在')
        results = [tracking.query(shipment) for shipment in order['shipments']]
        calculated = apply_shipping(order, results)
        return {'order_no': order_no, 'tracking': results, 'summary': calculated['summary'],
                'shipping_estimate': calculated['shipping_estimate']}

    return app


app = create_app()
