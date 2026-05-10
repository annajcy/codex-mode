import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import tomlkit


SCRIPT = Path(__file__).resolve().parents[1] / "src" / "codex_mode" / "cli.py"


def run_tool(root: Path, *args):
    env = os.environ.copy()
    env["CODEX_MODE_CONFIG"] = str(root / "config.toml")
    env["CODEX_MODE_PROFILES"] = str(root / "profiles.json")
    env["CODEX_MODE_BACKUP_DIR"] = str(root / "backups")
    env["CODEX_MODE_CODEX_BIN"] = str(root / "fake-codex")
    env["CODEX_MODE_PROXY_BIN"] = str(root / "fake-proxy")
    env["CODEX_MODE_RUN_LOG"] = str(root / "run-log.json")
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def setup_root():
    tmp = tempfile.TemporaryDirectory()
    root = Path(tmp.name)
    (root / "config.toml").write_text(
        'model = "gpt-5.5"\nmodel_reasoning_effort = "medium"\n[plugins.demo]\nenabled = true\n'
    )
    (root / "fake-codex").write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        "p=os.environ['CODEX_MODE_RUN_LOG']\n"
        "data=json.load(open(p)) if os.path.exists(p) else []\n"
        "data.append(['codex']+sys.argv[1:])\n"
        "open(p,'w').write(json.dumps(data))\n"
    )
    (root / "fake-proxy").write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        "p=os.environ['CODEX_MODE_RUN_LOG']\n"
        "data=json.load(open(p)) if os.path.exists(p) else []\n"
        "data.append(['proxy']+sys.argv[1:])\n"
        "open(p,'w').write(json.dumps(data))\n"
    )
    (root / "fake-codex").chmod(0o700)
    (root / "fake-proxy").chmod(0o700)
    return tmp, root


def read_toml(path: Path):
    return tomlkit.parse(path.read_text())


def test_add_deepseek_profile_writes_private_profile_file():
    tmp, root = setup_root()
    with tmp:
        result = run_tool(root, "add", "deepseek", "--token", "token-value")

        assert result.returncode == 0, result.stderr
        profiles_path = root / "profiles.json"
        profiles = json.loads(profiles_path.read_text())
        assert profiles["profiles"]["deepseek"]["base_url"] == "https://api.deepseek.com"
        assert profiles["profiles"]["deepseek"]["model"] == "deepseek-v4-pro"
        assert profiles["profiles"]["deepseek"]["api_key"] == "token-value"
        assert oct(profiles_path.stat().st_mode & 0o777) == "0o600"


def test_api_switch_updates_codex_config_and_preserves_unrelated_tables():
    tmp, root = setup_root()
    with tmp:
        run_tool(root, "add", "custom", "--base-url", "https://chat.example", "--token", "token", "--model", "chat-model")
        result = run_tool(root, "api", "custom")

        assert result.returncode == 0, result.stderr
        config = read_toml(root / "config.toml")
        assert config["model"] == "chat-model"
        assert config["model_provider"] == "chat_proxy"
        assert config["plugins"]["demo"]["enabled"] is True
        provider = config["model_providers"]["chat_proxy"]
        assert provider["base_url"] == "http://127.0.0.1:18089/v1"
        assert provider["wire_api"] == "responses"
        assert provider["requires_openai_auth"] is False
        assert any((root / "backups").iterdir())


def test_sub_switch_restores_chatgpt_mode():
    tmp, root = setup_root()
    with tmp:
        run_tool(root, "add", "deepseek", "--token", "token")
        run_tool(root, "api", "deepseek")
        result = run_tool(root, "sub")

        assert result.returncode == 0, result.stderr
        config = read_toml(root / "config.toml")
        assert config["model"] == "gpt-5.5"
        assert config["model_reasoning_effort"] == "medium"
        assert "model_provider" not in config


def test_run_starts_proxy_then_codex_with_dangerous_bypass():
    tmp, root = setup_root()
    with tmp:
        run_tool(root, "add", "deepseek", "--token", "token")
        run_tool(root, "api", "deepseek")
        result = run_tool(root, "run", "Say OK")

        assert result.returncode == 0, result.stderr
        log = json.loads((root / "run-log.json").read_text())
        assert log[0][:4] == ["proxy", "serve", "--host", "127.0.0.1"]
        assert log[0][-2:] == ["--profile", "deepseek"]
        assert log[1] == ["codex", "--dangerously-bypass-approvals-and-sandbox", "Say OK"]
