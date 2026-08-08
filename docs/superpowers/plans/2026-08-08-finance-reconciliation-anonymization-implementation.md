# Finance Reconciliation Anonymization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在首次 `v0.2.0` 发布前，将公开源码、镜像和 DSM 部署完整迁移到 `finance-reconciliation` 中性命名，同时保持真实财务数据和现有外部访问地址不变。

**Architecture:** 私有开发分支先完成所有运行时标识、界面、测试夹具、发布链路和运维脚本的中性化，再由安全快照工具创建无父历史的公开根提交。新 GitHub/GHCR 链路通过源码、历史和镜像三层扫描后发布 `v0.2.0`，DSM 使用可回滚的身份迁移切到新的 Compose project 和目录，最后才删除旧公开资产。

**Tech Stack:** Python 3.12、Django 5.2、PostgreSQL 16、Docker/Compose v2、Gunicorn、Bash、GitHub Actions、GHCR、Node test runner、Playwright、DSM Container Manager。

## Global Constraints

- 产品中文名称固定为“财务管理系统”，英文名称固定为 `Finance Reconciliation`。
- GitHub 仓库、Compose project 和 DSM 目录名固定为 `finance-reconciliation`。
- GHCR 镜像固定为 `ghcr.io/s450586793/finance-reconciliation-web` 和 `ghcr.io/s450586793/finance-reconciliation-updater`。
- 产品专用环境变量和构建参数统一使用 `FINREC_` 前缀，不公开旧前缀兼容别名。
- 外部地址 `http://sd.ace-station.top:1111` 保持不变。
- 发票、银行流水、微信账单、单位档案和其他真实财务数据不得因匿名化而改写。
- 公开仓库文件名/内容、全部可达 Git 历史、镜像文件系统、构建历史和 OCI labels 的外部品牌锚点命中数必须为 `0`。
- 扫描锚点文件必须位于仓库外、权限为 `0600`，任何命令不得输出其内容。
- release 只接受规范 `vX.Y.Z`；Web/updater 使用不可变版本 tag，Web `stable` 只在两张镜像全部发布成功后提升。
- Web 升级成功后只精准清理已验证的不再使用镜像；失败或身份含糊时保留回滚资产。
- DSM 迁移期间只能有一个 PostgreSQL 实例使用目标数据目录。
- 删除旧仓库、GHCR 包、容器、镜像或目录必须晚于新链路和 DSM 全部验收门。
- 所有新行为先写失败测试；每次只暂存当前任务列出的文件，不使用 `git add .`。

## File Structure

- Create `scripts/public_scan.py` and modify `scripts/scan-public-tree.py`: 通过可测试模块大小写不敏感地扫描路径、普通文件和 ZIP 成员。
- Create `scripts/scan-public-history.py`: 导出并扫描仓库全部可达提交，拒绝异常对象和失败命令。
- Create `scripts/scan-public-images.sh`: 扫描镜像 inspect、history 和导出的最终文件系统。
- Create `tests/test_public_scanning.py`, `scripts/scan-public-images.test.sh`: 公开扫描契约测试。
- Modify `apps/core/context_processors.py`, `templates/**/*.html`, `static/js/system-update.js`: 中性产品名称和浏览器状态 key。
- Modify `tests/web/`, `tests/e2e/`, `tests/imports/`, `tests/fixtures/`: 中性测试主体及重新生成的二进制夹具。
- Modify `config/settings/base.py`, `config/settings/prod.py`, `apps/system_update/client.py`: `FINREC_*` Django/updater 配置接口。
- Modify `updater/config.py`, `updater/platform.py`: 中性 Compose、镜像、环境文件 key 和 rollback alias。
- Modify `Dockerfile`, `compose.yml`, `.env.example`, `pyproject.toml`: 中性构建、镜像、数据库和 DSM 运行契约。
- Modify `scripts/system-update-*.sh`, `scripts/system-update-updater-atomic.py`, `scripts/deploy-dsm.sh`: 中性升级、清理、smoke 和身份迁移流程。
- Modify `.github/workflows/release-images.yml`, `scripts/release-images-contract.test.sh`: 中性镜像发布和公开扫描门。
- Modify `scripts/create-public-snapshot.sh`, `scripts/create-public-snapshot.test.sh`, `scripts/public-snapshot-manifest.txt`: 中性无父历史快照。
- Modify `README.md`, `docs/deployment-dsm.md`, `docs/system-update-runbook.md`, `docs/acceptance-results.md`: 中性公开说明和真实操作顺序。
- Rename the four dated historical design/plan files to neutral same-date filenames and update their content before public snapshot creation.

---

### Task 1: Fail-Closed Public Source, History, and Image Scanning

**Files:**
- Create: `scripts/public_scan.py`
- Modify: `scripts/scan-public-tree.py`
- Create: `scripts/scan-public-history.py`
- Create: `scripts/scan-public-images.sh`
- Create: `tests/test_public_scanning.py`
- Create: `scripts/scan-public-images.test.sh`
- Modify: `pyproject.toml`

