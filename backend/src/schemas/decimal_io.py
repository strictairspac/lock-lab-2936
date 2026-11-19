from decimal import Decimal
from pydantic import BaseModel, Field, field_validator

# v2：样本量/移交量支持两位小数；超过两位刻度直接判输入错误。
def two_places(value: Decimal) -> Decimal:
    if value is None:
        return value
    if value.as_tuple().exponent < -2:
        raise ValueError('数量最多保留两位小数')
    return value.quantize(Decimal('0.01'))

class SampleInputV2(BaseModel):
    code: str=Field(min_length=2,max_length=80)
    title: str=Field(min_length=2,max_length=160)
    quantity: Decimal=Field(gt=0,le=Decimal('100000'))
    location: str=Field(min_length=1,max_length=120)
    _normalize=field_validator('quantity')(lambda cls,v: two_places(v))

class TransferInputV2(BaseModel):
    code: str=Field(min_length=2,max_length=80)
    sample_id: int=Field(gt=0)
    destination: str=Field(min_length=2,max_length=120)
    quantity: Decimal=Field(gt=0,le=Decimal('100000'))
    note: str=Field(default='',max_length=300)
    _normalize=field_validator('quantity')(lambda cls,v: two_places(v))
