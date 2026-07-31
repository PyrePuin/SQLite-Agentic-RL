# tests README 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 `tests/` 提供一份只说明文件作用和运行方法的简洁 README。

**Architecture:** 单文件文档，不修改测试代码。内容以当前 6 个测试文件和实际 `pytest` 命令为准。

**Tech Stack:** Markdown、pytest。

## Global Constraints

- 只写文件作用和使用方式。
- 不介绍复杂测试架构、CI、历史版本或内部整修过程。
- 所有命令从仓库根目录运行。

---

### Task 1: 创建 tests 使用说明

**Files:**
- Create: `tests/README.md`
- Verify: `tests/test_*.py`

**Interfaces:**
- Consumes: 当前 6 个 pytest 文件和 `pyproject.toml` 的 `dev` 依赖。
- Produces: 测试文件索引和可复制的 pytest 命令。

- [x] **Step 1: 写文件作用**

用表格说明 6 个 `test_*.py` 覆盖的数据构造、JSON 协议、路径相对化、reward、CLI 入口和 Teacher rollout 转换。

- [x] **Step 2: 写使用方式**

提供以下命令：

```bash
python -m pip install -e '.[dev]'
pytest -q
pytest -q tests/test_reward.py
pytest -q tests/test_reward.py::test_unsafe_sql_is_rejected
```

- [x] **Step 3: 验证**

```bash
PYTHONDONTWRITEBYTECODE=1 pytest -q
git diff --check
```

预期：16 项测试通过，文档无格式错误。

- [x] **Step 4: 提交并推送**

```bash
git add tests/README.md docs/superpowers/plans/2026-08-01-tests-README实施计划.md
git commit -m "docs: 添加 tests 使用说明"
git push origin main
```
