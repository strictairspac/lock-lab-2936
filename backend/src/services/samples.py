from sqlalchemy import select
from fastapi import HTTPException
from datetime import datetime, timezone
from src.models.entities import Sample
from .common import save
from src.utils.serialization import record
from src.services.interface_mode import write_decimal

def listing(db): return [record(x) for x in db.scalars(select(Sample).order_by(Sample.id))]

def _stamp_business(obj):
    # 业务写入的行自带最新刻度与标记，回填作业不再处理（以业务写入为准）。
    obj.backfilled_at = datetime.now(timezone.utc)

# v1：升级期间旧接口照常按整数办理。
def create(db,data,user):
    obj = Sample(**data.model_dump())
    _stamp_business(obj)
    return save(db,obj,user,'创建样本 '+data.code)

def update(db,ident,data,user):
    obj=db.get(Sample,ident)
    if not obj: raise HTTPException(404,'样本不存在')
    for k,v in data.model_dump().items(): setattr(obj,k,v)
    _stamp_business(obj)
    return save(db,obj,user,'更新样本 '+data.code)

# v2：小数写入。咨询锁内确认 decimal 模式仍生效（回退先办成则在此报错）。
def create_v2(db,data,user):
    write_decimal(db)
    obj = Sample(**data.model_dump())
    _stamp_business(obj)
    return save(db,obj,user,'创建样本(小数) '+data.code)

def update_v2(db,ident,data,user):
    write_decimal(db)
    obj=db.get(Sample,ident)
    if not obj:
        db.rollback()
        raise HTTPException(404,'样本不存在')
    for k,v in data.model_dump().items(): setattr(obj,k,v)
    _stamp_business(obj)
    return save(db,obj,user,'更新样本(小数) '+data.code)
