"""历史数量回填的离线入口：循环分批直到完成，中断后重新执行即从断点续跑。

用法（backend 目录）：
    python -m scripts.backfill_history
    python -m scripts.backfill_history --batch-size=50
"""
import sys, time
from src.config.database import Session
from src.services import backfill

def main(batch_size=backfill.BATCH_SIZE, max_idle_rounds=50):
    idle_rounds = 0
    while True:
        with Session() as db:
            snap = backfill.run_all(db, batch_size)
        print(snap)
        if snap['all_completed']:
            print('backfill completed')
            return 0
        # 本轮回填没有推进（剩余行均被业务事务锁定）：让出后从断点续跑，不覆盖业务写入。
        progressed = any(j.get('processed_this_batch', 0) for j in snap['jobs'].values())
        idle_rounds = idle_rounds + 1 if not progressed else 0
        if idle_rounds >= max_idle_rounds:
            print('backfill paused: rows locked by business transactions; rerun later to resume')
            return 2
        time.sleep(0.2)

if __name__ == '__main__':
    args = [a for a in sys.argv[1:] if a.startswith('--batch-size=')]
    size = int(args[0].split('=', 1)[1]) if args else backfill.BATCH_SIZE
    raise SystemExit(main(size))
