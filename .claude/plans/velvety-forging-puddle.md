# ScrapydWeb CI 现代化迁移计划

## Context

ScrapydWeb 当前的 CI 完全依赖 `.circleci/config.yml`（399 行），使用 YAML anchor `&test-template` 复制了 12 个 job。每个 job 内联了所有步骤（apt 安装、venv 创建、依赖安装、Scrapyd 启动、Allure 报告生成等），导致：
- 配置体积大、重复严重（每个 job 都安装 Java 11 + 下载 Allure CLI）
- 无法在 GitHub 原生环境运行
- 无法在本地测试 CI 步骤
- 没有机制验证矩阵覆盖完整性

本方案将迁移到 GitHub Actions，通过矩阵策略 + 可复用 shell 脚本 + 矩阵校验脚本解决上述问题。

---

## 设计决策

| 决策 | 选择 | 理由 |
|------|------|------|
| CI 平台 | GitHub Actions | GitHub 原生、可持续演进、社区生态丰富 |
| 复用入口 | Shell 脚本（`scripts/ci/`） | 可本地运行、跨平台、不绑定特定 CI |
| 矩阵结构 | 基础维度 + `include` 特殊组合 | 避免无效组合的笛卡尔爆炸 |
| Lint | 独立 job | 与 Python 版本无关、快速失败信号 |
| Coverage 上传 | 仅 3 个代表性 job | 减少 API 调用、避免聚合竞争 |
| Allure | 仅 1 个 job（py312） | Java+CLI 下载开销大，一份报告足够 |
| CircleCI | 保留为空壳 stub | 过渡期安全网，后续可删除 |

---

## 文件变更总览

### 新建文件（9 个）

| 文件 | 用途 |
|------|------|
| `.github/workflows/ci.yml` | GitHub Actions 主工作流 |
| `scripts/ci/setup-env.sh` | 根据 DB_BACKEND 设置环境变量 |
| `scripts/ci/install.sh` | 依赖安装 + Scrapyd 变体切换 |
| `scripts/ci/setup-db.sh` | PostgreSQL/MySQL 数据库初始化 |
| `scripts/ci/launch-scrapyd.sh` | 启动 Scrapyd 并等待就绪 |
| `scripts/ci/run-tests.sh` | flake8 + pytest + coverage 执行 |
| `scripts/ci/coverage-report.sh` | 生成报告 + 可选上传 |
| `scripts/ci/validate-matrix.py` | 矩阵完整性校验脚本 |
| `scripts/ci/README.md` | CI 脚本文档 |

### 修改文件（1 个）

| 文件 | 变更 |
|------|------|
| `.circleci/config.yml` | 399 行 → ~8 行 deprecation stub |

### 不变文件

`.coveragerc`、`.codecov.yml`、`.pep8speaks.yml`、`tests/conftest.py`、`setup.py`、`requirements.txt`、`requirements-tests.txt`

---

## CI 矩阵设计（13 个测试 job + 1 个 lint job）

```
┌─────┬────────┬─────────────┬──────────────┬─────────┬────────┐
│  #  │ Python │ Scrapyd     │ DB Backend   │ Cov↑    │ Allure │
├─────┼────────┼─────────────┼──────────────┼─────────┼────────┤
│  1  │ 3.8    │ default     │ SQLite       │         │        │
│  2  │ 3.9    │ default     │ SQLite       │         │        │
│  3  │ 3.9    │ v1.4.3      │ SQLite       │         │        │
│  4  │ 3.10   │ default     │ SQLite       │         │        │
│  5  │ 3.10   │ default     │ PostgreSQL   │ ✅      │        │
│  6  │ 3.10   │ default     │ MySQL        │ ✅      │        │
│  7  │ 3.10   │ default     │ SQLite-custom│         │        │
│  8  │ 3.10   │ git HEAD    │ PostgreSQL   │         │        │
│  9  │ 3.10   │ git HEAD    │ MySQL        │         │        │
│ 10  │ 3.11   │ default     │ SQLite       │         │        │
│ 11  │ 3.12   │ default     │ SQLite       │ ✅      │ ✅     │
│ 12  │ 3.12   │ v1.4.3      │ SQLite       │         │        │
│ 13  │ 3.13   │ default     │ SQLite       │         │        │
│ lint│ 3.12   │ —           │ —            │         │        │
└─────┴────────┴─────────────┴──────────────┴─────────┴────────┘
```

### 原 CircleCI job → GHA job 映射

| 原 CircleCI Job | GHA Job | 匹配 |
|----------------|---------|------|
| `py38` | #1 | ✅ 完全匹配 |
| `py39` | #2 | ✅ 完全匹配 |
| `py39-scrapyd-v143` | #3 | ✅ 完全匹配 |
| `py310-postgresql` | #5 | ✅ + 覆盖上传 |
| `py310-mysql` | #6 | ✅ + 覆盖上传 |
| `py310-sqlite` | #7 | ✅ 保留 DATA_PATH |
| `py310-git-postgresql` | #8 | ✅ 完全匹配 |
| `py310-git-mysql` | #9 | ✅ 完全匹配 |
| `py311` | #10 | ✅ 完全匹配 |
| `py312` | #11 | ✅ + 覆盖 + Allure |
| `py312-scrapyd-v143` | #12 | ✅ 完全匹配 |
| `py313` | #13 | ✅ 完全匹配 |
| *(新增)* | lint | 独立 lint job |
| *(新增)* | #4 | 基础矩阵自然产生 3.10/default |

