# 执行计划：测试进程挂起修复（P4 — pytest_sessionfinish 钩子方案）

## 1. 修复目标

修复 DataLife 项目中 **pytest 测试进程在全部用例通过后仍然挂起不退出** 的问题。

此前的资源生命周期修复（P1-P3）已合并到 master，解决了 `close_client()` / `close_db()` 缺失和 `in_memory_db` fixture 连接泄露的问题。但 **P4（模块级 `httpx.AsyncClient` 在测试结束后未关闭）仍未解决**，导致测试进程挂起。

---

## 2. 问题来源

本修复基于上一轮资源生命周期修复的遗留问题 P4，以及实测验证后的根因分析。

| **编号** | **问题** | **位置** | **影响范围** |
| --- | --- | --- | --- |
| P4 | `httpx.AsyncClient` 在模块 import 时创建，测试结束后未关闭；`_cleanup_global_resources` fixture 为空操作 | `core/notion/client.py`（模块级创建）
`tests/conftest.py`（`_cleanup_global_resources`） | 测试进程挂起 |

### 根因分析

<aside>
🔍

**pytest-asyncio AUTO 模式下的事件循环生命周期冲突**：

pytest-asyncio 在 AUTO 模式下管理事件循环的生命周期。session 级别 fixture 的 teardown 执行时，**事件循环已经被 pytest-asyncio 关闭**，所有依赖 `await` 的异步清理操作都无法执行。

这就是为什么上一轮修复中 `_cleanup_global_resources` fixture 被实现为空操作——在 fixture teardown 中调用 `await close_client()` 会因事件循环已关闭而失败。

</aside>

### 上一轮尝试过的方案及失败原因

| **方案** | **结果** | **失败原因** |
| --- | --- | --- |
| session scope fixture teardown 中 `await close_client()` | ❌ 失败 | 事件循环已被 pytest-asyncio 关闭 |
| `asyncio.get_event_loop().run_until_complete()` | ❌ 失败 | 获取到的是已关闭的循环 |
| `ThreadPoolExecutor`  • `asyncio.run()` | ❌ 失败 | httpx 客户端绑定旧事件循环引用，新循环上无法完成 `aclose()` |

---

## 3. 前置条件

- 工作区在 `master` 分支且干净（P1-P3 修复已合并）
- 依赖：`aiosqlite`、`httpx`、`pytest`、`pytest-asyncio`（已有）
- 无需新增依赖

---

## 4. Git 准备

```bash
git checkout master && git pull origin master
git checkout -b fix/test-process-hanging-p4
```

---

## 5. 测试编写（Red 阶段）

<aside>
🔴

以下测试应在当前代码上**失败**或验证问题存在。

</aside>

### 5.1 诊断测试：确认存活线程

**文件**：`tests/test_resource_cleanup.py`（追加）

**测试用例**：`test_no_dangling_threads_after_cleanup`

- 调用 `close_client()` 和 `close_db()` 后，用 `threading.enumerate()` 检查非 daemon 线程
- 排除 MainThread 后，不应存在 `aiosqlite` 或 `httpx` / `anyio` 相关的存活线程
- 当前代码中 `_cleanup_global_resources` 为空操作，httpx 客户端未关闭 → **测试失败（存在残留线程）**

**运行验证**：

```bash
pytest tests/test_resource_cleanup.py::test_no_dangling_threads_after_cleanup -v
# 预期：FAILED（检测到残留非 daemon 线程）
```

**Git 提交**：

```bash
git add tests/test_resource_cleanup.py
git commit -m "test: add thread leak detection test for P4 diagnosis"
```

---

## 6. 修复步骤（Green 阶段）

### 步骤 1：在 `conftest.py` 中替换 `_cleanup_global_resources` 为 `pytest_sessionfinish` 钩子

- `depends_on: none`
- **问题类别**：测试基础设施修复
- **目标文件**：`tests/conftest.py`
- **描述**：

<aside>
⚡

**核心思路**：`pytest_sessionfinish` 是 pytest 插件钩子（不是 fixture），它在**所有测试和 fixture 清理之后**才执行，且不受 pytest-asyncio 事件循环管理的影响。配合 `asyncio.run()` 创建全新事件循环来执行异步清理。

</aside>

修改内容：

1. **删除** `_cleanup_global_resources` fixture（session scope, autouse）——它当前是空操作，已无存在价值
2. **新增** `pytest_sessionfinish` 钩子函数（模块级函数，不是 fixture）
3. 钩子内部定义 `async def _cleanup()` 协程，依次调用 `close_client()` 和 `close_db()`
4. 使用 `asyncio.run(_cleanup())` 创建全新事件循环执行清理
5. 如果 `asyncio.run()` 抛出异常（httpx 绑定旧循环引用导致 `aclose()` 挂起），**回退到同步强制关闭传输层**：
    - 直接调用 `httpx_client._transport.close()`（同步方法，不依赖事件循环）
    - 添加注释标注：这是访问私有 API 的防御性兜底，httpx 版本升级时需验证
    - `close_db()` 仍通过 `asyncio.run()` 在 except 块外单独执行
- **验证**：

```bash
# 运行新增的线程泄露检测测试
pytest tests/test_resource_cleanup.py::test_no_dangling_threads_after_cleanup -v

# 运行全量测试，确认不挂起（30 秒超时）
pytest --timeout=30
```

- **Git 提交**：`fix: test infrastructure - replace no-op fixture with pytest_sessionfinish hook for P4 cleanup`

### 步骤 2（可选，长期方案）：将 `httpx.AsyncClient` 改为懒加载