**Interfaces:**
- Produces from `scripts.public_scan`: `scan_tree(root: Path, anchor_path: Path) -> None`，对路径和内容执行大小写不敏感的 UTF-8/UTF-16 锚点扫描。
- Produces from `scripts.public_scan`: `scan_history(repository: Path, anchor_path: Path) -> None`，扫描 `git rev-list --all` 返回的每个可达提交。
- Produces: `scripts/scan-public-images.sh ANCHOR_FILE IMAGE...`，成功仅输出固定文本 `public image scan passed`。

- [ ] **Step 1: Write failing case-folded tree and history tests**

```python
def test_scan_tree_rejects_case_variant_in_nested_filename(tmp_path, anchors):
    root = tmp_path / "tree"
    root.mkdir()
    (root / "PRIVATE-COMPANY.txt").write_text("safe", encoding="utf-8")
    with pytest.raises(ValueError):
        scan_tree(root, anchors("private-company"))


def test_scan_history_rejects_anchor_in_older_reachable_commit(git_repo, anchors):
    git_repo.commit_file("record.txt", "PRIVATE-COMPANY")
    git_repo.commit_file("record.txt", "public")
    with pytest.raises(PublicScanError, match="public_history_scan_failed"):
        scan_history(git_repo.path, anchors("private-company"))
```

Cover UTF-8, UTF-16 LE/BE, ZIP member names/content, symlinks, forbidden suffixes, malformed Git output, failed `git archive`, and an anchor that exists only in an older commit. Assert exception text never contains the anchor or scanned path.

- [ ] **Step 2: Run the focused Python tests and verify RED**

Run: `.venv/bin/pytest tests/test_public_scanning.py -q`

Expected: FAIL because case variants are accepted and `scan-public-history.py` does not exist.

- [ ] **Step 3: Extract reusable scanning functions and implement history scanning**

Use byte-level ASCII folding for UTF-8 and both UTF-16 byte sequences so binary files stay supported:

```python
def _scan_bytes(data: bytes, anchors: list[tuple[bytes, bytes, bytes]]) -> None:
    folded = data.lower()
    if PRIVATE_KEY_PATTERN.search(data):
        raise ValueError
    if any(candidate.lower() in folded for variants in anchors for candidate in variants):
        raise ValueError
```

Implement both functions in `scripts/public_scan.py`. Keep `scan-public-tree.py` and `scan-public-history.py` as thin fixed-argument CLIs that import the module, return exit `1` on every rejected input, and print only their fixed success message. `scan_history()` must run fixed tuple argv with `shell=False`, validate each commit as a single 40-character lowercase hex SHA, export one commit at a time into a private `TemporaryDirectory`, use `tarfile.extractall(filter="data")`, call `scan_tree()`, and convert all subprocess/tar/scanner failures to `PublicScanError("public_history_scan_failed")`.

- [ ] **Step 4: Write failing image scanner contract tests**

Create a fake `docker` executable that supplies controlled JSON/history text and an uncompressed export tar. Cover clean success; anchor in inspect, history, and filesystem; missing image; multi-line image ID; failed export; and output redaction.

Run: `bash scripts/scan-public-images.test.sh`

Expected: FAIL because the image scanner does not exist.

- [ ] **Step 5: Implement the image scanner**

The shell script must use a mode-`0700` scratch directory and, for every exact image argument:

```bash
docker image inspect "$image" >"$scratch_dir/inspect-$index.json"
docker history --no-trunc "$image" >"$scratch_dir/history-$index.txt"
container_id="$(docker create "$image")"
docker export "$container_id" >"$scratch_dir/filesystem-$index.tar"
docker rm "$container_id" >/dev/null
python3 "$project_root/scripts/scan-public-tree.py" "$scratch_dir" "$anchor_file" >/dev/null
```

Reject ambient `DOCKER_HOST`/context/TLS overrides, reject a non-`0600` anchor file, remove temporary containers on every exit path, and never print Docker output.

- [ ] **Step 6: Verify and commit**

Run: `.venv/bin/pytest tests/test_public_scanning.py -q`

Run: `bash scripts/scan-public-images.test.sh`

```bash
git add scripts/public_scan.py scripts/scan-public-tree.py scripts/scan-public-history.py scripts/scan-public-images.sh tests/test_public_scanning.py scripts/scan-public-images.test.sh pyproject.toml
git diff --cached --check
git commit -m "feat: 增加公开历史与镜像匿名扫描"
```

### Task 2: Neutral Product UI and Synthetic Business Fixtures

**Files:**
- Modify: `apps/core/context_processors.py`
- Modify: `templates/base.html`
- Modify: `templates/registration/login.html`
- Modify: `templates/imports/index.html`
- Modify: `templates/imports/preview.html`
- Modify: `templates/ledger/invoice_list.html`
- Modify: `templates/ledger/transaction_list.html`
- Modify: `templates/parties/list.html`
- Modify: `templates/reconciliation/*.html`
- Modify: `templates/reporting/*.html`
- Modify: `templates/system_update/index.html`
- Modify: `static/js/system-update.js`
- Modify: `static/js/system-update.test.js`
- Modify: `tests/web/test_import_views.py`
- Modify: `tests/web/test_ledger_views.py`
- Modify: `tests/web/test_reporting_views.py`
- Modify: `tests/web/test_reconciliation_views.py`
- Modify: `tests/web/test_settlement_views.py`
- Modify: `tests/e2e/system-update.spec.ts`
- Modify: `tests/e2e/import-and-reconcile.spec.ts`
- Modify: `tests/e2e/test_synthetic_railway_workflow.py`
- Modify: `tests/imports/fakes.py`
- Modify: `tests/imports/test_tax_invoice_parser.py`
- Modify: `tests/fixtures/generate_synthetic_fixtures.py`
- Regenerate: `tests/fixtures/*.xls`, `tests/fixtures/*.xlsx`, `tests/fixtures/synthetic_railway/*`