---

## 关键实现细节

### 1. `.github/workflows/ci.yml` 结构

```yaml
# 触发条件: push/pull_request to master/main
# 全局环境变量: SCRAPYDWEB_TESTMODE=True

jobs:
  lint:
    # 独立 job，Python 3.12，仅安装 flake8
    # 步骤 1: flake8 --select=E9,F63,F7,F82 (关键错误，必须通过)
    # 步骤 2: flake8 --max-line-length=120 --ignore=E266,E303,E128,E701,W504 (风格检查，allow failure)

  validate-matrix:
    # 独立 job，Python 3.12，安装 pyyaml
    # 运行 scripts/ci/validate-matrix.py 验证矩阵完整性

  test:
    needs: [lint, validate-matrix]
    strategy:
      fail-fast: false
      matrix:
        python-version: ['3.8','3.9','3.10','3.11','3.12','3.13']
        # 基础维度产生 6 个默认 job
        include:
          # scrapyd-v143: py39, py312
          # git HEAD + DB: py310+git+postgresql, py310+git+mysql
          # DB variants: py310+postgresql, py310+mysql, py310+sqlite-custom
          # coverage+allure: py312 默认
    services:
      postgres:  # postgres:9.6 with health check
      mysql:     # mysql:5.7 with health check
    steps:
      - checkout → setup-python → setup-env.sh → install.sh
      → [可选] setup-db.sh → launch-scrapyd.sh → run-tests.sh
      → coverage-report.sh → [可选] upload artifacts
```

**Service 容器策略**：PostgreSQL 和 MySQL 服务容器在所有矩阵 job 中声明，但只在 `db-backend` 匹配时才使用。空闲容器仅消耗 ~10s 启动开销，可接受。

### 2. Shell 脚本关键逻辑

**`setup-env.sh`**：根据 `DB_BACKEND` 设置 `DATABASE_URL` 和 `DATA_PATH`
- `postgresql` → `postgresql://circleci:passw0rd@localhost:5432`
- `mysql` → `mysql://root:rootpw@127.0.0.1:3306`
- `sqlite-custom` → 创建自定义目录 + `sqlite:///...`
- `default` → 不设置（使用应用内部 SQLite 默认值）

**`install.sh`**：根据 `SCRAPYD_VARIANT` 安装依赖
- `git` → pip install 三个 git 仓库 HEAD
- `v1.4.3` → pip install scrapyd==1.4.3
- `default` → 仅 requirements.txt + requirements-tests.txt

**`launch-scrapyd.sh`**：写入 scrapyd.conf（admin:12345），nohup 启动，用 curl 轮询等待就绪（最长 30s）

**`run-tests.sh`**：flake8 关键检查 + coverage run pytest，可选 `--alluredir`（当 `ALLURE_ENABLED=true`）

**`coverage-report.sh`**：coverage report/html/xml，仅当 `UPLOAD_COVERAGE=true` 时上传 Codecov + Coveralls

### 3. 矩阵校验脚本 `validate-matrix.py`

解析 `.github/workflows/ci.yml` 的 YAML，提取实际矩阵组合，与预定义的 REQUIRED_COMBOS 集合对比：

```python
REQUIRED_COMBOS = [
    # 6 个 Python 版本基础测试
    ("3.8", "default", "default"),  ("3.9", "default", "default"), ...
    # 2 个 Scrapyd 版本锁定
    ("3.9", "v1.4.3", "default"),   ("3.12", "v1.4.3", "default"),
    # 2 个 git HEAD 组合
    ("3.10", "git", "postgresql"),  ("3.10", "git", "mysql"),
    # 3 个数据库变体
    ("3.10", "default", "postgresql"), ("3.10", "default", "mysql"),
    ("3.10", "default", "sqlite-custom"),
]
```

输出缺失组合 → exit 1（CI 阻断）。同时检查维度覆盖（Python 版本、Scrapyd 变体、DB 后端是否都被覆盖到）。

### 4. `.circleci/config.yml` 精简

```yaml
# DEPRECATED: CI migrated to GitHub Actions (.github/workflows/ci.yml)
version: 2.1
workflows:
  noop:
    jobs: []
```

---

## 实施顺序

1. 创建 `scripts/ci/` 目录及 6 个 shell 脚本
2. 创建 `scripts/ci/validate-matrix.py`
3. 创建 `scripts/ci/README.md` 文档
4. 创建 `.github/workflows/ci.yml` 工作流
5. 精简 `.circleci/config.yml` 为 deprecation stub
6. 本地验证：运行 `python scripts/ci/validate-matrix.py` 确认矩阵完整

---

## 校验方式

1. **矩阵校验**：`python scripts/ci/validate-matrix.py`（需安装 pyyaml）→ exit 0 表示全覆盖
2. **脚本本地测试**：`bash scripts/ci/install.sh && bash scripts/ci/launch-scrapyd.sh && bash scripts/ci/run-tests.sh`
3. **CI 自验**：push 后观察 GitHub Actions 所有 14 个 job 是否绿
