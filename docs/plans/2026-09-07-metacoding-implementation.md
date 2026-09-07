# MetaCoding V1 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 将现有 DevClaw 直接替换为一个只面向 TUI 的 MetaCoding V1，在当前项目目录中以 Planner、Coder、Tester 三个 Harness 完成可恢复的开发闭环，并支持可选的安全 GitHub 交付。

**Architecture:** 新建 `metacoding/` 作为唯一运行时包，删除旧 `devclaw/` 代码和旧入口，不做兼容适配。宿主机维护显式状态机、项目锁、文件所有权、结构化协议和 Git 门禁；三个 Harness 只通过当前项目目录中的开发契约、测试报告和运行记录交换上下文。Harness 的 provider、命令和 model 全部从当前项目 `.metacoding/config.toml` 读取，并允许当前命令行临时覆盖。

**Tech Stack:** Python 3、标准库 `argparse`/`tomllib`/`json`/`subprocess`/`pathlib`、TOML 配置、JSON Schema-like 手工校验、pytest、Git CLI、可选 GitHub CLI (`gh`)。

---

## V1 Scope And Decisions

### Included

- 前台、单项目、单进程 TUI；当前工作目录就是项目根目录。
- `metacoding` 交互式命令和 `metacoding run "..."` 一次性命令。
- 固定且仅有三个 Harness：Codex Planner、Pi Coder、Codex Tester。
- Planner 生成 PRD、架构、实施计划和验收标准。
- Coder 在当前项目目录中实现计划；Tester 独立执行检查并输出证据；Planner 决定接受或返工。
- `.metacoding/` 运行状态、轮次证据、transcript、锁和 GitHub 元数据。
- `docs/metacoding/` 人类可读开发契约和最终报告。
- Fake Harness 的无网络端到端测试。
- 本地 Git 分支和 commit；可选 push、Pull Request 和 CI 检查等待。
- 中断恢复、超时分类、重复失败指纹、最大轮次和人工复核状态。

### Excluded

- Web、移动端、后台 daemon、多项目服务和远程队列。
- 旧 `devclaw` 包的兼容入口、角色路由、Deepseek 工作流和旧 Agent API。
- 自动生产部署、直接推送保护分支和自动修改用户全局配置。
- V1 内置复杂终端 UI 框架；使用标准输入输出实现稳定 TUI，后续再评估 Textual/Rich。

### Model Configuration Decision

三个 Harness 的 model 在项目级 `.metacoding/config.toml` 中分别配置，不能共享一个隐式 model：

```toml
[harness.planner]
provider = "codex"
command = "codex"
model = "<planner-model>"
extra_args = []

[harness.coder]
provider = "pi"
command = "pi"
model = "<coding-model>"
extra_args = []

[harness.tester]
provider = "codex"
command = "codex"
model = "<tester-model>"
extra_args = []
```

每次调用都由宿主机把该 Harness 的 `model` 转换成对应 CLI 参数；Planner 和 Tester 即使同为 Codex，也分别生成独立 invocation。配置优先级为：内置默认值 → `.metacoding/config.toml` → 当前命令行参数。CLI 覆盖只存于本次 run，不写回配置。

建议覆盖参数：

```text
--planner-model MODEL
--coder-model MODEL
--tester-model MODEL
--planner-command PATH
--coder-command PATH
--tester-command PATH
```

不把 token、API key 或全局配置内容写入 `.metacoding/config.toml`；Harness 继承当前进程环境，但 MetaCoding 不持久化或修改环境变量。

---

## Task 1: Replace Package And CLI Skeleton

**Files:**
- Delete: `devclaw/`（整个旧包）
- Delete: `tests/` 下仅覆盖旧 DevClaw 行为且不迁移的测试文件
- Create: `metacoding/__init__.py`
- Create: `metacoding/__main__.py`
- Create: `metacoding/cli.py`
- Modify: `scripts/devclaw` → 改为调用 `python3 -m metacoding`，或删除并新增 `scripts/metacoding`
- Modify: `.gitignore`
- Create: `tests/metacoding/test_cli.py`

**Step 1: 记录旧实现行为和删除清单**

运行：

```bash
rg -n "devclaw|DevClaw" README.md scripts devclaw tests docs
git ls-files devclaw tests
```

确认旧入口、旧测试和文档引用都列入迁移范围，不在新包中保留 `devclaw` import 兼容层。

**Step 2: 写 CLI 失败测试**

覆盖：无子命令进入 TUI、`run` 接受 requirement、`status`/`report`/`artifacts` 可执行、退出码区分 accepted 和 blocked。

