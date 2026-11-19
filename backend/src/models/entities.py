from sqlalchemy import Column, Integer, String, JSON, DateTime, ForeignKey, Text, Numeric, UniqueConstraint
from datetime import datetime, timezone
from src.config.database import Base

# 数量统一为 DECIMAL(12,2)：v1 整数接口写入 12.00，v2 小数接口可写 12.34。
QUANTITY = Numeric(12, 2)

def utcnow():
    return datetime.now(timezone.utc)

class User(Base):
    __tablename__='users'
    id=Column(Integer,primary_key=True);email=Column(String(120),unique=True,nullable=False)
    password=Column(String(300),nullable=False);role=Column(String(20),nullable=False)
class Sample(Base):
    __tablename__='samples'
    id=Column(Integer,primary_key=True);code=Column(String(80),unique=True,nullable=False)
    title=Column(String(160),nullable=False);quantity=Column(QUANTITY,nullable=False);location=Column(String(120),nullable=False)
    # 历史数据回填标记：NULL=尚未回填；回填批次写入时间戳，业务并发写入的行以业务为准（回填跳过）。
    backfilled_at=Column(DateTime(timezone=True),nullable=True)
class Transfer(Base):
    __tablename__='transfers'
    id=Column(Integer,primary_key=True);code=Column(String(80),unique=True,nullable=False)
    sample_id=Column(Integer,ForeignKey('samples.id'),nullable=False);destination=Column(String(120),nullable=False)
    quantity=Column(QUANTITY,nullable=False);note=Column(String(300),default='')
    backfilled_at=Column(DateTime(timezone=True),nullable=True)
class Trial(Base):
    __tablename__='trials'
    id=Column(Integer,primary_key=True);name=Column(String(120),nullable=False)
    transfer_id=Column(Integer,ForeignKey('transfers.id'),nullable=False);timeout_ms=Column(Integer,nullable=False)
    status=Column(String(20),default='queued',nullable=False);result=Column(JSON,nullable=True)
    created_at=Column(DateTime(timezone=True),default=utcnow);error=Column(Text,default='')
class TrialBalance(Base):
    __tablename__='trial_balances'
    trial_id=Column(Integer,ForeignKey('trials.id'),primary_key=True);remaining=Column(QUANTITY,nullable=False);received=Column(QUANTITY,nullable=False,default=0)
class Receipt(Base):
    __tablename__='receipts'
    id=Column(Integer,primary_key=True);trial_id=Column(Integer,ForeignKey('trials.id'),nullable=False)
    actor=Column(String(20),nullable=False);quantity=Column(QUANTITY,nullable=False)
    __table_args__=(UniqueConstraint('trial_id','actor'),)
class Audit(Base):
    __tablename__='audit_logs'
    id=Column(Integer,primary_key=True);actor=Column(String(120),nullable=False);action=Column(String(160),nullable=False)
    created_at=Column(DateTime(timezone=True),default=utcnow)
class InterfaceMode(Base):
    """接口模式单行表（id 恒为 1）。integer=旧整数接口生效；decimal=两个新小数接口同时生效。"""
    __tablename__='interface_modes'
    id=Column(Integer,primary_key=True)
    mode=Column(String(20),nullable=False,default='integer')
    version=Column(Integer,nullable=False,default=0)
    updated_at=Column(DateTime(timezone=True),default=utcnow,onupdate=utcnow)
    updated_by=Column(String(120),nullable=False,default='system')
class BackfillJob(Base):
    """历史数量回填的断点续跑记录。last_id 之前的行均已处理（含因业务写入而跳过的行）。"""
    __tablename__='backfill_jobs'
    id=Column(Integer,primary_key=True)
    table_name=Column(String(40),nullable=False)
    last_id=Column(Integer,nullable=False,default=0)
    total_rows=Column(Integer,nullable=False,default=0)
    done_rows=Column(Integer,nullable=False,default=0)
    skipped_rows=Column(Integer,nullable=False,default=0)
    status=Column(String(20),nullable=False,default='running')
    started_at=Column(DateTime(timezone=True),default=utcnow)
    finished_at=Column(DateTime(timezone=True),nullable=True)
    last_error=Column(Text,default='')
