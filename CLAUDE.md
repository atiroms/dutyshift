# CLAUDE.md

Guidance for Claude Code when working in this repository.

## What this project is

`dutyshift` automates the monthly build of an on-call duty roster for hospital doctors: it
creates a Google Form to collect doctor availability, solves a two-stage mixed-integer linear
program (PuLP/CBC) to decide who works which shift, publishes the result to a shared Google
Calendar, and handles post-publication shift-swap requests. It's operated once a month via
`python main.py`, not a deployed service; that entry point opens a `PyQt5` desktop window with
one combined panel — common parameters on top, one `Tab` per pipeline stage below — rather than
hand-edited code across multiple cells.

For a full deep-dive (data model, MILP formulation, module-by-module walkthrough, known issues),
see [docs/PROJECT_OVERVIEW.md](docs/PROJECT_OVERVIEW.md).

## Scope: ignore `arch/`, `refs/`, and `test/`

`arch/` and `refs/` contain archived, obsolete notebooks and reference material (old per-season
scheduling notebooks, superseded docs). `test/` (`test01.py` … `test19.py`) is 19 undocumented,
ad hoc developer scratch scripts, not a maintained automated test suite (see Testing below). Do
not read, edit, or base new work on files in these directories unless the user explicitly asks
about archived history or these scripts specifically — a refactor elsewhere in `script/` is not
expected to keep `test/` in sync.

## Tech stack

Pure Python. Dependencies are pinned in `requirements.txt` (`pip install -r requirements.txt`)
— pinned to the versions this codebase is developed and tested against (Python 3.8.13); re-pin
deliberately, don't let installs silently drift. Core libraries actually imported by the code:
- `pulp`, `ortoolpy` — the MILP optimizer (PuLP modeling + CBC solver)
- `jpholiday` — Japanese national-holiday lookup, used only to default the "1. Create Form"
  tab's Holidays calendar. Pinned to `0.1.10` (not the current `1.0.x` line, which requires
  Python 3.9+ and breaks import on this codebase's pinned Python 3.8.13).
- `pandas`, `numpy` — all data handling
- `google-api-python-client`, `google-auth-oauthlib` — Google Forms/Drive/Calendar/Sheets/Gmail
  APIs. Drive is also the **data store**: doctor roster, per-month CSVs, and the Google Form
  itself all live in a `dutyshift` Drive folder, accessed directly via the API
  (`script/drive_io.py`) — there is no local file mirror. Sheets is used to read the doctor
  roster `config/member` (a native Google Sheet with one tab per month) and to duplicate a tab
  within it without disturbing its other tabs/formatting (`script/drive_io.py::read_gsheet`/
  `copy_gsheet_tab`). Gmail is used only to create **drafts** (never sent) of the pipeline's four
  notification emails — see `script/form.py::prepare_form`, `script/collect.py::
  collect_availability`, and `script/notify.py::draft_dropin_notification`/
  `draft_fixed_notification`.
- `PyQt5` — the GUI layer (`script/gui.py`), a plain desktop app with no notebook/kernel
  involved. Every pipeline call (Google API round-trips, the MILP solve) can take a while, so
  each button click runs its work on a background `QThread` (`_Worker`/`_run_async` in
  `script/gui.py`) instead of the GUI thread; anything a worker needs from a widget is captured
  into a plain value *before* dispatch, and anything its result needs to write back to a widget
  happens in an `on_success` callback marshaled back onto the GUI thread — Qt widgets may only
  be touched from the thread that owns them.

## How it runs

`main.py` is the entry point: `python main.py` opens the `PyQt5` window directly (`script/gui.py::AppState` + `build_app(state)`), no notebook/kernel involved.

`build_app` (`script/gui.py`) combines every stage into one window — just Year/Month dropdowns
pinned on top (the only inputs every stage shares), one `Tab` below per stage. No tab wraps its
content in a titled `QGroupBox` any more (the Tab already names the stage); each is a plain
`_panel()` holding its inputs, a "Run" button paired with a Running/Done/Failed status pill
(`_make_status_label()` / `_run_async(..., status=...)`), and its live output log — the pipeline
functions themselves print their own stage-by-stage progress (e.g. `[2/4] Creating Google
Form...`, ending `Done`):
1. **1. Create Form** — `script/form.py::prepare_form`, creates the availability Google Form
   (cloned from `id_template_form`, its grid questions keyed by `dict_itemid_form` — both read
   fresh from Drive, `dutyshift/config/config.json`, on every click; see
   `script/helper.py::load_drive_config`), copies forward next month's `dutyshift/config/member`
   tab from the nearest prior month (`script/helper.py::ensure_member_sheet`, never overwrites an
   existing tab), and drafts (never sends) a notification email to active doctors via Gmail,
   using a required response deadline date picker and wording read fresh from Drive
   (`dutyshift/template/announce.json`; see `script/helper.py::load_email_template`). Holidays
   and ECT-cancel — only ever used by this stage — are picked here as two week-per-row calendar
   grids (`script/gui.py::_CalendarSelector`); Holidays defaults to that month's official Japanese
   holidays via `jpholiday`, with weekend cells locked on since weekends are always holidays
   automatically regardless of this selection. The deadline is also saved to Drive
   (`dutyshift/result/<year>/<month>/deadline.json`) for "2. Collect" to reuse.
