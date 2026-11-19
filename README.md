# 实验样本流转并发台

青屿检测样本中心（24 人）的样本移交复核工作台。原生 HTML/CSS/JavaScript 前端，Python FastAPI 后端，真实 PostgreSQL 两连接事务与行锁演练。

## 场景和模块

团队原先通过纸质交接单、SQL 截图和 Excel 交接。三处痛点：样本版本难统一、并发移交容易重复、超时后无法确认回执是否回滚。上游为样本接收记录，本站承接样本登记、移交申请、并发复核和证据导出，下游为理化检测室与复核员。

- 样本台账：批次、可用份数、保管位置，可录入。
- 流转申请：关联样本、指定数量和接收实验室。
- 并发执行：Redis 队列、独立 Python worker、可设锁等待上限。
- 冲突证据：Backend PID、SQLSTATE、回执回滚、数量守恒与 JSON 导出。
- 管理员审计：登录、写入和执行动作。

## 启动

```sh
cp .env.example .env
docker compose up -d --build
docker compose exec -T backend python -m scripts.seed_demo
```

前端 http://localhost:18242 ，后端 http://localhost:19242/docs ，数据库 localhost:17742。

|角色|账号|密码|权限|
|---|---|---|---|
|admin|admin@qingyu.test|Demo2026!|全业务写入、执行、审计|
|operator|operator@qingyu.test|Demo2026!|创建样本、申请、执行、导出|
|viewer|viewer@qingyu.test|Demo2026!|只读、导出；写 API 返回403|

## 一天剧本

09:00 operator 登录；09:05 复核 `QY-261117-A` 近海水质留样 120 份，位置冷藏间 A-03；09:10 查看申请 `MOVE-1117-01`，接收理化检测室 30 份；09:15 新建 `shift-20261117` 流转申请；09:20 以该申请发起 250ms 并发演练；09:25 查看 A 提交 30、B SQLSTATE 55P03 回滚，90+30=120；09:30 导出 `trial-1.json`；09:40 viewer 复核证据；10:00 admin 查看审计。

## 算法与业务边界

这是**真实数据库行锁的受控演练**。每次以样本可用量建立独立 `trial_balances` 镜像行，不扣减原台账。A 使用 `SELECT FOR UPDATE` 持锁并写未提交回执；Python threading.Event 确保 B 在 A 持锁期间运行。B 先写自己的回执，再以指定 `lock_timeout` 请求同一行锁；PostgreSQL 返回 SQLSTATE 55P03 后完整 ROLLBACK。B 结束事件释放 A，A 扣减 remaining、增加 received 并 COMMIT。没有随机结果、sleep 假等待或假 SQL 计划。

输入：流转申请、50–2000ms 锁等待上限。输出：实际 PID、错误码、等待耗时、剩余量、接收量、回执数和 SHA256。口径为 `remaining + received == initial`、remaining非负、仅A回执一条；B回执必须为零。等待耗时受主机负载影响，SHA包含PID和实际耗时因此每次不同。算法输入和最终不变量可复现。失败态包括申请量超限、数据库错误、线程协调超时、队列不可用；页面显示错误并允许创建新演练。

单 worker 顺序运行任务，无生产重试/崩溃恢复调度；worker中断时 running 任务需要人工重建，不能用作生产样本库存扣减。

## 工程说明

|服务|技术|职责|
|---|---|---|
|frontend|原生HTML/CSS/JS + Nginx|4业务页+登录，反向代理 /api/|
|backend|Python3.11/FastAPI/SQLAlchemy/PyJWT|校验、权限、审计、持久化|
|worker|Python3.11/psycopg|真实双连接锁竞争|
|db|PostgreSQL16|业务数据、隔离镜像账本|
|redis|Redis7|持久队列|

目录：`frontend/src/{api,stores,types,components/common,hooks,pages,router,utils,constants}`；`backend/src/{routes,controllers,services,models,schemas,middlewares,utils,constants,config}`；`backend/scripts/seed_demo.py`；`backend/migrations/001_initial.sql`。
核心实体 Sample、Transfer、Trial 各有模型、schema、服务、路由、API、store与页面；共享 table/badge/frame 组件。共享枚举 roles/run states 位于后端 `src/constants/enums.py`、模型/权限引用和前端 `src/constants/enums.js`、frame/badge；状态枚举 queued/running/completed/failed。两个后端中间件：request_id/errors。

