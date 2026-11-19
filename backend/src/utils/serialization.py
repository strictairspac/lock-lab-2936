from decimal import Decimal
from datetime import datetime

def _json_safe(value):
    if isinstance(value, Decimal):
        # DECIMAL(12,2) 刻度内转 float 不丢精度（如 12.34、120.00）。
        return float(value)
    if hasattr(value, 'isoformat'):
        return value.isoformat()
    return value

def record(obj):
    return {col.name: _json_safe(getattr(obj, col.name)) for col in obj.__table__.columns}