**Interfaces:**
- Produces: every rendered page receives `product_name == "财务管理系统"`。
- Produces: browser pending-update key `finance-reconciliation.system-update.pending-start`。
- Produces: synthetic company display name `测试财务公司` and neutral workbook creator metadata.

- [ ] **Step 1: Write failing UI branding and browser-key tests**

```python
@pytest.mark.django_db
def test_login_uses_neutral_product_name(client):
    response = client.get("/accounts/login/")
    assert "财务管理系统" in response.content.decode()


def test_navigation_context_exposes_fixed_product_name(rf):
    context = navigation(rf.get("/"))
    assert context["product_name"] == "财务管理系统"
```

Update the JS test to assert recovery uses only `finance-reconciliation.system-update.pending-start`. Update page/E2E fixtures to expect `测试财务公司` as the synthetic buyer/seller name.

- [ ] **Step 2: Run focused tests and verify RED**

Run: `.venv/bin/pytest tests/web tests/e2e/test_synthetic_railway_workflow.py tests/imports/test_tax_invoice_parser.py -q`

Run: `node --test static/js/system-update.test.js`

Expected: FAIL on the old title, browser key, and synthetic company values.

- [ ] **Step 3: Implement the shared product name and neutral fixtures**

```python
PRODUCT_NAME = "财务管理系统"


def navigation(request):
    # Existing role and navigation behavior stays unchanged.
    return {
        "product_name": PRODUCT_NAME,
        "is_finance": is_finance,
        "navigation_items": items,
    }
```

Use `{{ product_name }}` in the base shell, login title and every `{% block title %}` suffix. Change all synthetic company names to `测试财务公司`, workbook creator to `Finance Reconciliation synthetic fixture generator`, and account display text to `测试财务账户`.

- [ ] **Step 4: Regenerate deterministic fixtures**

Run: `.venv/bin/python tests/fixtures/generate_synthetic_fixtures.py`

Run the generator twice and verify `git diff --exit-code` after the second run so generated XLS/XLSX/PDF metadata is deterministic.

- [ ] **Step 5: Verify and commit**

Run: `.venv/bin/pytest tests/web tests/e2e/test_synthetic_railway_workflow.py tests/imports/test_tax_invoice_parser.py -q`

Run: `node --test static/js/system-update.test.js`

```bash
git add apps/core/context_processors.py templates static/js/system-update.js static/js/system-update.test.js tests/web tests/e2e tests/imports tests/fixtures
git diff --cached --check
git commit -m "refactor: 中性化产品界面与测试数据"
```

### Task 3: Neutral Django, Image, Compose, and Environment Contract

**Files:**
- Modify: `config/settings/base.py`
- Modify: `config/settings/prod.py`
- Modify: `apps/system_update/client.py`
- Modify: `Dockerfile`
- Modify: `compose.yml`
- Modify: `.env.example`
- Modify: `pyproject.toml`
- Modify: `tests/system_update/test_client.py`
- Modify: `tests/test_health.py`
- Modify: `tests/test_deployment.py`
- Modify: `scripts/system-update-compose.test.sh`

**Interfaces:**
- Produces: `settings.FINREC_RELEASE_VERSION`, `settings.FINREC_UPDATER_URL`, `settings.FINREC_UPDATER_TOKEN`。
- Produces: Compose consumes `FINREC_APP_DIR`, `FINREC_DATA_DIR`, `FINREC_WEB_IMAGE_TAG`, `FINREC_UPDATER_IMAGE_TAG`, `FINREC_UPDATER_TOKEN`。
- Produces: build args `FINREC_RELEASE_VERSION`, `FINREC_RELEASE_REVISION`, `FINREC_RELEASE_CREATED`。
- Produces: default example database `finance_reconciliation` with neutral `finance` role.

- [ ] **Step 1: Change tests to the new runtime contract**

```python
def test_production_release_version_uses_finrec_prefix(monkeypatch):
    configure_production(monkeypatch)
    monkeypatch.setenv("FINREC_RELEASE_VERSION", "v12.34.56")
    settings = reload_production_settings()
    assert settings.FINREC_RELEASE_VERSION == "v12.34.56"


def test_updater_client_reads_neutral_settings(settings):
    settings.FINREC_UPDATER_URL = "http://updater:8090"
    settings.FINREC_UPDATER_TOKEN = "u" * 32
    client = UpdaterClient.from_settings(transport=transport)
    assert client.status().current_version == "v0.2.0"
```

Update Compose and Dockerfile assertions to the exact new repositories, database name and `FINREC_*` keys. Add an assertion that rendered Web and updater environments contain no keys matched by the external legacy anchor set.

- [ ] **Step 2: Run focused tests and verify RED**

