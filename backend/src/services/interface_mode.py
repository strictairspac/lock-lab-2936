"""接口模式与小数写入的并发控制。

需求口径：
- 两个接口（样本量、移交量）一起切换，模式只有 integer / decimal 两种，单行单版本。
- 切换失败沿用整数：任何前置条件不满足都抛 409，模式行保持 integer。
- 回退和小数写入撞在一起，谁先办成按谁的结果走，另一边报错。
  实现：两者在同一事务里取同一把 PostgreSQL 会话级咨询锁（74242），
  锁内重读模式并做条件更新（version 乐观校验），先提交者生效，后到者条件不成立 -> 报错。
"""
from sqlalchemy import text
from fastapi import HTTPException
from src.models.entities import InterfaceMode, Sample, Transfer, Audit

# 固定咨询锁键，仅本服务的切换/回退/小数写入三条路径使用。
WRITE_LOCK_KEY = 74242

def get_mode(db):
    row = db.get(InterfaceMode, 1)
    return row.mode if row else 'integer'

def snapshot(db):
    row = db.get(InterfaceMode, 1) or InterfaceMode(id=1, mode='integer', version=0)
    return {'mode': row.mode, 'version': row.version, 'updated_by': row.updated_by,
            'updated_at': row.updated_at.isoformat() if row.updated_at else None}

def _backfill_pending(db):
    """返回各表尚未回填的行数（NULL 标记即历史数据）。"""
    pending = {}
    for table, model in (('samples', Sample), ('transfers', Transfer)):
        pending[table] = db.query(model).filter(model.backfilled_at.is_(None)).count()
    return pending

def _acquire_write_lock(db):
    # 会话级咨询锁随事务提交/回滚自动释放；拿不到锁说明另一路径正在办理。
    locked = db.execute(text('SELECT pg_try_advisory_xact_lock(:k)'), {'k': WRITE_LOCK_KEY}).scalar()
    if not locked:
        raise HTTPException(409, '接口切换或回退正在办理，本次写入冲突，请按当前模式重试')

def switch_to_decimal(db, user):
    """两个接口一起切到小数。前置：历史数据回填全部完成，否则沿用整数并报错。"""
    _acquire_write_lock(db)
    row = db.get(InterfaceMode, 1)
    if row.mode == 'decimal':
        raise HTTPException(409, '小数接口已生效，无需重复切换')
    pending = _backfill_pending(db)
    if any(pending.values()):
        raise HTTPException(
            409, f"历史数据尚未回填完成，沿用整数接口（待回填：{pending}）"
        )
    row.mode = 'decimal'
    row.version += 1
    row.updated_by = user.email
    db.add(Audit(actor=user.email, action='接口切换 integer -> decimal（样本量/移交量同时生效）'))
    db.commit()
    return snapshot(db)

def rollback_to_integer(db, user):
    """回退到整数。与小数写互斥：先办成的生效，后到的一方报错。"""
    _acquire_write_lock(db)
    row = db.get(InterfaceMode, 1)
    if row.mode == 'integer':
        db.rollback()
        raise HTTPException(409, '当前已是整数接口，无需回退')
    row.mode = 'integer'
    row.version += 1
    row.updated_by = user.email
    db.add(Audit(actor=user.email, action='接口回退 decimal -> integer（恢复整数办理）'))
    db.commit()
    return snapshot(db)

def write_decimal(db):
    """v2 小数写入口：锁内确认当前确为 decimal 模式，否则拒绝（回退先办成的场景）。"""
    _acquire_write_lock(db)
    if get_mode(db) != 'decimal':
        db.rollback()
        raise HTTPException(409, '接口已回退为整数模式，本次小数写入失效，请改用整数接口重试')
