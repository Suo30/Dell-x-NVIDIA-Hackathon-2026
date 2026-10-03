# Box setup runbook (Person A)

Host = the Dell GB10 box shell. Sandbox = a shell inside the `career-agent` sandbox.
Anything marked `TODO(verify)` has not been confirmed on the box yet. Check it before relying on it.

**Sandbox name: `career-agent`.** `TODO(verify)`: confirm with `openshell sandbox list` (or `nemoclaw list`).
Every command below and the `SANDBOX` default in `push_to_sandbox.sh` and `box_preflight.sh` use it. If the real
name differs, run the scripts with `SANDBOX=<name>` and fix this file.

**Answer to Q3:** workspace path is `/sandbox/.openclaw/workspace/`, repo at `/sandbox/.openclaw/workspace/repo`,
skills at `/sandbox/.openclaw/workspace/skills`. `prompts/system.md` deploys as `/sandbox/.openclaw/workspace/AGENTS.md`.

Never paste a token into chat, a file in this repo, or a command line that ends up in shell history.

## (a) Rotate and create Slack tokens

1. If any token was ever pasted anywhere, rotate it first: in the Slack app settings, regenerate the
   app-level token and reinstall the app to invalidate the old bot token.
2. Create the app from the manifest: Slack app settings, "Create New App", "From an app manifest",
   paste the contents of `infra/slack-app-manifest.yaml`. Socket mode is on in the manifest.
3. "Basic Information", "App-Level Tokens": generate one with the `connections:write` scope. This is the app token.
4. "Install App" to the workspace. Copy the Bot User OAuth Token. This is the bot token.
5. Keep both in a password manager only. They are typed into onboarding in step (c).
6. Create `#hiring` and `#students` and add the bot to both: `/invite @Career Agent` in each channel. `TODO(verify)`
7. Collect member IDs of everyone allowed to talk to the bot (Slack profile, "Copy member ID").

## (b) vLLM readiness gate (host)

Do not onboard until both of these work.

```sh
curl -s http://127.0.0.1:8000/v1/models
curl -s http://127.0.0.1:8000/v1/chat/completions -H 'Content-Type: application/json' \
  -d '{"model":"nvidia/Qwen3.6-35B-A3B-NVFP4","messages":[{"role":"user","content":"Say OK"}],"max_tokens":1}'
```

Then run the full host preflight from the repo checkout on the host (prints PASS/FAIL/WARN per line):

```sh
bash scripts/box_preflight.sh
```

If it warns that port 8000 is bound only to 127.0.0.1, relaunch vLLM bound to all interfaces
(`--host 0.0.0.0`, `TODO(verify)` against the current launch command), because the sandbox reaches it via
`host.openshell.internal`.

## (c) Onboarding (host)

Tokens are entered with `read -rs` so they are never echoed or written to history.

```sh
printf 'Bot token: ';  read -rs SLACK_BOT_TOKEN; echo; export SLACK_BOT_TOKEN   # TODO(verify): variable name nemoclaw reads
printf 'App token: ';  read -rs SLACK_APP_TOKEN; echo; export SLACK_APP_TOKEN   # TODO(verify): variable name nemoclaw reads
export SLACK_ALLOWED_USERS="U0C6MD4RQJG,U0C7C2J0ZA4,U0C629WDZJT,U0C6BEMTC2F, U0C6CC00W85"   # member IDs from (a).7; TODO(verify): separator format
export NEMOCLAW_LOCAL_INFERENCE_TIMEOUT=600
nemoclaw onboard
```

If `nemoclaw onboard` asks for the tokens itself, paste them at its prompt instead of exporting them.

Choices during onboarding:
- Agent: OpenClaw
- Inference: local vLLM, or "Other OpenAI-compatible endpoint" with base URL `http://localhost:8000/v1` and API key `dummy`
- Sandbox name: `career-agent`
- Channels: toggle Slack on
- Policy: default policy tier

After onboarding, clear the tokens from the shell: `unset SLACK_BOT_TOKEN SLACK_APP_TOKEN`.

## (d) Confirm route and channel (host)

```sh
openshell inference get
nemoclaw career-agent channels list
```

The inference output must show only the local vLLM route. The channel list must show Slack.

## (e) Job board network policy (host, repo checkout)

```sh
nemoclaw career-agent policy-add --from-file infra/job-boards.yaml
```

The `binaries` path in `infra/job-boards.yaml` (`/usr/bin/python3`) is a guess. Keep `openshell term` open,
trigger one request to Greenhouse from the sandbox (ladder step 6), and if it shows as blocked, copy the
binary path it reports into the YAML and run `policy-add` again.

Applicant screening (`screen_resumes.py --consent-confirmed`) also needs the public GitHub API:

```sh
nemoclaw career-agent policy-add --from-file infra/recruit-research.yaml
```

Sandbox Python extras (`fastapi pydantic python-docx pypdf`, pinned in `requirements-sandbox.txt`) for
`screen_resumes.py` and PDF resumes. `scripts/push_to_sandbox.sh` does not install them; once per sandbox (and
after a rebuild), allow PyPI with NemoClaw's `pypi` preset (`nemoclaw career-agent policy-add --help` shows the
preset syntax), then run:

