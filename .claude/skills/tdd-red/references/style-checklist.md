# 风格一致性检查清单

在审查计划中的契约代码之前，先从项目已有代码中提取以下要素，作为基线进行对比。

## 命名约定
- [ ] 类名风格（PascalCase？是否有前缀/后缀约定？）
- [ ] 函数/方法名风格（snake_case？）
- [ ] 变量名风格
- [ ] 常量名风格（UPPER_SNAKE_CASE？）
- [ ] 私有成员风格（_leading_underscore？__double？）
- [ ] 模块/文件名风格
- [ ] 异常类命名模式（XXXError？有无统一基类？）

## Import 组织
- [ ] 分组方式（标准库 / 三方 / 本地）
- [ ] 组间是否有空行
- [ ] 排序规则（字母序？按 from / import 分？）
- [ ] 是否使用 `from __future__ import annotations`

## 类型标注
- [ ] 可选类型写法：`Optional[X]` vs `X | None`
- [ ] 集合类型写法：`List[X]` vs `list[X]`
- [ ] 返回值是否总是标注
- [ ] 是否使用 TypeVar / ParamSpec
- [ ] Union 写法：`Union[X, Y]` vs `X | Y`

## Docstring
- [ ] 风格（Google / NumPy / reST）
- [ ] 必须包含哪些部分（Args / Returns / Raises / Examples）
- [ ] 语言（中文 / 英文）
- [ ] 一行 docstring vs 多行 docstring 的使用场景

## 测试
- [ ] 测试框架（pytest？unittest？）
- [ ] 目录结构（`tests/` 镜像 `src/`？扁平？）
- [ ] 文件命名（`test_<模块名>.py`？）
- [ ] 函数命名（`test_<函数>_<场景>_<预期>`？）
- [ ] Fixture 定义位置（conftest.py？测试文件内？）
- [ ] Fixture scope 习惯
- [ ] Mock 方式（unittest.mock / pytest-mock / monkeypatch）
- [ ] 参数化测试方式（@pytest.mark.parametrize？）
- [ ] assert 风格（原生 assert？pytest 断言重写？）

## 错误处理
- [ ] 自定义异常基类
- [ ] 异常链 raise ... from ...
- [ ] 异常消息风格
- [ ] 是否使用 logging 记录异常

## 日志
- [ ] 日志库（structlog / logging / loguru）
- [ ] 日志级别使用约定
- [ ] 是否禁止裸 print

## 项目组织
- [ ] 源码根目录（`src/` 布局？扁平？）
- [ ] 模块拆分粒度
- [ ] `__init__.py` 导出策略
- [ ] 常量/配置的组织方式