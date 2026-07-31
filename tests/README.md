# 测试说明

`tests/` 使用 pytest 验证项目中的数据构造、Agent 协议、路径处理、奖励函数和脚本入口。

## 文件作用

| 文件 | 作用 |
|---|---|
| `test_data_builders.py` | 验证英文困难 mini 评测集的默认构造参数、输出规模和 manifest 行为 |
| `test_json_protocol.py` | 验证 `json_v2` 工具调用与最终回答的解析，并确认正式协议拒绝 XML 格式 |
| `test_relativize_paths.py` | 验证本地和远程绝对路径可以转换为项目相对路径，并能正确解析数据库路径 |
| `test_reward.py` | 验证结果等价、可执行但错误以及不安全 SQL 对应的 reward 和指标 |
| `test_script_entrypoints.py` | 验证数据处理脚本能从仓库根目录正常启动 |
| `test_teacher_rollout_conversion.py` | 验证 331 条成功 Teacher rollout 可以精确重建正式 SFT 中的对应样本 |

## 使用方式

所有命令从仓库根目录执行。

安装测试依赖：

```bash
python -m pip install -e '.[dev]'
```

运行全部测试：

```bash
pytest -q
```

运行单个测试文件：

```bash
pytest -q tests/test_reward.py
```

运行单个测试用例：

```bash
pytest -q tests/test_reward.py::test_unsafe_sql_is_rejected
```

当前完整测试集包含 16 个测试用例。
