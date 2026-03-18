# 风格一致性检查清单

在委派子代理前，主代理应阅读以下项目文件并提取风格基线摘要。子代理的产出必须与基线一致。

## 采集来源
- `pyproject.toml`（linter 规则、项目配置、Python 版本）
- `CLAUDE.md`（如存在，项目级约定）
- 已有的抽象基类、Protocol、TypedDict 定义
- 已有的测试文件（fixture、conftest、命名模式）

## 命名约定
- [ ] 类名：PascalCase（如 `ChunkPipeline`）
- [ ] 函数/方法名：snake_case（如 `build_chunk`）
- [ ] 私有函数：单下划线前缀（如 `_validate_range`）
- [ ] 常量：UPPER_SNAKE_CASE（如 `MAX_TOKEN_COUNT`）
- [ ] 模块名：snake_case（如 `chunk_pipeline.py`）
- [ ] 类型别名：PascalCase（如 `PageRange = tuple[int, int]`）

## Import 组织
- [ ] 分组顺序：标准库 → 第三方 → 本地（ruff / isort 规则）
- [ ] `from __future__ import annotations` 是否统一使用？
- [ ] 相对导入 vs 绝对导入的项目约定

## 类型标注
- [ ] Union 风格：`X | None`（3.10+）vs `Optional[X]`
- [ ] 容器风格：`list[X]`（3.9+）vs `List[X]`
- [ ] TypedDict vs dataclass vs Pydantic model 的使用边界
- [ ] 返回类型是否始终标注
- [ ] 参数类型是否始终标注

## Docstring
- [ ] 风格：Google / NumPy / reST（项目统一用哪种）
- [ ] 语言：中文 / 英文
- [ ] 类级 docstring 是否要求
- [ ] 函数级 docstring 是否要求（公开 / 私有）
- [ ] Args / Returns / Raises 各段格式

## 异常处理
- [ ] 自定义异常类命名（如 `XxxError` vs `XxxException`）
- [ ] 异常类的组织位置（集中 vs 就近）
- [ ] 异常链：是否使用 `raise ... from ...`

## 日志
- [ ] 日志库：`logging` / `loguru` / 其他
- [ ] Logger 获取方式：`logging.getLogger(__name__)` 还是全局实例
- [ ] 日志级别使用约定

## 测试
- [ ] 测试文件命名：`test_<module>.py`
- [ ] 测试类命名：`Test<Feature>`
- [ ] 测试函数命名：`test_<scenario>`
- [ ] fixture 组织：`conftest.py` 层级
- [ ] mock 方式：`unittest.mock` / `pytest-mock` / 其他
- [ ] 断言风格：`assert` 语句 vs pytest helpers