环境变量见 `.env.example`：COMPOSE_PROJECT_NAME、三端口、DB_PASSWORD、JWT_SECRET、SEED_DEMO。默认密码仅用于本地演示；JWT8小时有效。seed按自然键仅插入缺失行，不覆盖修改。所有5服务有健康检查，backend/worker依赖健康数据库/Redis，frontend依赖backend；db/redis/artifacts使用命名卷。停止及清空本项目数据：`docker compose down -v --remove-orphans`。

本地开发：Python3.11安装 backend/requirements.txt；设置 DATABASE_URL/REDIS_URL 后 `uvicorn src.main:app --reload`（backend目录）；worker `python -m src.worker`；前端用Nginx同源代理后端。前端双字体经Google Fonts加载，离线使用浏览器字体回退；业务不依赖外部字体。

## 数量精度升级（v1.1：两位小数）

样本量与移交量由 INTEGER 升级为 `DECIMAL(12,2)`，迁移在应用启动时幂等执行（`src/config/migrations.py`），旧整数库自动 `ALTER ... TYPE ... USING ::DECIMAL(12,2)`，历史值 120 变为 120.00 且不丢数。

|口径|实现|
|---|---|
|旧接口升级期按整数办理|`POST/PUT /samples`、`POST /transfers` 仍用 int schema，小数输入 422|
|两个接口一起切换|单行 `interface_modes`（integer/decimal）；`POST /interface/switch-decimal` 前置校验历史回填全部完成，失败保持 integer 并返回 409|
|切换失败沿用整数|模式行不满足前置条件时无任何写入，version 不变|
|v2 小数接口|`POST/PUT /v2/samples`、`POST /v2/transfers`，Decimal 且最多两位小数，超出刻度 422；integer 模式调用返回 409|
|回退|`POST /interface/rollback-integer`；回退与小数写在同一事务取同一把咨询锁（`pg_try_advisory_xact_lock(74242)`），先办成者生效，另一边 409|
|移交按当次样本量校验|创建移交时 `SELECT ... FOR UPDATE` 锁定样本行，阻塞并发改量，按锁定的当次 quantity 判定，超限 422|
|历史数据分批回填|`backfill_jobs` 持久化断点（last_id/done_rows/skipped_rows）；每批 `FOR UPDATE SKIP LOCKED`，业务持锁的行本批跳过、业务提交后下一轮补标记，**以业务写入为准**|
|回填中断续跑|离线脚本 `python -m scripts.backfill_history [--batch-size=N]`，中断后重跑从断点继续；管理端 `POST /backfill/run` 逐批推进、`GET /backfill/status` 查进度|
|业务行标记|升级期所有业务写入（v1/v2）自带 `backfilled_at`，回填作业不再覆盖这些行|

模式与回填端点仅 admin 可用（viewer/operator 返回 403），`GET /interface/current` 所有登录用户可读，前端据此把样本/移交表单分流到 v1（`step=1`）或 v2（`step=0.01`）；admin 导航新增「接口管理」页。并发演练的镜像账本、回执、不变量（`remaining + received = initial`）全部按 Decimal 计算，证据 JSON 以数值输出。

### 自动化验证（对接真实 PostgreSQL/Redis）

```sh
cd backend && python -m pytest tests/ -v          # 17 个用例
bash tests/e2e_lifecycle.sh                        # 真实 uvicorn+worker 的全生命周期 HTTP 联调
```

覆盖：v1 拒小数、回填前切换失败保整数、两接口同切、两位/三位小数校验、回退与小数写双向竞态（确定性次序 + 5 轮自由竞争各恰一方获胜）、改量撞回填（SKIP LOCKED 且业务值不被覆盖）、移交撞样本改量的行锁等待与当次量判定、回填中断续跑、小数演练数量守恒与 worker 队列端到端。

## License
MIT，见 LICENSE。测试脚本、截图与实际结果位于源码外 `../../test-artifacts/gb-4103/`。