Run: `.venv/bin/pytest tests/test_health.py tests/test_deployment.py tests/system_update/test_client.py -q`

Run: `bash scripts/system-update-compose.test.sh`

Expected: FAIL because runtime code and Compose still expose the previous contract.

- [ ] **Step 3: Implement settings and client renames**

```python
FINREC_RELEASE_VERSION = os.environ.get("FINREC_RELEASE_VERSION", "v0.0.0")
FINREC_UPDATER_URL = os.environ.get("FINREC_UPDATER_URL", "http://updater:8090")
FINREC_UPDATER_TOKEN = os.environ.get("FINREC_UPDATER_TOKEN", "")
```

Production validation must preserve the canonical SemVer, exact internal URL and 32-byte token checks under the new keys. `UpdaterClient.from_settings()` reads only the three new setting attributes.

- [ ] **Step 4: Implement image and Compose renames**

```yaml
web:
  image: ghcr.io/s450586793/finance-reconciliation-web:${FINREC_WEB_IMAGE_TAG:?required}
  environment:
    FINREC_UPDATER_URL: http://updater:8090
    FINREC_UPDATER_TOKEN: ${FINREC_UPDATER_TOKEN:?required}
updater:
  image: ghcr.io/s450586793/finance-reconciliation-updater:${FINREC_UPDATER_IMAGE_TAG:?required}
  environment:
    FINREC_UPDATER_TOKEN: ${FINREC_UPDATER_TOKEN:?required}
    FINREC_COMPOSE_PROJECT: finance-reconciliation
```

Use `/volume4/docker/docker/finance-reconciliation/app` and `/volume4/docker/docker/finance-reconciliation/data` in `.env.example`; use `POSTGRES_DB=finance_reconciliation`; change the Python package name to `finance-reconciliation`.

- [ ] **Step 5: Verify and commit**

Run: `.venv/bin/pytest tests/test_health.py tests/test_deployment.py tests/system_update/test_client.py -q`

Run: `bash scripts/system-update-compose.test.sh`

```bash
git add config/settings/base.py config/settings/prod.py apps/system_update/client.py Dockerfile compose.yml .env.example pyproject.toml tests/system_update/test_client.py tests/test_health.py tests/test_deployment.py scripts/system-update-compose.test.sh
git diff --cached --check
git commit -m "refactor: 统一中性运行与镜像标识"
```

### Task 4: Neutral Updater Platform Contract

**Files:**
- Modify: `updater/config.py`
- Modify: `updater/platform.py`
- Modify: `tests/updater/test_config.py`
- Modify: `tests/updater/test_platform.py`
- Modify: `tests/updater/test_manager_success.py`
- Modify: `tests/updater/test_manager_recovery.py`
- Modify: `tests/updater/test_manager_failure.py`
- Modify: `tests/updater/test_manual_cleanup.py`
- Modify: `tests/updater/test_runner.py`
- Modify: `tests/updater/fakes.py`

**Interfaces:**
- Consumes: `FINREC_UPDATER_TOKEN`, `FINREC_COMPOSE_PROJECT=finance-reconciliation`。
- Produces: `PlatformConfig.project_name == "finance-reconciliation"` and `web_repository == "ghcr.io/s450586793/finance-reconciliation-web"`。
- Produces: persisted image tag key `FINREC_WEB_IMAGE_TAG` and rollback alias `finance-reconciliation-rollback-web:{task_id}`。

- [ ] **Step 1: Change updater tests to exact neutral identities**

```python
def environment(**overrides):
    values = {
        "FINREC_UPDATER_TOKEN": TOKEN,
        "FINREC_COMPOSE_PROJECT": "finance-reconciliation",
    }
    values.update(overrides)
    return values


def test_config_uses_fixed_neutral_platform():
    result = UpdaterConfig.from_env(environment())
    assert result.platform.project_name == "finance-reconciliation"
    assert result.platform.web_repository == (
        "ghcr.io/s450586793/finance-reconciliation-web"
    )
```

Update every exact argv, task fixture, environment file, cleanup journal and rollback alias assertion.

- [ ] **Step 2: Run updater tests and verify RED**

Run: `.venv/bin/pytest tests/updater -q`

Expected: FAIL on old project, repository, environment key and rollback alias values.

- [ ] **Step 3: Implement the fixed platform contract**

```python
_PROJECT_NAME = "finance-reconciliation"
_WEB_REPOSITORY = "ghcr.io/s450586793/finance-reconciliation-web"
_WEB_TAG_KEY = "FINREC_WEB_IMAGE_TAG"


def _rollback_alias(task_id: UUID) -> str:
    return f"finance-reconciliation-rollback-web:{task_id}"
```

`UpdaterConfig.from_env()` must require only `FINREC_UPDATER_TOKEN` and exact `FINREC_COMPOSE_PROJECT`. Keep fixed-boundary override rejection under new `FINREC_*` names and preserve all existing redaction, atomic environment update and cleanup invariants.

- [ ] **Step 4: Verify and commit**

Run: `.venv/bin/pytest tests/updater -q`

```bash
git add updater/config.py updater/platform.py tests/updater
git diff --cached --check
git commit -m "refactor: 中性化升级器平台身份"
```

### Task 5: Neutral DSM Scripts and Reversible Identity Migration

