"""Explicit, read-only live testbed probe; excluded from default pytest runs."""
import json
from datetime import datetime, timezone

from app.main import ROOT
from app.orders import OrderRepository
from app.tracking import TrackingService, TrackingSettings

if __name__ == '__main__':
    service = TrackingService(TrackingSettings.from_env())
    results = [service.query(shipment) for order in OrderRepository(ROOT / 'data').read()
               for shipment in order['shipments']]
    report = {'checked_at': datetime.now(timezone.utc).isoformat(),
              'environment': 'Australia Post / StarTrack testbed',
              'credential_source': 'updated HTML; values omitted', 'tracking': results}
    path = ROOT / 'verification/tracking-check.json'
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    for result in results:
        print(result['tracking_no'], result['availability'], result['reason'] or result['status'])