**Step 3: 实现最小 CLI 骨架**

`metacoding/__main__.py` 只调用 `metacoding.cli.main()`；`cli.py` 负责 argparse 和当前目录解析，不在 CLI 中实现编排逻辑。

**Step 4: 验证并切换入口**

运行：

```bash
python3 -m pytest tests/metacoding/test_cli.py -q
python3 -m metacoding --help
```

预期：新命令可启动，旧 `python3 -m devclaw` 不再作为支持入口。

---

## Task 2: Define Models And Structured Protocols

**Files:**
- Create: `metacoding/models.py`
- Create: `metacoding/errors.py`
- Create: `tests/metacoding/test_models.py`

**Step 1: 写模型序列化失败测试**

覆盖 `RunState`、`RoundState`、`ProjectSnapshot`、`PlannerPlan`、`CodingResult`、`TesterReport`、`PlannerDecision`、`FinalReport` 的 `to_dict()`/`from_dict()`、枚举状态和必填字段校验。

**Step 2: 实现不可变边界模型**

优先使用 `dataclass` 和显式字段；时间统一保存 ISO 8601 UTC 字符串；路径在模型中保存为相对项目根的 POSIX 字符串，避免恢复时绑定旧绝对路径。

**Step 3: 实现协议校验**

提供：

- `validate_planner_plan(value)`：要求 PRD、架构、实施计划、验收项和允许修改范围。
- `validate_coding_result(value)`：要求修改摘要、变更路径和执行摘要。
- `validate_tester_report(value)`：要求 status、acceptance findings、evidence、commands 和 changed files。
- `validate_planner_decision(value)`：要求 `accept`、`rework`、`blocked` 或 `human_review_required` 之一。

模型输出无效时抛出 `ProtocolError`，不得静默填默认值。

**Step 4: 验证**

运行：

```bash
python3 -m pytest tests/metacoding/test_models.py -q
```

---

## Task 3: Implement Project Config With Per-Harness Models

**Files:**
- Create: `metacoding/config.py`
- Create: `tests/metacoding/test_config.py`
- Create: `docs/metacoding/config.example.toml`

**Step 1: 写配置失败测试**

覆盖：缺少配置时默认值、TOML 加载、三个 Harness 独立 model、CLI override、非法 provider、非法 max rounds、secret 字段拒绝持久化。

**Step 2: 实现配置模型**

使用 `tomllib.loads()`/`tomllib.load()`；在 Python 版本不支持 TOML 写入时只读 `config.toml`，示例配置通过静态模板维护。配置对象至少包含：

```text
ProjectConfig
  project.schema_version
  limits.max_rounds
  limits.same_failure_limit
  limits.idle_timeout_seconds
  harness.planner: provider, command, model, extra_args
  harness.coder: provider, command, model, extra_args
  harness.tester: provider, command, model, extra_args
  policy.allow_network
  policy.allow_destructive_commands
  policy.tester_can_modify_source
  github.*
```

**Step 3: 实现配置解析优先级**

`load_config(project_root, cli_overrides)` 按默认值、项目文件、CLI 覆盖合并；运行时保存 `config_snapshot` 到 `run.json`，但不改写项目配置。

**Step 4: 验证 model invocation 配置**

测试断言 Planner/Coder/Tester 的 model 分别为配置值，不能因为 provider 相同而互相覆盖。

**Step 5: 验证**

```bash
python3 -m pytest tests/metacoding/test_config.py -q
```

---

## Task 4: Add Project Snapshot, Git Baseline, And Lock

**Files:**
- Create: `metacoding/project.py`
- Create: `metacoding/locking.py`
- Create: `tests/metacoding/test_project.py`
- Create: `tests/metacoding/test_locking.py`

**Step 1: 写项目快照测试**

覆盖当前目录解析、Git revision、初始 dirty files、文件清单、测试命令探测和无 Git 项目降级。

**Step 2: 实现 `ProjectSnapshot`**

记录项目根、Git HEAD、dirty 文件、文件清单、检测到的测试命令和采集时间。排除 `.metacoding/runs`、transcripts 和 logs，避免运行记录污染业务快照。

**Step 3: 写锁测试**

一个进程持锁时第二个 `metacoding run` 必须得到可读的 active-run 错误；异常退出后支持 stale lock 检测，但不能无条件覆盖仍在运行的进程。

**Step 4: 实现项目锁**

