# 78 — LangGraph 持久化数据库连接配置重构设计

## 1. 背景与问题

### 1.1 现状

当前 `langgraph_persistence` 的数据库连接配置采用两种模式：

```yaml
# config.yaml
langgraph_persistence:
  database:
    use_global_config: false          # 当前值：false
    db_uri: ${LANGGRAPH_DB_URI:}      # 从 .env 读取完整 URI
    schema: langgraph                 # ← 实际上不生效！
    sslmode: disable                  # ← 实际上不生效！
    connect_timeout: 5                # ← 实际上不生效！
    statement_timeout_ms: 5000        # ← 实际上不生效！
```

```bash
# .env
LANGGRAPH_DB_URI=postgresql://postgres:PostgreSql-18@172.29.128.1:5432/lg_persist
```

### 1.2 问题分析

`build_db_uri_from_config()` 的 `use_global_config=false` 分支（`postgres.py:128-136`）**直接返回原始 URI**，完全跳过了 schema / sslmode / timeout 等配置项的拼接逻辑：

```python
if not db_config.get("use_global_config", True):
    db_uri = db_config.get("db_uri")
    ...
    return db_uri  # ← 直接返回，schema/sslmode/timeout 全部失效
```

**后果：**
- `schema: langgraph` 配置无效 → `search_path` 未设置 → PostgresSaver/PostgresStore 的 `setup()` 在 `public` schema 下建表
- 已有数据全在 `public` schema → 查询 `langgraph.store` 报错「关系不存在」
- `sslmode`、`connect_timeout`、`statement_timeout_ms` 配置也被完全忽略
- `chat_history_reader.py` 中被迫硬编码 `schema = "public"` 作为临时 workaround

### 1.3 目标

1. 将 `.env` 中的 `LANGGRAPH_DB_URI` 拆解为独立的环境变量（host/port/db/user/password）
2. 在 `config.yaml` 中引用这些环境变量，确保 schema/sslmode/timeout 配置生效
3. 所有使用 `build_db_uri_from_config()` 的代码无需修改（接口不变）
4. 移除 `chat_history_reader.py` 中的硬编码 `schema = "public"`

---

## 2. 修改方案

### 2.1 .env 文件修改

**删除：**
```bash
LANGGRAPH_DB_URI=postgresql://postgres:PostgreSql-18@172.29.128.1:5432/lg_persist
```

**新增：**
```bash
# LangGraph 持久化数据库（独立于业务数据库）
LANGGRAPH_DB_HOST=172.29.128.1
LANGGRAPH_DB_PORT=5432
LANGGRAPH_DB_NAME=lg_persist
LANGGRAPH_DB_USER=postgres
LANGGRAPH_DB_PASSWORD=PostgreSql-18
```

### 2.2 config.yaml 修改

**修改前：**
```yaml
langgraph_persistence:
  enabled: true

  database:
    use_global_config: false
    db_uri: ${LANGGRAPH_DB_URI:}
    schema: langgraph
    sslmode: disable
    connect_timeout: 5
    statement_timeout_ms: 5000
```

**修改后：**
```yaml
langgraph_persistence:
  enabled: true

  database:
    use_global_config: false

    # 独立连接参数（use_global_config=false 时生效）
    host: ${LANGGRAPH_DB_HOST:localhost}
    port: ${LANGGRAPH_DB_PORT:5432}
    database: ${LANGGRAPH_DB_NAME:lg_persist}
    user: ${LANGGRAPH_DB_USER:postgres}
    password: ${LANGGRAPH_DB_PASSWORD:}

    schema: langgraph
    sslmode: disable
    connect_timeout: 5
    statement_timeout_ms: 5000
```

**说明：**
- 删除 `db_uri` 配置项，改为独立的 host/port/database/user/password
- `schema`、`sslmode`、`connect_timeout`、`statement_timeout_ms` 保持不变，但修改代码后将真正生效

### 2.3 build_db_uri_from_config() 修改

**文件：** `src/services/langgraph_persistence/postgres.py`

**修改前（`use_global_config=false` 分支）：**

```python
if not db_config.get("use_global_config", True):
    db_uri = db_config.get("db_uri")
    if not db_uri:
        raise ValueError(
            "langgraph_persistence.database.db_uri is required when use_global_config=false"
        )
    return db_uri  # ← 直接返回，跳过所有配置
```

**修改后：**

```python
if not db_config.get("use_global_config", True):
    # 从 langgraph_persistence.database.* 读取独立连接参数
    host = db_config.get("host", "localhost")
    port = db_config.get("port", 5432)
    database = db_config.get("database", "postgres")
    user = db_config.get("user", "postgres")
    password = quote(str(db_config.get("password", "")), safe="")
else:
    # 从 database.* (全局业务数据库) 读取
    global_db = config.get("database", {})
    host = global_db.get("host", "localhost")
    port = global_db.get("port", 5432)
    database = global_db.get("database", "postgres")
    user = global_db.get("user", "postgres")
    password = quote(str(global_db.get("password", "")), safe="")

# 以下逻辑两种模式共用 ——————————————————————————

# 构建 query 参数
query_params = {}

sslmode = db_config.get("sslmode")
if sslmode:
    query_params["sslmode"] = sslmode

connect_timeout = db_config.get("connect_timeout", 5)
query_params["connect_timeout"] = str(connect_timeout)

schema = db_config.get("schema", "langgraph")
statement_timeout_ms = db_config.get("statement_timeout_ms", 5000)
options_parts = []
if schema:
    options_parts.append(f"-csearch_path={schema}")
options_parts.append(f"-cstatement_timeout={statement_timeout_ms}")
query_params["options"] = " ".join(options_parts)

query_string = f"?{urlencode(query_params, quote_via=quote)}" if query_params else ""

return f"postgresql://{user}:{password}@{host}:{port}/{database}{query_string}"
```

