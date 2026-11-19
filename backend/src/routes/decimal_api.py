"""v2 小数接口：样本量与移交量支持两位小数，两个接口一起随模式切换生效。"""
from fastapi import APIRouter,Depends
from src.config.database import db_session
from src.utils.security import current,writer
from src.schemas.decimal_io import SampleInputV2, TransferInputV2
from src.services import samples as sample_service
from src.services import transfers as transfer_service
router=APIRouter(prefix='/v2')

@router.post('/samples',status_code=201)
def create_sample(data:SampleInputV2,db=Depends(db_session),user=Depends(writer)):
    return sample_service.create_v2(db,data,user)

@router.put('/samples/{ident}')
def update_sample(ident:int,data:SampleInputV2,db=Depends(db_session),user=Depends(writer)):
    return sample_service.update_v2(db,ident,data,user)

@router.post('/transfers',status_code=201)
def create_transfer(data:TransferInputV2,db=Depends(db_session),user=Depends(writer)):
    return transfer_service.create_v2(db,data,user)
