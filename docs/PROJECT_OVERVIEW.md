# dutyshift — Project Overview

This document is a deep-dive reference for the `dutyshift` codebase, written to support a
discussion about improving the project. It describes what the code actually does today, not
what it should do — see [Known issues / improvement ideas](#known-issues--improvement-ideas)
at the end for gaps and pain points to use as discussion starters.

> **Scope note:** `arch/` and `refs/` are archived/obsolete material (old per-season notebooks,
> old reference docs) and are intentionally excluded from this document.

## Purpose & context

`dutyshift` automates the monthly process of building an on-call duty roster for doctors in a
hospital department (the Google Calendar/Form text is in Japanese and references 東大病院,
University of Tokyo Hospital). Each month it:

1. Builds a Google Form asking each doctor which duty slots they're available for.
2. Collects the responses.
3. Solves a two-stage optimization to decide who works which slot, balancing workload fairness
   against doctors' stated preferences/availability and a set of hard scheduling rules.
4. Publishes the resulting schedule as events on a shared Google Calendar.
5. Handles post-publication shift-swap ("replacement") requests submitted via a second Google
   Form.

It is a personal automation tool (the author is also the operator), not a packaged/deployed
application — there's no server, database, or UI beyond Jupyter + Google's own UIs (Forms,
Calendar).

## Tech stack

Pure Python, driven interactively from a single Jupyter notebook.

- **[PuLP](https://github.com/coin-or/pulp)** — MILP modeling library, solved with the bundled
  CBC solver. This is the optimization engine.
- **[ortoolpy](https://pypi.org/project/ortoolpy/)** — convenience helpers (`addvars`,
  `addbinvars`) for bulk-declaring PuLP variables from a pandas index.
- **pandas / numpy** — all data wrangling; nearly every intermediate result is a DataFrame
  keyed by `date_duty` (row) and/or member ID (column).
- **google-api-python-client / google-auth-oauthlib** — Google Forms API (create/read the
  availability and replacement-request surveys), Google Drive API (create/manage the per-month
  folder the form lives in), Google Calendar API (publish/diff the final schedule).
- Standard library: `os`, `datetime`, `calendar`, `math.ceil`, `random`, `time.sleep`.

**Gap:** there is no `requirements.txt`, `pyproject.toml`, or lockfile anywhere in the repo.
Dependencies must be inferred from imports and installed manually.

## Repo layout

| Path | What it is |
|---|---|
| `main.ipynb` | The single live entry point. Hand-edited and re-run every month. |
| `script/` | The Python package with all pipeline logic (see below). |
| `test/test01.py` … `test19.py` | Ad hoc, undocumented developer scratch scripts — not an automated test suite (no pytest/unittest, no assertions framework). |
| `README.md` | One paragraph: project purpose + CC BY-NC 4.0 license note. |
| `LICENSE` | Creative Commons Attribution-NonCommercial 4.0 license text. |
| `.gitignore` | Ignores `__pycache__`, `.vscode`, `.DS_Store`. |
| `arch/` | **Excluded from this doc** — archived/obsolete per-season notebooks and old code. |
| `refs/` | **Excluded from this doc** — archived/obsolete reference material. |

All *runtime data* — the doctor roster, per-month generated CSVs, and Google OAuth credentials
— lives **outside this repo**, in a Dropbox-synced folder resolved at runtime (see
[Data storage](#data-storage) below). Nothing under `Dropbox/dutyshift/...` is checked into
git.

## Pipeline walkthrough

`main.ipynb` has 7 cells, each a stage of the monthly pipeline. Cell outputs are cleared before
commit, so the notebook file itself carries no historical run output — only code.

**Cell 0 — Common parameters** (the only cell whose *content* changes every month):
```python
year_plan, month_plan, l_holiday = 2026, 8, [11]
l_date_ect_cancel = []
from script.parameter import *
```
`year_plan`/`month_plan` select the month to schedule; `l_holiday` is a plain list of
day-of-month integers for any weekday that should be treated as a holiday (weekends are always
holidays automatically — see [Data model](#data-model)). `l_date_ect_cancel` lists dates where
the ECT rotation is skipped (e.g. cancelled for a conference). Every past month's tuple is kept
as dead code in a triple-quoted comment block above the active line — see
[Known issues](#known-issues--improvement-ideas). `from script.parameter import *` loads the
fixed, rarely-changing configuration (duty types, scoring weights, per-title duty eligibility,
Google resource IDs) from `script/parameter.py`.

**Cell 1 — Create Google form** (`script/form.py::prepare_form`): builds the month's calendar
and duty-slot structure, then creates (from a template) a Google Form asking each doctor their
availability, printing the form's response URL for distribution.

**Cell 2 — Collect Google form response** (`script/collect.py::collect_availability`): reads
form responses plus the member roster, builds an availability matrix, flags doctors who haven't
responded or whose "designated physician" status doesn't match the roster, and prints any
free-text requests doctors left in the form.

**Cell 3 — Optimize assignment count and assign members** (`script/assign.py`): the core stage.
Solver-tuning hyperparameters are defined directly in this cell (weights for score-deviation
penalties, closeness thresholds, objective-term weights, manual overrides) — see
[Optimization engine](#optimization-engine). Calls
`optimize_count_and_assign(...)`, which runs two chained MILP solves.

**Cell 4 — Notify Google calendar** (`script/notify.py::update_calendar`): diffs the new
schedule against existing events on the shared Google Calendar and adds/deletes/updates events
(one per duty per doctor), including substitute-candidate info and a link to the shift-swap
request form in each event's description.

**Cell 5 — Collect replacement application** (`script/replace.py::check_replacement`): reads a
second, separate Google Form used for shift-swap requests and prints a proposed
before → after diff.

**Cell 6 — Apply checked replacement plan** (`script/replace.py::replace_assignment`):
re-applies the swap to the assignment tables and regenerates the summary/score outputs.

### `script/` module map

| Module | Lines | Role |
|---|---|---|
| `script/parameter.py` | 56 | Fixed, rarely-edited config: duty type ↔ label maps, scoring weights, per-title duty eligibility, class_duty aggregation rules, Google Form/Calendar IDs, duty clock times, machine-path list. |
| `script/helper.py` | 1057 | Shared building blocks: directory/credential resolution (`prep_dirs`, `prep_api_creds`), calendar construction (`prep_calendar`), roster loading/parsing (`read_member`, `prep_member2`, `split_lim`), the count-optimization MILP (`optimize_count`), result extraction/scoring/CSV export (`extract_assignment`, `extract_closeduty`, `convert_assignment`, `past_score`, `date_duty2class`). |
| `script/assign.py` | 835 | The assignment MILP (`optimize_assign`) and the orchestration function that runs both optimization stages and handles infeasibility (`optimize_count_and_assign`), plus a stale duplicate `optimize_count_and_assign_old`. |
| `script/form.py` | 81 | `prepare_form` — builds the availability-survey Google Form for the month. |
| `script/collect.py` | 184 | `collect_availability` — parses Google Form responses into an availability matrix. |
| `script/notify.py` | 244 | Google Calendar integration: `access_calendar`, `update_calendar`, `add_duty`, `delete_duty`, `list_duty`, `compare_event`. |
| `script/replace.py` | 125 | Shift-swap flow: `check_replacement`, `replace_assignment`. |
| `script/check.py` | 47 | Small sanity-check helpers: `check_availability_duty`, `check_availability_member`. |

## Data model

**Doctor / member** — one row per doctor in `member.xlsx` (an Excel workbook with one sheet per
year-month, e.g. `member_202608`). Key columns (parsed by `read_member`/`prep_member2`):
`id_member`, `name_jpn`, `title_short` (rank: `assoc` / `instr` / `assist_leader` /
`assist_subleader` / `limtermclin` / `stud`), `designation` (flags "指定医", a senior/designated
physician), `team`, `ect_leader`, `ect_subleader`, `active`, plus one column per `class_duty`
holding a limit spec string parsed by `split_lim`:
- `"3"` — exact count required
- `"2-4"` — hard range
- `"2(1-3)"` — soft target of 2, with a hard range of 1–3
- `"-"` — unconstrained

**Duty types** (`dict_duty` in `script/parameter.py`): `am`, `pm`, `day`, `ocday`, `night`,
`emnight`, `ocnight`, `ect`, each with a Japanese label (`dict_duty_jpn`) and start/end clock
time (`dict_time_duty`, e.g. night runs 17:15 → 32:30, i.e. 08:30 the *next* day).

**`date_duty`** — the universal index used throughout the codebase: a string key
`"<day-of-month>_<duty>"` (e.g. `"14_night"`). It's the row index of the availability matrix,
the assignment matrix, and most PuLP decision variables.

**`class_duty`** — an aggregation layer above raw duty types, used for counting and limit
enforcement (e.g. `ampm`, `daynight_tot`, `night_wd`, `night_em`, `daynight_hd`, `oc_tot`,
`oc_day`, `oc_night`, `ect`). Defined via `dict_class_duty` in `parameter.py`, which maps each
class to a set of `(duty, weekday/holiday qualifier)` pairs.

**Calendar/holidays** — `l_holiday` (a plain list of day-of-month ints) plus automatic weekend
detection are combined by `prep_calendar` (`helper.py`) into `d_cal`, which marks each day
`holiday=True`/`False`. This determines which duty types exist that day: holidays get
`day`/`night`/`ocday`/`ocnight`; weekdays get `am`/`pm`/`night`/`ocnight`; ECT only occurs on
specific configured weekdays (`l_day_ect`) and never on holidays.

**Scoring** — `dict_score_duty` (`parameter.py`) assigns a numeric workload weight to each duty
along several scoring axes (e.g. `ampm`: am/pm = 0.5 each; `daynight`: day/night = 1.0,
emnight = 1.5; `oc`: on-call = 1.0; `ect` = 1.0). These weights drive the fairness/equity
objective in the count-optimization stage, tracked both for the current month
(`d_score_current`) and cumulatively across months (`d_score_total`/`past_score`).

## Optimization engine

Two sequential MILP solves via PuLP, using the default bundled CBC solver.

### Stage 1 — `optimize_count` (`script/helper.py`)

Decides, per doctor per `class_duty`, the *target count* of assignments for the month
(integer variables `cnt_<member>_<class_duty>`). Objective: minimize pairwise absolute
deviation in workload *score* between doctors within equity groups — computed both for the
current month alone and cumulatively including past months — subject to each doctor's
hard min/max range parsed from their `member.xlsx` limit string.

### Stage 2 — `optimize_assign` (`script/assign.py`)

Decides the actual date-by-date, doctor-by-doctor assignment given Stage 1's targets.

**Decision variables:**
- `dv_assign` — the core binary matrix: rows = `date_duty`, columns = member ID
  (`ortoolpy.addbinvars`).
- `dv_deviation_target` / `dv_deviation_limit` — continuous slack per member per `class_duty`,
  penalizing deviation from the Stage 1 target / from the hard limit.
- `dict_dv_closeduty[...]` — continuous slack tracking assignment count within a rolling window
  of days per member, used to softly penalize duties scheduled too close together.

**Constraints:**
- Manually pre-assigned duties are fixed (`dv_assign == 1`).
- Doctors marked unavailable can never be assigned that slot.
- Exactly one assignee per `date_duty` for each duty type that exists that day.
- On-call (`ocday`/`ocnight`) is required exactly when the assigned `day`/`night` doctor is not
  a "designated" physician.
- Full-time-title doctors (`l_title_fulltime`) can be forced onto specific duties
  (`l_date_duty_fulltime`).
- Per-member per-`class_duty` counts are constrained to the Stage 1 output, in one of three
  modes selected by `type_limit`: `hard` (never exceed), `soft` (penalize deviation), or
  `ignore`.
- Students / limited-availability doctors are capped at 1–2 assignments per month.
- Only doctors flagged `ect_subleader` may take ECT duty; the ECT leader's own team is excluded
  from ECT that day.
- **Closeness/overlap avoidance**: a hard ban on more than one assignment within *N* days for
  configured duty groups (`dict_closeduty`, e.g. day/night cluster `thr_hard=3` days, ECT
  `thr_hard=1`, am/pm `thr_hard=1`), softly penalized over a wider window (`thr_soft`). This
  also accounts for the **previous month's tail-end assignments** (`d_assign_previous`) so
  continuity constraints span month boundaries.
- Explicit adjacent-duty avoidance pairs (`ll_avoid_adjacent`), e.g. don't let the same doctor
  do PM + night + emnight + ocnight the same day, or night/emnight/ocnight followed next-day by
  ECT/AM.

**Objective** (minimized): a weighted sum
`c_assign_suboptimal * v_assign_suboptimal + c_cnt_deviation * v_cnt_deviation + c_closeduty * v_closeduty`
— i.e. (a) count of available-but-not-preferred assignments, (b) total deviation from
target/hard-limit counts, (c) total closeness violations. Weights are set per-run in
`main.ipynb` cell 3 (current values: `0.00001, 0.1, 0.00001`).

**Infeasibility recovery** — `optimize_count_and_assign` wraps both stages: if a solve comes
back `Infeasible`, it retries with hard limits relaxed to soft, then runs a randomized
elimination search (iteratively drop random subsets of `date_duty` and re-solve) to isolate and
report which specific duty slots can't be filled under the current constraints.

## External integrations

- **Google Forms** — one form per month for availability collection (cloned from a template,
  `id_template_form`), plus a separate standing form for shift-swap requests. Response parsing
  in `script/collect.py` matches on exact Japanese question-text substrings.
- **Google Drive** — used to create/locate the per-month folder that houses each month's form.
- **Google Calendar** — the final schedule is published as one event per duty per doctor
  (`id_calendar` in `parameter.py`); `update_calendar` diffs against existing events so re-runs
  only add/remove/update what changed.
- **OAuth credentials** — `token.json`/`credentials.json`, referenced via
  `Dropbox/dutyshift/config/credentials/`, loaded by `helper.py::prep_api_creds`.

## Data storage

Nothing under `Dropbox/dutyshift/` is in this git repo. The path root is auto-detected by
`script/helper.py::prep_dirs` from a hardcoded candidate list,
`lp_root = ['/home/atiroms/Documents', 'D:/atiro', 'D:/NICT_WS', '/Users/smrt', 'C:/Users/atiro']`
(`script/parameter.py`) — whichever path exists on the machine currently running the notebook is
used. Layout: `<p_root>/Dropbox/dutyshift/<YYYYMM>/...`, with a `result/<prefix>_<timestamp>/`
subfolder holding a timestamped snapshot of every pipeline run (prefixes: `form_`, `clct_`,
`asgn_`, `rplc_`).

Representative files per month: `calendar.csv`, `date_duty.csv`, `assign_manual.csv`,
`member.csv`, `lim_hard.csv`/`lim_soft.csv`/`lim_exact.csv`, `availability.csv`,
`availability_ratio.csv`, `info.csv`, `assign_date_duty.csv`, `assign.csv`,
`assign_print.csv` (the human-readable roster with Japanese columns: 日付, 午前日直, 午後日直,
当直, 日直OC, 当直OC, ECT), `deviation.csv`/`deviation_summary.csv`, `score_current.csv`,
`score_total.csv`, `closeduty.csv`. The single Excel input `config/member.xlsx` (one sheet per
month) also lives here, not in git.

## Operational cadence

The notebook is re-run once per month. Git history is dominated by small commits — often
literally titled `param` — that append one new `(year_plan, month_plan, l_holiday)` tuple to
the growing commented-out history block in `main.ipynb` cell 0. Prior to the current
consolidated design, each irregular scheduling period (New Year, Golden Week, summer/winter
vacation weeks) had its own self-contained notebook; these are now archived under `arch/` once
their period has passed, and are out of scope for this document.

## Known issues / improvement ideas

These are observations from reading the code, offered as a starting point for discussion — not
a judgment of the project.

- **Hardcoded, machine-specific paths.** `lp_root` in `script/parameter.py` is a literal list of
  the author's personal machine paths. `prep_dirs` picks whichever exists — brittle, and not
  portable to a new machine or collaborator without editing source.
- **Monthly params accumulate as dead code.** `main.ipynb` cell 0 keeps every past month's
  `(year, month, holidays)` tuple as a commented-out line inside a growing triple-quoted string,
  rather than in a config file or table. This is also the *only* thing that changes about the
  notebook month to month.
- **Ad hoc solver-tuning presets.** Alternate values for `dict_c_diff_score_total`,
  `dict_closeduty`, and `c_assign_suboptimal, c_cnt_deviation, c_closeduty` are kept as
  commented-out sibling lines in cell 3 rather than named, documented presets — suggesting
  frequent trial-and-error re-tuning with no record of what was tried or why.
- **Stale duplicate function.** `script/assign.py` (835 lines total) contains both
  `optimize_count_and_assign` (lines 273–464, ~190 lines) and an apparently unused
  `optimize_count_and_assign_old` (lines 465–835, ~370 lines) — a near copy, roughly double the
  length. Both contain an identical unresolved `# TODO: equilize 3 continous holidays assignment
  count`, at lines 294 and 486 respectively.
- **Incomplete replacement/swap logic.** `script/replace.py` has two open TODOs: designated-
  physician status isn't accounted for during a swap (line 92), and a `d_assign.to_csv(...)`
  write is commented out rather than implemented (line 113).
- **Fragile Google Form parsing.** `script/collect.py` matches form questions by exact Japanese
  substring (e.g. `'[' + title_dateduty + ']'`, `'指定医'`, `'月2回'`, `'ご要望'`). Any wording
  change to the form template silently breaks parsing; the only feedback is a printed
  "missing member" list, no structured error handling.
- **No automated test suite.** `test/test01.py` … `test19.py` are 19 undocumented, ad hoc
  developer scripts (early PuLP prototypes, one-off data-migration patches, Google API
  experiments) — not a pytest/unittest suite, no assertions, no CI. The optimizer's correctness
  has no automated coverage.
- **No dependency lockfile.** No `requirements.txt`/`pyproject.toml` anywhere; dependencies must
  be inferred from imports and installed by hand.
- **Duplicated logic between the main pipeline and archived seasonal notebooks.** The
  now-archived per-season notebooks (summer/winter vacation assignment, etc.) reimplement their
  own inline PuLP model and their own result-extraction/CSV-saving/printing boilerplate rather
  than reusing `script/assign.py`/`script/helper.py::convert_assignment` — a structurally
  similar problem solved twice with diverging conventions.
