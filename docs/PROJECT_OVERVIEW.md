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
application — there's no server or database. The UI is Jupyter (via `ipywidgets` panels, one
per stage) plus Google's own UIs (Forms, Calendar).

## Tech stack

Pure Python, driven interactively from a single Jupyter notebook.

- **[PuLP](https://github.com/coin-or/pulp)** — MILP modeling library, solved with the bundled
  CBC solver. This is the optimization engine.
- **[ortoolpy](https://pypi.org/project/ortoolpy/)** — convenience helpers (`addvars`,
  `addbinvars`) for bulk-declaring PuLP variables from a pandas index.
- **pandas / numpy** — all data wrangling; nearly every intermediate result is a DataFrame
  keyed by `date_duty` (row) and/or member ID (column).
- **openpyxl** — pandas' engine for reading `config/member.xlsx`
  (`script/helper.py::read_member`'s `pd.read_excel(...)` call), and used directly (not via
  pandas) by `script/drive_io.py::copy_excel_sheet`/`list_workbook_sheets` to duplicate a sheet
  within that workbook without disturbing its other sheets or that sheet's own formatting.
- **google-api-python-client / google-auth / google-auth-oauthlib** — Google Forms API (create/read the
  availability and replacement-request surveys), Google Drive API (create/manage the per-month
  folder the form lives in, **and the primary data store** — see [Data storage](#data-storage)),
  Google Calendar API (publish/diff the final schedule), Google Gmail API (**draft-only**, never
  sends — `script/form.py::prepare_form` drafts a notification email to active doctors each
  month via the `gmail.compose` scope, which is the narrowest scope Gmail offers for draft
  creation; the "never send" guarantee is enforced by this codebase simply never calling a
  send/`drafts.send` endpoint, not by the scope itself).
- **ipywidgets** — the GUI layer (`script/gui.py`): dropdowns/buttons/output panels wired to
  the pipeline functions below. Requires a live Jupyter kernel (`ipykernel`, `notebook`) to
  actually capture button clicks and stage output — building the widgets themselves works
  anywhere ipywidgets is importable, but the interactive parts don't.
- Standard library: `os`, `datetime`, `calendar`, `math.ceil`, `random`, `time.sleep`, `traceback`.

Pinned in `requirements.txt` (`pip install -r requirements.txt`) — versions this codebase is
developed and tested against (Python 3.8.13).

## Repo layout

| Path | What it is |
|---|---|
| `main.ipynb` | The single live entry point. An `ipywidgets` panel per stage, re-run every month; no code editing needed for a normal month. |
| `requirements.txt` | Pinned dependency lockfile (`pip install -r requirements.txt`). |
| `script/` | The Python package with all pipeline logic (see below). |
| `test/test01.py` … `test19.py` | Ad hoc, undocumented developer scratch scripts — not an automated test suite (no pytest/unittest, no assertions framework). |
| `README.md` | One paragraph: project purpose + CC BY-NC 4.0 license note. |
| `LICENSE` | Creative Commons Attribution-NonCommercial 4.0 license text. |
| `.gitignore` | Ignores `__pycache__`, `.vscode`, `.DS_Store`, and the local, non-versioned `config.local.json` + `config/` credentials directory. |
| `config.local.example.json` | Checked-in template for each machine's `config.local.json` (never committed itself) — holds only where that machine's OAuth credential files live. |
| `arch/` | **Excluded from this doc** — archived/obsolete per-season notebooks and old code. |
| `refs/` | **Excluded from this doc** — archived/obsolete reference material. |

All *runtime data* — the doctor roster and per-month generated CSVs — lives **outside this
repo**, in a `dutyshift` folder on **Google Drive**, accessed directly via the Drive API (see
[Data storage](#data-storage) below). There is no local file mirror and no per-machine path to
configure; nothing under it is checked into git.

## Pipeline walkthrough

`main.ipynb` is a single cell: it sets up an `AppState` and `display()`s one combined panel,
`script/gui.py::build_app(state)`, covering the whole monthly pipeline. That panel is common
parameters pinned on top, above a `Tab` with one tab per stage — so opening the notebook and
running its one cell is enough to see the entire workflow, rather than running 7 cells in
order. Cell output is cleared before commit, so the notebook file itself carries no historical
run output — only code. Every panel only wires widgets to the underlying `script/*.py` function
below it — none of the pipeline logic lives in `script/gui.py` itself; `build_app` and each
`build_*_panel` function can still be `display()`-ed individually (e.g. in a scratch cell) if
useful for debugging just one stage.

**Common parameters** (`build_common_params_panel`, pinned above the tabs): Year/Month
dropdowns plus Holiday/ECT-cancel multi-selects, the latter two rebuilt from
`calendar.monthrange` whenever year or month changes. These replace what used to be a
hand-edited `year_plan, month_plan, l_holiday = ...` tuple; a comment block preserving every
past month's tuple (back to 2024-06) is kept in the notebook cell above the GUI code purely as a
historical record — weekends are always holidays automatically regardless of the selection (see
[Data model](#data-model)). Populates the `AppState` (`state`) that every tab reads
`year_plan`/`month_plan`/`l_holiday`/`l_date_ect_cancel` from at click time, plus the one value
that genuinely flows between tabs in memory, `d_replace_checked` (see "5. Check Replace" →
"6. Apply Replace" below). `script/gui.py` itself does `from script.parameter import *` etc.,
loading the fixed, rarely-changing configuration (duty types, scoring weights, per-title duty
eligibility, Google resource IDs) from `script/parameter.py`.

**Tab "1. Create Form"** (`build_form_panel` → `script/form.py::prepare_form`): builds the
month's calendar and duty-slot structure, then creates (from a template) a Google Form asking
each doctor their availability, printing the form's response URL for distribution into the
tab's output area. Also, best-effort (a failure here doesn't fail the form creation itself):
copies forward next month's `dutyshift/config/member.xlsx` sheet from the nearest prior month
(`script/helper.py::ensure_member_sheet` — skips gaps, never overwrites an existing sheet) as a
starting point for that month's per-doctor parameter edits, then drafts (never sends) a
notification email to every active doctor via Gmail, using the response deadline entered in
this tab's date picker (auto-formatted `M/D(曜)` via `dict_jpnday`) and the template in
`script/parameter.py::str_email_template`.

**Tab "2. Collect"** (`build_collect_panel` → `script/collect.py::collect_availability`): reads
form responses plus the member roster, builds an availability matrix, flags doctors who haven't
responded or whose "designated physician" status doesn't match the roster, and prints any
free-text requests doctors left in the form.

**Tab "3. Assign"** (`build_assign_panel` → `script/assign.py`): the core stage. Solver-tuning
hyperparameters (weights for score-deviation penalties, closeness thresholds, objective-term
weights, `type_limit`, manual overrides/skips) are editable widgets grouped into a collapsed
"Advanced solver parameters" accordion, defaulting to the values that used to be hardcoded here
— see [Optimization engine](#optimization-engine). The "Run Optimization" button calls
`optimize_count_and_assign(...)`, which runs two chained MILP solves; expect a long output log
(the function itself prints ~40 progress lines, plus PuLP/CBC's own solver log).

**Tab "4. Notify"** (`build_notify_panel` → `script/notify.py::update_calendar`): diffs the new
schedule against existing events on the shared Google Calendar and adds/deletes/updates events
(one per duty per doctor), including substitute-candidate info and a link to the shift-swap
request form in each event's description.

**Tab "5. Check Replace"** (`build_replace_check_panel` →
`script/replace.py::check_replacement`): reads a second, separate Google Form used for
shift-swap requests, prints a proposed before → after diff, and stores the result on
`state.d_replace_checked` for the next tab.

**Tab "6. Apply Replace"** (`build_replace_apply_panel` →
`script/replace.py::replace_assignment`): re-applies the swap to the assignment tables and
regenerates the summary/score outputs, using `state.d_replace_checked` from the previous tab
(prints a friendly reminder instead of erroring if that tab hasn't been run yet).

### `script/` module map

| Module | Lines | Role |
|---|---|---|
| `script/parameter.py` | 125 | Fixed, rarely-edited config: duty type ↔ label maps, scoring weights, per-title duty eligibility, class_duty aggregation rules, Google Form/Calendar IDs, duty clock times. |
| `script/drive_io.py` | 485 | Google Drive-backed data I/O: OAuth credential caching/reuse (`get_credentials`, `get_services`, now also building a Gmail client), Drive folder resolution/creation (`resolve_folder_id`, `DriveFolderCache`, plus the moved-from-`helper.py` `check_gdrive_path`/`create_gdrive_path`/etc.), `read_csv`/`write_csv`/`read_excel`/`read_json`/`write_json`/`list_month_folders`, `list_workbook_sheets`/`copy_excel_sheet` (openpyxl-based, for duplicating a sheet within `member.xlsx`), `month_folder_path` (single source of truth for the `dutyshift/result/<year>/<month>/` layout), and `prep_drive_paths` (the `(p_root, p_month, p_data)` → Drive-folder-id replacement for the old local-path resolver `prep_dirs`). |
| `script/helper.py` | 923 | Shared building blocks: calendar construction (`prep_calendar`), roster loading/parsing (`read_member`, `prep_member2`, `split_lim`), `member_sheet_name`/`ensure_member_sheet` (copies next month's `member.xlsx` sheet forward from the nearest prior month), the count-optimization MILP (`optimize_count`), result extraction/scoring (`extract_assignment`, `extract_closeduty`, `convert_assignment`, `past_score`, `date_duty2class`) — all reading/writing via `script/drive_io.py`. |
| `script/assign.py` | 461 | The assignment MILP (`optimize_assign`) and the orchestration function that runs both optimization stages and handles infeasibility (`optimize_count_and_assign`). |
| `script/form.py` | 113 | `prepare_form` — builds the availability-survey Google Form for the month, ensures next month's `member.xlsx` sheet exists, and drafts a notification email to active doctors (never sent). |
| `script/collect.py` | 188 | `collect_availability` — parses Google Form responses into an availability matrix. |
| `script/notify.py` | 209 | Google Calendar integration: `update_calendar`, `add_duty`, `delete_duty`, `list_duty`, `compare_event`. |
| `script/replace.py` | 191 | Shift-swap flow: `check_replacement`, `replace_assignment`, and `_check_designation_pairing` (warns, doesn't block, if a swap breaks the day/night + on-call designated-physician pairing invariant). |
| `script/check.py` | 47 | Small sanity-check helpers: `check_availability_duty`, `check_availability_member`. No Drive I/O. |
| `script/gui.py` | 500 | `ipywidgets` GUI layer: `AppState` (also loads `config.local.json` once, as `state.config`), one `build_*_panel()` function per stage above, and `build_app()` combining them into the single panel `main.ipynb` displays (params on top, stages as `Tab`s). The Assign panel also handles solver-parameter preset save/load/auto-default (`_pack_solver_params`/`_apply_solver_params`/`_load_last_month_solver_params`). No pipeline logic of its own. |

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
target/hard-limit counts, (c) total closeness violations. Weights are set per-run via the
"Advanced solver parameters" widgets in the "3. Assign" tab (`script/gui.py::build_assign_panel`),
defaulting to `0.00001, 0.1, 0.00001`.

**Infeasibility recovery** — `optimize_count_and_assign` wraps both stages: if a solve comes
back `Infeasible`, it retries with hard limits relaxed to soft, then runs a randomized
elimination search to isolate and report which specific duty slots can't be filled under the
current constraints, in two phases:
1. **Reduction** — repeatedly sample a random 80% subset of the current suspect set to skip and
   re-solve. A successful (`Optimal`) solve narrows the suspects to that tested subset. An
   infeasible solve leaves the suspect set (and so the sample size) unchanged, so the next
   iteration tries a *differently-sampled* subset of the same size. Once
   `n_troubleshoot_infeasible_max` (`script/parameter.py`, default 10) differently-sampled
   subsets of the same size have all come back infeasible in a row — no progress narrowing the
   suspects — reduction stops and the remaining suspects move to phase 2.
2. **One-by-one testing** — each remaining suspected duty is tested individually (include vs.
   skip) to confirm whether it's genuinely unassignable, accumulating a final
   `l_date_duty_unassignable` list.

## External integrations

- **Google Forms** — one form per month for availability collection (cloned from a template,
  `id_template_form`), plus a separate standing form for shift-swap requests. Response parsing
  in `script/collect.py` matches on exact Japanese question-text substrings.
- **Google Drive** — creates/locates the per-month folder that houses each month's form **and**
  is the primary data store for the whole pipeline (see [Data storage](#data-storage)) — every
  CSV read/write goes through `script/drive_io.py`, not a local filesystem.
- **Google Calendar** — the final schedule is published as one event per duty per doctor
  (`id_calendar` in `parameter.py`); `update_calendar` diffs against existing events so re-runs
  only add/remove/update what changed.
- **Gmail** — `prepare_form` creates (never sends) one draft notification email per month, Bcc'd
  to every active doctor, via the `gmail.compose` scope (`SCOPE_DRIVE_FORMS_GMAIL` in
  `drive_io.py`, requested only by `prepare_form` — no other stage needs Gmail access).
- **OAuth credentials** — per-user `InstalledAppFlow`, via `script/drive_io.py::get_credentials`.
  Unlike the pre-migration code, an existing `token.json` is loaded and refreshed before falling
  back to a fresh interactive browser consent — a normal run doesn't need a browser at all once
  a token exists. Credential/token file *locations* come from each machine's local
  `config.local.json` (see [Data storage](#data-storage)); the credentials themselves are never
  synced to Drive or committed to git.

## Data storage

Nothing under the Drive `dutyshift` folder is in this git repo, and — since the migration off
Dropbox — there is no local file mirror of it either: every read/write goes through the Drive
API (`script/drive_io.py`), resolved **by name** from `root`, not by any per-machine path. This
is what eliminates the old `lp_root` hardcoded-machine-path-list problem outright rather than
relocating it: a Drive folder name resolves identically from every machine/account with access.

Layout: `dutyshift/config/member.xlsx` (roster — one sheet per month, `member_<yyyymm>`;
`script/helper.py::ensure_member_sheet` copies the nearest prior month's sheet forward as a
starting point whenever `prepare_form` runs and that month's sheet doesn't exist yet);
`dutyshift/result/<year>/<month, zero-padded>/`
(live per-month data, e.g. `dutyshift/result/2026/08/` — matching where `script/form.py` has
always created that month's Google Form, so the data and the form live side by side; this is
also literally where the operator's own Drive already had past months' data, so it's treated as
the canonical convention rather than something to normalize away); nested beneath it,
`.../result/<prefix>_<timestamp>/` (a snapshot of every pipeline run, prefixes `form_`, `clct_`,
`asgn_`, `rplc_` — the system's only audit trail); `dutyshift/result/replacement/replacement`
(the one standing, non-monthly shift-swap-request form — a sibling of the year folders under
`dutyshift/result/`, not itself year/month-specific).
`script/drive_io.py::month_folder_path(year, month)` is the single source of truth for the
`dutyshift/result/<year>/<month>/` shape — `list_month_folders` walks that two-level hierarchy
(explicitly skipping non-year siblings like `replacement`) to enumerate past months for
cumulative scoring (`past_score`) and month-boundary continuity (`prep_assign_previous`).

Representative files per month: `calendar.csv`, `date_duty.csv`, `assign_manual.csv`,
`member.csv`, `lim_hard.csv`/`lim_soft.csv`/`lim_exact.csv`, `availability.csv`,
`availability_ratio.csv`, `info.csv`, `assign_date_duty.csv`, `assign.csv`,
`assign_print.csv` (the human-readable roster with Japanese columns: 日付, 午前日直, 午後日直,
当直, 日直OC, 当直OC, ECT), `deviation.csv`/`deviation_summary.csv`, `score_current.csv`,
`score_total.csv`, `closeduty.csv`.

**Local, per-machine config**: `config.local.json` (gitignored; `config.local.example.json` is
the checked-in template) holds only `credentials_path`/`token_path` — where *that machine's*
OAuth credential files live. `AppState()` (`script/gui.py`) loads it once via
`drive_io.load_config()`, failing fast and visibly if it's missing, rather than deep inside a
button click. Every pipeline entry point (`prepare_form`, `collect_availability`,
`optimize_count_and_assign`, `update_calendar`, `check_replacement`, `replace_assignment`) takes
this loaded config as its first argument, replacing the old `lp_root` parameter.

## Operational cadence

The notebook is re-run once per month. Historically, git history was dominated by small commits
— often literally titled `param` — that appended one new `(year_plan, month_plan, l_holiday)`
tuple to the growing commented-out history block in `main.ipynb` cell 0; since year/month/
holidays are now set via the GUI's dropdowns rather than editing that tuple, a normal month no
longer requires a code commit at all. Prior to the current consolidated design, each irregular
scheduling period (New Year, Golden Week, summer/winter vacation weeks) had its own
self-contained notebook; these are now archived under `arch/` once their period has passed, and
are out of scope for this document.

## Known issues / improvement ideas

These are observations from reading the code, offered as a starting point for discussion — not
a judgment of the project.

- **~~Hardcoded, machine-specific paths~~ (resolved).** Data storage moved from a
  Dropbox-synced local folder (resolved by guessing which of a hardcoded `lp_root` list of
  personal machine paths existed) to direct Google Drive API access (`script/drive_io.py`),
  resolved by folder *name*, not path — identical from every machine/account with access. The
  one remaining machine-specific value (local OAuth credential file locations) lives in each
  machine's own gitignored `config.local.json`, never in versioned source. `prep_dirs`'s second,
  separate hardcoded assumption (`<p_root>/GitHub/dutyshift` as the repo checkout location, plus
  a process-wide `os.chdir`) is also gone — nothing needs it once there's no local data path to
  resolve.
- **~~Monthly params accumulate as dead code~~ (resolved).** Year/month/holidays are now set via
  dropdowns/multi-selects (`script/gui.py::build_common_params_panel`) instead of editing a
  Python tuple each month; the old commented-out per-month history block is kept in cell 0
  purely as an inert historical record, not something that grows via further hand-edits.
- **~~Ad hoc solver-tuning presets~~ (resolved).** The "3. Assign" tab's solver hyperparameters
  (`dict_c_diff_score_current`/`_total`, `dict_closeduty` thresholds, objective weights,
  `type_limit`, fulltime/skip overrides) are editable widgets that now persist through
  `script/drive_io.py`'s `read_json`/`write_json`:
  - **Named presets** — "Save as Preset"/"Load Preset" read and write
    `dutyshift/config/solver_presets.json` (`{"<name>": {...params...}}`).
  - **Per-month audit record** — every successful "Run Optimization" writes the exact values
    used to `dutyshift/result/<year>/<month>/solver_params.json`, closing the "what was actually
    used for a past month" gap.
  - **Auto-loaded defaults** — the panel seeds its widgets from the nearest prior month's
    recorded `solver_params.json` on build (falling back to the original hardcoded defaults if
    none exists), rather than always resetting to hardcoded values; a "Load Last Month's Config"
    button re-triggers the same lookup on demand. This auto-load is the *first* Drive API call
    `build_app()` makes (previously, opening the notebook was instant/offline until the first
    button click) — it's wrapped in a broad `try/except` and fails silently to the hardcoded
    defaults, so a missing-credentials or network problem at notebook-open time can't prevent
    the panel from rendering.
- **~~Stale duplicate function~~ (resolved).** `script/assign.py` no longer contains
  `optimize_count_and_assign_old` — it was an unused, ~370-line near-copy of
  `optimize_count_and_assign`, left uncallable (referencing the removed `prep_dirs`) after the
  Drive migration, and has now been deleted outright. The live function still has one open
  `# TODO: equilize 3 continous holidays assignment count` (`script/assign.py:296`).
- **~~Incomplete replacement/swap logic~~ (resolved).** `script/replace.py` had two open TODOs,
  turned out to be very different in nature on investigation: the `d_assign.to_csv(...)` one was
  **stale** — `d_assign` wasn't even defined at that point in the function, and the real
  `d_assign` matrix was already being correctly rebuilt and saved later via `convert_assignment`
  — so that dead comment/line was simply deleted. The designated-physician one was real:
  `script/assign.py::optimize_assign` enforces exactly one designated physician (`指定医`)
  covering each day/night duty between the primary doctor and its on-call pair
  (`ocday`/`ocnight`), and a swap could silently break that. `_check_designation_pairing`
  (`script/replace.py`) now detects this — including the nuance that an on-call slot with
  nobody assigned is itself a normal, valid state (only needed when the day/night doctor isn't
  designated) that must be treated as "not designated," not skipped — and prints a warning in
  both `check_replacement`'s review step and `replace_assignment` before applying. It warns,
  doesn't block: this subsystem is human-reviewed before a swap is ever applied, so surfacing
  the problem is the goal, not overriding the admin's decision.
- **Fragile Google Form parsing.** `script/collect.py` matches form questions by exact Japanese
  substring (e.g. `'[' + title_dateduty + ']'`, `'指定医'`, `'月2回'`, `'ご要望'`). Any wording
  change to the form template silently breaks parsing; the only feedback is a printed
  "missing member" list, no structured error handling.
- **No automated test suite.** `test/test01.py` … `test19.py` are 19 undocumented, ad hoc
  developer scripts (early PuLP prototypes, one-off data-migration patches, Google API
  experiments) — not a pytest/unittest suite, no assertions, no CI. The optimizer's correctness
  has no automated coverage.
- **~~No dependency lockfile~~ (resolved).** `requirements.txt` now pins every direct dependency
  (`pulp`, `ortoolpy`, `pandas`, `numpy`, `openpyxl`, `google-api-python-client`, `google-auth`,
  `google-auth-oauthlib`, `ipywidgets`, `ipython`, `ipykernel`, `notebook`) to the exact versions
  this codebase is developed and tested against — including `openpyxl`, which is never imported
  by name but is pandas' engine for reading `config/member.xlsx`, and the Jupyter runtime pieces
  (`ipykernel`/`notebook`) needed to actually *run* `script/gui.py`'s widgets interactively, not
  just import them. Re-pin deliberately (e.g. after verifying a version bump still works), don't
  let installs silently drift.
- **Duplicated logic between the main pipeline and archived seasonal notebooks.** The
  now-archived per-season notebooks (summer/winter vacation assignment, etc.) reimplement their
  own inline PuLP model and their own result-extraction/CSV-saving/printing boilerplate rather
  than reusing `script/assign.py`/`script/helper.py::convert_assignment` — a structurally
  similar problem solved twice with diverging conventions.