使用原子创建 `.metacoding/active-run.lock`，保存 PID、run id、主机和时间；使用 context manager 确保正常结束释放。

**Step 5: 验证**

```bash
python3 -m pytest tests/metacoding/test_project.py tests/metacoding/test_locking.py -q
```

---

## Task 5: Implement Persistence And Resume Records

**Files:**
- Create: `metacoding/persistence.py`
- Create: `tests/metacoding/test_persistence.py`
- Create: `tests/metacoding/test_resume.py`

**Step 1: 写原子持久化测试**

覆盖 run 创建、状态更新、round 追加、transcript 元数据、final report、损坏 JSON 和中断恢复。

**Step 2: 实现文件布局**

每次 run 使用：

```text
.metacoding/runs/<run-id>/
  run.json
  initial-plan.json
  rounds/round-001/{planner,coding,tester,planner-review}*.json
  transcripts/<harness>-<attempt>.{json,stdout,stderr}
  git/{baseline,changes,delivery}.json
  final.json
```

人类文档写入：

```text
docs/metacoding/{PRD,ARCHITECTURE,IMPLEMENTATION_PLAN,ACCEPTANCE,TEST_REPORT,FINAL_REPORT}.md
```

**Step 3: 实现原子写入**

先写同目录临时文件，`flush`/`fsync` 后使用 `os.replace()`；每次状态变更同时写 `state.json` 的 active run 指针。

**Step 4: 实现恢复选择**

读取 active run，按状态决定下一步：`PLANNING` 重跑 Planner、`CODING` 重跑当前轮 Coder、`TESTING` 重跑 Tester、`PLANNER_REVIEW` 重跑 Planner review；已完成状态不可 resume。

**Step 5: 验证**

```bash
python3 -m pytest tests/metacoding/test_persistence.py tests/metacoding/test_resume.py -q
```

---

## Task 6: Build Process Runner And Harness Adapters

**Files:**
- Create: `metacoding/process_runner.py`
- Create: `metacoding/harnesses/base.py`
- Create: `metacoding/harnesses/codex_planner.py`
- Create: `metacoding/harnesses/pi_coder.py`
- Create: `metacoding/harnesses/codex_tester.py`
- Create: `metacoding/harnesses/fake.py`
- Create: `tests/metacoding/test_process_runner.py`
- Create: `tests/metacoding/test_harnesses.py`

**Step 1: 写 command construction 测试**

精确断言：

- Planner 命令包含 Codex command、Planner model 和 JSON 输出参数。
- Coder 命令包含 Pi command、Coder model 和 coding prompt。
- Tester 命令包含 Codex command、Tester model 和 tester prompt。
- 三次调用的 model 不被共享变量覆盖。

**Step 2: 实现通用 process runner**

提供 stdout/stderr 捕获、实时 progress callback、idle timeout、退出码、信号中断、命令元数据和 transcript 写入。区分 `HarnessTimeout`、`HarnessCommandMissing`、`HarnessNonZeroExit` 和 `MalformedHarnessOutput`。

**Step 3: 实现统一 Harness 基类**

Harness 接口接收项目根、run/round、契约文件路径和配置快照，不把整个项目历史拼进 prompt；prompt 指向工作区中的文档路径。

**Step 4: 实现 Codex Planner**

初始调用要求写入 Planner-owned 文档并返回 `PlannerPlan`；review 调用只读取最新 Tester 报告、Git changes 和契约，返回接受或明确 rework tasks。

**Step 5: 实现 Pi Coder**

只执行 Planner 允许范围和当前 rework tasks，返回变更摘要；宿主机在前后采集 Git diff，不信任 Coder 自报路径。

**Step 6: 实现 Codex Tester**

读取 PRD、架构、实施计划和 acceptance，运行项目测试/检查，写 `TEST_REPORT.md` 并返回结构化证据；宿主机比较 Tester 前后工作区以检测污染。

**Step 7: 实现 Fake Harness**

支持脚本化序列：首次失败、第二轮通过、重复失败、非法 JSON、超时和修改受保护文件，供所有核心流程测试使用。

**Step 8: 验证**

```bash
python3 -m pytest tests/metacoding/test_process_runner.py tests/metacoding/test_harnesses.py -q
```

---

## Task 7: Implement Deterministic Policies And Orchestrator

**Files:**
- Create: `metacoding/policies.py`
- Create: `metacoding/orchestrator.py`
- Create: `tests/metacoding/test_policies.py`
- Create: `tests/metacoding/test_orchestrator.py`

**Step 1: 写状态机失败测试**

