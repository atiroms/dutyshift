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
application — there's no server or database. The UI is a `PyQt5` desktop window (one panel per
stage) plus Google's own UIs (Forms, Calendar).

## Tech stack

Pure Python, driven interactively from a `PyQt5` desktop app.

- **[PuLP](https://github.com/coin-or/pulp)** — MILP modeling library, solved with the bundled
  CBC solver. This is the optimization engine.
- **[ortoolpy](https://pypi.org/project/ortoolpy/)** — convenience helpers (`addvars`,
  `addbinvars`) for bulk-declaring PuLP variables from a pandas index.
- **pandas / numpy** — all data wrangling; nearly every intermediate result is a DataFrame
  keyed by `date_duty` (row) and/or member ID (column).
- **google-api-python-client / google-auth / google-auth-oauthlib** — Google Forms API (create/read the
  availability and replacement-request surveys), Google Drive API (create/manage the per-month
  folder the form lives in, **and the primary data store** — see [Data storage](#data-storage)),
  Google Calendar API (publish/diff the final schedule), Google Sheets API (read `config/member`,
  a native Google Sheet with one tab per month — `script/helper.py::read_member`'s
  `spreadsheets.values.get` call — and duplicate a tab within it without disturbing its other
  tabs or that tab's own formatting, via `script/drive_io.py::read_gsheet`/`copy_gsheet_tab`/
  `list_gsheet_tabs`; no scope of its own, the broad Drive scope both other scope bundles already
  request covers Sheets API calls too), Google Gmail API (**draft-only**, never
  sends — `script/form.py::prepare_form` drafts a notification email to active doctors each
  month via the `gmail.compose` scope, which is the narrowest scope Gmail offers for draft
  creation; the "never send" guarantee is enforced by this codebase simply never calling a
  send/`drafts.send` endpoint, not by the scope itself).
- **PyQt5** — the GUI layer (`script/gui.py`): dropdowns/buttons/output panels wired to the
  pipeline functions below, a plain desktop app with no notebook/kernel involved. Every pipeline
  call (Google API round-trips, the MILP solve) can take a while, so each button click runs its
  work on a background `QThread` (`_Worker`/`_run_async`) instead of the GUI thread — Qt widgets
  may only be touched from the thread that owns them, so anything a worker needs from a widget
  is captured into a plain value before dispatch, and anything its result needs to write back to
  a widget happens in an `on_success` callback marshaled back onto the GUI thread.
- **[jpholiday](https://pypi.org/project/jpholiday/)** — Japanese national-holiday lookup, used
  only to default the "1. Create Form" tab's Holidays calendar to that month's official holidays;
  pinned to `0.1.10`, since `jpholiday>=1.0` requires Python 3.9+ and breaks import on this
  codebase's pinned Python 3.8.13.
- Standard library: `os`, `datetime`, `calendar`, `math.ceil`, `random`, `time.sleep`, `traceback`.

Pinned in `requirements.txt` (`pip install -r requirements.txt`) — versions this codebase is
developed and tested against (Python 3.8.13).

## Repo layout

| Path | What it is |
|---|---|
| `main.py` | The live entry point (`python main.py`). Opens a `PyQt5` window with one panel per stage, re-run every month; no code editing needed for a normal month. |
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

`python main.py` opens a `PyQt5` window directly (`script/gui.py::AppState` + `build_app(state)`,
no notebook/kernel involved), covering the whole monthly pipeline. That window is common
parameters pinned on top, above a `Tab` with one tab per stage — so running `main.py` is enough
to see the entire workflow, rather than running 7 cells in order. Every panel only wires widgets
to the underlying `script/*.py` function below it — none of the pipeline logic lives in
`script/gui.py` itself; `build_app` and each `build_*_panel` function return a plain `QWidget`
and can still be embedded/shown individually (e.g. from a scratch script) if useful for
debugging just one stage.

**Common parameters** (`build_common_params_panel`, pinned above the tabs): just the Year/Month
dropdowns — the only inputs every stage actually shares. These replace what used to be a
hand-edited `year_plan, month_plan, l_holiday = ...` tuple (past months' tuples, back to
2024-06, are recoverable from git history if ever needed, e.g. `git log -p -- main.ipynb`).
Populates the `AppState` (`state`) that every tab reads `year_plan`/`month_plan` from at click
time, plus the one value that genuinely flows between steps in memory, `d_replace_checked` (see
"5. Replace" below).

**Tab "1. Create Form"** (`build_form_panel` → `script/form.py::prepare_form`): builds the
month's calendar and duty-slot structure, then creates (from a template) a Google Form asking
each doctor their availability, printing the form's response URL for distribution into the
tab's output area (which also shows each stage's progress, e.g. `[1/4] Preparing calendar...`,
ending `Done`). Holidays and ECT-cancel dates — only ever used by this stage — are picked here as
two week-per-row calendar grids (`script/gui.py::_CalendarSelector`), Sunday-first with
Sunday/Saturday tinted red/blue; Holidays defaults to that month's official Japanese holidays
(`jpholiday`), with weekend cells locked on (weekends are always holidays automatically
regardless of this selection — see [Data model](#data-model)), both grids rebuilding whenever
year/month changes. The Google Form template to clone (`id_template_form`) and that template's
grid-question item IDs (`dict_itemid_form`) are read fresh from Drive on every click
(`dutyshift/config/config.json`, via `script/helper.py::load_drive_config` — see [Data
storage](#data-storage)), not hardcoded. The response deadline (a required date picker,
auto-formatted `M/D(曜)` via `dict_jpnday`) is used for the notification email drafted here
(never sent; wording read fresh from `dutyshift/template/announce.json`, via
`script/helper.py::load_email_template`) — copying forward next month's `dutyshift/config/member`
tab from the nearest prior month (`script/helper.py::ensure_member_sheet` — skips gaps, never
overwrites an existing tab) is a separate, independently best-effort step — and is also persisted
to Drive (`dutyshift/result/<year>/<month>/deadline.json` via `script/gui.py::_save_deadline`) so
"2. Collect" can reuse it automatically.

**Tab "2. Collect"** (`build_collect_panel` → `script/collect.py::collect_availability`): reads
form responses plus the member roster, builds an availability matrix, flags doctors who haven't
responded or whose "designated physician" status doesn't match the roster, and prints any
free-text requests doctors left in the form. Drafts (never sends) a reminder email Bcc'd to
not-yet-answered doctors automatically — no separate opt-in checkbox — reusing the deadline saved
by "1. Create Form" (`script/gui.py::_load_deadline`) and wording read fresh from
`dutyshift/template/reminder.json`; it's a no-op once everyone has answered.

**Tab "3. Assign"** (`build_assign_panel` → `script/assign.py`): the core stage. Solver-tuning
hyperparameters (weights for score-deviation penalties, closeness thresholds, objective-term
weights, `type_limit`, manual overrides/skips) are editable widgets grouped into a collapsed
"Advanced solver parameters" accordion, defaulting to the values that used to be hardcoded here
— see [Optimization engine](#optimization-engine). The "Run Optimization" button calls
`optimize_count_and_assign(...)`, which runs two chained MILP solves; expect a long output log
(the function itself prints ~40 progress lines, plus PuLP/CBC's own solver log).

**Tab "4. Notify"** stacks four steps, top to bottom:
- **Create Assignment Sheet** (→ `script/notify.py::create_assignment_sheet`): writes the
  human-readable "調整結果" Google Sheet (a `ver.<today>` roster tab plus a `score` tab) for the
  month.
- **Draft Drop-in Notification** (→ `script/notify.py::draft_dropin_notification`): drafts
  (never sends) an email to active doctors linking to that assignment sheet, for a last look
  while the roster is still a work-in-progress draft — i.e. any time after the step above and
  before Publish to Calendar below. Wording read fresh from `dutyshift/template/dropin.json`.
- **Publish to Calendar** (→ `script/notify.py::update_calendar`): diffs the new schedule
  against existing events on the shared Google Calendar (`id_calendar`, read fresh from
  `dutyshift/config/config.json`) and adds/deletes/updates events (one per duty per doctor),
  including substitute-candidate info and a link to the shift-swap request form in each event's
  description.
- **Draft Fixed Notification** (→ `script/notify.py::draft_fixed_notification`): drafts (never
  sends) an email announcing the finalized roster, Bcc'd to active doctors plus any extra
  recipients configured in `dutyshift/config/config.json`'s `l_email_extra_fixed` (e.g.
  secretaries who never fill in the availability form). Wording read fresh from
  `dutyshift/template/fixed.json`.

**Tab "5. Replace"** (`build_replace_panel`) holds both former "check" and "apply" steps
stacked in one panel, each with its own button/status/output, since applying a swap always needs
a specific check's result read and accepted first:
- **Check** (→ `script/replace.py::check_replacement`): reads a second, separate Google Form
  used for shift-swap requests, prints a proposed before → after diff, and stores the result on
  `state.d_replace_checked` for the Apply step below.
- **Apply** (→ `script/replace.py::replace_assignment`): re-applies the swap to the assignment
  tables and regenerates the summary/score outputs, using `state.d_replace_checked` from the
  Check step above (prints a friendly reminder instead of erroring if Check hasn't been run
  yet).

Every tab's action button is paired with a small Running/Done/Failed status pill
(`script/gui.py::_make_status_label` / `_run_async(..., status=...)`) as a quick-glance
complement to the detailed stage-by-stage log each pipeline function prints into that tab's
output box.

### `script/` module map

| Module | Lines | Role |
|---|---|---|
| `script/parameter.py` | 113 | Fixed, rarely-edited **base data only** — no precomputed derived views: `dict_duty_info` (duty master table), `dict_score_duty`, `dict_title_duty`, `dict_class_duty`, `dict_score_classes` (score axis -> list of class_duty names), plus scalars like `l_day_ect`/`ll_avoid_adjacent`/`l_title_fulltime`/`str_email_button_html`. Every derived shape of this data (duty sort order, Japanese labels, the class_duty name list, the class_duty score-weight table) is computed on demand by `script/helper.py` functions, called right where each is needed rather than imported as an already-derived global — see that row below. Google Form/Calendar IDs and every notification email's wording no longer live here either — see `script/helper.py::load_drive_config`/`load_email_template` below and [Data storage](#data-storage). |
| `script/drive_io.py` | 613 | Google Drive-backed data I/O: OAuth credential caching/reuse (`get_credentials`, `get_services`, now also building Gmail and Sheets clients), Drive folder resolution/creation (`resolve_folder_id`, `DriveFolderCache`, plus the moved-from-`helper.py` `check_gdrive_path`/`create_gdrive_path`/etc.), `read_csv`/`write_csv`/`read_gsheet`/`read_json`/`write_json`/`get_file_web_link`/`list_month_folders`, `list_gsheet_tabs`/`copy_gsheet_tab` (Sheets-API-based, for duplicating a tab within the native Google Sheet `member`), `month_folder_path` (single source of truth for the `dutyshift/result/<year>/<month>/` layout), and `prep_drive_paths` (the `(p_root, p_month, p_data)` → Drive-folder-id replacement for the old local-path resolver `prep_dirs`). |
| `script/helper.py` | 1236 | Shared building blocks: `script/parameter.py` base-table derivers (`duty_order`, `duty_jpn_labels`, `duty_time_table`, `class_duty_names`, `score_class_table`/`derive_score_class_constants`), calendar construction (`prep_calendar`), roster loading/parsing (`read_member`, `prep_member2`, `split_lim`), `member_sheet_name`/`ensure_member_sheet` (copies next month's `member` tab forward from the nearest prior month), `load_drive_config`/`load_email_template` (read `dutyshift/config/config.json`/`dutyshift/template/<name>.json` fresh on every call, seeding each with this codebase's original hardcoded content the first time it's read), the count-optimization MILP (`optimize_count`), result extraction/scoring (`extract_assignment`, `extract_closeduty`, `convert_assignment`, `past_score`, `date_duty2class`) — all reading/writing via `script/drive_io.py`. |
| `script/assign.py` | 486 | The assignment MILP (`optimize_assign`) and the orchestration function that runs both optimization stages and handles infeasibility (`optimize_count_and_assign`). |
| `script/form.py` | 139 | `prepare_form` — builds the availability-survey Google Form for the month (template ID/item IDs read from Drive config), ensures next month's `member` tab exists, and drafts a notification email to active doctors (never sent, wording read from Drive). |
| `script/collect.py` | 225 | `collect_availability` — parses Google Form responses into an availability matrix. |
| `script/notify.py` | 465 | Google Calendar/notification integration: `create_assignment_sheet`, `draft_dropin_notification`, `update_calendar` (target calendar ID read from Drive config), `draft_fixed_notification`, plus `add_duty`, `delete_duty`, `list_duty`, `compare_event`. |
| `script/replace.py` | 190 | Shift-swap flow: `check_replacement`, `replace_assignment`, and `_check_designation_pairing` (warns, doesn't block, if a swap breaks the day/night + on-call designated-physician pairing invariant). |
| `script/check.py` | 46 | Small sanity-check helpers: `check_availability_duty`, `check_availability_member`. No Drive I/O. |
| `script/gui.py` | 1146 | `PyQt5` GUI layer: `AppState` (also loads `config.local.json` once, as `state.config`), the `_Worker`/`_run_async` background-`QThread` machinery every button click runs through (with an optional Running/Done/Failed status pill), `_CalendarSelector` (the week-per-row Holidays/ECT-cancel day picker), one `build_*_panel()` function per stage above (5 tabs; "5. Replace" covers both check and apply), and `build_app()` combining them into the single window `main.py` shows (Year/Month on top, stages as `Tab`s). The Assign panel also handles solver-parameter preset save/load/auto-default (`_pack_solver_params`/`_apply_solver_params`/`_load_last_month_solver_params`). No pipeline logic of its own. |

## Data model

**Doctor / member** — one row per doctor in `member` (a native Google Sheet with one tab per
year-month, e.g. `member_202608`). Key columns (parsed by `read_member`/`prep_member2`):
`id_member`, `name_jpn`, `title_short` (rank: `assoc` / `instr` / `assist_leader` /
`assist_subleader` / `limtermclin` / `stud`), `designation` (flags "指定医", a senior/designated
physician), `team`, `ect_leader`, `ect_subleader`, `active`, plus one column per `class_duty`
holding a limit spec string parsed by `split_lim`:
- `"3"` — exact count required
- `"2-4"` — hard range
- `"2(1-3)"` — soft target of 2, with a hard range of 1–3
- `"-"` — unconstrained

**Duty types** (`dict_duty_info` in `script/parameter.py`, base data only): `am`, `pm`, `day`,
`ocday`, `night`, `emnight`, `ocnight`, `ect`, each with a sort order, Japanese label, and
start/end clock time. `script/parameter.py` holds no precomputed derived view of this table —
whichever function needs one calls `script/helper.py::duty_order` (duty→order),
`duty_jpn_labels` (duty→Japanese label, excludes `ect` by default since it has no dedicated Form
question), or `duty_time_table` (the full `{duty, duty_jpn, start, end}` table, e.g. night runs
17:15 → 32:30, i.e. 08:30 the *next* day) right where it's used, rather than importing an
already-derived global.

**`date_duty`** — the universal index used throughout the codebase: a string key
`"<day-of-month>_<duty>"` (e.g. `"14_night"`). It's the row index of the availability matrix,
the assignment matrix, and most PuLP decision variables.

**`class_duty`** — an aggregation layer above raw duty types, used for counting and limit
enforcement (e.g. `ampm`, `daynight_tot`, `night_wd`, `night_em`, `daynight_hd`, `oc_tot`,
`oc_day`, `oc_night`, `ect`). Defined via `dict_class_duty` in `parameter.py` (base data), which
maps each class to a set of `(duty, weekday/holiday qualifier)` pairs; the unique, order-preserving
list of class_duty names (used to live as the precomputed `l_class_duty` global) is derived on
demand via `script/helper.py::class_duty_names(dict_class_duty)`.

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
hard min/max range parsed from their `member` limit string.

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
  `id_template_form`, read fresh from Drive config — see [Data storage](#data-storage)), plus a
  separate standing form for shift-swap requests. Response parsing in `script/collect.py`
  matches on exact Japanese question-text substrings.
- **Google Drive** — creates/locates the per-month folder that houses each month's form **and**
  is the primary data store for the whole pipeline (see [Data storage](#data-storage)) — every
  CSV read/write goes through `script/drive_io.py`, not a local filesystem.
- **Google Calendar** — the final schedule is published as one event per duty per doctor
  (`id_calendar`, read fresh from Drive config on every "Publish to Calendar" click);
  `update_calendar` diffs against existing events so re-runs only add/remove/update what changed.
- **Gmail** — every draft-only notification email (`prepare_form`'s initial announcement,
  `collect_availability`'s reminder, and "4. Notify"'s `draft_dropin_notification`/
  `draft_fixed_notification`) is created, never sent, via the `gmail.compose` scope
  (`SCOPE_DRIVE_FORMS_GMAIL` for the first two, `SCOPE_DRIVE_GMAIL` — no Forms/Calendar scope —
  for the notify.py pair, both in `drive_io.py`; no other stage needs Gmail access).
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

Layout: `dutyshift/config/member` (roster — a native Google Sheet, one tab per month,
`member_<yyyymm>`; `script/helper.py::ensure_member_sheet` copies the nearest prior month's tab
forward as a starting point whenever `prepare_form` runs and that month's tab doesn't exist yet);
`dutyshift/config/config.json` (`id_template_form`, `dict_itemid_form`, `id_calendar`,
`l_email_extra_fixed` — moved off `script/parameter.py` so an admin can edit them without a code
change; `script/helper.py::load_drive_config` reads this fresh on every call and seeds it with
this codebase's original hardcoded values the first time it's read, so an existing installation
keeps working with no manual migration step); `dutyshift/template/<name>.json` (one file per
notification email — `announce`, `reminder`, `dropin`, `fixed` — each `{subject, body,
button_label}`, `body`/`subject` being `str.format()` templates; `script/helper.py::
load_email_template` reads/seeds these the same way); `dutyshift/config/solver_presets.json`
(named "3. Assign" hyperparameter presets); `dutyshift/result/<year>/<month, zero-padded>/`
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

### CSV conventions: where member IDs and `date_duty` live

Every stage hands data to the next one purely through these Drive CSVs, resolved by filename
within the shared month folder — there's no in-memory object passed between separate pipeline
runs. That makes the CSV schema the real interface between stages, so keeping `id_member`/
`date_duty` placement (index vs. plain column) consistent across files matters more than it
would in a codebase that could pass DataFrames directly. Three shapes cover essentially every
file:

- **`date_duty` × member wide matrices** — `availability.csv`, `assign.csv`. Row index is
  `date_duty` (a duty slot is the natural unit here — exactly one member gets assigned per row),
  columns are member IDs. CSV headers always round-trip as strings, so these two files are read
  through `script/drive_io.py::read_member_matrix_csv` — the single place that restores column
  labels to `int` — rather than each call site casting by hand (that used to be done ad hoc: one
  call site cast, others didn't, which meant a pandas `.loc[date_duty, id_member] = ...`
  assignment with a still-`str` column would silently *add a new column* instead of matching the
  existing one — `script/helper.py::convert_assignment`'s member-availability lookups depend on
  this).
- **`date_duty`-per-row "long" tables** — `assign_manual.csv`, `assign_date_duty.csv`,
  `closeduty.csv`. One row per duty slot, `id_member` an ordinary (nullable) column. This is the
  most robust of the three shapes precisely because it never relies on either axis being an
  index; `assign_date_duty.csv` in particular is the row-level source both the wide matrix
  (`assign.csv`) and the member-per-row tables below are derived from.
- **member-per-row tables** — `lim_hard.csv`/`lim_soft.csv`/`lim_exact.csv`, `grp_score.csv`,
  `score_past.csv`, `score_current.csv`/`score_total.csv`,
  `score_current_plan.csv`/`score_total_plan.csv`, `assign_member.csv`, `deviation.csv`/
  `deviation_summary.csv`, `availability_member.csv`. `id_member` is always an explicit column on
  disk, never the CSV's own row index — a plain pandas index survives a Drive round-trip far less
  reliably than a real column (dtype drift, no name, easy to read back with the wrong
  `index_col`). Several of these (the `lim_*`/`grp_score`/`score_*` family) are still built as a
  member-*indexed* DataFrame in memory, because that's the shape `ortoolpy.addvars` needs to
  declare one PuLP decision variable per member — they're only flattened to a plain `id_member`
  column at the moment they're written (`d_lim_hard.rename_axis('id_member').reset_index()`
  pattern in `script/helper.py::prep_member2` / `script/assign.py::optimize_count_and_assign`),
  and restored with `.set_index('id_member')` wherever a later read needs the member-indexed
  shape back (e.g. `script/replace.py::replace_assignment`). The solver logic itself never
  changed — only the Drive read/write boundary did.
- **Presentation-only files** — `assign_print.csv` (Japanese columns, names embedded as text, no
  `id_member` at all), `availability_duty.csv` (comma-joined name/email strings per `date_duty`).
  Not really part of the machine-readable interface; nothing reads these back.
- **Duty-count Series** — `cnt_duty.csv`/`cnt_class_duty.csv` are plain pandas `Series` keyed by
  duty type / `class_duty` name (not by member), saved with `index=True` so that label survives
  — the one place a bare pandas index actually is the right on-disk representation, since the
  label *is* the data here, not something reconstructable from another column.
- **`member.csv`** has exactly one writer, `collect_availability`
  (`script/collect.py`) — every other stage only reads it. It used to also be written by
  `script/helper.py::prep_member2` (with different columns and `index=True`, since that function
  builds its own trimmed, actively-used member subset), so which write "won" depended on run
  order; consolidating to one writer removed that.
- `script/assign.py::optimize_count_and_assign`'s own `write_csv` calls (as opposed to ones
  inside helpers it calls) are now all deferred to a single block, gated on the two-stage solve
  having actually succeeded (`LpStatus == 'Optimal'`). Stage 1's audit outputs
  (`lim_exact.csv`/`score_current_plan.csv`/`score_total_plan.csv`) used to be saved immediately
  after Stage 1 finished, before Stage 2 had even run — a vestige of when count-optimization and
  assignment were separate, independently-run/saved steps — so a Stage 2 failure (including one
  the infeasibility-troubleshooting search couldn't recover from) could still leave Stage 1's
  outputs on Drive despite the run failing overall.

**Local, per-machine config**: `config.local.json` (gitignored; `config.local.example.json` is
the checked-in template) holds only `credentials_path`/`token_path` — where *that machine's*
OAuth credential files live. `AppState()` (`script/gui.py`) loads it once via
`drive_io.load_config()`, failing fast and visibly if it's missing, rather than deep inside a
button click. Every pipeline entry point (`prepare_form`, `collect_availability`,
`optimize_count_and_assign`, `create_assignment_sheet`, `draft_dropin_notification`,
`update_calendar`, `draft_fixed_notification`, `check_replacement`, `replace_assignment`) takes
this loaded config as its first argument, replacing the old `lp_root` parameter -- distinct from
the Drive-hosted `dutyshift/config/config.json` above (same name, different thing: this one is
the local machine's own `config.local.json`).

## Operational cadence

`main.py` is re-run once per month. Historically, git history was dominated by small commits —
often literally titled `param` — that appended one new `(year_plan, month_plan, l_holiday)`
tuple to a growing commented-out history block in what was then `main.ipynb`'s cell 0; since
year/month/holidays are now set via the GUI's dropdowns rather than editing that tuple, a normal
month no longer requires a code commit at all. Prior to the current consolidated design, each
irregular scheduling period (New Year, Golden Week, summer/winter vacation weeks) had its own
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
- **~~Monthly params accumulate as dead code~~ (resolved).** Year/month are now set via
  dropdowns (`script/gui.py::build_common_params_panel`) and holidays/ECT-cancel via
  week-per-row calendar grids on the "1. Create Form" tab (`script/gui.py::_CalendarSelector`)
  instead of editing a Python tuple each month; the old commented-out per-month history block no
  longer exists in the live app at all (past months' tuples, back to 2024-06, are recoverable
  from git history if ever needed, e.g. `git log -p -- main.ipynb`) — nothing grows via further
  hand-edits.
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
    `build_app()` makes (previously, opening the window was instant/offline until the first
    button click) — it's wrapped in a broad `try/except` and fails silently to the hardcoded
    defaults, so a missing-credentials or network problem at window-open time can't prevent the
    panel from rendering.
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
  (`pulp`, `ortoolpy`, `pandas`, `numpy`, `google-api-python-client`, `google-auth`,
  `google-auth-oauthlib`, `PyQt5`, `jpholiday`) to the exact versions this codebase is developed
  and tested against. Re-pin deliberately (e.g. after verifying a version bump still works),
  don't let installs silently drift.
- **Duplicated logic between the main pipeline and archived seasonal notebooks.** The
  now-archived per-season notebooks (summer/winter vacation assignment, etc.) reimplement their
  own inline PuLP model and their own result-extraction/CSV-saving/printing boilerplate rather
  than reusing `script/assign.py`/`script/helper.py::convert_assignment` — a structurally
  similar problem solved twice with diverging conventions.