**Files:**
- Modify: `scripts/deploy-dsm.sh`
- Modify: `scripts/system-update-dsm-smoke.sh`
- Modify: `scripts/system-update-dsm-smoke.test.sh`
- Modify: `scripts/system-update-updater.sh`
- Modify: `scripts/system-update-updater-atomic.py`
- Modify: `scripts/system-update-updater.test.sh`
- Modify: `scripts/system-update-updater-test-namespace.sh`
- Modify: `scripts/system-update-manual-cleanup.sh`
- Modify: `scripts/system-update-manual-cleanup.test.sh`
- Modify: `tests/test_deployment.py`
- Modify: `tests/test_updater_atomic.py`

**Interfaces:**
- Produces: `FINREC_DEPLOY_MODE=identity-migration|upgrade`。
- Consumes in identity migration only: `FINREC_LEGACY_APP_DIR`, `FINREC_LEGACY_DATA_DIR`, `FINREC_LEGACY_DATABASE_NAME`, `FINREC_LEGACY_DATABASE_ROLE` from private DSM state.
- Produces: fixed target app/data paths under `/volume4/docker/docker/finance-reconciliation`。
- Produces: root-only cleanup confirmation `FINREC_CONFIRM_MANUAL_CLEANUP=yes` and updater confirmation `FINREC_CONFIRM_UPDATER_UPDATE=yes`。

- [ ] **Step 1: Write failing identity-migration and neutral-script tests**

Extend the fake Docker/filesystem harness with these cases:

```python
def test_identity_migration_moves_data_only_after_legacy_db_stops(deploy_context):
    result = deploy_context.run(mode="identity-migration")
    assert result.returncode == 0
    assert deploy_context.events.index("stop-legacy-db") < deploy_context.events.index(
        "move-data-to-neutral-path"
    )


def test_identity_migration_restores_data_path_when_target_health_fails(
    deploy_context,
):
    result = deploy_context.run(mode="identity-migration", target_web_health="unhealthy")
    assert result.returncode != 0
    assert deploy_context.legacy_data_path.exists()
    assert not deploy_context.target_data_path.exists()
    assert deploy_context.legacy_db_running()
```

Also cover target path already exists, source symlink, cross-device move rejection, database/role rename failure, duplicate database container, signal during move, target DB identity ambiguity, and failure to restart legacy containers. Assert scripts expose only fixed error categories.

- [ ] **Step 2: Run focused tests and verify RED**

Run: `.venv/bin/pytest tests/test_deployment.py tests/test_updater_atomic.py -q`

Run: `bash scripts/system-update-dsm-smoke.test.sh`

Run: `bash scripts/system-update-updater.test.sh`

Run: `bash scripts/system-update-manual-cleanup.test.sh`

Expected: FAIL because the scripts do not accept the neutral interface or move paths safely.

- [ ] **Step 3: Implement the reversible data-path move**

In `identity-migration` mode:

1. Canonicalize both legacy paths without logging them; reject symlinks and paths outside `/volume4/docker/docker`.
2. Require target app directory to contain mode-`0600` `.env` and the reviewed neutral `compose.yml`.
3. Capture exact old `db`/`web` container IDs, stop both, and prove the old database is stopped.
4. Require legacy and target parent directories to share `st_dev`, then rename the data directory atomically.
5. Start only the target DB, prove its Compose identity, and run safe identifier migration from private old database/role values to `finance_reconciliation` and `finance`.
6. Run Django migration, start updater/Web, and wait for health.
7. On any failure, stop and prove the target DB stopped, reverse the data-directory rename, then restart the captured legacy IDs.

Use PostgreSQL identifier quoting through server-side `format('%I', value)` and `\gexec`; never interpolate identifiers into shell or SQL source text.

- [ ] **Step 4: Rename every DSM/update shell boundary**

Replace all script-facing product variables, fixed project/repository/path values, temporary-file prefixes, lock paths and test namespaces with `FINREC_*` / `finance-reconciliation`. Preserve updater self-update atomic file replacement, same-directory `fsync`, fixed Docker argv, health verification, and precise old-image cleanup.

- [ ] **Step 5: Verify and commit**

Run: `.venv/bin/pytest tests/test_deployment.py tests/test_updater_atomic.py -q`

Run: `bash scripts/system-update-dsm-smoke.test.sh`

Run: `bash scripts/system-update-updater.test.sh`

Run: `bash scripts/system-update-manual-cleanup.test.sh`

```bash
git add scripts/deploy-dsm.sh scripts/system-update-dsm-smoke.sh scripts/system-update-dsm-smoke.test.sh scripts/system-update-updater.sh scripts/system-update-updater-atomic.py scripts/system-update-updater.test.sh scripts/system-update-updater-test-namespace.sh scripts/system-update-manual-cleanup.sh scripts/system-update-manual-cleanup.test.sh tests/test_deployment.py tests/test_updater_atomic.py
git diff --cached --check
git commit -m "feat: 增加 DSM 中性身份迁移"
```

### Task 6: Neutral Public Snapshot, Release Workflow, and Documentation

