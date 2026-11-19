"""历史数量分批回填。

口径：
- DECIMAL 列升级后历史整数已可直接读写；回填的职责是把 backfilled_at 标记补齐，
  让接口切换的前置条件（无历史未回填行）可判定，并把数量规范化为两位小数刻度。
- 分批处理，进度记录在 backfill_jobs（last_id 断点），中断后再次调用从断点续跑。
- 撞上并发业务写入：业务事务持有的行锁用 FOR UPDATE SKIP LOCKED 识别，回填本批跳过该行，
  等业务提交后下一轮（或下次续跑）再按业务已提交的值补标记——以业务写入为准，回填不覆盖。
"""
from sqlalchemy import text, select
from fastapi import HTTPException
from src.models.entities import BackfillJob
from src.services.interface_mode import get_mode

TABLES = ('samples', 'transfers')
BATCH_SIZE = 200

def _get_or_create_job(db, table_name):
    job = db.scalar(select(BackfillJob).where(BackfillJob.table_name == table_name).order_by(BackfillJob.id.desc()))
    if job and job.status == 'completed':
        # 完成后若又出现未回填行（升级期新写入），原地续跑而不是新建作业。
        pending = db.execute(text(
            f"SELECT count(*) FROM {table_name} WHERE backfilled_at IS NULL"
        )).scalar()
        if pending == 0:
            return job, False
        job.status = 'running'
        job.finished_at = None
        db.commit()
        db.refresh(job)
        return job, True
    if not job:
        total = db.execute(text(f'SELECT count(*) FROM {table_name}')).scalar()
        job = BackfillJob(table_name=table_name, total_rows=total, status='running')
        db.add(job)
        db.commit()
        db.refresh(job)
    return job, True

def run_batch(db, table_name, batch_size=BATCH_SIZE):
    if table_name not in TABLES:
        raise HTTPException(404, '回填目标表不存在')
    job, active = _get_or_create_job(db, table_name)
    if not active:
        return status(db)
    # 新增行可能晚于建档时的 total_rows，每轮刷新总量。
    job.total_rows = db.execute(text(f'SELECT count(*) FROM {table_name}')).scalar()
    # 每轮只挑未回填行；SKIP LOCKED 让被并发业务事务锁住的行本批直接让出。
    # 不用 id 游标：被跳过的行 id 可能更小，按 NULL 标记重选才能保证不遗漏、可续跑。
    rows = db.execute(text(
        f"SELECT id FROM {table_name} WHERE backfilled_at IS NULL "
        f"ORDER BY id LIMIT :limit FOR UPDATE SKIP LOCKED"
    ), {'limit': batch_size}).mappings().all()
    processed = 0
    skipped = 0
    max_id = job.last_id
    for row in rows:
        rid = row['id']
        # 规范化数量刻度（保留两位小数，值本身不变），并补回填标记。
        updated = db.execute(text(
            f"UPDATE {table_name} SET quantity = quantity::DECIMAL(12,2), "
            f"backfilled_at = now() WHERE id = :id AND backfilled_at IS NULL"
        ), {'id': rid})
        if updated.rowcount == 1:
            processed += 1
        else:
            skipped += 1
        max_id = max(max_id, rid)
    job.last_id = max_id
    job.done_rows += processed
    job.skipped_rows += skipped
    remaining = db.execute(text(
        f"SELECT count(*) FROM {table_name} WHERE backfilled_at IS NULL"
    )).scalar()
    if remaining == 0:
        job.status = 'completed'
        from datetime import datetime, timezone
        job.finished_at = datetime.now(timezone.utc)
    db.commit()
    snap = status(db)
    snap['jobs'][table_name]['processed_this_batch'] = processed
    snap['jobs'][table_name]['skipped_this_batch'] = skipped
    return snap

def run_all(db, batch_size=BATCH_SIZE):
    """逐表分批跑完；任意一批失败时断点保留，下次调用继续。"""
    for table_name in TABLES:
        while True:
            snap = run_batch(db, table_name, batch_size)
            job = snap['jobs'].get(table_name)
            if not job or job['status'] == 'completed':
                break
            if job['processed_this_batch'] == 0 and job['pending'] > 0:
                # 所有待办行都被业务锁住：让出，待续跑处理，不算失败。
                break
    return status(db)

def status(db):
    jobs = {j.table_name: {
        'id': j.id, 'last_id': j.last_id, 'total_rows': j.total_rows,
        'done_rows': j.done_rows, 'skipped_rows': j.skipped_rows,
        'status': j.status,
        'finished_at': j.finished_at.isoformat() if j.finished_at else None,
        'last_error': j.last_error,
    } for j in db.scalars(select(BackfillJob).order_by(BackfillJob.id))}
    pending = {}
    for table_name in TABLES:
        pending[table_name] = db.execute(text(
            f"SELECT count(*) FROM {table_name} WHERE backfilled_at IS NULL"
        )).scalar()
    # 最近一轮处理量由调用方临时附加；这里给默认值便于断点轮询。
    for table_name, job in jobs.items():
        job.setdefault('processed_this_batch', 0)
        job['pending'] = pending[table_name]
    return {
        'mode': get_mode(db),
        'pending': pending,
        'all_completed': all(v == 0 for v in pending.values()),
        'jobs': jobs,
    }
