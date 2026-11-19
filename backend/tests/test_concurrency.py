"""并发对抗：回退撞小数写入（先到先得、另一边报错）、移交校验撞样本改量。"""
import threading
import time
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import text

from src.config.database import Session, engine
from src.services import interface_mode, samples as sample_service, transfers as transfer_service
from src.schemas.decimal_io import SampleInputV2, TransferInputV2


class _User:
    email = 'admin@qingyu.test'


def _set_decimal_mode():
    with Session() as db:
        row = db.get(interface_mode.InterfaceMode, 1)
        row.mode = 'decimal'
        row.version += 1
        db.commit()


def _make_sample(code='RACE-S', qty='50.00'):
    with Session() as db:
        db.execute(text(
            "INSERT INTO samples(code,title,quantity,location,backfilled_at) "
            "VALUES (:c,'并发样本',:q,'A-1',now())"), {'c': code, 'q': Decimal(qty)})
        db.commit()
        return db.execute(text("SELECT id FROM samples WHERE code=:c"), {'c': code}).scalar()


def test_rollback_first_wins_decimal_write_rejected():
    """确定性次序一：回退先持锁，小数写入立即 409。"""
    _set_decimal_mode()
    _make_sample('RB-1')
    outcome = {}

    with engine.begin() as holder:
        holder.execute(text('SELECT pg_advisory_xact_lock(:k)'),
                       {'k': interface_mode.WRITE_LOCK_KEY})

        def decimal_write():
            try:
                with Session() as db:
                    sample_service.create_v2(
                        db, SampleInputV2(code='RB-W1', title='小数写入',
                                          quantity=Decimal('1.23'), location='A-1'), _User)
                outcome['write'] = 'ok'
            except HTTPException as e:
                outcome['write'] = ('409', e.status_code, e.detail)

        t = threading.Thread(target=decimal_write)
        t.start(); t.join(10)
        # 回退尚未提交，但写锁被占，写入已失败
        assert outcome['write'][0] == '409' and outcome['write'][1] == 409

        # 持锁方完成回退
        mode_row = holder.execute(text('SELECT mode FROM interface_modes WHERE id=1 FOR UPDATE'))
        holder.execute(text("UPDATE interface_modes SET mode='integer', version=version+1 WHERE id=1"))

    with Session() as db:
        assert interface_mode.get_mode(db) == 'integer'
        # 回退办成后，新的小数写入同样被拒
        with pytest.raises(HTTPException) as exc:
            sample_service.create_v2(
                db, SampleInputV2(code='RB-W2', title='小数写入',
                                  quantity=Decimal('1.23'), location='A-1'), _User)
        assert exc.value.status_code == 409


def test_decimal_write_first_wins_rollback_rejected():
    """确定性次序二：小数写入先持锁（未提交），回退 409。"""
    _set_decimal_mode()
    _make_sample('RB-2')
    outcome = {}
    write_holds_lock = threading.Event()
    release_write = threading.Event()

    def decimal_write():
        try:
            with Session() as db:
                interface_mode.write_decimal(db)  # 拿到咨询锁
                db.execute(text(
                    "INSERT INTO samples(code,title,quantity,location,backfilled_at) "
                    "VALUES ('RB-W3','小数写入',1.23,'A-1',now())"))
                write_holds_lock.set()
                release_write.wait(10)
                db.commit()
            outcome['write'] = 'ok'
        except HTTPException as e:
            outcome['write'] = ('409', e.status_code, e.detail)

    t = threading.Thread(target=decimal_write)
    t.start()
    assert write_holds_lock.wait(5)
    try:
        with Session() as db:
            with pytest.raises(HTTPException) as exc:
                interface_mode.rollback_to_integer(db, _User)
            assert exc.value.status_code == 409
            assert interface_mode.get_mode(db) == 'decimal'
    finally:
        release_write.set(); t.join(10)

    with Session() as db:
        assert interface_mode.get_mode(db) == 'decimal'
        assert db.execute(text("SELECT count(*) FROM samples WHERE code='RB-W3'")).scalar() == 1


def test_free_race_exactly_one_side_wins_each_round():
    """自由竞争多轮：每轮回退与小数写入同时发起，恰一方成功，另一方 409，结果自洽。"""
    for round_no in range(5):
        _set_decimal_mode()
        barrier = threading.Barrier(2)
        results = {}

        def rollback_side():
            barrier.wait()
            try:
                with Session() as db:
                    interface_mode.rollback_to_integer(db, _User)
                results['rollback'] = 'ok'
            except HTTPException as e:
                results['rollback'] = f'err-{e.status_code}'

        def write_side():
            barrier.wait()
            try:
                with Session() as db:
                    sample_service.create_v2(
                        db, SampleInputV2(code=f'RACE-W{round_no}', title='竞写',
                                          quantity=Decimal('2.34'), location='A-1'), _User)
                results['write'] = 'ok'
            except HTTPException as e:
                results['write'] = f'err-{e.status_code}'

        threads = [threading.Thread(target=rollback_side), threading.Thread(target=write_side)]
        for t in threads: t.start()
        for t in threads: t.join(15)

        assert set(results.values()) == {'ok', 'err-409'}, results
        with Session() as db:
            mode = interface_mode.get_mode(db)
            sample_exists = db.execute(
                text("SELECT count(*) FROM samples WHERE code=:c"),
                {'c': f'RACE-W{round_no}'}).scalar() == 1
        # 模式与获胜方严格一致
        if results['rollback'] == 'ok':
            assert mode == 'integer' and not sample_exists
        else:
            assert mode == 'decimal' and sample_exists


def test_transfer_blocks_on_sample_change_and_uses_committed_quantity():
    """移交按当次生效的样本量校验：样本改量持锁期间移交等待，提交后按新量判定。"""
    _set_decimal_mode()
    sample_id = _make_sample('LOCK-S', '50.00')
    changed = threading.Event()
    release = threading.Event()

    def business_change():
        with engine.begin() as conn:
            conn.execute(text("SELECT id FROM samples WHERE id=:id FOR UPDATE"),
                         {'id': sample_id})
            conn.execute(text("UPDATE samples SET quantity=10.00 WHERE id=:id"),
                         {'id': sample_id})
            changed.set()
            release.wait(10)

    t = threading.Thread(target=business_change)
    t.start()
    assert changed.wait(5)
    try:
        def create_transfer(qty):
            with Session() as db:
                return transfer_service.create_v2(
                    db, TransferInputV2(code=f'T-{qty}', sample_id=sample_id,
                                        destination='理化检测室', quantity=Decimal(qty)), _User)

        # 30 > 新量 10：等待业务提交后按当次样本量拒绝
        start = time.perf_counter()
        box = {}
        def over_transfer():
            try: create_transfer('30.00')
            except HTTPException as e: box['err'] = e.status_code
        tt = threading.Thread(target=over_transfer)
        tt.start()
        time.sleep(0.5)  # 确认移交确实在等行锁，而不是立刻读到旧量
        assert 'err' not in box
        release.set(); tt.join(15); t.join(10)
        assert time.perf_counter() - start > 0.4
        assert box == {'err': 422}
    finally:
        release.set()

    # 业务提交后：5 <= 10，按新量通过
    with Session() as db:
        out = transfer_service.create_v2(
            db, TransferInputV2(code='T-OK', sample_id=sample_id,
                                destination='理化检测室', quantity=Decimal('5.00')), _User)
        assert float(out['quantity']) == 5.0
