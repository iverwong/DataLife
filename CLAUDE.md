# CLAUDE.md
This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.
## ⚠️ 虚拟环境（必须）
所有 Python 命令都必须通过虚拟环境执行：
```
./venv/Scripts/python

./venv/Scripts/python -m pytest

./venv/Scripts/python -m basedpyright

./venv/Scripts/python -m ruff
```
## 开发环境
- Python版本： 3.13.3

## 代码规范
- 完整 type hints，用 `basedpyright` 检查
- 无需使用 `from __future__ import annotations`，该行为为默认行为
- Google 风格 docstring
- PEP 8，行宽 120
- 所有 I/O 用 async/await
- 日志用 logfire，禁止 print()
- 外部 API 调用必须设超时
## 数据结构
- Pydantic：网络请求与响应模型
- SQLAlchemy ORM：数据库模型
- dataclass：业务领域对象，按需使用 frozen / 非 frozen
## 测试
```
# 运行所有测试
pytest tests/ -v
# 仅单元测试
pytest tests/ -m unit -v
# 覆盖率
pytest tests/ --cov=core --cov-report=html
```
### 测试标记
- `@pytest.mark.unit`：单元测试（使用 mock）
- `@pytest.mark.asyncio`：异步测试
- `@pytest.mark.real_network`：需要真实网络，CI 中跳过
## 工作流
- **TDD**：`/tdd-red`（契约 + 测试）→ `/tdd-green`（实现），计划文件在 `.claude/plans/`
- **重构**：使用前先读 `.claude/skills/refactor/SKILL.md`，确保有测试覆盖