2. **2. Collect** — `script/collect.py::collect_availability`, parses form responses and drafts
   (never sends) a reminder email Bcc'd to not-yet-answered doctors (wording from
   `dutyshift/template/reminder.json`), reusing the deadline saved by "1. Create Form" — no
   separate opt-in checkbox; it's a no-op once everyone has answered.
3. **3. Assign** — `script/assign.py::optimize_count_and_assign`, runs the two-stage MILP. Its
   hyperparameters (score-deviation weights, close-duty thresholds, `type_limit`, etc.) are
   editable widgets in a collapsed "Advanced solver parameters" section (`_CollapsibleBox`).
   They persist via
   `drive_io.read_json`/`write_json`: named presets in `dutyshift/config/solver_presets.json`,
   and an automatic per-month audit record (`dutyshift/result/<year>/<month>/solver_params.json`)
   written on every successful run. The panel seeds its defaults from the nearest prior month's
   audit record on build, falling back to hardcoded defaults if none exists.
4. **4. Notify** — four steps stacked in one tab: `script/notify.py::create_assignment_sheet`
   (the human-readable "調整結果" Google Sheet); `draft_dropin_notification` (drafts, never
   sends, an email to active doctors linking to that sheet, wording from
   `dutyshift/template/dropin.json` — meant for a last look before publishing); `update_calendar`
   (publishes to Google Calendar, target `id_calendar` read fresh from
   `dutyshift/config/config.json`); `draft_fixed_notification` (drafts, never sends, an email
   announcing the finalized roster, Bcc'd to active doctors plus any extras configured in
   `dutyshift/config/config.json`'s `l_email_extra_fixed`, wording from
   `dutyshift/template/fixed.json`).
5. **5. Replace** — one tab holding both check and apply steps stacked, since apply always needs
   a specific check's result: `script/replace.py::check_replacement` /`replace_assignment` handle
   shift-swap requests. `check_replacement`'s result is held on `state.d_replace_checked` (the
   only value that flows between steps in memory) and consumed by the apply step below it.

Each tab only wires widgets to these unchanged `script/*.py` functions — the pipeline logic
itself did not change. Every `build_*_panel(state)` function returns a plain `QWidget` and can
still be embedded/shown on its own (e.g. from a scratch script) if needed for debugging just one
stage.

All runtime data (`config/member` doctor roster, per-month generated CSVs) lives in a
`dutyshift` folder on **Google Drive**, read/written directly via the Drive API
(`script/drive_io.py`) — no local file mirror, no per-machine path guessing. The only thing
still local per machine is `config.local.json` (gitignored; copy
`config.local.example.json` to create it), which holds where that machine's OAuth
`credentials.json`/`token.json` files live. `AppState()` (`script/gui.py`) loads it once, up
front, and every pipeline entry point takes it as its first argument (`config`, replacing the
old `lp_root`). Nothing under the Drive `dutyshift` folder is version-controlled here.

## Key files