**核心改动：**
- `use_global_config=false` 时不再读取 `db_uri`，改为从 `db_config` 读取独立的 host/port/database/user/password
- 两种模式仅在「连接参数来源」上不同，query 参数拼接逻辑完全共用
- `schema`、`sslmode`、`connect_timeout`、`statement_timeout_ms` 在两种模式下都生效

### 2.4 chat_history_reader.py 修改

**文件：** `src/services/langgraph_persistence/chat_history_reader.py`

还原临时 workaround，改回从配置读取 schema：

```python
# 修改前（临时 workaround）：
# TODO: 历史原因 store 表在 public schema 下，后续统一迁移到 langgraph schema 后改回配置读取
# schema = persistence_config.get("database", {}).get("schema", "langgraph")
schema = "public"

# 修改后：
schema = persistence_config.get("database", {}).get("schema", "langgraph")
```

**说明：** 由于 `build_db_uri_from_config()` 修复后 URI 会携带 `search_path=langgraph`，PostgresSaver/PostgresStore 的 `setup()` 将在 `langgraph` schema 下建表。但现有数据在 `public` schema 中，需要先做数据迁移（见 §3）。

---

## 3. 数据迁移方案

### 3.1 迁移步骤

现有 store/checkpoint 表在 `public` schema 下，需迁移到 `langgraph` schema：

```sql
-- 1. 创建 langgraph schema（如不存在）
CREATE SCHEMA IF NOT EXISTS langgraph;

-- 2. 迁移 store 表
ALTER TABLE public.store SET SCHEMA langgraph;

-- 3. 迁移 checkpoint 相关表（如存在）
ALTER TABLE IF EXISTS public.checkpoints SET SCHEMA langgraph;
ALTER TABLE IF EXISTS public.checkpoint_blobs SET SCHEMA langgraph;
ALTER TABLE IF EXISTS public.checkpoint_writes SET SCHEMA langgraph;
ALTER TABLE IF EXISTS public.checkpoint_migrations SET SCHEMA langgraph;

-- 3b. 迁移 store 迁移记录表
ALTER TABLE IF EXISTS public.store_migrations SET SCHEMA langgraph;

-- 4. 验证
SELECT schemaname, tablename
FROM pg_tables
WHERE tablename IN ('store', 'store_migrations', 'checkpoints', 'checkpoint_blobs', 'checkpoint_writes', 'checkpoint_migrations');
```

### 3.2 迁移时序

1. **先执行 SQL 迁移**（将表从 `public` 移到 `langgraph`）
2. **再部署代码修改**（新代码会连接 `langgraph` schema）
3. 验证 CLI 启动正常、历史会话列表可展示

### 3.3 回退方案

如果迁移后出现问题：
```sql
-- 回退：将表移回 public
ALTER TABLE langgraph.store SET SCHEMA public;
ALTER TABLE IF EXISTS langgraph.checkpoints SET SCHEMA public;
-- ... 其余表同理
```
同时将 config.yaml 中 `schema` 改为 `public` 即可。

---

## 4. 文件变更清单

| 文件 | 变更类型 | 说明 |
|------|----------|------|
| `.env` | 修改 | 删除 `LANGGRAPH_DB_URI`，新增 5 个独立环境变量 |
| `src/configs/config.yaml` | 修改 | `langgraph_persistence.database` 配置块重构 |
| `src/services/langgraph_persistence/postgres.py` | 修改 | `build_db_uri_from_config()` 的 `use_global_config=false` 分支重写 |
| `src/services/langgraph_persistence/chat_history_reader.py` | 修改 | 还原 schema 为配置读取（移除硬编码 `"public"`） |

**无需修改的文件：**
- 所有调用 `build_db_uri_from_config()` 的文件（接口签名不变，返回的 URI 格式不变）
- 所有测试脚本中使用 `build_db_uri_from_config()` 的代码（透明兼容）

---

## 5. 测试计划

### 5.1 验证 URI 拼接

```bash
# 在 WSL 下执行
.venv-wsl/bin/python -c "
from src.services.langgraph_persistence.postgres import build_db_uri_from_config
uri = build_db_uri_from_config()
print(uri)
# 预期输出：
# postgresql://postgres:PostgreSql-18@172.29.128.1:5432/lg_persist?sslmode=disable&connect_timeout=5&options=-csearch_path%3Dlanggraph%20-cstatement_timeout%3D5000
"
```

验证要点：
- host/port/database/user/password 与 `.env` 一致
- `options` 中包含 `-csearch_path=langgraph`
- `sslmode`、`connect_timeout` 存在

### 5.2 验证 store/checkpoint 连接

```bash
# 迁移后验证
.venv-wsl/bin/python -c "
from src.services.langgraph_persistence.postgres import setup_persistence
result = setup_persistence()
print(f'初始化结果: {result}')
"
```

### 5.3 验证 CLI 历史会话列表

```bash
python scripts/nl2sql_father_cli.py
# 预期：正常展示历史会话列表（从 langgraph.store 查询）
```

### 5.4 现有单元测试

```bash
.venv-wsl/bin/python -m pytest src/tests/unit/services/test_chat_history_reader.py -v
.venv-wsl/bin/python -m pytest src/tests/unit/services/test_identifiers.py -v
```

---

## 6. 风险评估

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| SQL 迁移期间服务中断 | 低（开发环境） | 先迁移再部署代码 |
| 漏迁移某张表 | checkpoint/store 查询失败 | 迁移脚本包含所有 6 张表 + 验证查询 |
| `.env` 漏改 | 启动报错（env var 未定义） | config.yaml 有默认值兜底 |
| 其他 schema 的表名冲突 | 极低 | `langgraph` 是专用 schema |