```sh
nemoclaw career-agent exec -- python3 -m pip install --user -r /sandbox/.openclaw/workspace/repo/requirements-sandbox.txt
nemoclaw career-agent exec -- python3 -c "import fastapi, pydantic, docx, pypdf; print('ok')"
```

No PyPI: on the host, with a Python whose `X.Y` matches the sandbox `python3 --version`, run
`python3 -m pip download --only-binary=:all: -d wheels -r requirements-sandbox.txt`, then
`openshell sandbox upload career-agent wheels /sandbox/` and install with
`pip install --user --no-index --find-links /sandbox/wheels -r .../requirements-sandbox.txt`.

Without them every tool except `screen_resumes.py` still works (PDF resumes ask for pasted text instead).

## (f) Get the repo into the sandbox

Default path (host, repo checkout on `main`): `bash scripts/push_to_sandbox.sh`. It uploads the committed `HEAD`
with `openshell sandbox upload`, unpacks it to the repo path, refreshes skills and `AGENTS.md`, installs
`infra/sandbox.env` as `.env` and re-applies missing egress policies. Then run (g) from `sandbox_check.sh` on.
The options below are the manual fallback.

First open a shell inside the sandbox. `TODO(verify)`: exact command (check `nemoclaw --help`).

Option 1: git clone inside the sandbox (needs github.com on the allowlist; `TODO(verify)`: how to add it):

```sh
git clone https://github.com/Suo30/Dell-x-NVIDIA-Hackathon-2026 /sandbox/.openclaw/workspace/repo
```

Later updates: `git -C /sandbox/.openclaw/workspace/repo pull` (`TODO(verify)`: git exists in the sandbox).

Option 2: upload from the host. `TODO(verify)`: check `openshell sandbox --help` for an upload or copy command.

## (g) Deploy and check (sandbox)

```sh
cd /sandbox/.openclaw/workspace/repo
bash scripts/deploy_box.sh
```

`deploy_box.sh` copies skills (real copies, no symlinks) and `prompts/system.md` to `AGENTS.md`, never touches
`.env` or the DB, and prints the seed command. If it reports `.env: MISSING`, create it (no secrets in it):

```sh
cat > /sandbox/.openclaw/workspace/repo/.env <<'EOF'
LLM_BASE_URL=REPLACE_WITH_INFERENCE_LOCAL_URL
LLM_MODEL=nvidia/Qwen3.6-35B-A3B-NVFP4
DB_PATH=app.db
DATA_DIR=data
MOCK_LLM=0
EOF
```

`TODO(verify)`: the exact `inference.local` base URL and whether the model name is passed through unchanged.

Then seed once with the command `deploy_box.sh` printed, and run:

```sh
bash scripts/sandbox_check.sh
```

Every redeploy: `deploy_box.sh`, then send `/new` in Slack so the agent rereads `AGENTS.md` and the skills.

## (h) Test ladder

Go in order. Do not move on until the step passes.

1. Slack ping: in `#students`, `@Career Agent hello`. Expect a reply.
2. Smoke test (sandbox): `cd /sandbox/.openclaw/workspace/repo && MOCK_LLM=1 bash tests/smoke.sh`. Expect `FAIL count: 0`.
3. Skills loaded (sandbox): `openclaw skills list`. Expect `role-architect` and `career-matcher`.
4. One tool from Slack: `@Career Agent list the latest internal jobs`. Expect the agent to run `list_jobs.py` and report its JSON.
5. File upload: upload `tests/fixtures/resume.txt` in `#students` with `@Career Agent here is my resume`.
   If the agent cannot read it, the demo uses pasted resume text. Diagnosis and fixes: handoff A step 2
   (egress fix: set the binary path in `infra/slack-files.yaml`, then
   `nemoclaw career-agent policy-add --from-file infra/slack-files.yaml`).
   Slack attachment result: pending diagnosis (A step 2). Fallback in skills: pasted text.
6. Live fetch with `openshell term` open on the host: `@Career Agent refresh the job list`.
   Watch for blocked requests; fix the policy binary path per (e).

## (i) Local-only proof

```sh
openshell inference get
```

It must show only the local vLLM route (no NVIDIA cloud endpoints, OpenAI or Anthropic). Screenshot it for
the submission. `box_preflight.sh` warns if a cloud provider appears in this output.

## (j) Known gotchas

- Channel messages need an explicit mention. Every demo message starts with `@Career Agent`.
- Never run `openclaw channels add` inside the sandbox. Channels are managed from the host through onboarding.
- `openshell policy set` replaces the whole policy. Use `nemoclaw career-agent policy-add` instead.
- Adding a Slack channel rebuilds the sandbox image. Do it before loading code into the workspace.
- The workspace is lost on `nemoclaw career-agent destroy`. Back it up first (`.env` and the DB are the only
  things not in git). `TODO(verify)`: how to copy files out of the sandbox.
- vLLM must be launched with tool-call parsing enabled (`--enable-auto-tool-choice --tool-call-parser ...`,
  `TODO(verify)`). The parser name for Qwen3.6-35B-A3B is unknown; check the model card.
- `ufw` active on the host: allow the Docker bridge subnets to port 8000 (`TODO(verify)`: exact `ufw allow` rule
  and subnets), or the sandbox cannot reach vLLM.
