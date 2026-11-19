"""002 数量精度升级的幂等迁移。

- 旧整数库：samples/transfers/trial_balances/receipts 的数量列 INTEGER -> DECIMAL(12,2)，
  并为 samples/transfers 增加 backfilled_at 回填标记列。
- 新库：SQLAlchemy metadata 已按新结构建表，本模块全部语句走 IF NOT EXISTS / 类型判断，重复执行无副作用。
- interface_modes 单行初始化为 integer（旧接口按整数办理），backfill_jobs 由回填服务按需创建。
"""
from sqlalchemy import text
from src.config.database import engine

QUANTITY_TABLES = {
    'samples': ['quantity'],
    'transfers': ['quantity'],
    'trial_balances': ['remaining', 'received'],
    'receipts': ['quantity'],
}
BACKFILL_TABLES = ('samples', 'transfers')

def _column_type(conn, table, column):
    return conn.execute(text(
        "SELECT data_type FROM information_schema.columns "
        "WHERE table_name=:t AND column_name=:c"
    ), {'t': table, 'c': column}).scalar()

def run_migrations():
    with engine.begin() as conn:
        for table, columns in QUANTITY_TABLES.items():
            for column in columns:
                kind = _column_type(conn, table, column)
                if kind is None:
                    continue  # 表尚未由 metadata 创建，create_all 会直接建成 DECIMAL
                if kind.upper() != 'NUMERIC':
                    conn.execute(text(
                        f'ALTER TABLE {table} ALTER COLUMN {column} TYPE DECIMAL(12,2) '
                        f'USING {column}::DECIMAL(12,2)'
                    ))
        for table in BACKFILL_TABLES:
            if _column_type(conn, table, 'backfilled_at') is None:
                conn.execute(text(f'ALTER TABLE {table} ADD COLUMN backfilled_at TIMESTAMPTZ'))
        exists = conn.execute(text(
            "SELECT 1 FROM information_schema.tables WHERE table_name='interface_modes'"
        )).scalar()
        if exists:
            seeded = conn.execute(text('SELECT count(*) FROM interface_modes')).scalar()
            if seeded == 0:
                conn.execute(text(
                    "INSERT INTO interface_modes(id,mode,version,updated_by) "
                    "VALUES (1,'integer',0,'system')"
                ))
