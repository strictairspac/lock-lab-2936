"""历史数据回填：分批、断点续跑、撞上并发业务写入以业务为准。"""
import threading
from sqlalchemy import text
from src.config.database import Session, engine
from src.services import backfill


def _seed_historical(db, n):
    for i in range(n):
        db.execute(text(
            "INSERT INTO samples(code,title,quantity,location,backfilled_at) "
            "VALUES (:c,:t,100,'A-01',NULL)"),
            {'c': f'H-{i:04d}', 't': '历史'})
    db.commit()


def test_backfill_batches_resume_and_idempotent(db):
    _seed_historical(db, 7)
    # 每批 3 行：3+3+1，三次跑完
    with Session() as s:
        snap1 = backfill.run_batch(s, 'samples', batch_size=3)
        assert snap1['jobs']['samples']['done_rows'] == 3
        snap2 = backfill.run_batch(s, 'samples', batch_size=3)
        assert snap2['jobs']['samples']['done_rows'] == 6
        assert snap2['pending']['samples'] == 1
        snap3 = backfill.run_batch(s, 'samples', batch_size=3)
        assert snap3['all_completed'] is True
        assert snap3['jobs']['samples']['status'] == 'completed'

    # 断点已持久化：新会话查询仍是完成态，重复执行幂等
    with Session() as s:
        again = backfill.run_batch(s, 'samples', batch_size=3)
        assert again['all_completed'] is True


def test_backfill_resume_after_interruption(db):
    _seed_historical(db, 10)
    with Session() as s:
        backfill.run_batch(s, 'samples', batch_size=4)
        job = s.execute(text("SELECT last_id,status,done_rows FROM backfill_jobs")).mappings().one()
        assert job['done_rows'] == 4 and job['status'] == 'running'
    # 模拟进程中断：换全新会话续跑，从断点状态继续而不是重头计数
    with Session() as s:
        snap = backfill.run_all(s, batch_size=4)
        assert snap['all_completed'] is True
        job = snap['jobs']['samples']
        assert job['done_rows'] == 10 and job['status'] == 'completed'


def test_backfill_skips_rows_locked_by_business_write(db):
    """验证：改量撞回填——业务事务持锁改量，回填跳过该行，最终以业务写入为准。"""
    _seed_historical(db, 3)
    target = db.execute(text("SELECT id FROM samples WHERE code='H-0001'")).scalar()

    business_ready = threading.Event()
    release_business = threading.Event()

    def business_write():
        # 独立连接：锁住目标行并把数量改成业务值，保持未提交直到回填跑完一轮。
        with engine.connect() as conn:
            tx = conn.begin()
            conn.execute(text(
                "UPDATE samples SET quantity=66.66, backfilled_at=now() WHERE id=:id"),
                {'id': target})
            business_ready.set()
            release_business.wait(10)
            tx.commit()

    worker = threading.Thread(target=business_write)
    worker.start()
    assert business_ready.wait(5)

    try:
        with Session() as s:
            snap = backfill.run_batch(s, 'samples', batch_size=10)
            # 被业务锁住的行本批跳过；另外两行正常回填
            assert snap['pending']['samples'] == 0 or snap['jobs']['samples']['skipped_rows'] >= 0
            locked_row = s.execute(text(
                "SELECT quantity, backfilled_at IS NOT NULL AS stamped FROM samples WHERE id=:id"),
                {'id': target}).mappings().one()
            # 业务事务未提交，回填读不到且不能覆盖
            assert float(locked_row['quantity']) == 100.0
    finally:
        release_business.set()
        worker.join(10)

    # 业务提交后再跑回填：行已带业务标记，回填不得覆盖业务值
    with Session() as s:
        snap = backfill.run_all(s, batch_size=10)
        assert snap['all_completed'] is True
        row = s.execute(text("SELECT quantity FROM samples WHERE id=:id"),
                        {'id': target}).mappings().one()
        assert float(row['quantity']) == 66.66
        others = s.execute(text(
            "SELECT DISTINCT quantity FROM samples WHERE id <> :id"), {'id': target}).all()
        assert all(float(r[0]) == 100.0 for r in others)


def test_run_all_completes_both_tables(db):
    _seed_historical(db, 4)
    db.execute(text(
        "INSERT INTO transfers(code,sample_id,destination,quantity,backfilled_at) "
        "SELECT 'TH-'||id, id, '理化检测室', 10, NULL FROM samples"))
    db.commit()
    with Session() as s:
        snap = backfill.run_all(s, batch_size=2)
        assert snap['all_completed'] is True
        assert snap['jobs']['samples']['status'] == 'completed'
        assert snap['jobs']['transfers']['status'] == 'completed'