- `depends_on: [步骤 1]`
- **问题类别**：架构改进（从根源消除问题）
- **目标文件**：`core/notion/client.py`
- **描述**：

<aside>
💡

**长期最优解**：将模块级 `httpx.AsyncClient` 创建改为懒加载（lazy init），使得 import 模块时不触发客户端创建。测试中 mock 了网络层，根本不需要真实客户端存在，问题从根源消失。

</aside>

修改内容：

1. 将模块级 `httpx_client = httpx.AsyncClient(...)` 改为 `httpx_client: httpx.AsyncClient | None = None`
2. 新增 `def get_httpx_client() -> httpx.AsyncClient` 懒加载函数：首次调用时创建客户端并缓存，后续调用直接返回
3. 将所有使用 `httpx_client` 的地方改为调用 `get_httpx_client()`
4. 更新 `close_client()` 函数：检查 `httpx_client is None` 时直接 return；关闭后重置为 `None`
5. 同步更新 `notion = AsyncClient(client=httpx_client, ...)` 为懒加载
6. 更新 `__all__` 导出列表

<aside>
⚠️

**注意**：此步骤改变了模块的公开接口（从直接访问 `httpx_client` 变量改为通过 `get_httpx_client()` 函数获取），需要检查所有 import 了 `httpx_client` 的文件并更新调用方式。包括：

- `tests/test_resource_cleanup.py` 中直接访问 `httpx_client.is_closed` 的断言
- 其他可能直接引用 `httpx_client` 的模块
</aside>

- **验证**：

```bash
# 确认懒加载正确工作
pytest tests/test_resource_cleanup.py -v

# 全量测试无回归
pytest --timeout=30

# 手动验证：import core.notion.client 不应触发 httpx 客户端创建
python -c "import core.notion.client; print(core.notion.client.httpx_client)"  
# 预期输出：None
```

- **Git 提交**：`refactor: lazy-init httpx.AsyncClient to avoid module-level creation`

---

## 7. 旧测试修改说明

### 步骤 1 影响

<aside>
✅

步骤 1（`pytest_sessionfinish` 钩子）**不需要修改任何旧测试的断言**。

- 只是替换了清理机制（从空 fixture → 钩子函数），对测试用例透明
- 已有的 `test_resource_cleanup.py` 中的 4 个测试不受影响
</aside>

### 步骤 2 影响（如执行）

若执行步骤 2（懒加载），需要修改以下测试：

- `tests/test_resource_cleanup.py` → `test_close_client_exists_and_works`：
    - 修改前：直接检查 `httpx_client.is_closed`
    - 修改后：先调用 `get_httpx_client()` 触发创建，再检查关闭状态
    - 修改原因：懒加载模式下 import 后 `httpx_client` 为 `None`，需先触发创建

---

## 8. 验证清单

所有步骤完成后：

- [ ]  **新测试通过**：`pytest tests/test_resource_cleanup.py -v`（含新增的线程泄露检测测试）
- [ ]  **旧测试无回归**：`pytest tests/ -v --timeout=30`（全量测试套件，30 秒超时）
- [ ]  **测试进程正常退出**：`pytest` 命令执行完毕后，shell 立即返回提示符，不挂起
- [ ]  **线程诊断确认**：在 `pytest_sessionfinish` 中打印 `threading.enumerate()`，确认无残留非 daemon 线程
- [ ]  **主程序不受影响**：`python main.py` 执行完毕后正常退出（exit code 0）

---

## 9. 修复决策说明

### 为什么选择 `pytest_sessionfinish` 钩子而非 fixture？

| 方案 | 优点 | 缺点 |
| --- | --- | --- |
| **A：`pytest_sessionfinish` 钩子 + `asyncio.run()`**（步骤 1 采用） | 在所有 fixture 之后执行；`asyncio.run()` 创建全新事件循环，不受 pytest-asyncio 影响 | 如果 httpx 绑定旧循环引用，`aclose()` 可能仍然挂起（需回退到同步关闭） |
| B：session fixture teardown 中 `await` | 语义清晰 | **已证实失败**：pytest-asyncio AUTO 模式下事件循环在 fixture teardown 前已关闭 |
| C：`atexit` 注册 | 不侵入 pytest 框架 | `atexit` 不支持 async 函数；且 pytest 进程已挂起时 `atexit` 根本不会执行 |
| **D：httpx 懒加载**（步骤 2 采用） | **从根源消除问题**——测试中不创建真实客户端 | 需修改模块接口和所有调用方；改动面稍大 |

**Trade-off**：步骤 1 是最小侵入的即时修复，步骤 2 是长期最优解。建议先实施步骤 1 验证效果，稳定后再推进步骤 2。

### 同步关闭传输层的风险说明

<aside>
⚠️

`httpx_client._transport.close()` 访问了 httpx 的**私有 API**（下划线前缀）。这是防御性兜底方案，仅在 `asyncio.run(close_client())` 失败时触发。

**风险**：httpx 版本升级可能改变内部实现，导致此调用失败。

**缓解**：用 `try/except` 包裹，失败时仅记录警告而非抛出异常；在代码注释中标注 httpx 版本依赖。

</aside>

---

## 并发执行策略

```jsx
阶段 1（串行）：编写线程泄露检测测试 → 验证 Red → git commit
阶段 2（串行）：步骤 1 - 替换为 pytest_sessionfinish 钩子 → 全量验证 → git commit
阶段 3（串行，可选）：步骤 2 - httpx 懒加载改造 → 全量验证 → git commit
```

<aside>
📌

本次修复步骤间存在严格依赖，无可并发单元。步骤 2 为可选的长期改进，可在步骤 1 验证通过后独立决策是否执行。

</aside>