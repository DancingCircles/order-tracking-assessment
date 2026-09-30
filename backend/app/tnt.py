"""TNT Australia's public domestic tracking service (HTML, not ExpressConnect).

Only tracking and history are submitted. No login, booking or notification actions.
"""
from dataclasses import dataclass, field
from datetime import datetime
from html.parser import HTMLParser
import re
from urllib.parse import urljoin, urlsplit

import httpx

TNT_TRACKING_URL = 'https://www.tntexpress.com.au/interaction/trackntrace.aspx'
MAX_RESPONSE_BYTES = 2_000_000


class TntUnavailable(ValueError):
    """Only contains messages constructed locally, never a provider response."""


@dataclass
class Node:
    tag: str
    attrs: dict
    text: str = ''
    children: list = field(default_factory=list)

    def descendants(self, tag):
        for child in self.children:
            if child.tag == tag:
                yield child
            yield from child.descendants(tag)


class Page(HTMLParser):
    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.root = Node('document', {})
        self.stack = [self.root]
        self.ids = {}
        self.hidden = {}
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        node = Node(tag, attrs)
        self.stack[-1].children.append(node)
        if attrs.get('id'):
            self.ids[attrs['id']] = node
        if tag == 'input' and attrs.get('type', '').lower() == 'hidden' and attrs.get('name'):
            self.hidden[attrs['name']] = attrs.get('value', '')
        if tag not in ('area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'):
            self.stack.append(node)

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                self.stack = self.stack[:i]
                break

    def handle_data(self, data):
        for node in self.stack:
            node.text += data


def text(node):
    return ' '.join(node.text.split()) if node else ''


def empty_result(shipment, reason=None):
    return {**shipment, 'availability': 'unavailable', 'status': None,
            'last_updated': None, 'reason': reason, 'events': [], 'source': 'tnt_domestic_public'}


def parse_history(html, shipment):
    result = empty_result(shipment)
    page = Page(html)
    collection = page.ids.get('bodycontent_divcollection')
    headings = list(collection.descendants('h5')) if collection else []
    matching = any(re.fullmatch(r'Consignment:\s*' + re.escape(shipment['tracking_no']), text(h), re.I) for h in headings)
    if not matching:
        result['reason'] = 'TNT 未返回该单号的有效历史记录，或网站结构已变化'
        return result
    events = []
    for table in collection.descendants('table'):
        rows = list(table.descendants('tr'))
        if not rows or [text(c) for c in rows[0].children if c.tag in ('td', 'th')] != ['Status', 'Date & Time', 'Depot']:
            continue
        for row in rows[1:]:
            cells = [text(c) for c in row.children if c.tag == 'td']
            if len(cells) != 3 or not cells[0]:
                continue
            try:
                date = datetime.strptime(cells[1], '%d/%m/%Y %H:%M').isoformat(timespec='minutes')
            except ValueError:
                date = None
            events.append({'description': cells[0], 'date': date,
                           'location': cells[2], 'article_id': shipment['tracking_no']})
    if not events:
        result['reason'] = 'TNT 查询成功，但没有可用物流事件'
        return result
    dated = sorted((e for e in events if e['date']), key=lambda e: e['date'], reverse=True)
    undated = [e for e in events if not e['date']]
    # Without dates we cannot infer which event is current from labels or order.
    result.update(availability='available', status=dated[0]['description'] if dated else None,
                  last_updated=dated[0]['date'] if dated else None, events=dated + undated)
    return result


class TntService:
    def __init__(self, transport=None, enabled=True):
        self.transport = transport
        self.enabled = enabled

    @staticmethod
    def safe_url(url):
        parsed = urlsplit(url)
        if (parsed.scheme != 'https' or parsed.hostname != 'www.tntexpress.com.au'
                or parsed.port not in (None, 443) or parsed.username or parsed.password
                or parsed.path.lower() not in ('/interaction/trackntrace.aspx', '/interaction/trackntraceresult.aspx', '/interaction/consignmenthistory.aspx')):
            raise ValueError('TNT 查询跳转不符合预期')
        return url

    def request(self, client, method, url, data=None):
        for _ in range(4):
            response = client.request(method, self.safe_url(url), data=data)
            if response.status_code in (301, 302, 303):
                if not response.headers.get('location'):
                    raise ValueError('TNT 查询返回无效跳转')
                url = self.safe_url(urljoin(url, response.headers['location']))
                method, data = 'GET', None
                continue
            if response.status_code != 200:
                raise TntUnavailable(f'TNT 查询暂不可用（HTTP {response.status_code}）')
            if len(response.content) > MAX_RESPONSE_BYTES:
                raise ValueError('TNT 响应超出可处理大小')
            return response
        raise ValueError('TNT 查询跳转过多')

    def query(self, shipment):
        result = empty_result(shipment)
        if not self.enabled:
            result['reason'] = 'TNT 国内查询已通过环境变量停用；相关运费为 A$0.00'
            return result
        if not re.fullmatch(r'\d{9}', shipment.get('tracking_no', '')):
            result['reason'] = 'TNT 国内单号必须为九位数字'
            return result
        try:
            with httpx.Client(transport=self.transport, timeout=5.0, follow_redirects=False) as client:
                response = self.request(client, 'GET', TNT_TRACKING_URL)
                page = Page(response.text)
                if '__VIEWSTATE' not in page.hidden or 'bodycontent_btnSubmit' not in page.ids:
                    raise ValueError('TNT 查询表单不可用或网站结构已变化')
                response = self.request(client, 'POST', TNT_TRACKING_URL, {
                    **page.hidden, '__EVENTTARGET': 'ctl00$bodycontent$btnSubmit',
                    '__EVENTARGUMENT': '', 'TextArea': shipment['tracking_no'], 'method': 'CON',
                })
                page = Page(response.text)
                single = page.ids.get('bodycontent_divSingle')
                labels = list(single.descendants('label')) if single else []
                matching = any(re.fullmatch(r'CONSIGNMENT NUMBER\s*' + re.escape(shipment['tracking_no']), text(label), re.I) for label in labels)
                if not matching or 'bodycontent_A1' not in page.ids or '__VIEWSTATE' not in page.hidden:
                    raise ValueError('TNT 未找到该单号，或查询结果结构已变化')
                # The milestone timeline can be empty even when history exists.
                response = self.request(client, 'POST', str(response.url), {
                    **page.hidden, '__EVENTTARGET': 'ctl00$bodycontent$A1', '__EVENTARGUMENT': '',
                })
                return parse_history(response.text, shipment)
        except httpx.TimeoutException:
            result['reason'] = 'TNT 查询超时，请稍后重试'
        except httpx.RequestError:
            result['reason'] = '无法连接 TNT 国内查询服务'
        except TntUnavailable as exc:
            result['reason'] = str(exc)
        except (ValueError, TypeError, RecursionError):
            # No provider body, tokens or credentials are exposed.
            result['reason'] = 'TNT 查询结构无效或暂无有效记录'
        return result
