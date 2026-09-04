import json
import os
import re
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
import yaml

VALID_PRODUCTION_TAX_ID = "91320281" + "SAFE" + "000001"


def _production_settings_process(company_tax_id=...):
    environment = os.environ.copy()
    environment.update(
        {
            "DJANGO_ALLOWED_HOSTS": "localhost",
            "CSRF_TRUSTED_ORIGINS": "https://localhost",
            "DJANGO_SECRET_KEY": "p" * 50,
            "DJANGO_DEBUG": "false",
            "DATABASE_URL": (
                "postgresql://finance:long-production-password@db:5432/finance"
            ),
            "FINREC_RELEASE_VERSION": "v0.1.0",
            "FINREC_UPDATER_URL": "http://updater:8090",
            "FINREC_UPDATER_TOKEN": "u" * 32,
        }
    )
    if company_tax_id is ...:
        environment.pop("COMPANY_TAX_ID", None)
    else:
        environment["COMPANY_TAX_ID"] = company_tax_id
    return subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from config.settings import prod; "
                "print(prod.COMPANY_TAX_ID)"
            ),
        ],
        cwd=Path.cwd(),
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def _compose_fixture_environment() -> dict[str, str]:
    return {
        "DJANGO_SETTINGS_MODULE": "config.settings.prod",
        "DJANGO_SECRET_KEY": "p" * 50,
        "DJANGO_DEBUG": "false",
        "DJANGO_ALLOWED_HOSTS": "localhost",
        "CSRF_TRUSTED_ORIGINS": "https://localhost",
        "DJANGO_COOKIE_SECURE": "true",
        "COMPANY_TAX_ID": VALID_PRODUCTION_TAX_ID,
        "POSTGRES_DB": "finance_reconciliation",
        "POSTGRES_USER": "finance",
        "POSTGRES_PASSWORD": "long-production-password",
        "FINREC_WEB_IMAGE_TAG": "v0.2.0",
        "FINREC_UPDATER_IMAGE_TAG": "v0.2.1",
        "FINREC_UPDATER_TOKEN": "u" * 32,
        "FINREC_APP_DIR": "/volume4/docker/docker/finance-reconciliation/app",
        "FINREC_DATA_DIR": "/volume4/docker/docker/finance-reconciliation/data",
        "IMPORT_MAX_UPLOAD_BYTES": "20971520",
        "IMPORT_MAX_ROWS": "100000",
        "DATABASE_URL": (
            "postgresql://finance:long-production-password@db:5432/finance_reconciliation"
        ),
    }


def _render_compose():
    environment = _compose_fixture_environment()
    compose_template = Path("compose.yml").read_text()
    return re.sub(
        r"\$\{(?P<name>[A-Z0-9_]+)(?::\?[^}]*)?\}",
        lambda match: environment[match.group("name")],
        compose_template,
    )


def _fake_compose_json(
    data_dir: Path,
    *,
    release_version_override: str | None = None,
    web_image: str = "ghcr.io/s450586793/finance-reconciliation-web:v0.2.0",
    updater_image: str = "ghcr.io/s450586793/finance-reconciliation-updater:v0.2.1",
) -> str:
    web_environment = {
        "DJANGO_SETTINGS_MODULE": "config.settings.prod",
        "DJANGO_SECRET_KEY": "p" * 50,
        "DJANGO_DEBUG": "false",
        "DJANGO_ALLOWED_HOSTS": "web,localhost",
        "CSRF_TRUSTED_ORIGINS": "https://localhost",
        "DJANGO_COOKIE_SECURE": "true",
        "COMPANY_TAX_ID": VALID_PRODUCTION_TAX_ID,
        "FINREC_UPDATER_URL": "http://updater:8090",
        "FINREC_UPDATER_TOKEN": "u" * 32,
        "IMPORT_MAX_UPLOAD_BYTES": "20971520",
        "IMPORT_MAX_ROWS": "100000",
        "DATABASE_URL": (
            "postgresql://finance:long-production-password@db:5432/finance_reconciliation"
        ),
    }
    if release_version_override is not None:
        web_environment["FINREC_RELEASE_VERSION"] = release_version_override
    return json.dumps(
        {
            "services": {
                "db": {
                    "volumes": [
                        {
                            "type": "bind",
                            "source": f"{data_dir}/postgres",
                            "target": "/var/lib/postgresql/data",
                        }
                    ]
                },
                "web": {
                    "image": web_image,
                    "pull_policy": "never",
                    "environment": web_environment,
                    "volumes": [
                        {
                            "type": "bind",
                            "source": f"{data_dir}/uploads",
                            "target": "/data/uploads",
                        }
                    ],
                },
                "updater": {
                    "image": updater_image,
                    "pull_policy": "never",
                    "environment": {
                        "FINREC_UPDATER_TOKEN": "u" * 32,
                        "FINREC_COMPOSE_PROJECT": "finance-reconciliation",
                    },
                    "volumes": [
                        {
                            "type": "bind",
                            "source": "/var/run/docker.sock",
                            "target": "/var/run/docker.sock",
                        },
                        {
                            "type": "bind",
                            "source": f"{data_dir}/updater-state",
                            "target": "/state",
                        },
                    ],
                },
            }
        },
        separators=(",", ":"),
    )


def _materialize_temp_deploy_script(tmp_path: Path, app_dir: Path, data_dir: Path) -> Path:
    script_path = tmp_path / "deploy-dsm-test.sh"
    payload = Path("scripts/deploy-dsm.sh").read_text(encoding="utf-8")
    payload = payload.replace(
        'default_app_dir="/volume4/docker/docker/finance-reconciliation/app"',
        f'default_app_dir="{app_dir}"',
    )
    payload = payload.replace(
        'default_data_dir="/volume4/docker/docker/finance-reconciliation/data"',
        f'default_data_dir="{data_dir}"',
    )
    script_path.write_text(payload, encoding="utf-8")
    script_path.chmod(0o755)
    return script_path