| File | Role |
|---|---|
| `main.py` | Entry point; opens the `PyQt5` window (`script/gui.py::AppState` + `build_app(state)`). |
| `script/gui.py` | `PyQt5` GUI layer: `AppState` (shared widgets + cross-panel state, loads `config.local.json` once), one `build_*_panel()` function per pipeline stage, `build_app()` combining them into the single window `main.py` shows, and the `_Worker`/`_run_async` background-thread machinery every button click runs through. Wires widgets to the functions below; contains no pipeline logic itself. |
| `script/drive_io.py` | Google Drive-backed data I/O layer: OAuth credential caching/reuse (`get_credentials`/`get_services`), Drive folder resolution/creation, `read_csv`/`write_csv`/`read_gsheet`/`read_json`/`write_json`/`get_file_web_link`/`list_month_folders`, and `prep_drive_paths` (replaces the old local-path resolver `prep_dirs`). No pipeline logic. |
| `script/parameter.py` | Fixed config: duty types, scoring weights, per-title duty eligibility, `str_email_button_html` (shared notification-email button styling). Edited rarely. Google resource IDs (`id_template_form`, `dict_itemid_form`, `id_calendar`) and every notification email's wording live on Drive instead — see `script/helper.py::load_drive_config`/`load_email_template` and the Drive folder layout bullet below. |
| `script/helper.py` | Shared building blocks: calendar prep, roster loading/parsing, `load_drive_config`/`load_email_template` (Drive-backed config/email-template loaders, read fresh on every call), the Stage-1 count-optimization MILP (`optimize_count`), result extraction/CSV export (all via `script/drive_io.py`). |
| `script/assign.py` | The Stage-2 assignment MILP (`optimize_assign`) and orchestration (`optimize_count_and_assign`), including infeasibility recovery. |
| `script/form.py` | Creates the monthly availability Google Form. |
| `script/collect.py` | Parses Google Form responses into an availability matrix. |
| `script/notify.py` | Creates the assignment Google Sheet, drafts drop-in/fixed notification emails, and publishes/diffs the schedule against Google Calendar events. |
| `script/replace.py` | Shift-swap request handling. |
| `script/check.py` | Small sanity-check helpers. |

## Conventions to know before editing

- **`date_duty`** is the universal index used everywhere: a string key
  `"<day-of-month>_<duty>"` (e.g. `"14_night"`), indexing the availability matrix, assignment
  matrix, and most PuLP decision variables.
- **`class_duty`** is an aggregation layer above raw duty types (`am`, `pm`, `day`, `night`,
  `emnight`, `ocday`, `ocnight`, `ect`), used for per-doctor count limits — defined in
  `dict_class_duty` in `script/parameter.py`.
- Per-doctor limits in `config/member` are encoded as strings parsed by `split_lim`:
  `"3"` = exact, `"2-4"` = hard range, `"2(1-3)"` = soft target with hard range, `"-"` =
  unconstrained.
- Holidays are passed per-run as a plain list of day-of-month integers (`l_holiday`); weekends
  are always holidays automatically.
- **Drive folder layout**: `dutyshift/config/member` (roster, a native Google Sheet with one
  tab per month, `member_<yyyymm>`); `dutyshift/config/config.json` (`id_template_form`,
  `dict_itemid_form`, `id_calendar`, `l_email_extra_fixed` — seeded with this codebase's
  original hardcoded values the first time `script/helper.py::load_drive_config` reads it, then
  edited directly on Drive, no code change needed); `dutyshift/template/<name>.json` (one file
  per notification email — `announce`/`reminder`/`dropin`/`fixed`, each `{subject, body,
  button_label}` — same seed-on-first-read pattern via `script/helper.py::load_email_template`);
  `dutyshift/result/<year>/
  <month, zero-padded>/` (live per-month CSVs + that month's Google Form, e.g.
  `dutyshift/result/2026/08/`); `.../result/<prefix>_<timestamp>/` nested beneath it (a
  timestamped snapshot written on every pipeline run, alongside the live copy — the only audit
  trail this system has). `script/drive_io.py::month_folder_path(year, month)` is the single
  source of truth for that path shape and `prep_drive_paths` resolves/creates it — don't
  hand-build Drive paths elsewhere.
- `script/parameter.py` holds base data only — no precomputed derived globals. Views that used
  to live there as `dict_duty`/`dict_duty_jpn`/`dict_time_duty`/`l_class_duty`/`dict_score_class`
  are now computed on demand, at the point of use, by shared functions in `script/helper.py`:
  `duty_order`/`duty_jpn_labels`/`duty_time_table` (from `dict_duty_info`), `class_duty_names`
  (from `dict_class_duty`), and `score_class_table`/`derive_score_class_constants` (from
  `dict_score_duty` + `dict_class_duty` + `dict_score_classes` — a `{score axis: [class_duty,
  ...]}` mapping — raising `ValueError` if the two can no longer be reconciled). **To change
  scoring weights, edit `dict_score_duty`, not
  `score_class_table`'s output** — the latter is computed, not a knob.

## Testing

`test/` contains 19 undocumented, ad hoc developer scripts (`test01.py`…`test19.py`) — not an
automated test suite. There is no pytest/unittest setup and no test command to run. Treat
changes to the optimizer as needing manual verification (re-run the relevant GUI panel against
real or sample data) rather than assuming test coverage exists.
