# codex-mode

CLI for switching Codex between ChatGPT subscription mode and a local
`codex-chat-proxy` Responses-compatible provider.

`codex-mode` manages Codex config and starts the proxy. The proxy itself lives
in the separate `codex-chat-proxy` project.

## Install

```bash
uv sync
uv run codex-mode --help
```

For command-line use from anywhere:

```bash
uv tool install -e .
```

## Usage

Add DeepSeek:

```bash
codex-mode add deepseek --token your-api-key
```

Add a custom OpenAI-compatible ChatCompletions provider:

```bash
codex-mode add custom \
  --base-url https://api.example.com \
  --token your-api-key \
  --model provider-model
```

Switch Codex to the local proxy provider:

```bash
codex-mode api deepseek
```

Run Codex. This starts `codex-chat-proxy` in the background and launches Codex
with `--dangerously-bypass-approvals-and-sandbox`:

```bash
codex-mode run "Say OK"
```

Return to ChatGPT subscription mode:

```bash
codex-mode sub
```

## Files

`~/.codex/config.toml` is backed up before each switch.

`~/.codex/codex-mode-profiles.json` stores provider API keys and is written
with mode `600`.

## Test

```bash
uv run pytest -q
```
