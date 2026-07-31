# 历史协议兼容层

`xml_v1.py` 只用于读取早期实验数据中的 XML envelope，例如 `<tool_call>...</tool_call>`。它会优先尝试当前 JSON V2 parser，再回退到 XML 标签提取。

正式训练、评测和 RL runtime 均只使用 canonical JSON V2，不应从该模块导入 parser。需要迁移历史数据时可使用：

```python
from sqlite_agent_pkg.compat.xml_v1 import parse_tool_call, parse_final
```

兼容成功只表示旧样本可以被读取，不表示其协议满足当前训练数据的质量要求。
