from sqlalchemy import select,func
from src.config.database import Session,Base,engine
from src.config.migrations import run_migrations
from src.models.entities import User,Sample,Transfer,Trial,InterfaceMode
from src.utils.security import password_hash

def seed():
    Base.metadata.create_all(engine)
    run_migrations()
    with Session() as db:
        for role in ('admin','operator','viewer'):
            email=role+'@qingyu.test'
            if not db.scalar(select(User).where(User.email==email)):
                db.add(User(email=email,password=password_hash('Demo2026!'),role=role))
        # 演示数据视为升级前的历史数据：不写 backfilled_at，交由回填作业分批处理。
        samples=[('QY-261117-A','近海水质留样 · A组',120,'冷藏间 A-03'),('QY-261117-B','土壤重金属平行样',80,'样本柜 B-12'),('QY-261117-C','饮用水复测留样',60,'冷藏间 A-07')]
        for code,title,qty,loc in samples:
            if not db.scalar(select(Sample).where(Sample.code==code)): db.add(Sample(code=code,title=title,quantity=qty,location=loc))
        db.flush()
        for i,(code,_,_,_) in enumerate(samples):
            req=f'MOVE-1117-{i+1:02}'
            if not db.scalar(select(Transfer).where(Transfer.code==req)):
                sample=db.scalar(select(Sample).where(Sample.code==code))
                db.add(Transfer(code=req,sample_id=sample.id,destination=['理化检测室','金属分析室','复核室'][i],quantity=[30,20,15][i],note='09:15 交接班复核'))
        if not db.get(InterfaceMode,1):
            db.add(InterfaceMode(id=1,mode='integer',version=0,updated_by='system'))
        db.commit()
        counts={cls.__tablename__:db.scalar(select(func.count()).select_from(cls)) for cls in (User,Sample,Transfer,Trial)}
        print(counts)
if __name__=='__main__': seed()
