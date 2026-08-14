# CLAUDE.md

Guidance for Claude Code when working in this repository.

## What this project is

`dutyshift` automates the monthly build of an on-call duty roster for hospital doctors: it
creates a Google Form to collect doctor availability, solves a two-stage mixed-integer linear
program (PuLP/CBC) to decide who works which shift, publishes the result to a shared Google
Calendar, and handles post-publication shift-swap requests. It's operated as a single Jupyter
notebook re-run once per month, not a deployed service. The notebook is a single cell that
displays one combined `ipywidgets` panel — common parameters on top, one `Tab` per pipeline
stage below — rather than hand-edited code across multiple cells.

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
- `ipywidgets` — the GUI layer (`script/gui.py`); runs under classic Jupyter Notebook, which
  must be running an actual `ipykernel` for widget `Button`/`Output` capture to work — running
  cells via `nbconvert --execute` or a plain script only checks that panels *build*, not that
  clicks/output-capture work end to end.

## How it runs

There is no CLI or `main.py`. `main.ipynb` is one cell:
```python
state = AppState()
display(build_app(state))
```
`build_app` (`script/gui.py`) combines every stage into one panel — common parameters
(year/month dropdowns, holiday/ECT-cancel multi-selects) pinned on top, one `Tab` below per
stage:
1. **1. Create Form** — `script/form.py::prepare_form`, creates the availability Google Form.
2. **2. Collect** — `script/collect.py::collect_availability`, parses form responses.
3. **3. Assign** — `script/assign.py::optimize_count_and_assign`, runs the two-stage MILP. Its
   hyperparameters (score-deviation weights, close-duty thresholds, `type_limit`, etc.) are
   editable widgets in a collapsed "Advanced solver parameters" accordion, defaulting to the
   values that used to be hardcoded in the old cell 3.
4. **4. Notify** — `script/notify.py::update_calendar`, publishes to Google Calendar.
5. **5. Check Replace** / **6. Apply Replace** — `script/replace.py::check_replacement` /
   `replace_assignment`, handle shift-swap requests. `check_replacement`'s result is held on
   `state.d_replace_checked` (the only value that flows between tabs in memory) and consumed by
   the apply-replacement tab.

Each tab only wires widgets to these unchanged `script/*.py` functions — the pipeline logic
itself did not change. Every `build_*_panel(state)` function (and `build_app` itself) can still
be called/`display()`-ed directly from a plain script/notebook cell, exactly like the pre-GUI
code, if needed for debugging just one stage.

All runtime data (`config/member.xlsx` doctor roster, per-month generated CSVs, Google OAuth
credentials) lives outside this repo in a Dropbox-synced folder, path auto-detected from a
hardcoded machine-path list (`lp_root` in `script/parameter.py`). Nothing under
`Dropbox/dutyshift/...` is version-controlled here.

## Key files

| File | Role |
|---|---|
| `main.ipynb` | Entry point; single cell, displays `script/gui.py::build_app(state)`. |
| `script/gui.py` | `ipywidgets` GUI layer: `AppState` (shared widgets + cross-panel state), one `build_*_panel()` function per pipeline stage, and `build_app()` combining them into the single panel `main.ipynb` displays. Wires widgets to the functions below; contains no pipeline logic itself. |
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
- `script/parameter.py`'s duty-related tables have single sources of truth, not independent
  hand-typed copies: `dict_duty`/`dict_duty_jpn`/`dict_time_duty` are all derived from one
  `_dict_duty_info` table; `l_class_duty` is derived from `dict_class_duty`; `dict_score_class`
  (per-`class_duty` score weights, used by `optimize_count`) is derived from `dict_score_duty`
  (per-duty score weights) via `_derive_score_class_constants`, which raises `ValueError` if the
  two can no longer be reconciled. **To change scoring weights, edit `dict_score_duty`, not
  `dict_score_class`** — the latter is computed, not a knob.

## Testing

`test/` contains 19 undocumented, ad hoc developer scripts (`test01.py`…`test19.py`) — not an
automated test suite. There is no pytest/unittest setup and no test command to run. Treat
changes to the optimizer as needing manual verification (re-run the relevant notebook cell
against real or sample data) rather than assuming test coverage exists.