**Files:**
- Modify: `scripts/create-public-snapshot.sh`
- Modify: `scripts/create-public-snapshot.test.sh`
- Modify: `scripts/public-snapshot-manifest.txt`
- Modify: `.github/workflows/release-images.yml`
- Modify: `scripts/release-images-contract.test.sh`
- Modify: `README.md`
- Modify: `docs/deployment-dsm.md`
- Modify: `docs/system-update-runbook.md`
- Modify: `docs/acceptance-results.md`
- Rename: the four dated historical design/plan files to `2026-07-27-finance-reconciliation-design.md`, `2026-07-28-finance-reconciliation-implementation.md`, `2026-08-06-web-managed-upgrades-design.md`, and `2026-08-06-web-managed-upgrades-implementation.md`
- Modify: all files below `docs/superpowers/` after rename

**Interfaces:**
- Consumes: `FINREC_PUBLIC_SENSITIVE_ANCHORS_FILE` for local snapshot creation.
- Consumes in GitHub Actions: secret `FINREC_PUBLIC_SCAN_ANCHORS_B64`.
- Produces: parentless `main` commit authored by `Finance Reconciliation Snapshot <snapshot@example.invalid>`。
- Produces: CI jobs `test`, `public-scan`, `preflight`, `publish`, `promote-stable`。

- [ ] **Step 1: Change snapshot and release contract tests**

Assert the public snapshot uses the new environment variable and author, retains exactly one parentless commit, and does not include any path outside the manifest. In release contract tests require:

```python
assert jobs["public-scan"]["needs"] == ["test"]
assert sorted(jobs["preflight"]["needs"]) == ["public-scan", "test"]
assert "FINREC_PUBLIC_SCAN_ANCHORS_B64" in workflow_text
assert "ghcr.io/s450586793/finance-reconciliation-web" in workflow_text
assert "ghcr.io/s450586793/finance-reconciliation-updater" in workflow_text
```

The `public-scan` job must fail if its secret is empty or invalid, scan all reachable commits, build both Docker targets locally, and scan both images before any tag can publish.

- [ ] **Step 2: Run contract tests and verify RED**

Run: `bash scripts/create-public-snapshot.test.sh`

Run: `PATH="$PWD/.venv/bin:$PATH" bash scripts/release-images-contract.test.sh`

Expected: FAIL because the snapshot identity, workflow repositories and scan job still use the legacy contract.

- [ ] **Step 3: Implement the neutral snapshot and CI scan gate**

Use this job dependency and secret boundary:

```yaml
public-scan:
  if: ${{ github.event_name != 'pull_request' }}
  needs:
    - test
  runs-on: ubuntu-latest
  env:
    FINREC_PUBLIC_SCAN_ANCHORS_B64: ${{ secrets.FINREC_PUBLIC_SCAN_ANCHORS_B64 }}
```

The job creates a mode-`0600` anchor file in `$RUNNER_TEMP`, decodes the secret without logging it, runs `scan-public-history.py`, builds targets as `finance-reconciliation-public-scan-web:${GITHUB_SHA}` and `finance-reconciliation-public-scan-updater:${GITHUB_SHA}`, then invokes `scan-public-images.sh`.

Update all release image names and build args to `FINREC_*`. `preflight` must require both `test` and `public-scan`; tag publish remains impossible when either fails.

- [ ] **Step 4: Rewrite public documentation and historical docs**

Use the approved names, new repository/GHCR URLs, new DSM paths and new commands throughout README/runbooks. Rename the four historical documents to their exact neutral destinations and update all links/content. The runbook must describe secure source/history/image scanning, repository secret provisioning, `v0.2.0` release, identity migration, rollback, updater manual rollout, automatic successful-upgrade cleanup and final old-asset deletion.

- [ ] **Step 5: Verify local contracts and commit**

Run: `bash scripts/create-public-snapshot.test.sh`

Run: `PATH="$PWD/.venv/bin:$PATH" bash scripts/release-images-contract.test.sh`

```bash
git add scripts/create-public-snapshot.sh scripts/create-public-snapshot.test.sh scripts/public-snapshot-manifest.txt .github/workflows/release-images.yml scripts/release-images-contract.test.sh README.md docs
git diff --cached --check
git commit -m "docs: 中性化公开发布与运维链路"
```

### Task 7: Full Regression and Parentless Public Snapshot Qualification

**Files:**
- Modify only files required to correct qualification failures.
- Create outside repository: `/tmp/finance-reconciliation-public-sensitive-anchors.txt`
- Create outside repository: `/tmp/finance-reconciliation-public-snapshot`

**Interfaces:**
- Produces: clean private source HEAD with all tests passing.
- Produces: one parentless public `main` snapshot that passes tree, history and image scans.

- [ ] **Step 1: Run the complete local quality gate**

Run: `.venv/bin/ruff check .`

Run: `.venv/bin/pytest --cov --cov-report=term-missing`

Run: `npm run test:js`

Run: `npm run test:e2e`

Run every shell contract individually:

```bash
bash scripts/create-public-snapshot.test.sh
bash scripts/scan-public-images.test.sh
bash scripts/system-update-compose.test.sh
bash scripts/system-update-dsm-smoke.test.sh
bash scripts/system-update-updater.test.sh
bash scripts/system-update-manual-cleanup.test.sh
PATH="$PWD/.venv/bin:$PATH" bash scripts/release-images-contract.test.sh
```

