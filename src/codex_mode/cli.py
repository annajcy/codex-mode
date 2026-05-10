from __future__ import annotations

import argparse
import json
import os
import shutil
import stat
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

import tomlkit


CONFIG_PATH = Path(os.environ.get("CODEX_MODE_CONFIG", "~/.codex/config.toml")).expanduser()
PROFILES_PATH = Path(os.environ.get("CODEX_MODE_PROFILES", "~/.codex/codex-mode-profiles.json")).expanduser()
BACKUP_DIR = Path(os.environ.get("CODEX_MODE_BACKUP_DIR", "~/.codex/backups")).expanduser()
CODEX_BIN = os.environ.get("CODEX_MODE_CODEX_BIN", "codex")
PROXY_BIN = os.environ.get("CODEX_MODE_PROXY_BIN", "codex-chat-proxy")
PROXY_HOST = os.environ.get("CODEX_MODE_PROXY_HOST", "127.0.0.1")
PROXY_PORT = int(os.environ.get("CODEX_MODE_PROXY_PORT", "18089"))


def load_profiles() -> dict:
    if not PROFILES_PATH.exists():
        return {"profiles": {}, "active_profile": None}
    return json.loads(PROFILES_PATH.read_text(encoding="utf-8"))


def save_profiles(data: dict) -> None:
    PROFILES_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = PROFILES_PATH.with_suffix(PROFILES_PATH.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    tmp.replace(PROFILES_PATH)
    PROFILES_PATH.chmod(stat.S_IRUSR | stat.S_IWUSR)


def command_add(args) -> int:
    data = load_profiles()
    data.setdefault("profiles", {})
    if args.name == "deepseek":
        profile = {
            "provider": "deepseek",
            "base_url": "https://api.deepseek.com",
            "chat_path": "/chat/completions",
            "api_key": args.token,
            "model": args.model or "deepseek-v4-pro",
            "small_model": args.small_model or "deepseek-v4-flash",
        }
    else:
        if not args.base_url or not args.model:
            print("custom profiles require --base-url and --model", file=sys.stderr)
            return 2
        profile = {
            "provider": args.name,
            "base_url": args.base_url,
            "chat_path": args.chat_path,
            "api_key": args.token,
            "model": args.model,
            "small_model": args.small_model,
        }
    data["profiles"][args.name] = profile
    save_profiles(data)
    print(f"Saved profile: {args.name}")
    return 0


def command_api(args) -> int:
    data = load_profiles()
    profile = data.get("profiles", {}).get(args.profile)
    if not profile:
        print(f"Unknown profile: {args.profile}", file=sys.stderr)
        return 2

    config = load_config()
    backup_config()
    config["model"] = profile["model"]
    config["model_provider"] = "chat_proxy"
    providers = config.setdefault("model_providers", tomlkit.table())
    provider = providers.setdefault("chat_proxy", tomlkit.table())
    provider["name"] = "Codex Chat Proxy"
    provider["base_url"] = f"http://{PROXY_HOST}:{PROXY_PORT}/v1"
    provider["wire_api"] = "responses"
    provider["requires_openai_auth"] = False
    write_config(config)

    data["active_profile"] = args.profile
    save_profiles(data)
    print(f"Codex mode: api ({args.profile})")
    return 0


def command_sub(_args) -> int:
    config = load_config()
    backup_config()
    config["model"] = "gpt-5.5"
    config["model_reasoning_effort"] = "medium"
    config.pop("model_provider", None)
    write_config(config)

    data = load_profiles()
    data["active_profile"] = None
    save_profiles(data)
    print("Codex mode: subscription")
    return 0


def command_status(_args) -> int:
    data = load_profiles()
    config = load_config()
    active = data.get("active_profile")
    if config.get("model_provider") == "chat_proxy" and active:
        profile = data.get("profiles", {}).get(active, {})
        print(f"Mode: api ({active})")
        print(f"Model: {profile.get('model', config.get('model'))}")
        print(f"Base URL: {profile.get('base_url', '(unknown)')}")
    else:
        print("Mode: subscription")
        print(f"Model: {config.get('model', '(unset)')}")
    return 0


def command_run(args) -> int:
    data = load_profiles()
    profile = data.get("active_profile")
    if not profile:
        print("No active API profile. Run `codex-mode api <profile>` first.", file=sys.stderr)
        return 2

    proxy_cmd = [
        PROXY_BIN,
        "serve",
        "--host",
        PROXY_HOST,
        "--port",
        str(PROXY_PORT),
        "--profile-file",
        str(PROFILES_PATH),
        "--profile",
        profile,
    ]
    if os.environ.get("CODEX_MODE_RUN_LOG"):
        subprocess.call(proxy_cmd)
        proxy_proc = None
    else:
        proxy_proc = subprocess.Popen(proxy_cmd)
    try:
        wait_for_proxy(PROXY_HOST, PROXY_PORT, timeout=5.0)
        codex_cmd = [CODEX_BIN, "--dangerously-bypass-approvals-and-sandbox", *args.codex_args]
        return subprocess.call(codex_cmd)
    finally:
        if proxy_proc is not None and proxy_proc.poll() is None:
            proxy_proc.terminate()


def load_config():
    if not CONFIG_PATH.exists():
        return tomlkit.document()
    return tomlkit.parse(CONFIG_PATH.read_text(encoding="utf-8"))


def write_config(config) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_PATH.with_suffix(CONFIG_PATH.suffix + ".tmp")
    tmp.write_text(tomlkit.dumps(config), encoding="utf-8")
    tmp.replace(CONFIG_PATH)


def backup_config() -> Path | None:
    if not CONFIG_PATH.exists():
        return None
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    backup = BACKUP_DIR / f"config.toml.bak-{stamp}"
    shutil.copy2(CONFIG_PATH, backup)
    return backup


def wait_for_proxy(host: str, port: int, timeout: float) -> None:
    if os.environ.get("CODEX_MODE_RUN_LOG"):
        return
    deadline = time.time() + timeout
    url = f"http://{host}:{port}/healthz"
    while time.time() < deadline:
        try:
            with urlopen(url, timeout=0.5) as response:
                if response.status == 200:
                    return
        except URLError:
            time.sleep(0.1)
    raise RuntimeError(f"proxy did not become healthy at {url}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="codex-mode")
    subparsers = parser.add_subparsers(dest="command", required=True)

    add = subparsers.add_parser("add")
    add.add_argument("name")
    add.add_argument("--token", required=True)
    add.add_argument("--base-url")
    add.add_argument("--model")
    add.add_argument("--small-model")
    add.add_argument("--chat-path", default="/chat/completions")
    add.set_defaults(func=command_add)

    api = subparsers.add_parser("api")
    api.add_argument("profile")
    api.set_defaults(func=command_api)

    sub = subparsers.add_parser("sub")
    sub.set_defaults(func=command_sub)
    subscription = subparsers.add_parser("subscription")
    subscription.set_defaults(func=command_sub)

    status = subparsers.add_parser("status")
    status.set_defaults(func=command_status)

    run = subparsers.add_parser("run")
    run.add_argument("codex_args", nargs=argparse.REMAINDER)
    run.set_defaults(func=command_run)
    return parser


def main(argv=None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    if argv and argv[0] == "run":
        return command_run(argparse.Namespace(codex_args=argv[1:]))
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
