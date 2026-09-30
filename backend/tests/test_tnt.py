from pathlib import Path

import httpx
import pytest

from app.tnt import TNT_TRACKING_URL, TntService, parse_history

SHIPMENT = {'id': 'tnt', 'label': 'TNT', 'carrier': 'tnt', 'tracking_no': '305506914'}


def fixture():
    return (Path(__file__).parent / 'fixtures/tnt-domestic-history-real.html').read_text(encoding='utf-8')


def test_observed_domestic_history_is_parsed_without_using_static_labels():
    result = parse_history(fixture(), SHIPMENT)
    assert result['availability'] == 'available'
    assert result['status'] == "We've delivered your shipment"
    assert result['last_updated'] == '2025-12-04T13:00'
    assert result['source'] == 'tnt_domestic_public'
    assert len(result['events']) == 6


def test_another_consignment_and_static_empty_timeline_are_unavailable():
    assert parse_history(fixture().replace('305506914', '999999999'), SHIPMENT)['availability'] == 'unavailable'
    result = parse_history('<div id="bodycontent_divSingle"><span>305506914</span><span>DELIVERED</span></div>', SHIPMENT)
    assert result['availability'] == 'unavailable'
    assert result['status'] is None


@pytest.mark.parametrize('status', [403, 429, 500])
def test_tnt_http_failures_are_sanitized(status):
    service = TntService(httpx.MockTransport(lambda _: httpx.Response(status, text='private provider detail')))
    result = service.query(SHIPMENT)
    assert result['availability'] == 'unavailable'
    assert f'HTTP {status}' in result['reason']
    assert 'private provider detail' not in result['reason']


def test_tnt_timeout_and_changed_form_degrade():
    def timeout(request):
        raise httpx.ReadTimeout('private', request=request)
    assert TntService(httpx.MockTransport(timeout)).query(SHIPMENT)['availability'] == 'unavailable'
    assert TntService(httpx.MockTransport(lambda _: httpx.Response(200, text='<html>changed form</html>'))).query(SHIPMENT)['availability'] == 'unavailable'


def test_foreign_redirect_is_not_followed_and_no_credentials_are_sent():
    def redirect(request):
        assert 'authorization' not in request.headers
        assert request.url == httpx.URL(TNT_TRACKING_URL)
        return httpx.Response(302, headers={'location': 'https://example.com/collect'})
    result = TntService(httpx.MockTransport(redirect)).query(SHIPMENT)
    assert result['availability'] == 'unavailable'


def test_invalid_tracking_number_does_not_call_provider():
    def forbidden(_):
        pytest.fail('Invalid domestic tracking number must not be submitted')
    result = TntService(httpx.MockTransport(forbidden)).query({**SHIPMENT, 'tracking_no': '<script>'})
    assert result['availability'] == 'unavailable'


def domestic_transport():
    """Minimal observed form contract; final history is the recorded real fragment."""
    def respond(request):
        assert request.url.host == 'www.tntexpress.com.au'
        assert 'authorization' not in request.headers
        if request.url.path == '/interaction/trackntrace.aspx' and request.method == 'GET':
            return httpx.Response(200, text='<input type="hidden" name="__VIEWSTATE" value="test-token"><button id="bodycontent_btnSubmit">Track</button>')
        if request.url.path == '/interaction/trackntrace.aspx':
            assert b'TextArea=305506914' in request.content
            assert b'ctl00%24bodycontent%24btnSubmit' in request.content
            return httpx.Response(302, headers={'location': '/interaction/trackntraceResult.aspx?con=test'})
        if request.url.path == '/interaction/trackntraceResult.aspx' and request.method == 'GET':
            return httpx.Response(200, text='<input type="hidden" name="__VIEWSTATE" value="next-token"><div id="bodycontent_divSingle"><label>CONSIGNMENT NUMBER <span>305506914</span></label></div><a id="bodycontent_A1">View Details</a>')
        if request.url.path == '/interaction/trackntraceResult.aspx':
            assert b'ctl00%24bodycontent%24A1' in request.content
            assert b'next-token' in request.content
            return httpx.Response(302, headers={'location': '/interaction/ConsignmentHistory.aspx?con=test'})
        assert request.url.path == '/interaction/ConsignmentHistory.aspx'
        assert request.method == 'GET'
        return httpx.Response(200, text=fixture())
    return httpx.MockTransport(respond)


def test_domestic_submission_and_history_path():
    result = TntService(domestic_transport()).query(SHIPMENT)
    assert result['status'] == "We've delivered your shipment"
    assert result['last_updated'] == '2025-12-04T13:00'
    assert len(result['events']) == 6