Expected: Python count at least `1005`, JS count at least `31`, Playwright count `10`, coverage at least the project threshold, and all commands exit `0`.

- [ ] **Step 2: Prepare the external neutral anchor file without output**

Clone the already reviewed mode-`0600` external anchor set to `/tmp/finance-reconciliation-public-sensitive-anchors.txt`, add the approved legacy brand variants outside Git, preserve mode `0600`, and verify only its mode and nonzero size. Do not print, hash, diff or archive its contents.

- [ ] **Step 3: Create and scan the parentless snapshot**

```bash
FINREC_PUBLIC_SENSITIVE_ANCHORS_FILE=/tmp/finance-reconciliation-public-sensitive-anchors.txt \
  bash scripts/create-public-snapshot.sh \
  /tmp/finance-reconciliation-public-snapshot
python3 scripts/scan-public-history.py \
  /tmp/finance-reconciliation-public-snapshot \
  /tmp/finance-reconciliation-public-sensitive-anchors.txt
```

Assert branch `main`, exactly one reachable commit and no parent. Run `git status --short` inside the snapshot and require empty output.

- [ ] **Step 4: Build and scan both snapshot images**

```bash
release_revision="$(git -C /tmp/finance-reconciliation-public-snapshot rev-parse main)"
release_created="$(date --utc --date="$(git -C /tmp/finance-reconciliation-public-snapshot show -s --format=%cI main)" '+%Y-%m-%dT%H:%M:%SZ')"
docker build --target web \
  --build-arg FINREC_RELEASE_VERSION=v0.2.0 \
  --build-arg FINREC_RELEASE_REVISION="$release_revision" \
  --build-arg FINREC_RELEASE_CREATED="$release_created" \
  -t finance-reconciliation-public-scan-web:v0.2.0 \
  /tmp/finance-reconciliation-public-snapshot
docker build --target updater \
  -t finance-reconciliation-public-scan-updater:v0.2.0 \
  /tmp/finance-reconciliation-public-snapshot
bash /tmp/finance-reconciliation-public-snapshot/scripts/scan-public-images.sh \
  /tmp/finance-reconciliation-public-sensitive-anchors.txt \
  finance-reconciliation-public-scan-web:v0.2.0 \
  finance-reconciliation-public-scan-updater:v0.2.0
```

- [ ] **Step 5: Verify a fresh clone of the snapshot**

Clone the snapshot into a new temporary directory, create its `.venv`, install `.[dev]`, run the complete Python/JS/Playwright/shell contract gate there, and require a clean worktree afterward.

- [ ] **Step 6: Commit qualification-only corrections if needed**

Stage only files changed to fix an observed qualification failure, rerun the failed gate plus the complete gate, and commit with a Chinese `fix:` message naming the actual failure. Recreate the parentless snapshot after every correction.

### Task 8: Create the Neutral GitHub/GHCR Release Chain

**Files:**
- External state: GitHub repository `s450586793/finance-reconciliation`
- External state: repository secret `FINREC_PUBLIC_SCAN_ANCHORS_B64`
- External state: GHCR packages `finance-reconciliation-web`, `finance-reconciliation-updater`

**Interfaces:**
- Consumes: qualified snapshot from Task 7 and the external mode-`0600` anchor file.
- Produces: public `main`, immutable `v0.2.0` images, and Web `stable`.

- [ ] **Step 1: Prove the target names are unused**

Use unauthenticated GitHub and GHCR API/manifest checks to require repository `s450586793/finance-reconciliation`, both package names and tag `v0.2.0` to be absent. Any network ambiguity fails closed.

- [ ] **Step 2: Create the public repository and scan secret securely**

Obtain the existing GitHub credential through `git credential fill` into a mode-`0600` temporary file without printing it. Use GitHub REST to create the public repository with description `Finance reconciliation and operations system`. Use a temporary Python virtual environment with `PyNaCl==1.5.0` to encrypt the base64-encoded anchor file using the repository Actions public key and PUT secret `FINREC_PUBLIC_SCAN_ANCHORS_B64`. Remove credential and encryption temporary files immediately.

- [ ] **Step 3: Push only the parentless snapshot**

```bash
git -C /tmp/finance-reconciliation-public-snapshot remote add origin \
  https://github.com/s450586793/finance-reconciliation.git
git -C /tmp/finance-reconciliation-public-snapshot push --set-upstream origin main
```

Fresh anonymous clone the remote, require one parentless commit, and run `scan-public-history.py` with the external anchor file.

- [ ] **Step 4: Wait for the main CI run to succeed**

Poll the public GitHub Actions API by the pushed commit SHA. Require `test` and `public-scan` to conclude `success`; `preflight`, `publish`, and `promote-stable` must be skipped on the branch push. Report any failed step without printing secret-derived logs.

- [ ] **Step 5: Publish `v0.2.0` and verify all release jobs**

```bash
git -C /tmp/finance-reconciliation-public-snapshot tag v0.2.0 main
git -C /tmp/finance-reconciliation-public-snapshot push origin refs/tags/v0.2.0
```

Require `test`, `public-scan`, `preflight`, both publish matrix jobs and `promote-stable` to conclude `success`.

- [ ] **Step 6: Anonymous pull and scan published images**

