# 航班节点匹配仿真验证系统

独立的人机协同仿真工具，用于将算法/人工保障节点先聚类为临时航班组，再尝试关联航班计划，并通过人工反馈迭代匹配策略。

## 本地启动

推荐在项目根目录使用启动脚本，服务会自动打开页面，并由当前终端监督：

```bash
./start.sh
```

保持该终端开启。按 `Ctrl+C` 或关闭脚本时，会同时停止前后端、清理 PID 文件；任一服务异常退出时，
脚本也会停止另一服务，避免留下只有页面、没有后端的半运行状态。

常用管理命令：

```bash
./start.sh status
./start.sh restart
./start.sh stop
```

`status` 和 `stop` 可在另一个终端执行。启动日志保存在 `.run/backend.log` 和
`.run/frontend.log`，脚本只会停止工作目录属于本项目的进程，避免陈旧 PID 误杀其他程序。

也可以分别手动启动：

```bash
cd backend
uv sync --extra dev
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8900
```

另开终端：

```bash
cd frontend
npm install
npm run dev -- --host 0.0.0.0 --port 5178
```

打开 `http://localhost:5178`。首次启动会自动创建 SQLite 数据库并写入典型问题样本。

## 生产配置

- `DATABASE_URL`：默认 `sqlite+aiosqlite:///./flight_simulator.db`，生产可切换 PostgreSQL。
- `CELERY_BROKER_URL` / `CELERY_RESULT_BACKEND`：配置 Redis 后可运行后台导入和仿真任务。
- `CORS_ORIGINS`：允许访问 API 的前端地址，逗号分隔。
- 原始文件、认证和出站发送通过 `app/gateways.py` 的 HTTP 适配器边界接入，不依赖 PM Platform 内部代码。

## 数据导入

批次中心支持航班计划、算法节点和可选的 A-CDM 现场节点 Excel。A-CDM 现场节点与算法节点共用事件类型，但通过 `source_type` 保留来源。核验台还可为单个保障组模拟 A-CDM 航班号证据，用于比较无参考、一致参考和冲突参考场景；仿真证据不会写成算法节点，也不计入节点守恒数量。

历史批次需要应用新版驻位归一化规则时，使用独立重建命令。命令会新建批次并保留原批次、原始行、A-CDM/外观证据和已核验结论：

```bash
cd backend
.venv/bin/python scripts/rebuild_normalized_batch.py 2 --strategy-id 2
```

外观证据支持人工模拟飞机注册号及 OCR 置信度。注册号相似度由独立模块计算，候选得分保留原始相似度，便于未来直接替换为 OCR 输出。
