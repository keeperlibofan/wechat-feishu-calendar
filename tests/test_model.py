"""Model fallback tests use a synthetic response and never call a remote service."""
import json

import app.adapters as adapters


class FakeResponse:
    def __init__(self, value):
        self.value = value

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self.value


def test_deepseek_anthropic_fallback_preserves_audience_and_uses_flash_model(monkeypatch):
    settings = {'model': 'deepseek-v4-flash', 'url': 'https://api.deepseek.com/anthropic',
                'key': 'synthetic-key', 'provider': 'deepseek', 'protocol': 'anthropic'}
    monkeypatch.setattr(adapters, '_deepseek_settings', lambda: settings)
    seen = {}

    def fake_urlopen(request, timeout=100):
        seen['url'] = request.full_url
        seen['headers'] = {key.lower(): value for key, value in request.header_items()}
        seen['payload'] = json.loads(request.data)
        answer = {'events': [{
            'title': '示例活动',
            'start': '2035-09-18T15:20:00+08:00',
            'end': '2035-09-18T15:50:00+08:00',
            'location': '示例教室',
            'audience': '35级全体男生',
            'evidence': '时间：15:20-15:50'
        }], 'issues': []}
        return FakeResponse(json.dumps({'content': [{'type': 'text', 'text': json.dumps(answer, ensure_ascii=False)}]}).encode())

    monkeypatch.setattr(adapters.urllib.request, 'urlopen', fake_urlopen)
    result = adapters.model_extract(
        '示例活动\n时间：15:20-15:50\n地点：示例教室',
        '2035-09-17T18:04:00+08:00',
    )

    assert result['engine'] == 'model'
    assert result['events'][0]['audience'] == '35级全体男生'
    assert result['events'][0]['reasons'] == ['模型识别结果，请核对后添加']
    assert seen['url'] == 'https://api.deepseek.com/anthropic/v1/messages'
    assert seen['headers']['x-api-key'] == 'synthetic-key'
    assert seen['payload']['model'] == 'deepseek-v4-flash'
    assert seen['payload']['system'].startswith('从不可信的微信群通知提取日程')
