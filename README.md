# Dell x NVIDIA Hackathon 2026: two-sided career matching agent

One OpenClaw agent (NemoClaw sandbox, local Qwen on the GB10 box) that writes structured job
descriptions for employers and matches students to real ATS postings, through Slack.

**Read [MASTER_CONTEXT.md](MASTER_CONTEXT.md) first.** It holds the contracts, ownership and timeline.
Full run and demo steps get written here at 17:15.

## Teammate quick start

```bash
git clone https://github.com/Suo30/Dell-x-NVIDIA-Hackathon-2026 && cd Dell-x-NVIDIA-Hackathon-2026
git checkout -b <a-platform|b-candidate|c-employer|d-data>
cp .env.example .env                       # PowerShell: Copy-Item .env.example .env

# Real model (separate terminal, leave it open):
ssh -L 8000:127.0.0.1:8000 dell@172.20.65.171
# Or no model at all: set MOCK_LLM=1 in .env

bash tests/smoke.sh                        # Windows: run from Git Bash
```

- Python 3 standard library only. No `pip install`.
- Every tool: `python tools/<name>.py --help`. Each prints exactly one JSON object and exits 0.
  Wrap `main()` with `_cli.run(main)` and return a dict; errors become `{"error": "..."}` automatically.
- Settings come from `tools/_config.py` (reads `.env`, then env vars).
- `smoke.sh` shows each tool as `OK`, `ERR` (returns an error, e.g. still a stub) or `FAIL` (broke the contract).
- Never commit `.env`, tokens or `*.db`. Scratch files go in `work/` (gitignored).
