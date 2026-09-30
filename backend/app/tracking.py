"""Read-only testbed tracking. Provider failures never invent events."""
from dataclasses import dataclass
from datetime import datetime, timezone
import os

import httpx

from .tnt import TntService

TESTBED_URL = 'https://digitalapi.auspost.com.au/test/shipping/v1/track'


@dataclass(frozen=True)
class TrackingSettings:
    key: str = ''
    secret: str = ''
    account: str = ''

    @classmethod
    def from_env(cls):
        return cls(*(os.getenv(name, '').strip() for name in
                     ('AUSPOST_API_KEY', 'AUSPOST_API_SECRET', 'AUSPOST_ACCOUNT_NUMBER')))


def base_result(shipment):
    return {**shipment, 'availability': 'unavailable', 'status': None,
            'last_updated': None, 'reason': None, 'events': [], 'source': 'testbed'}


def event_date(value):
    if not isinstance(value, str):
        return None
    try:
        date = datetime.fromisoformat(value.replace('Z', '+00:00'))
        # Provider dates without offsets retain their text; UTC is only for ordering.
        return date.replace(tzinfo=timezone.utc) if date.tzinfo is None else date
    except ValueError:
        return None


def parse_tracking(payload, shipment):
    result = base_result(shipment)
    if not isinstance(payload, dict) or payload.get('errors'):
        result['reason'] = '物流服务返回业务错误'
        return result
    rows = payload.get('tracking_results')
    if not isinstance(rows, list):
        result['reason'] = '物流响应缺少有效记录'
        return result
    row = next((row for row in rows if isinstance(row, dict) and row.get('tracking_id') == shipment['tracking_no']), None)
    if row is None:
        result['reason'] = '未找到该物流单号的记录'
        return result
    if row.get('errors'):
        result['reason'] = '该物流单号不可查询或服务返回业务错误'
        return result
    items = row.get('trackable_items', [])
    if not isinstance(items, list):
        result['reason'] = '物流响应结构无效'
        return result
    events = []
    item_statuses = []
    for item in items:
        if not isinstance(item, dict) or item.get('errors'):
            result['reason'] = '物流明细不可用'
            return result
        item_status = item.get('status')
        if isinstance(item_status, str) and item_status.strip() and item_status.strip() not in item_statuses:
            item_statuses.append(item_status.strip())
        raw_events = item.get('events', [])
        if not isinstance(raw_events, list):
            result['reason'] = '物流事件结构无效'
            return result
        for event in raw_events:
            if isinstance(event, dict):
                date = event_date(event.get('date'))
                events.append({'date': event.get('date') if date else None,
                               'article_id': item.get('article_id', ''),
                               'description': event.get('description') if isinstance(event.get('description'), str) else '',
                               'location': event.get('location') if isinstance(event.get('location'), str) else ''})
    dated_events = [event for event in events if event['date']]
    dated_events.sort(key=lambda event: event_date(event['date']), reverse=True)
    status = row.get('status')
    status = status.strip() if isinstance(status, str) and status.strip() else None
    if status is None and item_statuses:
        status = ' / '.join(item_statuses)
    if not status and not events:
        result['reason'] = '物流响应没有状态或事件信息'
        return result
    result.update(availability='available', status=status,
                  last_updated=dated_events[0]['date'] if dated_events else None,
                  events=dated_events + [event for event in events if not event['date']])
    return result


class TrackingService:
    def __init__(self, settings: TrackingSettings, transport=None, tnt_service=None):
        self.settings = settings
        self.transport = transport
        self.tnt = tnt_service or TntService(transport, enabled=os.getenv('TNT_TRACKING_ENABLED', '1').strip().lower() not in ('0', 'false', 'no'))

    def query(self, shipment):
        result = base_result(shipment)
        if shipment['carrier'] == 'tnt':
            return self.tnt.query(shipment)
        if shipment['carrier'] not in ('startrack', 'auspost'):
            result['reason'] = '未支持此物流公司'
            return result
        settings = self.settings
        if not (settings.key and settings.secret and settings.account):
            result['reason'] = '测试环境凭据未配置，暂无法查询物流'
            return result
        try:
            with httpx.Client(transport=self.transport, timeout=5.0) as client:
                response = client.get(TESTBED_URL, params={'tracking_ids': shipment['tracking_no']},
                                      auth=(settings.key, settings.secret),
                                      headers={'Account-Number': settings.account, 'Accept': 'application/json'})
                if response.status_code != 200:
                    reason = {401: '测试环境认证失败', 403: '测试环境权限不足',
                              429: '物流查询频率受限，请稍后手动重试'}.get(response.status_code, '物流服务暂不可用')
                    result['reason'] = f'{reason}（HTTP {response.status_code}）'
                    return result
                return parse_tracking(response.json(), shipment)
        except httpx.TimeoutException:
            result['reason'] = '物流请求超时，请稍后手动重试'
        except httpx.RequestError:
            result['reason'] = '无法连接物流测试服务'
        except (ValueError, TypeError):
            result['reason'] = '物流服务返回无效响应'
        return result