def _write_fake_docker(fake_bin: Path) -> None:
    (fake_bin / "docker").write_text(
        "#!/usr/bin/env python3\n"
        "from __future__ import annotations\n"
        "import json\n"
        "import os\n"
        "import sys\n"
        "from pathlib import Path\n"
        "\n"
        "log_path = Path(os.environ['FAKE_DOCKER_LOG'])\n"
        "log_path.parent.mkdir(parents=True, exist_ok=True)\n"
        "with log_path.open('a', encoding='utf-8') as handle:\n"
        "    handle.write(' '.join(sys.argv[1:]) + '\\n')\n"
        "state_path = Path(os.environ['FAKE_DOCKER_STATE'])\n"
        "state = json.loads(state_path.read_text(encoding='utf-8'))\n"
        "\n"
        "def save() -> None:\n"
        "    state_path.write_text(json.dumps(state, separators=(',', ':')), encoding='utf-8')\n"
        "\n"
        "if sys.argv[1] == 'compose':\n"
        "    args = sys.argv[2:]\n"
        "    project = None\n"
        "    index = 0\n"
        "    while index < len(args):\n"
        "        token = args[index]\n"
        "        if token == '--project-name':\n"
        "            project = args[index + 1]\n"
        "            index += 2\n"
        "            continue\n"
        "        if token in {'--env-file', '-f'}:\n"
        "            index += 2\n"
        "            continue\n"
        "        break\n"
        "    command = args[index]\n"
        "    rest = args[index + 1:]\n"
        "    services = state.setdefault('services', {})\n"
        "    services.setdefault('app', {})\n"
        "    services.setdefault('finance-reconciliation', {})\n"
        "    if command == 'config':\n"
        "        sys.stdout.write(Path(os.environ['FAKE_COMPOSE_CONFIG']).read_text(encoding='utf-8'))\n"
        "        raise SystemExit(0)\n"
        "    if command == 'ps' and rest[:1] in (['-q'], ['--all']):\n"
        "        if rest[:1] == ['--all']:\n"
        "            if rest[1:2] != ['-q']:\n"
        "                raise SystemExit(2)\n"
        "            service = rest[2]\n"
        "            include_stopped = True\n"
        "        else:\n"
        "            service = rest[1]\n"
        "            include_stopped = False\n"
        "        container = services.get(project, {}).get(service, '')\n"
        "        running = state.setdefault('running', {}).get(container, False)\n"
        "        if container and (include_stopped or running):\n"
        "            sys.stdout.write(container)\n"
        "        raise SystemExit(0)\n"
        "    if command == 'pull':\n"
        "        raise SystemExit(1 if os.environ.get('FAKE_FAIL_PULL') == '1' else 0)\n"
        "    if command == 'stop':\n"
        "        service_names = [service for service in rest if not service.startswith('-')]\n"
        "        if (\n"
        "            os.environ.get('FAKE_FAIL_LEGACY_STOP_AFTER_DB') == '1'\n"
        "            and project == 'app'\n"
        "            and service_names == ['db', 'web']\n"
        "        ):\n"
        "            container = services[project].get('db', '')\n"
        "            if container:\n"
        "                state.setdefault('running', {})[container] = False\n"
        "            save()\n"
        "            raise SystemExit(1)\n"
        "        if (\n"
        "            os.environ.get('FAKE_FAIL_TARGET_SERVICE_STOP_AFTER_WEB') == '1'\n"
        "            and project == 'finance-reconciliation'\n"
        "            and service_names == ['web', 'updater']\n"
        "        ):\n"
        "            container = services[project].get('web', '')\n"
        "            if container:\n"
        "                state.setdefault('running', {})[container] = False\n"
        "            save()\n"
        "            raise SystemExit(1)\n"
        "        for service in rest:\n"
        "            if service.startswith('-'):\n"
        "                continue\n"
        "            container = services[project].get(service, '')\n"
        "            if container:\n"
        "                state.setdefault('running', {})[container] = False\n"
        "        save()\n"
        "        raise SystemExit(0)\n"
        "    if command == 'up':\n"
        "        service_names = [service for service in rest if not service.startswith('-')]\n"
        "        if (\n"
        "            os.environ.get('FAKE_FAIL_TARGET_UP_AFTER_DB') == '1'\n"
        "            and project == 'finance-reconciliation'\n"
        "            and service_names == ['db', 'updater']\n"
        "        ):\n"
        "            services[project]['db'] = 'finance-reconciliation-db'\n"
        "            state.setdefault('running', {})['finance-reconciliation-db'] = True\n"
        "            save()\n"
        "            raise SystemExit(1)\n"
        "        for service in rest:\n"
        "            if service.startswith('-'):\n"
        "                continue\n"
        "            services[project][service] = (\n"
        "                f'legacy-{service}' if project == 'app' else f'{project}-{service}'\n"
        "            )\n"
        "            state.setdefault('running', {})[services[project][service]] = True\n"
        "        save()\n"
        "        raise SystemExit(0)\n"
        "    if command == 'run':\n"
        "        raise SystemExit(1 if os.environ.get('FAKE_FAIL_MIGRATE') == '1' else 0)\n"
        "if sys.argv[1] == 'start':\n"
        "    for container in sys.argv[2:]:\n"
        "        if container not in state.setdefault('running', {}):\n"
        "            raise SystemExit(1)\n"
        "        state['running'][container] = True\n"
        "    save()\n"
        "    raise SystemExit(0)\n"
        "if sys.argv[1] == 'stop':\n"
        "    if len(sys.argv) != 3:\n"
        "        raise SystemExit(2)\n"
        "    container = sys.argv[2]\n"
        "    if container == 'finance-reconciliation-db' and os.environ.get('FAKE_FAIL_TARGET_DB_STOP') == '1':\n"
        "        raise SystemExit(1)\n"
        "    if container not in state.setdefault('running', {}):\n"
        "        raise SystemExit(1)\n"
        "    if not (\n"
        "        container == 'finance-reconciliation-db'\n"
        "        and os.environ.get('FAKE_TARGET_DB_STOP_STAYS_RUNNING') == '1'\n"
        "    ):\n"
        "        state['running'][container] = False\n"
        "    if container == 'finance-reconciliation-db' and os.environ.get('FAKE_STALE_TARGET_DB_ID') == '1':\n"
        "        del state['running'][container]\n"
        "    save()\n"
        "    raise SystemExit(0)\n"
        "if sys.argv[1] == 'inspect':\n"
        "    container = sys.argv[-1]\n"
        "    if container not in state.setdefault('running', {}):\n"
        "        raise SystemExit(1)\n"
        "    if (\n"
        "        '{{.State.Running}}' in sys.argv\n"
        "        and container == 'finance-reconciliation-db'\n"
        "        and os.environ.get('FAKE_FAIL_TARGET_DB_INSPECT') == '1'\n"
        "    ):\n"
        "        raise SystemExit(1)\n"
        "    if '{{.State.Running}}' in sys.argv:\n"
        "        sys.stdout.write('true' if state['running'][container] else 'false')\n"
        "        raise SystemExit(0)\n"
        "    key = 'FAKE_HEALTH_' + container.upper().replace('-', '_')\n"
        "    sys.stdout.write(os.environ.get(key, 'healthy'))\n"
        "    raise SystemExit(0)\n"
        "raise SystemExit(0)\n",
        encoding="utf-8",
    )
    (fake_bin / "docker").chmod(0o755)


def _write_python_commands(fake_bin: Path, *, python_fails: bool) -> None:
    (fake_bin / "python").write_text(
        "#!/bin/sh\n"
        + ("exit 127\n" if python_fails else f"exec {sys.executable} \"$@\"\n"),
        encoding="utf-8",
    )
    (fake_bin / "python").chmod(0o755)
    (fake_bin / "python3").write_text(
        f"#!/bin/sh\nexec {sys.executable} \"$@\"\n",
        encoding="utf-8",
    )
    (fake_bin / "python3").chmod(0o755)


