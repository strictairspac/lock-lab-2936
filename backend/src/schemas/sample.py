from pydantic import BaseModel, Field
# v1：升级期间旧接口照常按整数办理，拒绝小数输入。
class SampleInput(BaseModel):
    code: str=Field(min_length=2,max_length=80)
    title: str=Field(min_length=2,max_length=160)
    quantity: int=Field(ge=1,le=100000)
    location: str=Field(min_length=1,max_length=120)
