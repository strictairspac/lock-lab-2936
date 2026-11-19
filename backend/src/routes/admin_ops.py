"""接口模式切换与历史数据回填管理（仅管理员）。"""
from fastapi import APIRouter,Depends
from src.config.database import db_session
from src.utils.security import admin, current
from src.services import interface_mode, backfill
router=APIRouter()

@router.get('/interface/current')
def current_mode(db=Depends(db_session),user=Depends(current)):
    # 所有登录用户均可读取当前生效模式，前端据此选择 v1/v2 接口。
    return interface_mode.snapshot(db)

@router.get('/interface/mode')
def mode(db=Depends(db_session),user=Depends(admin)):
    return interface_mode.snapshot(db)

@router.post('/interface/switch-decimal')
def switch_decimal(db=Depends(db_session),user=Depends(admin)):
    return interface_mode.switch_to_decimal(db,user)

@router.post('/interface/rollback-integer')
def rollback_integer(db=Depends(db_session),user=Depends(admin)):
    return interface_mode.rollback_to_integer(db,user)

@router.get('/backfill/status')
def backfill_status(db=Depends(db_session),user=Depends(admin)):
    return backfill.status(db)

@router.post('/backfill/run')
def backfill_run(db=Depends(db_session),user=Depends(admin)):
    # 每次请求各推一批；前端/脚本轮询直到 all_completed，天然支持中断续跑。
    backfill.run_batch(db, 'samples')
    return backfill.run_batch(db, 'transfers')
