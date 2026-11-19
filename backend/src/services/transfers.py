from sqlalchemy import select
from fastapi import HTTPException
from datetime import datetime, timezone
from src.models.entities import Transfer,Sample
from src.utils.serialization import record
from .common import save
from src.services.interface_mode import write_decimal

def listing(db): return [record(x) for x in db.scalars(select(Transfer).order_by(Transfer.id))]

def _validate_against_live_sample(db, sample_id, quantity):
    # 移交按当次生效的样本量校验：锁定样本行，阻塞并发改量，读到的 quantity 即本次办理口径。
    sample = db.execute(
        select(Sample).where(Sample.id == sample_id).with_for_update()
    ).scalar_one_or_none()
    if not sample:
        raise HTTPException(404,'样本不存在')
    if quantity > sample.quantity:
        db.rollback()
        raise HTTPException(422,'移交量超过样本可用量')
    return sample

# v1：旧整数接口。
def create(db,data,user):
    payload=data.model_dump()
    _validate_against_live_sample(db, payload['sample_id'], payload['quantity'])
    obj=Transfer(**payload)
    obj.backfilled_at=datetime.now(timezone.utc)
    return save(db,obj,user,'创建流转申请 '+data.code)

# v2：小数接口，锁内先确认模式仍为 decimal，再按当次样本量校验。
def create_v2(db,data,user):
    write_decimal(db)
    payload=data.model_dump()
    _validate_against_live_sample(db, payload['sample_id'], payload['quantity'])
    obj=Transfer(**payload)
    obj.backfilled_at=datetime.now(timezone.utc)
    return save(db,obj,user,'创建流转申请(小数) '+data.code)
