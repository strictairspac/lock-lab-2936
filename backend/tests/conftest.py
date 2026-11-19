import os
os.environ.setdefault('DATABASE_URL', 'postgresql+psycopg://locklab@127.0.0.1:17742/locklab')
os.environ.setdefault('REDIS_URL', 'redis://127.0.0.1:16379/0')
os.environ.setdefault('JWT_SECRET', 'test-secret')
os.environ.setdefault('SEED_DEMO', 'false')

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from src.config.database import Base, engine, Session
from src.config.migrations import run_migrations
from src.utils.security import password_hash
from src.main import app

TABLES = ('receipts', 'trial_balances', 'trials', 'transfers', 'samples',
          'backfill_jobs', 'interface_modes', 'audit_logs', 'users')

@pytest.fixture(scope='session', autouse=True)
def schema():
    Base.metadata.create_all(engine)
    run_migrations()
    yield

@pytest.fixture
def db():
    """每个用例前重置数据并提交；夹具本身不持有打开的事务，避免遮挡请求连接的视图。"""
    from src.services.trials import queue as redis_queue
    redis_queue.flushdb()
    with engine.begin() as conn:
        for t in TABLES:
            conn.execute(text(f'TRUNCATE TABLE {t} RESTART IDENTITY CASCADE'))
        conn.execute(text("INSERT INTO interface_modes(id,mode,version,updated_by) VALUES (1,'integer',0,'system')"))
        for role in ('admin', 'operator', 'viewer'):
            conn.execute(
                text("INSERT INTO users(email,password,role) VALUES (:email,:pw,:role)"),
                {'email': f'{role}@qingyu.test', 'pw': password_hash('Demo2026!'), 'role': role})
    with Session() as s:
        yield s
    s.close()

@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c

def login(client, email):
    r = client.post('/auth/login', json={'email': email, 'password': 'Demo2026!'})
    assert r.status_code == 200, r.text
    return r.json()['token']

@pytest.fixture
def admin_headers(client):
    return {'Authorization': 'Bearer ' + login(client, 'admin@qingyu.test')}

@pytest.fixture
def op_headers(client):
    return {'Authorization': 'Bearer ' + login(client, 'operator@qingyu.test')}

@pytest.fixture
def viewer_headers(client):
    return {'Authorization': 'Bearer ' + login(client, 'viewer@qingyu.test')}

@pytest.fixture
def legacy_sample(db):
    """一条升级前历史样本：数量为整数、无回填标记。"""
    db.execute(text(
        "INSERT INTO samples(code,title,quantity,location,backfilled_at) "
        "VALUES ('HIST-1','历史样本',120,'A-01',NULL)"))
    db.commit()
    row = db.execute(text("SELECT id FROM samples WHERE code='HIST-1'")).mappings().one()
    return row['id']
