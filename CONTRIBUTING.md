# Contributing

How the five of us (and Claude Code) work in this repo. The full rules are in [ROADMAP.md](ROADMAP.md) (Team rules T1–T17).

## First-time setup

1. Install [uv](https://docs.astral.sh/uv/).
2. Clone and install:
   ```bash
   git clone https://github.com/pratox1112/finqa-verify.git
   cd finqa-verify
   uv sync
   uv run pre-commit install
   ```
   `pre-commit install` sets up three Git hooks: lint/format and a `.env` guard on every commit, and an automatic `uv sync` whenever a pull, merge or checkout changes `uv.lock`.
3. Copy `.env.example` to `.env` and fill in your own keys and `EDGAR_IDENTITY`. Never commit `.env`.

## API keys

- **Everyone uses their own keys** in their own `.env` (copied from `.env.example`). Never share keys in chat or commit them; the pre-commit hook blocks `.env`.
- **`GROQ_API_KEY`:** create one at console.groq.com → API Keys. Results don't depend on whose key made a call: the model and settings come from `configs/`, and the response cache key doesn't include the API key, so cached responses are valid for everyone.
- **`EDGAR_IDENTITY`:** your name and email, e.g. `"Jane Doe jane@northeastern.edu"`. The SEC requires it on every download; no signup.
- **Langfuse keys** are optional; tracing turns off cleanly without them.
- **Check your setup:** `uv run pytest -m integration` makes one real Groq call (it is skipped if no key is found).
- **Rate limits:** the free tier is fine for development. Groq limits apply per organization, so keys in the same Groq org share one set of limits. Official test-set runs happen from one account on a clean `main` (see `docs/DECISIONS.md` for the current plan).

## Working on a task

1. **Claim it** in [PROGRESS.md](PROGRESS.md): status `in-progress`, your name, your branch.
2. **Branch from an up-to-date `main`**, one task per branch, with a short descriptive name. **No task IDs or phase names** in branch names, commit messages or PR titles (T7):
   ```bash
   git switch main
   git pull
   git switch -c section-chunking
   ```
3. **Run the checks locally** before every push:
   ```bash
   uv run pre-commit run --all-files
   uv run pytest -m "not integration"
   ```
4. **Update `PROGRESS.md`** in the same PR (status `review`, notes, one Log line).
5. **Open a PR** into `main`. Keep it under ~400 changed lines where possible (T8). Mention any dependency change.
6. **Get one approving review** from a teammate who didn't write the code, including code Claude Code wrote (T9). CI must be green.
7. **Squash and merge** (T10), then set the task to `done` with the PR link.

If `main` is ever red, fixing it comes before everything else (T4).

## Dependencies

Only through `uv add <pkg>` / `uv remove <pkg>` (or `uv add --dev`), committing the updated `uv.lock` in the same PR (T2). Never edit `uv.lock` by hand. CI fails if `uv.lock` is out of date.

## Tests

- Unit tests never touch the network. Use small fixtures in `tests/fixtures/`.
- Tests that call Groq, EDGAR, Hugging Face or yfinance are marked `@pytest.mark.integration`. They are skipped in normal CI and run only through the manual **Integration** workflow (Actions tab → Integration → Run workflow).

## Frozen files and `approved-freeze-change`

These are frozen once they exist on `main`: `src/finqa/schemas.py`, `data/splits.json`, the `model:` section of `configs/base.yaml`, `src/finqa/prompts/FROZEN.txt`, and every prompt listed in it. CI fails any PR that changes them.

To change one:

1. Open the PR and explain in its description why the change is needed and what it affects.
2. Get the team's agreement (at the weekly sync or in the team channel) and record it in `docs/DECISIONS.md` in the same PR.
3. Get **two** approving reviews.
4. A reviewer adds the label `approved-freeze-change`; CI re-runs and passes.

To freeze a prompt, add its file name to `src/finqa/prompts/FROZEN.txt` and record the commit hash in `docs/DECISIONS.md`.

## Data and shared artifacts

- Committed: small curated files in `data/` (`splits.json`, `SCOPE.md`, `QA_CHECKS.md`, `metric_map.yaml`, `companies.csv`, `financebench_audit.csv`).
- Never committed: downloads and generated data (`data/raw/`, `data/xbrl/`, the index), `runs/`, caches, `.env` (T14).
- **Shared artifact location:** *[TBD: agree on a shared drive folder and put the link here]*. The index, XBRL cache, completed runs and response cache live there.
- Test-set runs only from a clean checkout of `main` (T12). Run IDs: `{date}_{config-name}_{short-commit}` (T13).

## Design decisions

Any research-design decision (scoring edge cases, thresholds, inclusion rules) goes in `docs/DECISIONS.md` with date, who decided and why, before the code that depends on it is merged (T15).

## Claude Code

Claude Code reads [CLAUDE.md](CLAUDE.md) every session. It never runs Git or GitHub commands that change anything. It ends each hand-off with a "Human steps" block of commands for you to run (T17).