覆盖完整路径：planning → coding → testing → planner review → accepted；失败后 rework → coding；blocked、human review 和 infrastructure failure。

**Step 2: 实现宿主机状态转移**

每次转移先校验前置 artifact，再持久化新状态，最后启动下一个 Harness。严禁通过 Harness 返回值直接跳过状态。

**Step 3: 实现初始规划阶段**

采集项目快照，创建 run，调用 Planner，校验计划，保存四份开发契约，然后进入 Coding。

**Step 4: 实现 coding/testing/review loop**

每轮按严格顺序调用 Coder、采集 diff、调用 Tester、校验报告、调用 Planner review。下一轮只接收持久化的 rework tasks，不依赖进程内聊天状态。

**Step 5: 实现 policy gates**

至少包含：有效计划 gate、Tester evidence gate、P0/P1 gate、failed deterministic checks gate、scope gate、protected path gate、Tester contamination gate 和 owned diff gate。

**Step 6: 实现 stop conditions**

达到 `max_rounds`、同一 failure fingerprint 达到 `same_failure_limit`、scope 持续越界或需要外部危险动作时分别生成 blocked/human review 结果，并保留全部证据。

**Step 7: 验证核心验收**

```bash
python3 -m pytest tests/metacoding/test_policies.py tests/metacoding/test_orchestrator.py -q
```

---

## Task 8: Implement TUI And Operator Commands

**Files:**
- Modify: `metacoding/cli.py`
- Create: `metacoding/tui.py`
- Create: `tests/metacoding/test_tui.py`

**Step 1: 写 TUI 测试**

覆盖需求输入、阶段进度、错误可读性、`/status`、`/report`、`/artifacts`、`/resume`、`/cancel`、`/deliver`、`/help` 和 `/exit`。

**Step 2: 实现非交互命令**

支持：

```bash
metacoding run "..."
metacoding status
metacoding resume
metacoding report
metacoding artifacts
metacoding cancel
metacoding deliver
```

所有命令都显式接收项目根和 CLI overrides；`run` 的返回码为 accepted/delivered=0，其余终态为非零。

**Step 3: 实现交互式 TUI**

只渲染阶段状态、round、finding 数和最终 artifact 路径；不直接打印完整模型输出。输入循环不阻塞后台状态持久化，Ctrl-C 转为可恢复的 interrupted 状态。

**Step 4: 验证**

```bash
python3 -m pytest tests/metacoding/test_tui.py -q
```

---

## Task 9: Implement Git-Owned Diff And Local Delivery

**Files:**
- Create: `metacoding/github.py`
- Create: `tests/metacoding/test_github_delivery.py`

**Step 1: 写 Git 安全测试**

覆盖 dirty baseline、无关预存改动、专用分支、只提交 owned diff、受保护分支、无 Git 仓库和 commit 失败。

**Step 2: 实现 baseline/diff ownership**

记录运行前 HEAD 和 dirty files；运行后只允许 Planner/Coder 授权路径变化。提交前将新增和修改文件与 baseline 做差集，拒绝 stage 无关文件。

**Step 3: 实现本地交付**

接受后创建 `metacoding/<run-id>` 分支，使用确定性 commit message，禁止 force-push 和重写已有 commit；写入 `.metacoding/runs/<run-id>/git/delivery.json`。

**Step 4: 验证**

```bash
python3 -m pytest tests/metacoding/test_github_delivery.py -q
```

---

## Task 10: Add Optional GitHub Push, Pull Request, And CI Evidence

**Files:**
- Modify: `metacoding/github.py`
- Modify: `metacoding/config.py`
- Modify: `metacoding/orchestrator.py`
- Modify: `tests/metacoding/test_github_delivery.py`

**Step 1: 写远程交付测试**

使用 fake GitHub client 覆盖 push、PR 创建、已存在 PR 更新、required check 通过/失败和远程不可用。

**Step 2: 实现 GitHub client**

优先调用现有 `gh` 登录状态和环境认证；不写全局 Git/gh 配置，不保存 token。远程动作必须显式由 `[github]` 配置开启或 `/deliver` 确认。

**Step 3: 实现 CI 回流**

CI 失败只在 `wait_for_checks=true` 且项目启用远程验收时回到 Tester evidence → Planner review；否则记录为 delivery warning，不推翻已通过的本地实现。

**Step 4: 验证**

```bash
python3 -m pytest tests/metacoding/test_github_delivery.py -q
```

---

## Task 11: Delete Old DevClaw And Migrate Documentation

