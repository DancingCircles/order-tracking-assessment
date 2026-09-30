import json
from pathlib import Path

import httpx
import pytest

from app.tracking import parse_tracking, TrackingService, TrackingSettings

SHIPMENT = {'id': 'track-1', 'label': 'Track 1', 'carrier': 'startrack', 'tracking_no': '2FWZ50008569'}


def real_fixture():
    return json.loads((Path(__file__).parent / 'fixtures/auspost-testbed-real.json').read_text(encoding='utf-8'))['payload']


def test_recorded_real_testbed_status_and_time():
    result = parse_tracking(real_fixture(), SHIPMENT)
    assert result['availability'] == 'available'
    assert result['status'] == 'Item Delivered'
    assert result['last_updated'] == '2025-02-13T11:49:59+11:00'
    assert result['source'] == 'testbed'


def test_results_match_tracking_id_not_array_position():
    payload = real_fixture()
    payload['tracking_results'].insert(0, {'tracking_id': 'OTHER', 'status': 'In Transit'})
    payload['tracking_results'][1]['trackable_items'][0]['events'].reverse()
    result = parse_tracking(payload, SHIPMENT)
    assert result['status'] == 'Item Delivered'
    assert result['last_updated'] == '2025-02-13T11:49:59+11:00'


@pytest.mark.parametrize('payload', [
    {}, [], {'errors': [{'code': 'ESB-20010'}]}, {'tracking_results': []},
    {'tracking_results': [{'tracking_id': '2FWZ50008569', 'errors': [{'code': 'ESB-10001'}]}]},
    {'tracking_results': [{'tracking_id': '2FWZ50008569', 'trackable_items': 'invalid'}]},
    {'tracking_results': [{'tracking_id': '2FWZ50008569', 'trackable_items': [{'events': 'invalid'}]}]},
])
def test_bad_or_missing_provider_results_are_explicit(payload):
    result = parse_tracking(payload, SHIPMENT)
    assert result['availability'] == 'unavailable'
    assert result['reason']
    assert result['status'] is None
    assert result['last_updated'] is None


def test_partial_fields_are_not_invented():
    payload = {'tracking_results': [{'tracking_id': SHIPMENT['tracking_no'], 'status': 'In Transit'}]}
    result = parse_tracking(payload, SHIPMENT)
    assert result['availability'] == 'available'
    assert result['status'] == 'In Transit'
    assert result['last_updated'] is None
    payload['tracking_results'][0] = {'tracking_id': SHIPMENT['tracking_no'], 'trackable_items': [
        {'events': [{'date': 'invalid', 'description': 'Received'}]}]}
    result = parse_tracking(payload, SHIPMENT)
    assert result['availability'] == 'available'
    assert result['status'] is None
    assert result['last_updated'] is None


@pytest.mark.parametrize('status', [401, 403, 429, 500])
def test_http_failures_do_not_expose_provider_body(status):
    def respond(request):
        assert request.url.params['tracking_ids'] == '2FWZ50008569'
        assert request.headers['account-number'] == 'test-account'
        assert request.headers['authorization'].startswith('Basic ')
        return httpx.Response(status, text='private-provider-error')
    service = TrackingService(TrackingSettings('test-key', 'test-secret', 'test-account'), httpx.MockTransport(respond))
    result = service.query(SHIPMENT)
    assert result['availability'] == 'unavailable'
    assert f'HTTP {status}' in result['reason']
    assert 'private-provider-error' not in json.dumps(result)
    assert 'test-secret' not in json.dumps(result)


@pytest.mark.parametrize('error,fragment', [(httpx.ReadTimeout, '超时'), (httpx.ConnectError, '连接')])
def test_transport_failure_degrades(error, fragment):
    def respond(request):
        raise error('private-detail', request=request)
    service = TrackingService(TrackingSettings('k', 's', 'a'), httpx.MockTransport(respond))
    result = service.query(SHIPMENT)
    assert result['availability'] == 'unavailable'
    assert fragment in result['reason']
    assert 'private-detail' not in result['reason']


def test_invalid_json_response():
    service = TrackingService(TrackingSettings('k', 's', 'a'), httpx.MockTransport(lambda _: httpx.Response(200, text='<html>not JSON</html>')))
    result = service.query(SHIPMENT)
    assert result['availability'] == 'unavailable'
    assert result['reason'] == '物流服务返回无效响应'


def test_http_200_business_error():
    service = TrackingService(TrackingSettings('k', 's', 'a'), httpx.MockTransport(lambda _: httpx.Response(200, json={'errors': [{'code': 'bad'}]})))
    result = service.query(SHIPMENT)
    assert result['availability'] == 'unavailable'
    assert result['reason'] == '物流服务返回业务错误'


def test_tnt_and_missing_credentials_never_call_network():
    def forbidden(_):
        pytest.fail('Network should not be called')
    service = TrackingService(TrackingSettings(), httpx.MockTransport(forbidden))
    result = service.query({**SHIPMENT, 'carrier': 'tnt'})
    assert result['availability'] == 'unavailable'
    assert result['status'] is None
    assert 'A$0.00' in result['reason']
    assert service.query(SHIPMENT)['availability'] == 'unavailable'
