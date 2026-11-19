"""接口模式、v1/v2 输入校验与权限测试。"""
from decimal import Decimal
from sqlalchemy import text
from src.config.database import Session


def test_v1_accepts_integer_and_rejects_decimal(client, op_headers):
    r = client.post('/samples', headers=op_headers,
                    json={'code': 'S1', 'title': '整数样本', 'quantity': 100, 'location': 'A-1'})
    assert r.status_code == 201, r.text
    assert r.json()['quantity'] == 100.0

    r = client.post('/samples', headers=op_headers,
                    json={'code': 'S2', 'title': '小数被旧接口拒绝', 'quantity': 100.5, 'location': 'A-1'})
    assert r.status_code == 422, r.text


def test_v2_rejects_when_mode_integer(client, op_headers):
    r = client.post('/v2/samples', headers=op_headers,
                    json={'code': 'D1', 'title': '切换前的小数写入', 'quantity': 12.34, 'location': 'A-1'})
    assert r.status_code == 409, r.text
    assert '整数' in r.json()['detail']


def test_v2_two_decimal_places_validation(client, admin_headers, op_headers, db, legacy_sample):
    # 回填完成后两接口一起切换
    client.post('/backfill/run', headers=admin_headers)
    client.post('/backfill/run', headers=admin_headers)
    r = client.post('/interface/switch-decimal', headers=admin_headers)
    assert r.status_code == 200 and r.json()['mode'] == 'decimal'

    r = client.post('/v2/samples', headers=op_headers,
                    json={'code': 'D2', 'title': '两位小数', 'quantity': 88.88, 'location': 'A-2'})
    assert r.status_code == 201, r.text
    assert r.json()['quantity'] == 88.88

    # 超过两位小数
    r = client.post('/v2/samples', headers=op_headers,
                    json={'code': 'D3', 'title': '三位小数', 'quantity': 1.234, 'location': 'A-2'})
    assert r.status_code == 422
    # 零与负数
    r = client.post('/v2/samples', headers=op_headers,
                    json={'code': 'D4', 'title': '零量', 'quantity': 0, 'location': 'A-2'})
    assert r.status_code == 422


def test_switch_requires_backfill_complete_and_keeps_integer(client, admin_headers, legacy_sample):
    r = client.post('/interface/switch-decimal', headers=admin_headers)
    assert r.status_code == 409
    mode = client.get('/interface/current', headers=admin_headers).json()
    assert mode['mode'] == 'integer' and mode['version'] == 0


def test_two_interfaces_switch_together(client, admin_headers, op_headers, db, legacy_sample):
    client.post('/backfill/run', headers=admin_headers)
    client.post('/backfill/run', headers=admin_headers)
    assert client.post('/interface/switch-decimal', headers=admin_headers).json()['mode'] == 'decimal'
    # v1 旧接口仍在，但按整数办理
    r = client.post('/samples', headers=op_headers,
                    json={'code': 'V1-STILL', 'title': '旧路径整数', 'quantity': 5, 'location': 'A-3'})
    assert r.status_code == 201 and r.json()['quantity'] == 5.0
    # 两接口都接受小数
    r1 = client.post('/v2/samples', headers=op_headers,
                     json={'code': 'V2-S', 'title': '小数样本', 'quantity': 1.5, 'location': 'A-3'})
    assert r1.status_code == 201
    r2 = client.post('/v2/transfers', headers=op_headers,
                     json={'code': 'V2-T', 'sample_id': r1.json()['id'],
                           'destination': '理化检测室', 'quantity': 1.25})
    assert r2.status_code == 201 and r2.json()['quantity'] == 1.25


def test_admin_only_endpoints(client, viewer_headers, op_headers, admin_headers):
    for path, method in (('/interface/mode', 'get'), ('/backfill/status', 'get'),
                         ('/interface/switch-decimal', 'post'), ('/backfill/run', 'post')):
        r = getattr(client, method)(path, headers=viewer_headers)
        assert r.status_code == 403, (path, r.status_code)
    # 普通操作员也不能切换
    assert client.post('/interface/switch-decimal', headers=op_headers).status_code == 403
    # 所有人可读当前模式
    assert client.get('/interface/current', headers=viewer_headers).status_code == 200


def test_transfer_validated_against_effective_sample_quantity(client, admin_headers, op_headers, db, legacy_sample):
    client.post('/backfill/run', headers=admin_headers)
    client.post('/backfill/run', headers=admin_headers)
    client.post('/interface/switch-decimal', headers=admin_headers)
    # 样本量 12.5；移交 12.5 恰好通过，12.51 被拒
    r = client.put('/v2/samples/' + str(legacy_sample), headers=op_headers,
                   json={'code': 'HIST-1', 'title': '历史样本', 'quantity': 12.5, 'location': 'A-01'})
    assert r.status_code == 200, r.text
    ok = client.post('/v2/transfers', headers=op_headers,
                     json={'code': 'T-OK', 'sample_id': legacy_sample,
                           'destination': '理化检测室', 'quantity': 12.5})
    assert ok.status_code == 201, ok.text
    bad = client.post('/v2/transfers', headers=op_headers,
                      json={'code': 'T-BAD', 'sample_id': legacy_sample,
                            'destination': '理化检测室', 'quantity': 12.51})
    assert bad.status_code == 422
