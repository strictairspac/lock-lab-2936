"""小数数量下的并发演练不变量，以及 worker 队列端到端。"""
import json
import os
import socket
import subprocess
import sys
import time
from decimal import Decimal

from sqlalchemy import text

from src.config.database import Session, engine
from src.models.entities import Sample, Transfer, Trial, TrialBalance, Receipt
from src.services import trials as trial_service
from src.services.concurrency import execute
from src.schemas.trial import TrialInput


def _decimal_prerequisites(db):
    db.execute(text(
        "INSERT INTO samples(code,title,quantity,location,backfilled_at) "
        "VALUES ('DEC-1','小数样本',100.00,'A-1',now())"))
    db.commit()
    sample_id = db.execute(text("SELECT id FROM samples WHERE code='DEC-1'")).scalar()
    db.execute(text(
        "INSERT INTO transfers(code,sample_id,destination,quantity,note,backfilled_at) "
        "VALUES ('DEC-T1',:sid,'理化检测室',30.50,'',now())"), {'sid': sample_id})
    db.commit()
    transfer_id = db.execute(text("SELECT id FROM transfers WHERE code='DEC-T1'")).scalar()
    return sample_id, transfer_id


def test_decimal_trial_invariant(db, monkeypatch):
    _, transfer_id = _decimal_prerequisites(db)
    # 不经 Redis 队列，避免环境中的常驻 worker 抢先执行同一演练。
    monkeypatch.setattr(trial_service, 'queue', type('DummyQueue', (), {
        'rpush': lambda *a, **k: 1})())
    with Session() as s:
        saved = trial_service.create(
            s, TrialInput(name='decimal-trial', transfer_id=transfer_id, timeout_ms=250),
            type('U', (), {'email': 'operator@qingyu.test'})())
        trial_id = saved['id']
    result = execute(trial_id)
    assert result['invariant_passed'] is True
    assert result['initial'] == 100.0
    assert result['transfer_quantity'] == 30.5
    assert result['remaining'] == 69.5 and result['received'] == 30.5
    assert result['receipt_count'] == 1
    # 数据库中确为两位小数刻度
    with engine.connect() as conn:
        balance = conn.execute(text(
            "SELECT remaining,received FROM trial_balances WHERE trial_id=:id"),
            {'id': trial_id}).one()
        assert balance.remaining == Decimal('69.50')
        assert balance.received == Decimal('30.50')
        receipts = conn.execute(text(
            "SELECT actor,quantity FROM receipts WHERE trial_id=:id ORDER BY actor"),
            {'id': trial_id}).all()
        assert receipts == [('A', Decimal('30.50'))]


def test_worker_end_to_end_with_decimal_queue(db, monkeypatch):
    _, transfer_id = _decimal_prerequisites(db)
    artifact_dir = '/tmp/locklab-test-artifacts'
    os.makedirs(artifact_dir, exist_ok=True)
    # 独立 Redis DB，避免环境里常驻 worker 抢走本测试的队列消息。
    iso_url = os.environ['REDIS_URL'].rsplit('/', 1)[0] + '/14'
    from redis import Redis
    iso_queue = Redis.from_url(iso_url, decode_responses=True)
    iso_queue.flushdb()
    monkeypatch.setattr(trial_service, 'queue', iso_queue)
    env = dict(os.environ, ARTIFACT_DIR=artifact_dir, REDIS_URL=iso_url)
    proc = subprocess.Popen(
        [sys.executable, '-m', 'src.worker'], cwd='/workspace/backend',
        env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    try:
        with Session() as s:
            saved = trial_service.create(
                s, TrialInput(name='worker-decimal', transfer_id=transfer_id, timeout_ms=250),
                type('U', (), {'email': 'operator@qingyu.test'})())
            trial_id = saved['id']
        deadline = time.time() + 30
        while time.time() < deadline:
            with Session() as s:
                trial = s.get(Trial, trial_id)
                if trial.status in ('completed', 'failed'):
                    break
            time.sleep(0.5)
        with Session() as s:
            trial = s.get(Trial, trial_id)
            assert trial.status == 'completed', trial.error
            assert trial.result['invariant_passed'] is True
        path = os.path.join(artifact_dir, f'trial-{trial_id}.json')
        assert os.path.exists(path)
        payload = json.loads(open(path, encoding='utf-8').read())
        assert payload['remaining'] == 69.5
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        iso_queue.flushdb()
