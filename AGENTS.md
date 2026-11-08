# Working instructions

- Implement the approved autonomous six-player «Бункер» game in this repository.
- Read `/Users/nucyc/.codex/CODING_STANDARDS.md` before code changes and checks.
- Read `/Users/nucyc/.codex/RTK.md`; prefix shell commands with `rtk`.
- Run Python only through this project's `.venv` (`uv run` is acceptable).
- Rules, quotas, visibility, votes and eliminations belong to code, not the LLM host.
- Never fabricate model responses, successful runs, votes, token counts or timings.
- Never commit keys, `.env`, authorization headers or credential URLs.
- Keep test fixtures distinguishable from real saved games.
- Keep complete Python implementation embedded in `LLM_Theatre.ipynb` via
  `scripts/build_notebook.py`; default notebook execution replays saved evidence.
- Frontend source is in `frontend/`; backend source is in `bunker/`.
