# CLAUDE.md

Guidance for Claude Code when working in this repository.

## What this project is

`dutyshift` automates the monthly build of an on-call duty roster for hospital doctors: it
creates a Google Form to collect doctor availability, solves a two-stage mixed-integer linear
program (PuLP/CBC) to decide who works which shift, publishes the result to a shared Google
Calendar, and handles post-publication shift-swap requests. It's operated as a single Jupyter
notebook re-run once per month, not a deployed service.

For a full deep-dive (data model, MILP formulation, module-by-module walkthrough, known issues),
see [docs/PROJECT_OVERVIEW.md](docs/PROJECT_OVERVIEW.md).

## Scope: ignore `arch/` and `refs/`

`arch/` and `refs/` contain archived, obsolete notebooks and reference material (old per-season
scheduling notebooks, superseded docs). Do not read, edit, or base new work on files in these
directories unless the user explicitly asks about archived history.

## Tech stack

Pure Python + Jupyter. No `requirements.txt`/`pyproject.toml`/lockfile exists — dependencies
must be installed manually. Core libraries actually imported by the code:
- `pulp`, `ortoolpy` — the MILP optimizer (PuLP modeling + CBC solver)
- `pandas`, `numpy` — all data handling
- `google-api-python-client`, `google-auth-oauthlib` — Google Forms/Drive/Calendar APIs

## How it runs

There is no CLI or `main.py`. The pipeline is `main.ipynb`, executed cell by cell:
1. Set `year_plan, month_plan, l_holiday` (cell 0) — the only per-month edit.
2. `script/form.py::prepare_form` — create the availability Google Form.
3. `script/collect.py::collect_availability` — parse form responses.
4. `script/assign.py::optimize_count_and_assign` — run the two-stage MILP.
5. `script/notify.py::update_calendar` — publish to Google Calendar.
6. `script/replace.py::check_replacement` / `replace_assignment` — handle shift-swap requests.

All runtime data (`config/member.xlsx` doctor roster, per-month generated CSVs, Google OAuth
credentials) lives outside this repo in a Dropbox-synced folder, path auto-detected from a
hardcoded machine-path list (`lp_root` in `script/parameter.py`). Nothing under
`Dropbox/dutyshift/...` is version-controlled here.

## Key files

| File | Role |
|---|---|
| `main.ipynb` | Entry point; the monthly pipeline, cell by cell. |
| `script/parameter.py` | Fixed config: duty types, scoring weights, per-title duty eligibility, Google resource IDs. Edited rarely. |
| `script/helper.py` | Shared building blocks: calendar prep, roster loading/parsing, the Stage-1 count-optimization MILP (`optimize_count`), result extraction/CSV export. |
| `script/assign.py` | The Stage-2 assignment MILP (`optimize_assign`) and orchestration (`optimize_count_and_assign`), including infeasibility recovery. Contains a stale unused duplicate, `optimize_count_and_assign_old`. |
| `script/form.py` | Creates the monthly availability Google Form. |
| `script/collect.py` | Parses Google Form responses into an availability matrix. |
| `script/notify.py` | Publishes/diffs the schedule against Google Calendar events. |
| `script/replace.py` | Shift-swap request handling. |
| `script/check.py` | Small sanity-check helpers. |

## Conventions to know before editing

- **`date_duty`** is the universal index used everywhere: a string key
  `"<day-of-month>_<duty>"` (e.g. `"14_night"`), indexing the availability matrix, assignment
  matrix, and most PuLP decision variables.
- **`class_duty`** is an aggregation layer above raw duty types (`am`, `pm`, `day`, `night`,
  `emnight`, `ocday`, `ocnight`, `ect`), used for per-doctor count limits — defined in
  `dict_class_duty` in `script/parameter.py`.
- Per-doctor limits in `config/member.xlsx` are encoded as strings parsed by `split_lim`:
  `"3"` = exact, `"2-4"` = hard range, `"2(1-3)"` = soft target with hard range, `"-"` =
  unconstrained.
- Holidays are passed per-run as a plain list of day-of-month integers (`l_holiday`); weekends
  are always holidays automatically.

## Testing

`test/` contains 19 undocumented, ad hoc developer scripts (`test01.py`…`test19.py`) — not an
automated test suite. There is no pytest/unittest setup and no test command to run. Treat
changes to the optimizer as needing manual verification (re-run the relevant notebook cell
against real or sample data) rather than assuming test coverage exists.