**Files:**
- Delete: `devclaw/`
- Delete or replace: 旧 `tests/test_*.py`
- Modify: `README.md`
- Modify: `docs/plans/devclaw-roadmap.md`
- Modify: `docs/plans/devclaw-real-completion-todo.md`
- Create: `docs/metacoding/README.md`
- Create: `docs/metacoding/config.example.toml`
- Modify: `.gitignore`

**Step 1: 清理旧引用**

运行：

```bash
rg -n "devclaw|DevClaw|Deepseek|ROLE_ASSIGNMENTS|role_assignments" README.md scripts docs tests metacoding
```

将用户文档、命令示例和测试全部切换到 `metacoding`，不向目标项目根目录自动写入或覆盖 README。

**Step 2: 删除旧实现**

删除旧 package、旧入口脚本和无法表达新契约的旧测试；不创建 `devclaw` 转发模块，不保留旧配置迁移兼容。

**Step 3: 更新文档**

明确写出三 Harness 的配置位置、model 覆盖参数、TUI 命令、`.metacoding/` 与 `docs/metacoding/` 的边界、GitHub 默认安全行为和恢复方式。

**Step 4: 验证无残留**

```bash
rg -n "devclaw|DevClaw|Deepseek" . --glob '!docs/plans/2026-09-07-metacoding-design.md' --glob '!docs/plans/2026-09-07-metacoding-implementation.md'
```

预期：仅保留必要的历史设计说明或迁移记录，不存在可执行旧入口和旧 import。

---

## Task 12: Run Full Deterministic Validation

**Files:**
- Modify: `tests/metacoding/test_e2e.py`
- Modify: `tests/metacoding/test_real_integrations.py`（默认 skip，仅显式环境变量启用）

**Step 1: 写 fake E2E 场景**

至少覆盖：一次通过、一次返工后通过、重复失败 blocked、max-rounds blocked、Planner 接受但 deterministic gate 失败、Tester 污染工作区、恢复和 GitHub fake delivery。

**Step 2: 运行聚焦测试**

```bash
python3 -m pytest tests/metacoding -q
```

**Step 3: 运行全套测试**

```bash
python3 -m pytest -q
```

**Step 4: 检查命令冒烟**

```bash
tmpdir="$(mktemp -d)"
(cd "$tmpdir" && PYTHONPATH="$OLDPWD" python3 -m metacoding --help)
(cd "$tmpdir" && PYTHONPATH="$OLDPWD" python3 -m metacoding status)
rm -rf "$tmpdir"
```

预期：新 TUI/CLI 可运行；未配置真实 Harness 时给出明确配置提示，不发起隐式网络调用。

---

## Cross-Cutting Acceptance Criteria

- `metacoding` 不导入或调用旧 `devclaw` 模块。
- Planner model 来自 `[harness.planner].model`，Coder model 来自 `[harness.coder].model`，Tester model 来自 `[harness.tester].model`；三者可完全不同。
- CLI 的 `--planner-model`、`--coder-model`、`--tester-model` 只覆盖本次 run。
- Planner 和 Tester 即使 provider 都是 Codex，也拥有独立 command invocation、transcript 和 model snapshot。
- Coding 没有有效 Planner plan 时不会执行。
- Tester 在每次 Coding 结束后必定执行，除非进入 infrastructure failure。
- Planner review 必须读取当前轮 Tester report，不能只依赖 Coder output。
- P0/P1、blocking finding、失败 deterministic gate 或污染检测未解决时不能交付。
- 中断、超时、malformed output 和重复失败都会留下可诊断记录。
- 交付只提交本次 run 的 owned diff，不提交用户已有 dirty files。
- GitHub 默认不 push、不创建 PR；启用后只从专用分支执行，不 force-push。
- 所有 fake E2E 不依赖 Codex、Pi、GitHub 或网络。

## Suggested Implementation Order And Checkpoints

1. Task 1–3：包、CLI、模型、配置和三 model 配置测试。
2. Task 4–5：项目快照、锁、持久化和 resume。
3. Task 6–7：Fake Harness、协议、状态机和确定性门禁；完成 Milestone 1。
4. Task 8：TUI 和 operator commands。
5. Task 9–10：Git 本地交付、可选 GitHub/CI。
6. Task 11：删除旧 DevClaw 和迁移文档。
7. Task 12：完整验证；完成 V1。

每个 Task 完成后先运行该 Task 的聚焦测试，再进入下一 Task；真实 Codex/Pi 集成测试只在显式设置环境变量时运行。