With an empty `DOCKER_CONFIG`, pull both immutable images and Web `stable`. Prove immutable Web and `stable` resolve to the same digest, updater has no mutable tag, OCI version is `v0.2.0`, revision equals public `main`, and created time is normalized UTC. Run `scan-public-images.sh` on both immutable images.

### Task 9: Back Up and Cut DSM Production Over to the Neutral Identity

**Files:**
- Deploy to: `/volume4/docker/docker/finance-reconciliation/app/compose.yml`
- Deploy to: `/volume4/docker/docker/finance-reconciliation/app/.env`
- Migrate data to: `/volume4/docker/docker/finance-reconciliation/data`
- External state: DSM host `ace-station.top:9099`

**Interfaces:**
- Consumes: public `v0.2.0` images and private existing DSM configuration.
- Produces: healthy `finance-reconciliation` `db`, `web`, `updater` services at the existing public URL.

- [ ] **Step 1: Recheck DSM preflight read-only**

Connect as the existing DSM operator over SSH port `9099`. Record only non-sensitive facts: Docker/Compose versions, free space, active Compose project/service names, current container health, current image IDs and canonical source/target path device IDs. Require no second PostgreSQL instance and no existing target project or target data directory.

- [ ] **Step 2: Create and verify an independent backup**

Use the existing Web backup command while the legacy service is healthy. Copy database dump, uploads archive, current compose and `.env` into a root-owned mode-`0700` backup directory outside both source and target paths. Verify files are nonempty and record only `db_backup_verified=true` / `uploads_backup_verified=true`.

- [ ] **Step 3: Prepare neutral configuration without exposing credentials**

Copy the reviewed `compose.yml` and deployment scripts from the anonymous public clone. Generate a mode-`0600` target `.env` by carrying forward the existing Django secret, database password, tax ID, hosts and import limits under the new keys; set exact target paths, `v0.2.0` tags, neutral database/role names, and a fresh 32-byte updater token. Validate `docker compose config --format json` without printing environment values.

- [ ] **Step 4: Run the reversible identity migration**

Invoke `scripts/deploy-dsm.sh` with `FINREC_DEPLOY_MODE=identity-migration`, exact source paths supplied privately, fixed target paths, private legacy database/role values, `v0.2.0` tags and the new updater token. Keep the SSH session attached until the script exits; on failure verify the legacy service and source data path were restored before any further action.

- [ ] **Step 5: Bootstrap or verify Owner access and run DSM smoke**

Do not recreate the Owner if it already exists. Read the Owner password interactively and run `scripts/system-update-dsm-smoke.sh` against `http://sd.ace-station.top:1111` with expected current target `v0.2.0`. Verify login, imports, ledgers, reporting, reconciliation, update status, container identities and unchanged `db`/updater fingerprints.

- [ ] **Step 6: Verify business-data invariants**

Compare pre/post database key-table counts, latest import IDs, attachment/upload manifest and selected invoice/transaction aggregate totals. Store only boolean/count results in the migration record; never export row-level business data to Git or logs.

- [ ] **Step 7: Exercise successful cleanup and failure retention**

Create an isolated Compose drill project with its own empty PostgreSQL data directory, uploads, updater state and no published host port. Use locally built neutral `v0.2.0` and `v0.2.1` drill images to prove a successful Web update removes only its verified superseded Web image after health stabilization, while an injected pre-switch or health failure retains current and rollback images. Remove the isolated project and drill images after verification; production must remain on public `v0.2.0` throughout and its container fingerprints must not change.

### Task 10: Final Cleanup and Old Public Asset Removal

**Files:**
- External state only.

**Interfaces:**
- Consumes: all Task 8 and Task 9 acceptance evidence.
- Produces: only the neutral public repository/packages and neutral active DSM deployment remain.

- [ ] **Step 1: Run the final go/no-go gate**

Require all of the following in one fresh check: new anonymous clone passes history scan, new images pass anonymous pull/image scan, DSM is healthy, Owner login works, business-data invariants match, updater has no active/failed/manual-intervention task, and rollback backup is verified.

- [ ] **Step 2: Remove retired DSM containers, images, and active legacy paths**

Delete only captured retired container/image IDs after re-inspecting that none are referenced by current services or rollback state. Remove active legacy config/data paths only after proving the target paths are canonical and mounted by the healthy project. Keep the independent migration backup until the agreed backup retention policy expires.

- [ ] **Step 3: Delete old GHCR packages**

Derive the old package names from the original remote recorded before Task 8, enumerate exact package versions through authenticated GitHub API, and delete the two old packages only. Re-query and require `404`/empty package results while the new packages remain anonymously pullable.

- [ ] **Step 4: Delete the old public GitHub repository**

Use authenticated GitHub API with the exact repository identity captured before migration. Require a final confirmation that its current HEAD equals the previously qualified old public HEAD, delete it, then verify unauthenticated access no longer returns repository content. Never delete or rename the new repository.

- [ ] **Step 5: Record final non-sensitive acceptance results**

Update the private acceptance record with new repository URL, public release SHA/tag, image digests, DSM project/service health, test counts, coverage, scan pass booleans, cleanup results and deletion confirmations. Do not record credentials, anchor values, business rows, internal Docker aliases or backup payload paths.