def _prepare_deploy_fixture(
    tmp_path: Path,
    *,
    legacy_db: bool = False,
    legacy_web: bool = False,
    create_pg_version: bool = True,
    python_fails: bool = False,
) -> tuple[dict[str, str], Path, Path, Path]:
    app_dir = tmp_path / "app"
    data_dir = tmp_path / "data"
    fake_bin = tmp_path / "bin"
    state_path = tmp_path / "docker-state.json"
    command_log = tmp_path / "docker.log"
    compose_config = tmp_path / "compose-config.json"

    app_dir.mkdir()
    data_dir.mkdir()
    fake_bin.mkdir()
    postgres_dir = data_dir / "postgres"
    postgres_dir.mkdir()
    if create_pg_version:
        (postgres_dir / "PG_VERSION").write_text("16\n", encoding="utf-8")
    (app_dir / "compose.yml").write_text(Path("compose.yml").read_text(), encoding="utf-8")
    (app_dir / ".env").write_text("PLACEHOLDER=1\n", encoding="utf-8")
    script_path = _materialize_temp_deploy_script(tmp_path, app_dir, data_dir)
    compose_config.write_text(_fake_compose_json(data_dir), encoding="utf-8")
    state_path.write_text(
        json.dumps(
            {
                "services": {
                    "app": {
                        "db": "legacy-db" if legacy_db else "",
                        "web": "legacy-web" if legacy_web else "",
                    },
                    "finance-reconciliation": {"db": "", "web": "", "updater": ""},
                },
                "running": {
                    **({"legacy-db": True} if legacy_db else {}),
                    **({"legacy-web": True} if legacy_web else {}),
                },
            },
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    _write_fake_docker(fake_bin)
    _write_python_commands(fake_bin, python_fails=python_fails)

    environment = os.environ.copy()
    environment.update(
        {
            "PATH": f"{fake_bin}:{environment['PATH']}",
            "FAKE_DOCKER_LOG": str(command_log),
            "FAKE_DOCKER_STATE": str(state_path),
            "FAKE_COMPOSE_CONFIG": str(compose_config),
            "FINREC_APP_DIR": str(app_dir),
            "FINREC_DATA_DIR": str(data_dir),
            "FINREC_WEB_IMAGE_TAG": "v0.2.0",
            "FINREC_UPDATER_IMAGE_TAG": "v0.2.1",
            "FINREC_UPDATER_TOKEN": "u" * 32,
            "FINREC_HEALTH_MAX_ATTEMPTS": "1",
            "FINREC_HEALTH_SLEEP_SECONDS": "0",
            "FAKE_DEPLOY_SCRIPT": str(script_path),
        }
    )
    return environment, app_dir, data_dir, command_log


def _run_deploy_script(environment: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "sh",
            environment.get(
                "FAKE_DEPLOY_SCRIPT", str(Path.cwd() / "scripts" / "deploy-dsm.sh")
            ),
        ],
        cwd=Path.cwd(),
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


class DeployContext:
    def __init__(self, tmp_path: Path):
        self.root = tmp_path / "deployment-root"
        self.target_app_path = self.root / "finance-reconciliation" / "app"
        self.target_data_path = self.root / "finance-reconciliation" / "data"
        self.legacy_app_path = self.root / "private-legacy" / "app"
        self.legacy_data_path = self.root / "private-legacy" / "data"
        self.fake_bin = tmp_path / "bin"
        self.command_log = tmp_path / "docker.log"
        self.event_log = tmp_path / "events.log"
        self.sql_log = tmp_path / "sql.log"
        self.state_path = tmp_path / "docker-state.json"
        self.compose_config = tmp_path / "compose-config.json"

        self.target_app_path.mkdir(parents=True)
        self.legacy_app_path.mkdir(parents=True)
        (self.legacy_data_path / "postgres").mkdir(parents=True)
        (self.legacy_data_path / "postgres" / "PG_VERSION").write_text(
            "16\n", encoding="utf-8"
        )
        for app_path in (self.target_app_path, self.legacy_app_path):
            (app_path / "compose.yml").write_text(
                Path("compose.yml").read_text(encoding="utf-8"), encoding="utf-8"
            )
            (app_path / ".env").write_text("PLACEHOLDER=1\n", encoding="utf-8")
            (app_path / ".env").chmod(0o600)

        self.fake_bin.mkdir()
        self.compose_config.write_text(
            _fake_compose_json(self.target_data_path), encoding="utf-8"
        )
        self.state_path.write_text(
            json.dumps(
                {
                    "services": {
                        "app": {"db": ["legacy-db"], "web": ["legacy-web"]},
                        "finance-reconciliation": {
                            "db": [],
                            "web": [],
                            "updater": [],
                        },
                    },
                    "running": {"legacy-db": True, "legacy-web": True},
                    "labels": {
                        "legacy-db": ["app", "db"],
                        "legacy-web": ["app", "web"],
                    },
                    "exec_count": 0,
                },
                separators=(",", ":"),
            ),
            encoding="utf-8",
        )
        self._write_fake_docker()
        self._write_fake_mv()
        self._write_fake_stat()
        self.script_path = self._materialize_script(tmp_path)
        self.environment = os.environ.copy()
        self.environment.update(
            {
                "PATH": f"{self.fake_bin}:{self.environment['PATH']}",
                "FAKE_DOCKER_LOG": str(self.command_log),
                "FAKE_DOCKER_STATE": str(self.state_path),
                "FAKE_EVENT_LOG": str(self.event_log),
                "FAKE_SQL_LOG": str(self.sql_log),
                "FAKE_COMPOSE_CONFIG": str(self.compose_config),
                "FINREC_APP_DIR": str(self.target_app_path),
                "FINREC_DATA_DIR": str(self.target_data_path),
                "FINREC_WEB_IMAGE_TAG": "v0.2.0",
                "FINREC_UPDATER_IMAGE_TAG": "v0.2.1",
                "FINREC_UPDATER_TOKEN": "u" * 32,
                "FINREC_HEALTH_MAX_ATTEMPTS": "1",
                "FINREC_HEALTH_SLEEP_SECONDS": "0",
                "FINREC_LEGACY_APP_DIR": str(self.legacy_app_path),
                "FINREC_LEGACY_DATA_DIR": str(self.legacy_data_path),
                "FINREC_LEGACY_DATABASE_NAME": "private_database",
                "FINREC_LEGACY_DATABASE_ROLE": "private_role",
            }
        )

    def _materialize_script(self, tmp_path: Path) -> Path:
        script_path = tmp_path / "deploy-dsm-identity-test.sh"
        payload = Path("scripts/deploy-dsm.sh").read_text(encoding="utf-8")
        payload = payload.replace(
            'deployment_root="/volume4/docker/docker"',
            f'deployment_root="{self.root}"',
        )
        payload = payload.replace(
            'default_app_dir="/volume4/docker/docker/finance-reconciliation/app"',
            f'default_app_dir="{self.target_app_path}"',
        )
        payload = payload.replace(
            'default_data_dir="/volume4/docker/docker/finance-reconciliation/data"',
            f'default_data_dir="{self.target_data_path}"',
        )
        payload = payload.replace(
            'required_target_owner_uid="0"',
            f'required_target_owner_uid="{os.getuid()}"',
        )
        script_path.write_text(payload, encoding="utf-8")
        script_path.chmod(0o755)
        return script_path

    def _write_fake_docker(self) -> None:
        payload = textwrap.dedent(
            r'''#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

log_path = Path(os.environ["FAKE_DOCKER_LOG"])
event_path = Path(os.environ["FAKE_EVENT_LOG"])
state_path = Path(os.environ["FAKE_DOCKER_STATE"])
with log_path.open("a", encoding="utf-8") as handle:
    handle.write(" ".join(sys.argv[1:]) + "\n")
state = json.loads(state_path.read_text(encoding="utf-8"))


def save() -> None:
    state_path.write_text(json.dumps(state, separators=(",", ":")), encoding="utf-8")


def event(name: str) -> None:
    with event_path.open("a", encoding="utf-8") as handle:
        handle.write(name + "\n")


def service_ids(project: str, service: str) -> list[str]:
    value = state["services"].setdefault(project, {}).get(service, [])
    return value if isinstance(value, list) else ([value] if value else [])


if sys.argv[1] == "compose":
    args = sys.argv[2:]
    project = ""
    index = 0
    while index < len(args):
        if args[index] == "--project-name":
            project = args[index + 1]
            index += 2
        elif args[index] in {"--env-file", "-f"}:
            index += 2
        else:
            break
    command = args[index]
    rest = args[index + 1 :]
    if command == "config":
        sys.stdout.write(Path(os.environ["FAKE_COMPOSE_CONFIG"]).read_text(encoding="utf-8"))
        raise SystemExit(0)
    if command == "ps":
        include_stopped = rest[:2] == ["--all", "-q"]
        service = rest[2] if include_stopped else rest[1]
        ids = service_ids(project, service)
        visible = [item for item in ids if include_stopped or state["running"].get(item, False)]
        sys.stdout.write("\n".join(visible))
        raise SystemExit(0)
    if command == "pull":
        raise SystemExit(1 if os.environ.get("FAKE_FAIL_PULL") == "1" else 0)
    if command == "stop":
        services = [item for item in rest if not item.startswith("-")]
        if project == "finance-reconciliation" and services == ["web", "updater"]:
            event("stop-target-clients")
            if os.environ.get("FAKE_FAIL_TARGET_CLIENT_STOP") == "1":
                raise SystemExit(1)
        if (
            project == "finance-reconciliation"
            and "db" in services
            and os.environ.get("FAKE_FAIL_TARGET_STOP") == "1"
        ):
            raise SystemExit(1)
        for service in services:
            for container_id in service_ids(project, service):
                state["running"][container_id] = False
                if project == "app" and service == "db":
                    event("stop-legacy-db")
                if project == "finance-reconciliation" and service == "db":
                    event("stop-target-db")
        save()
        raise SystemExit(0)
    if command == "up":
        services = [item for item in rest if not item.startswith("-")]
        for service in services:
            if project == "finance-reconciliation" and service == "db":
                ids = ["target-db"]
                if os.environ.get("FAKE_AMBIGUOUS_TARGET_DB") == "1":
                    ids.append("target-db-duplicate")
                state["services"][project][service] = ids
                for container_id in ids:
                    state["running"][container_id] = True
                    state["labels"][container_id] = [project, service]
                if os.environ.get("FAKE_TARGET_DB_IDENTITY_DRIFT") == "1":
                    state["labels"][ids[0]] = ["other-project", service]
                event("start-target-db")
            else:
                container_id = f"{project}-{service}"
                state["services"][project][service] = [container_id]
                state["running"][container_id] = True
                state["labels"][container_id] = [project, service]
        save()
        raise SystemExit(0)
    if command == "run":
        raise SystemExit(1 if os.environ.get("FAKE_FAIL_DJANGO_MIGRATE") == "1" else 0)

if sys.argv[1] == "inspect":
    container_id = sys.argv[-1]
    if container_id not in state["running"]:
        raise SystemExit(1)
    template = next((item for item in sys.argv if "{{" in item), "")
    if "State.Running" in template:
        sys.stdout.write("true" if state["running"][container_id] else "false")
    elif "com.docker.compose.project" in template:
        sys.stdout.write("|".join(state["labels"].get(container_id, ["", ""])))
    else:
        key = "FAKE_HEALTH_" + container_id.upper().replace("-", "_")
        sys.stdout.write(os.environ.get(key, "healthy"))
    raise SystemExit(0)

if sys.argv[1] == "stop":
    container_id = sys.argv[-1]
    if os.environ.get("FAKE_FAIL_TARGET_STOP") == "1":
        raise SystemExit(1)
    state["running"][container_id] = False
    event("stop-target-db")
    save()
    raise SystemExit(0)

if sys.argv[1] == "start":
    if os.environ.get("FAKE_FAIL_LEGACY_RESTART") == "1":
        raise SystemExit(1)
    for container_id in sys.argv[2:]:
        state["running"][container_id] = True
    event("restart-legacy-db")
    save()
    raise SystemExit(0)

if sys.argv[1] == "exec":
    sql = sys.stdin.read()
    if "SELECT 1 AS database_ready" in sql:
        ready_count = state.setdefault("ready_count", 0)
        state["ready_count"] = ready_count + 1
        event("legacy-database-readiness")
    else:
        ready_count = -1
    if "format('%I', :'target_database'),\n    format('%I', :'legacy_database')" in sql:
        event("rollback-identifiers")
        rollback_identifier_sql = True
    else:
        rollback_identifier_sql = False
    with Path(os.environ["FAKE_SQL_LOG"]).open("a", encoding="utf-8") as handle:
        handle.write(sql)
    state["exec_count"] += 1
    forward_identifier_sql = (
        "format('%I', :'legacy_database'),\n    format('%I', :'target_database')"
        in sql
    )
    should_fail = (
        forward_identifier_sql
        and not state.get("identifier_failure_consumed", False)
        and (
            os.environ.get("FAKE_FAIL_DATABASE_RENAME") == "1"
            or os.environ.get("FAKE_FAIL_ROLE_RENAME") == "1"
        )
    )
    if should_fail:
        state["identifier_failure_consumed"] = True
    should_fail = should_fail or (
        "AS role_safe" in sql
        and os.environ.get("FINREC_LEGACY_DATABASE_ROLE")
        == os.environ.get("FINREC_IDENTITY_MIGRATION_ROLE")
    )
    should_fail = should_fail or (
        ready_count >= 0
        and ready_count < int(os.environ.get("FAKE_PSQL_READY_FAILURES", "0"))
    )
    should_fail = should_fail or (
        rollback_identifier_sql
        and os.environ.get("FAKE_FAIL_IDENTIFIER_ROLLBACK") == "1"
    )
    save()
    raise SystemExit(1 if should_fail else 0)

raise SystemExit(97)
'''
        )
        path = self.fake_bin / "docker"
        path.write_text(payload, encoding="utf-8")
        path.chmod(0o755)

    def _write_fake_mv(self) -> None:
        path = self.fake_bin / "mv"
        path.write_text(
            textwrap.dedent(
                r'''#!/usr/bin/env bash
set -euo pipefail
/bin/mv "$@"
if [ "${*: -1}" = "${FINREC_DATA_DIR:-}" ]; then
  printf '%s\n' move-data-to-neutral-path >>"${FAKE_EVENT_LOG:?}"
  if [ "${FAKE_SIGNAL_DURING_MOVE:-}" = "1" ]; then
    kill -TERM "$PPID"
  fi
else
  printf '%s\n' restore-data-to-legacy-path >>"${FAKE_EVENT_LOG:?}"
fi
'''
            ),
            encoding="utf-8",
        )
        path.chmod(0o755)

    def _write_fake_stat(self) -> None:
        path = self.fake_bin / "stat"
        path.write_text(
            textwrap.dedent(
                r'''#!/usr/bin/env bash
set -euo pipefail
if [ "${FAKE_CROSS_DEVICE:-}" = "1" ] && [ "${*: -1}" = "${FINREC_DATA_DIR%/*}" ]; then
  printf '999999\n'
  exit 0
fi
exec /usr/bin/stat "$@"
'''
            ),
            encoding="utf-8",
        )
        path.chmod(0o755)

    @property
    def events(self) -> list[str]:
        if not self.event_log.exists():
            return []
        return self.event_log.read_text(encoding="utf-8").splitlines()

    def legacy_db_running(self) -> bool:
        state = json.loads(self.state_path.read_text(encoding="utf-8"))
        return state["running"]["legacy-db"]

    def run(self, mode: str = "identity-migration", **options: str) -> subprocess.CompletedProcess[str]:
        environment = self.environment.copy()
        environment["FINREC_DEPLOY_MODE"] = mode
        option_names = {
            "target_web_health": "FAKE_HEALTH_FINANCE_RECONCILIATION_WEB",
            "fail_database_rename": "FAKE_FAIL_DATABASE_RENAME",
            "fail_role_rename": "FAKE_FAIL_ROLE_RENAME",
            "ambiguous_target_db": "FAKE_AMBIGUOUS_TARGET_DB",
            "target_db_identity_drift": "FAKE_TARGET_DB_IDENTITY_DRIFT",
            "signal_during_move": "FAKE_SIGNAL_DURING_MOVE",
            "fail_legacy_restart": "FAKE_FAIL_LEGACY_RESTART",
            "fail_target_stop": "FAKE_FAIL_TARGET_STOP",
            "fail_target_client_stop": "FAKE_FAIL_TARGET_CLIENT_STOP",
            "fail_identifier_rollback": "FAKE_FAIL_IDENTIFIER_ROLLBACK",
            "cross_device": "FAKE_CROSS_DEVICE",
            "psql_ready_failures": "FAKE_PSQL_READY_FAILURES",
        }
        for name, value in options.items():
            environment[option_names[name]] = value
        return subprocess.run(
            ["sh", str(self.script_path)],
            cwd=Path.cwd(),
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )


@pytest.fixture
def deploy_context(tmp_path: Path) -> DeployContext:
    return DeployContext(tmp_path)


def test_production_paths_match_compose_mounts_and_backup_scripts(monkeypatch):
    monkeypatch.setenv("DJANGO_ALLOWED_HOSTS", "localhost")
    monkeypatch.setenv("CSRF_TRUSTED_ORIGINS", "https://localhost")
    monkeypatch.setenv("DJANGO_SECRET_KEY", "p" * 50)
    monkeypatch.setenv(
        "DATABASE_URL", "postgresql://finance:long-production-password@db:5432/finance"
    )
    monkeypatch.setenv("COMPANY_TAX_ID", VALID_PRODUCTION_TAX_ID)
    monkeypatch.setenv("FINREC_RELEASE_VERSION", "v0.1.0")
    monkeypatch.setenv("FINREC_UPDATER_URL", "http://updater:8090")
    monkeypatch.setenv("FINREC_UPDATER_TOKEN", "u" * 32)

    from config.settings import prod

    compose = Path("compose.yml").read_text()
    backup = Path("scripts/backup.sh").read_text()
    restore = Path("scripts/restore.sh").read_text()
    pg_restore_clean = Path("scripts/pg_restore_clean.sh").read_text()
    dockerfile = Path("Dockerfile").read_text()

    assert prod.MEDIA_ROOT == Path("/data/uploads")
    assert prod.EXPORT_ROOT == Path("/data/exports")
    assert prod.BACKUP_ROOT == Path("/data/backups")
    assert "${FINREC_DATA_DIR:?required}/uploads:/data/uploads" in compose
    assert "${FINREC_DATA_DIR:?required}/exports:/data/exports" in compose
    assert "${FINREC_DATA_DIR:?required}/backups:/data/backups" in compose
    assert "${FINREC_DATA_DIR:?required}/postgres:/var/lib/postgresql/data" in compose
    assert 'uploads_dir="${UPLOADS_DIR:-/data/uploads}"' in backup
    assert 'backup_dir="${BACKUP_DIR:-/data/backups}"' in backup
    assert "127.0.0.1:8000:8000" in compose
    assert "postgresql16-client" in dockerfile
    assert "collectstatic --noinput" in dockerfile
    assert 'canonical_backup_dir="$(realpath -e "$backup_dir")"' in restore
    assert 'restore_dir="$(mktemp -d "$backup_dir/.uploads-restore.XXXXXX")"' in restore
    assert 'tar -C "$data_dir" -czf "$preserved_archive.tmp" -- uploads' in restore
    assert 'find "$uploads_dir" -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +' in restore
    assert 'mv "$uploads_dir"' not in restore
    assert "restore_safety.py validate-target" in restore
    assert "restore_safety.py extract-uploads" in restore
    assert "pg_restore_clean.sh" in restore
    assert "env -i" in pg_restore_clean


def test_docker_collectstatic_uses_a_valid_build_only_company_tax_id():
    dockerfile = Path("Dockerfile").read_text()
    collectstatic_instruction = next(
        line for line in dockerfile.splitlines() if "COMPANY_TAX_ID=" in line
    )
    match = re.search(
        r"COMPANY_TAX_ID=(?P<company_tax_id>[0-9A-Z]{15,20})",
        collectstatic_instruction,
    )

    assert match is not None
    result = _production_settings_process(match.group("company_tax_id"))
    assert result.returncode == 0


def test_docker_production_image_excludes_development_dependencies():
    dockerfile = Path("Dockerfile").read_text()

    assert 'pip install --no-cache-dir "."' in dockerfile
    assert 'pip install --no-cache-dir ".[dev]"' not in dockerfile


def test_postgres_client_major_matches_database_image():
    compose = Path("compose.yml").read_text()
    dockerfile = Path("Dockerfile").read_text()
    database_image = re.search(r"image: postgres:(?P<major>\d+)-", compose)

    assert database_image is not None
    assert f"postgresql{database_image.group('major')}-client" in dockerfile


def test_web_image_uses_pinned_alpine_runtime_packages():
    dockerfile = Path("Dockerfile").read_text()

    assert "FROM python:3.12.11-alpine3.21 AS web" in dockerfile
    assert "apk add --no-cache" in dockerfile
    for package in ("ca-certificates", "curl", "postgresql16-client"):
        assert package in dockerfile
    for forbidden in ("apt-get", "apt.postgresql.org", "slim-bookworm"):
        assert forbidden not in dockerfile
    assert "addgroup -S -g 10001 app" in dockerfile
    assert "adduser -S -D -H -u 10001 -G app app" in dockerfile


def test_production_static_assets_collect_without_missing_references(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("DJANGO_ALLOWED_HOSTS", "localhost")
    monkeypatch.setenv("CSRF_TRUSTED_ORIGINS", "https://localhost")
    monkeypatch.setenv("DJANGO_SECRET_KEY", "p" * 50)
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://finance:long-production-password@db:5432/finance",
    )
    monkeypatch.setenv("COMPANY_TAX_ID", VALID_PRODUCTION_TAX_ID)
    monkeypatch.setenv("FINREC_RELEASE_VERSION", "v0.1.0")
    monkeypatch.setenv("FINREC_UPDATER_URL", "http://updater:8090")
    monkeypatch.setenv("FINREC_UPDATER_TOKEN", "u" * 32)

    from django.core.management import call_command
    from django.test import override_settings

    from config.settings import prod

    with override_settings(STATIC_ROOT=tmp_path, STORAGES=prod.STORAGES):
        call_command("collectstatic", interactive=False, verbosity=0)

    assert (tmp_path / "staticfiles.json").is_file()


def test_production_default_storage_persists_uploaded_files(monkeypatch, tmp_path):
    monkeypatch.setenv("DJANGO_ALLOWED_HOSTS", "localhost")
    monkeypatch.setenv("CSRF_TRUSTED_ORIGINS", "https://localhost")
    monkeypatch.setenv("DJANGO_SECRET_KEY", "p" * 50)
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://finance:long-production-password@db:5432/finance",
    )
    monkeypatch.setenv("COMPANY_TAX_ID", VALID_PRODUCTION_TAX_ID)
    monkeypatch.setenv("FINREC_RELEASE_VERSION", "v0.1.0")
    monkeypatch.setenv("FINREC_UPDATER_URL", "http://updater:8090")
    monkeypatch.setenv("FINREC_UPDATER_TOKEN", "u" * 32)

    from django.core.files.base import ContentFile
    from django.core.files.storage import storages
    from django.test import override_settings

    from config.settings import prod

    with override_settings(MEDIA_ROOT=tmp_path, STORAGES=prod.STORAGES):
        saved_name = storages["default"].save(
            "imports/source.xlsx",
            ContentFile(b"workbook"),
        )

    assert saved_name == "imports/source.xlsx"
    assert (tmp_path / saved_name).read_bytes() == b"workbook"


def test_production_settings_require_company_tax_id_without_leaking_a_value():
    result = _production_settings_process()

    assert result.returncode != 0
    assert "COMPANY_TAX_ID" in result.stderr


@pytest.mark.parametrize(
    "company_tax_id",
    [
        "REPLACE_COMPANY_TAX_ID",
        "91320281TEST000001",
        "123-INVALID-TAX-ID",
        "12345678901234",
        "111111111111111111",
    ],
)
def test_production_settings_reject_placeholder_or_invalid_company_tax_id(
    company_tax_id,
):
    result = _production_settings_process(company_tax_id)
    combined_output = result.stdout + result.stderr

    assert result.returncode != 0
    assert "COMPANY_TAX_ID" in result.stderr
    assert company_tax_id not in combined_output


def test_production_settings_normalize_valid_company_tax_id():
    result = _production_settings_process(" 91320281ma1abcd123 ")

    assert result.returncode == 0
    assert result.stdout.strip() == "91320281MA1ABCD123"


@pytest.mark.parametrize(
    ("pg_dump_content", "fail_archive_move", "use_relative_directories"),
    [("dump", False, False), ("dump", False, True), ("", False, False), ("dump", True, False)],
)
def test_backup_script_emits_manifest_only_after_nonempty_final_backups(
    tmp_path, pg_dump_content, fail_archive_move, use_relative_directories
):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    backup_dir = tmp_path / "backups"
    uploads_dir = tmp_path / "uploads"
    uploads_dir.mkdir()
    (uploads_dir / "invoice.pdf").write_bytes(b"uploaded document")

    (fake_bin / "pg_dump").write_text(
        "#!/bin/sh\n"
        "for argument do\n"
        "  case \"$argument\" in --file=*) output=${argument#--file=} ;; esac\n"
        "done\n"
        "printf '%s' \"${PG_DUMP_CONTENT-dump}\" > \"$output\"\n",
        encoding="utf-8",
    )
    (fake_bin / "tar").write_text(
        "#!/bin/sh\n"
        "while [ \"$#\" -gt 0 ]; do\n"
        "  if [ \"$1\" = \"-czf\" ]; then output=$2; break; fi\n"
        "  shift\n"
        "done\n"
        "printf archive > \"$output\"\n",
        encoding="utf-8",
    )
    (fake_bin / "mv").write_text(
        "#!/bin/sh\n"
        "case \"$1\" in\n"
        "  *.tar.gz.tmp) [ \"${FAIL_ARCHIVE_MOVE:-0}\" = 1 ] && exit 1 ;;\n"
        "esac\n"
        "/bin/mv \"$@\"\n",
        encoding="utf-8",
    )
    (fake_bin / "find").write_text(
        "#!/bin/sh\n"
        "exit 0\n",
        encoding="utf-8",
    )
    for command in fake_bin.iterdir():
        command.chmod(0o755)

    environment = os.environ.copy()
    working_directory = tmp_path if use_relative_directories else Path.cwd()
    backup_directory_value = (
        str(backup_dir.relative_to(tmp_path)) if use_relative_directories else str(backup_dir)
    )
    uploads_directory_value = (
        str(uploads_dir.relative_to(tmp_path)) if use_relative_directories else str(uploads_dir)
    )
    environment.update(
        {
            "BACKUP_DIR": backup_directory_value,
            "UPLOADS_DIR": uploads_directory_value,
            "DATABASE_URL": "postgresql://backup:secret@db:5432/finance_reconciliation",
            "FAIL_ARCHIVE_MOVE": "1" if fail_archive_move else "0",
            "PG_DUMP_CONTENT": pg_dump_content,
            "PATH": f"{fake_bin}:{environment['PATH']}",
        }
    )
    result = subprocess.run(
        ["sh", str(Path.cwd() / "scripts" / "backup.sh")],
        cwd=working_directory,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    if fail_archive_move or not pg_dump_content:
        assert result.returncode != 0
        assert result.stdout == ""
        if fail_archive_move:
            assert list(backup_dir.glob("uploads-*.tar.gz")) == []
        return

    dump_path = next(backup_dir.glob("db-*.dump"))
    archive_path = next(backup_dir.glob("uploads-*.tar.gz"))
    assert result.returncode == 0
    assert result.stdout.splitlines() == [
        f"DB_BACKUP={dump_path}",
        f"UPLOADS_BACKUP={archive_path}",
    ]
    assert dump_path.stat().st_size > 0
    assert archive_path.stat().st_size > 0


def test_production_compose_uses_release_images_and_internal_service_boundaries():
    compose = _render_compose()
    config = yaml.safe_load(compose)
    web = config["services"]["web"]

    assert "services:\n  db:\n" in compose
    assert "\n  web:\n" in compose
    assert "\n  updater:\n" in compose
    assert "image: ghcr.io/s450586793/finance-reconciliation-web:v0.2.0" in compose
    assert "image: ghcr.io/s450586793/finance-reconciliation-updater:v0.2.1" in compose
    assert "build:" not in compose
    assert "127.0.0.1:8000:8000" in compose
    assert "FINREC_UPDATER_URL: http://updater:8090" in compose
    assert "env_file" not in web
    assert web["environment"] == {
        "DJANGO_SETTINGS_MODULE": "config.settings.prod",
        "DJANGO_SECRET_KEY": "p" * 50,
        "DJANGO_DEBUG": "false",
        "DJANGO_ALLOWED_HOSTS": "web,localhost",
        "CSRF_TRUSTED_ORIGINS": "https://localhost",
        "DJANGO_COOKIE_SECURE": "true",
        "COMPANY_TAX_ID": VALID_PRODUCTION_TAX_ID,
        "FINREC_UPDATER_URL": "http://updater:8090",
        "FINREC_UPDATER_TOKEN": "u" * 32,
        "IMPORT_MAX_UPLOAD_BYTES": "20971520",
        "IMPORT_MAX_ROWS": "100000",
        "DATABASE_URL": (
            "postgresql://finance:long-production-password@db:5432/finance_reconciliation"
        ),
    }
    assert config["services"]["updater"]["environment"] == {
        "FINREC_UPDATER_TOKEN": "u" * 32,
        "FINREC_COMPOSE_PROJECT": "finance-reconciliation",
    }
    assert set(config["services"]["db"]["networks"]) == {"internal"}
    assert set(config["services"]["updater"]["networks"]) == {"internal"}
    assert set(web["networks"]) == {"internal", "edge"}
    assert set(config["networks"]) == {"internal", "edge"}
    assert config["networks"]["internal"]["internal"] is True
    assert config["networks"]["edge"] is None
    assert compose.count("/var/run/docker.sock:/var/run/docker.sock") == 1
    assert "/volume4/docker/docker/finance-reconciliation/app:/config" in compose
    assert "/volume4/docker/docker/finance-reconciliation/data/updater-state:/state" in compose
    assert "condition: service_healthy" in compose
    assert "healthcheck:" in compose
    assert "networks:\n      - internal" in compose
    assert "internal: true" in compose


def test_deployment_contract_files_exclude_sensitive_local_state_and_pin_images():
    env_example = Path(".env.example").read_text()
    dockerignore = Path(".dockerignore").read_text()
    gitignore = Path(".gitignore").read_text()
    dockerfile = Path("Dockerfile").read_text()
    deploy_script = Path("scripts/deploy-dsm.sh").read_text()

    for name in (
        "FINREC_APP_DIR",
        "FINREC_DATA_DIR",
        "FINREC_WEB_IMAGE_TAG",
        "FINREC_UPDATER_IMAGE_TAG",
        "FINREC_UPDATER_TOKEN",
    ):
        assert f"{name}=" in env_example
    assert "FINREC_RELEASE_VERSION=" not in env_example
    assert {line for line in gitignore.splitlines() if line} >= {
        ".venv/",
        ".workflow/",
        "db.sqlite3",
        ".superpowers/",
    }
    assert {line for line in dockerignore.splitlines() if line} == {
        "**",
        "!Dockerfile",
        "!pyproject.toml",
        "!manage.py",
        "!apps/",
        "!apps/**",
        "!config/",
        "!config/**",
        "!scripts/",
        "!scripts/backup.sh",
        "!scripts/pg_restore_clean.sh",
        "!scripts/restore.sh",
        "!scripts/restore_safety.py",
        "!scripts/wait_for_db.py",
        "!templates/",
        "!templates/**",
        "!static/",
        "!static/**",
        "static/js/*.test.js",
        "!updater/",
        "!updater/**",
    }
    assert "FROM python:3.12.11-alpine3.21 AS web" in dockerfile
    assert "FROM docker:27.5.1-cli AS updater" in dockerfile
    assert "ARG FINREC_RELEASE_VERSION" in dockerfile
    assert "ARG FINREC_RELEASE_REVISION" in dockerfile
    assert "ARG FINREC_RELEASE_CREATED" in dockerfile
    assert "org.opencontainers.image.version=$FINREC_RELEASE_VERSION" in dockerfile
    assert 'ENTRYPOINT ["python3", "-m", "updater.main"]' in dockerfile
    assert "target_compose pull --policy always web updater" in deploy_script
    assert "target_compose up -d db" in deploy_script
    assert "target_compose up -d db updater" not in deploy_script
    assert "target_compose run --rm --no-deps web python manage.py migrate" in deploy_script
    assert "target_compose up -d --no-deps web" in deploy_script
    assert "target_compose config --format json" in deploy_script
    assert "python3" in deploy_script
    assert "PG_VERSION" in deploy_script
    assert "FINREC_DEPLOY_MODE" in deploy_script
    assert "FINREC_EXPECTED_APP_DIR" not in deploy_script
    assert "FINREC_EXPECTED_DATA_DIR" not in deploy_script
    assert "docker image prune" not in deploy_script
    assert "--force" not in deploy_script


def test_deploy_script_is_owner_executable():
    assert Path("scripts/deploy-dsm.sh").stat().st_mode & 0o100


def test_web_upgrade_override_targets_web_service_only():
    platform_code = Path("updater/platform.py").read_text()

    assert '"services:\\n"' in platform_code
    assert '"  web:\\n"' in platform_code
    assert '"    pull_policy: never\\n"' in platform_code
    assert "db:" not in platform_code.split("def _write_override", maxsplit=1)[1].split(
        "def _rollback_alias", maxsplit=1
    )[0]
    assert "updater:" not in platform_code.split(
        "def _write_override", maxsplit=1
    )[1].split("def _rollback_alias", maxsplit=1)[0]


@pytest.mark.parametrize(
    ("service", "image"),
    [
        ("web", "ghcr.io/example/unreviewed-web:v9.9.9"),
        ("updater", "ghcr.io/example/unreviewed-updater:v9.9.9"),
    ],
)
def test_deploy_script_rejects_unreviewed_service_image_before_mutation(
    deploy_context, service, image
):
    rendered = json.loads(deploy_context.compose_config.read_text(encoding="utf-8"))
    rendered["services"][service]["image"] = image
    deploy_context.compose_config.write_text(
        json.dumps(rendered, separators=(",", ":")), encoding="utf-8"
    )

    result = deploy_context.run(mode="identity-migration")

    commands = deploy_context.command_log.read_text(encoding="utf-8").splitlines()
    assert result.returncode != 0
    assert result.stdout == ""
    assert result.stderr == "deployment validation failed\n"
    assert deploy_context.legacy_db_running()
    assert deploy_context.events == []
    assert all(" pull " not in command for command in commands)


def test_deploy_script_rejects_unreviewed_compose_owner_before_docker(
    deploy_context,
):
    script = deploy_context.script_path.read_text(encoding="utf-8")
    script = script.replace(
        "or compose.st_uid != required_uid",
        f"or compose.st_uid != {os.getuid() + 1}",
    )
    deploy_context.script_path.write_text(script, encoding="utf-8")

    result = deploy_context.run(mode="identity-migration")

    assert result.returncode != 0
    assert result.stdout == ""
    assert result.stderr == "deployment validation failed\n"
    assert deploy_context.legacy_db_running()
    assert not deploy_context.command_log.exists()


def test_identity_migration_moves_data_only_after_legacy_db_stops(deploy_context):
    result = deploy_context.run(mode="identity-migration")

    assert result.returncode == 0, result.stderr
    assert deploy_context.events.index("stop-legacy-db") < deploy_context.events.index(
        "move-data-to-neutral-path"
    )
    assert deploy_context.target_data_path.exists()
    assert not deploy_context.legacy_data_path.exists()


def test_identity_migration_retries_postgres_readiness_before_identifier_changes(
    deploy_context,
):
    deploy_context.environment["FINREC_HEALTH_MAX_ATTEMPTS"] = "2"
    result = deploy_context.run(
        mode="identity-migration", psql_ready_failures="1"
    )

    assert result.returncode == 0, result.stderr
    assert deploy_context.events.count("legacy-database-readiness") == 2


def test_identity_migration_restores_data_path_when_target_health_fails(
    deploy_context,
):
    result = deploy_context.run(
        mode="identity-migration", target_web_health="unhealthy"
    )

    assert result.returncode != 0
    assert deploy_context.legacy_data_path.exists()
    assert not deploy_context.target_data_path.exists()
    assert deploy_context.legacy_db_running()
    assert deploy_context.events.index("stop-target-db") < deploy_context.events.index(
        "restore-data-to-legacy-path"
    )
    assert deploy_context.events.index(
        "stop-target-clients"
    ) < deploy_context.events.index("rollback-identifiers")
    assert deploy_context.events.index(
        "restore-data-to-legacy-path"
    ) < deploy_context.events.index("restart-legacy-db")


def test_identity_migration_rejects_existing_target_before_stopping_legacy(
    deploy_context,
):
    deploy_context.target_data_path.mkdir()

    result = deploy_context.run(mode="identity-migration")

    assert result.returncode != 0
    assert deploy_context.legacy_db_running()
    assert "stop-legacy-db" not in deploy_context.events


def test_identity_migration_rejects_symlink_source_without_logging_paths(
    deploy_context,
):
    outside = deploy_context.root / "outside-data"
    deploy_context.legacy_data_path.rename(outside)
    deploy_context.legacy_data_path.symlink_to(outside, target_is_directory=True)

    result = deploy_context.run(mode="identity-migration")

    assert result.returncode != 0
    assert deploy_context.legacy_db_running()
    assert str(outside) not in result.stdout + result.stderr
    assert str(deploy_context.legacy_data_path) not in result.stdout + result.stderr
    assert "stop-legacy-db" not in deploy_context.events


def test_identity_migration_rejects_cross_device_move_before_stopping_legacy(
    deploy_context,
):
    result = deploy_context.run(mode="identity-migration", cross_device="1")

    assert result.returncode != 0
    assert deploy_context.legacy_db_running()
    assert "stop-legacy-db" not in deploy_context.events


def test_identity_migration_rejects_source_outside_deployment_root(deploy_context):
    outside = deploy_context.root.parent / "private-outside-data"
    deploy_context.legacy_data_path.rename(outside)
    deploy_context.environment["FINREC_LEGACY_DATA_DIR"] = str(outside)

    result = deploy_context.run(mode="identity-migration")

    assert result.returncode != 0
    assert deploy_context.legacy_db_running()
    assert "stop-legacy-db" not in deploy_context.events


@pytest.mark.parametrize("failure", ["fail_database_rename", "fail_role_rename"])
def test_identity_migration_rolls_back_data_when_identifier_rename_fails(
    deploy_context, failure
):
    result = deploy_context.run(mode="identity-migration", **{failure: "1"})

    assert result.returncode != 0
    assert deploy_context.legacy_data_path.exists()
    assert not deploy_context.target_data_path.exists()
    assert deploy_context.legacy_db_running()


def test_identity_migration_never_drops_preexisting_migration_role(deploy_context):
    deploy_context.environment["FINREC_LEGACY_DATABASE_ROLE"] = (
        "finance_reconciliation_identity_migrator"
    )

    result = deploy_context.run(mode="identity-migration")

    sql = deploy_context.sql_log.read_text(encoding="utf-8")
    assert result.returncode != 0
    assert "DROP ROLE" not in sql
    assert deploy_context.legacy_data_path.exists()
    assert deploy_context.legacy_db_running()


def test_identity_migration_rejects_duplicate_target_database_and_rolls_back(
    deploy_context,
):
    result = deploy_context.run(mode="identity-migration", ambiguous_target_db="1")

    assert result.returncode != 0
    assert deploy_context.legacy_data_path.exists()
    assert not deploy_context.target_data_path.exists()
    assert deploy_context.legacy_db_running()


def test_identity_migration_rejects_duplicate_legacy_database_before_move(
    deploy_context,
):
    state = json.loads(deploy_context.state_path.read_text(encoding="utf-8"))
    state["services"]["app"]["db"].append("legacy-db-duplicate")
    state["running"]["legacy-db-duplicate"] = True
    state["labels"]["legacy-db-duplicate"] = ["app", "db"]
    deploy_context.state_path.write_text(
        json.dumps(state, separators=(",", ":")), encoding="utf-8"
    )

    result = deploy_context.run(mode="identity-migration")

    assert result.returncode != 0
    assert deploy_context.legacy_data_path.exists()
    assert "stop-legacy-db" not in deploy_context.events


def test_identity_migration_rolls_back_when_signalled_after_move(deploy_context):
    result = deploy_context.run(mode="identity-migration", signal_during_move="1")

    assert result.returncode != 0
    assert deploy_context.legacy_data_path.exists()
    assert not deploy_context.target_data_path.exists()
    assert deploy_context.legacy_db_running()


def test_identity_migration_rejects_target_db_identity_drift_and_rolls_back(
    deploy_context,
):
    result = deploy_context.run(
        mode="identity-migration", target_db_identity_drift="1"
    )

    assert result.returncode != 0
    assert deploy_context.legacy_data_path.exists()
    assert not deploy_context.target_data_path.exists()
    assert deploy_context.legacy_db_running()


def test_identity_migration_reports_manual_recovery_when_legacy_restart_fails(
    deploy_context,
):
    result = deploy_context.run(
        mode="identity-migration",
        target_web_health="unhealthy",
        fail_legacy_restart="1",
    )

    assert result.returncode != 0
    assert deploy_context.legacy_data_path.exists()
    assert not deploy_context.target_data_path.exists()
    assert not deploy_context.legacy_db_running()
    assert result.stdout == ""
    assert result.stderr == "identity migration requires manual recovery\n"


def test_identity_migration_never_moves_or_restarts_when_target_stop_is_unproven(
    deploy_context,
):
    result = deploy_context.run(
        mode="identity-migration",
        target_web_health="unhealthy",
        fail_target_stop="1",
    )

    assert result.returncode != 0
    assert not deploy_context.legacy_data_path.exists()
    assert deploy_context.target_data_path.exists()
    assert not deploy_context.legacy_db_running()
    assert "restore-data-to-legacy-path" not in deploy_context.events
    assert "restart-legacy-db" not in deploy_context.events
    assert result.stderr == "identity migration requires manual recovery\n"


def test_identity_migration_stops_recovery_when_target_clients_are_unproven(
    deploy_context,
):
    result = deploy_context.run(
        mode="identity-migration",
        target_web_health="unhealthy",
        fail_target_client_stop="1",
    )

    assert result.returncode != 0
    assert not deploy_context.legacy_data_path.exists()
    assert deploy_context.target_data_path.exists()
    assert not deploy_context.legacy_db_running()
    assert "rollback-identifiers" not in deploy_context.events
    assert "stop-target-db" not in deploy_context.events
    assert "restore-data-to-legacy-path" not in deploy_context.events
    assert "restart-legacy-db" not in deploy_context.events
    assert result.stderr == "identity migration requires manual recovery\n"


def test_identity_migration_stops_recovery_when_identifier_rollback_fails(
    deploy_context,
):
    result = deploy_context.run(
        mode="identity-migration",
        target_web_health="unhealthy",
        fail_identifier_rollback="1",
    )

    assert result.returncode != 0
    assert not deploy_context.legacy_data_path.exists()
    assert deploy_context.target_data_path.exists()
    assert not deploy_context.legacy_db_running()
    assert "stop-target-clients" in deploy_context.events
    assert "rollback-identifiers" in deploy_context.events
    assert "stop-target-db" not in deploy_context.events
    assert "restore-data-to-legacy-path" not in deploy_context.events
    assert "restart-legacy-db" not in deploy_context.events
    assert result.stderr == "identity migration requires manual recovery\n"


def test_identity_migration_quotes_private_identifiers_on_postgres_server(
    deploy_context,
):
    result = deploy_context.run(mode="identity-migration")

    sql = deploy_context.sql_log.read_text(encoding="utf-8")
    public_output = result.stdout + result.stderr + deploy_context.command_log.read_text(
        encoding="utf-8"
    )
    assert result.returncode == 0, result.stderr
    assert "format('%I'" in sql
    assert "\\gexec" in sql
    assert "private_database" not in sql
    assert "private_role" not in sql
    assert "private_database" not in public_output
    assert "private_role" not in public_output


def test_identity_migration_requires_private_legacy_inputs_only_in_migration_mode(
    deploy_context,
):
    deploy_context.environment.pop("FINREC_LEGACY_DATABASE_ROLE")
    migration = deploy_context.run(mode="identity-migration")

    deploy_context.environment.pop("FINREC_LEGACY_APP_DIR")
    deploy_context.environment.pop("FINREC_LEGACY_DATA_DIR")
    deploy_context.environment.pop("FINREC_LEGACY_DATABASE_NAME")
    deploy_context.target_data_path.parent.mkdir(parents=True, exist_ok=True)
    deploy_context.legacy_data_path.rename(deploy_context.target_data_path)
    upgrade = deploy_context.run(mode="upgrade")

    assert migration.returncode != 0
    assert upgrade.returncode == 0, upgrade.stderr


def test_deploy_script_requires_mode_0600_target_environment(deploy_context):
    (deploy_context.target_app_path / ".env").chmod(0o640)

    result = deploy_context.run(mode="identity-migration")

    assert result.returncode != 0
    assert deploy_context.legacy_db_running()
    assert "stop-legacy-db" not in deploy_context.events


def test_deploy_script_exposes_only_fixed_error_categories(deploy_context):
    deploy_context.environment["FINREC_UPDATER_TOKEN"] = "private-short-token"

    result = deploy_context.run(mode="identity-migration")

    assert result.returncode != 0
    assert result.stdout == ""
    assert result.stderr in {
        "deployment input rejected\n",
        "deployment validation failed\n",
        "deployment state conflict\n",
        "identity migration failed\n",
        "identity migration requires manual recovery\n",
        "deployment failed\n",
    }
    assert "private-short-token" not in result.stderr
    assert str(deploy_context.target_app_path) not in result.stderr
