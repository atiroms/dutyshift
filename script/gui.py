
###############################################################################
# PyQt5 GUI layer, launched via main.py
#
# build_app(state) is the one entry point main.py needs: it combines every stage below into a
# single window -- common parameters (year/month only; every other stage-specific input lives on
# its own tab) pinned on top, one Tab per pipeline stage underneath:
#   common params -> [1. form | 2. collect | 3. assign | 4. notify | 5. replace]
# "5. Replace" holds both the check-requests and apply-replacement steps, stacked in one panel
# (build_replace_panel), since apply always needs a prior check's result.
#
# Each build_*_panel() function returns a QWidget for one stage. None of them wrap their content
# in a titled QGroupBox any more -- the Tab itself already names the stage, so an identical label
# repeated inside it would be redundant; each panel is a plain, borderless container (_panel())
# holding just its inputs, one 'Run' button paired with a Running/Done/Failed status pill
# (_make_status_label() / _run_async(..., status=...)), and its live output log. The pipeline
# functions themselves (script/*.py) print their own progress as they go (e.g. "[2/4] Creating
# Google Form...", ending "Done") -- the status pill is only a quick-glance summary of that same
# run, not a separate source of truth.
#
# This module only wires widgets to the existing script/*.py functions -- it does not change
# any pipeline logic. AppState carries the one thing that genuinely has to flow between panels
# in memory (d_replace_checked, produced by the "check" step and consumed by the "apply" step,
# both inside build_replace_panel); every other stage re-reads its inputs from Google Drive via
# script/drive_io.py (state.config, loaded once at AppState() construction time), so panels only
# need state.year_plan / state.month_plan at click time -- state.l_holiday / state.l_date_ect_cancel
# (read from the Create Form tab's own calendars) are only used by build_form_panel itself, and
# the Create Form tab's response deadline is persisted to Drive and re-read automatically by the
# Collect tab (_save_deadline / _load_deadline) rather than flowing through AppState.
#
# Every pipeline call (Google API round-trips, the MILP solve) can take a while, so each button
# click runs its work on a background QThread (_Worker/_run_async below) instead of the GUI
# thread -- Qt widgets may only be read or mutated from the GUI thread, so anything a worker
# needs from a widget is captured into a plain value *before* dispatch, and anything a worker's
# result needs to write back to a widget happens in an on_success callback that _run_async
# marshals back onto the GUI thread, never inside the worker function itself. All of the app's
# action buttons (state.l_button) are disabled while any one worker is running, so only one
# pipeline stage ever runs at a time -- matching the old single-threaded Jupyter-kernel behavior.
###############################################################################

import calendar, contextlib, datetime, traceback

import jpholiday

from PyQt5.QtCore import Qt, QDate, QThread, pyqtSignal
from PyQt5.QtGui import QFontDatabase, QTextCursor
from PyQt5.QtWidgets import (
    QAbstractItemView, QComboBox, QDateEdit, QDoubleSpinBox, QFrame, QGridLayout, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QPushButton,
    QSpinBox, QTabWidget, QTextEdit, QVBoxLayout, QWidget,
)

from script.parameter import (
    dict_jpnday, dict_duty_info, dict_title_duty, dict_class_duty, dict_score_duty,
    l_day_ect, day_em, l_week_em, ll_avoid_adjacent, l_title_fulltime,
    n_troubleshoot_infeasible_max, n_retry_calendar, year_start, month_start,
)
from script.drive_io import (
    load_config, get_services, prep_drive_paths, resolve_folder_id,
    read_json, write_json, month_folder_path, list_month_folders, SCOPE_DRIVE_FORMS,
)
from script.form import prepare_form
from script.collect import collect_availability
from script.helper import load_manual_assign_options, write_manual_assign, duty_order, duty_jpn_labels
from script.assign import optimize_count_and_assign
from script.notify import update_calendar, create_assignment_sheet, draft_dropin_notification, draft_fixed_notification
from script.replace import check_replacement, replace_assignment


###############################################################################
# Shared state and helpers
###############################################################################
class AppState:
    """Holds the shared year/month widgets (built by build_common_params_panel()), the Create
    Form tab's Holidays/ECT-cancel calendars (built by build_form_panel(), read by nothing else),
    and d_replace_checked, the one value that has to flow in memory from the 'check' step to the
    'apply' step inside build_replace_panel(). Construct once per app session, pass to every
    build_*_panel().

    Also loads config.local.json once (self.config) -- failing fast and visibly here, at
    AppState() construction time, rather than deep inside some button's click handler if
    config.local.json is missing or malformed."""

    def __init__(self):
        self.config = load_config()
        self.w_year = None
        self.w_month = None
        self.w_holiday = None       # _CalendarSelector, built by build_form_panel
        self.w_ect_cancel = None    # _CalendarSelector, built by build_form_panel
        self.d_replace_checked = None
        self.l_button = []   # every action button in the app -- _run_async() disables/enables
                              # all of them together so only one pipeline stage ever runs at a
                              # time.
        self.l_worker = []   # references started _Worker threads so PyQt doesn't garbage
                              # collect (and abort) a still-running QThread.

    @property
    def year_plan(self):
        return self.w_year.currentData()

    @property
    def month_plan(self):
        return self.w_month.currentData()

    @property
    def l_holiday(self):
        return self.w_holiday.selected_days()

    @property
    def l_date_ect_cancel(self):
        return self.w_ect_cancel.selected_days()


class _StreamToSignal:
    """File-like stand-in for stdout inside a worker thread: each write() just emits a Qt
    signal instead of touching a widget directly -- Qt widgets may only be touched from the GUI
    thread that owns them."""

    def __init__(self, signal):
        self._signal = signal

    def write(self, text):
        if text:
            self._signal.emit(text)

    def flush(self):
        pass


class _Worker(QThread):
    """Runs fn() (a zero-arg callable capturing only plain values, never widgets) on a
    background thread, with its stdout captured live via the `output` signal and its return
    value delivered via `succeeded` on success, or a formatted traceback via `failed` on any
    exception -- mirrors the old ipywidgets-era _run_in_output's "never lose an error silently"
    contract."""
    output = pyqtSignal(str)
    succeeded = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, fn, parent=None):
        super().__init__(parent)
        self._fn = fn

    def run(self):
        stream = _StreamToSignal(self.output)
        try:
            with contextlib.redirect_stdout(stream):
                result = self._fn()
        except Exception:
            self.failed.emit(traceback.format_exc())
        else:
            self.succeeded.emit(result)


def _append_text(output, text):
    cursor = output.textCursor()
    cursor.movePosition(QTextCursor.End)
    output.setTextCursor(cursor)
    output.insertPlainText(text)


_DICT_STATUS_STYLE = {
    'ready':   'color: #888;',
    'running': 'color: #b8860b; font-weight: bold;',
    'done':    'color: #2e7d32; font-weight: bold;',
    'failed':  'color: #c0392b; font-weight: bold;',
}
_DICT_STATUS_TEXT = {
    'ready': '', 'running': '● Running…', 'done': '● Done', 'failed': '● Failed',
}


def _make_status_label():
    """A small 'Running.../Done/Failed' indicator that _run_async drives -- a quick-glance
    complement to the detailed stage-by-stage progress each pipeline function prints into its
    output box."""
    label = QLabel('')
    label.setStyleSheet(_DICT_STATUS_STYLE['ready'])
    return label


def _set_status(label, kind):
    if label is None:
        return
    label.setStyleSheet(_DICT_STATUS_STYLE[kind])
    label.setText(_DICT_STATUS_TEXT[kind])


def _run_async(state, output, fn, on_success=None, status=None):
    """Run fn() on a background QThread so a long Google API call or the MILP solve doesn't
    freeze the GUI, streaming its stdout into `output` live. Disables every action button in the
    app for the duration (state.l_button). If given, on_success(result) runs back on the GUI
    thread once fn() returns successfully -- use it for anything that needs to write back to a
    widget; fn() itself must never touch widgets, since it runs on the background thread. If
    given, `status` (a _make_status_label()) is set to Running at the start and Done/Failed once
    fn() finishes."""
    output.clear()
    _set_status(status, 'running')
    for button in state.l_button:
        button.setEnabled(False)

    worker = _Worker(fn)
    worker.output.connect(lambda text: _append_text(output, text), Qt.QueuedConnection)

    def _on_failed(tb):
        _append_text(output, tb)
        _set_status(status, 'failed')
    worker.failed.connect(_on_failed, Qt.QueuedConnection)

    def _on_succeeded(result):
        _set_status(status, 'done')
        if on_success is not None:
            on_success(result)
    worker.succeeded.connect(_on_succeeded, Qt.QueuedConnection)

    def _on_finished():
        for button in state.l_button:
            button.setEnabled(True)
        state.l_worker.remove(worker)
    worker.finished.connect(_on_finished, Qt.QueuedConnection)

    state.l_worker.append(worker)
    worker.start()


def _make_output(min_height=160):
    output = QTextEdit()
    output.setReadOnly(True)
    output.setFont(QFontDatabase.systemFont(QFontDatabase.FixedFont))
    output.setMinimumHeight(min_height)
    return output


def _action_row(button, status):
    """Button + its status indicator, left-aligned, for the top of an action panel."""
    row = QHBoxLayout()
    row.addWidget(button)
    row.addWidget(status)
    row.addStretch()
    return row


def _panel(*items):
    """A plain, unlabeled, unbordered container stacking `items` vertically -- replaces the old
    per-tab QGroupBox(title) wrapper so tabs no longer repeat their own name as a heading inside
    themselves."""
    widget = QWidget()
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(8, 8, 8, 8)
    for item in items:
        if isinstance(item, QHBoxLayout) or isinstance(item, QVBoxLayout):
            layout.addLayout(item)
        else:
            layout.addWidget(item)
    return widget


def _labeled(text, widget):
    """A QLabel stacked above `widget`, as one QWidget -- stands in for the description= label
    ipywidgets bakes into every widget."""
    container = QWidget()
    layout = QVBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.addWidget(QLabel(text))
    layout.addWidget(widget)
    return container


def _float_spin(value, decimals=6, step=0.001, minimum=0.0, maximum=1000.0):
    w = QDoubleSpinBox()
    w.setDecimals(decimals)
    w.setRange(minimum, maximum)
    w.setSingleStep(step)
    w.setValue(value)
    return w


def _int_spin(value, minimum=0, maximum=30):
    w = QSpinBox()
    w.setRange(minimum, maximum)
    w.setValue(value)
    return w


class _CollapsibleBox(QWidget):
    """Minimal collapsible container (a checkable QPushButton toggling a content widget's
    visibility) -- Qt has no built-in ipywidgets.Accordion equivalent, and this internal tool
    doesn't need one fancier than click-to-expand/collapse."""

    def __init__(self, title, parent=None):
        super().__init__(parent)
        self._toggle = QPushButton(title)
        self._toggle.setCheckable(True)
        self._toggle.setChecked(False)
        self._content = QWidget()
        self._content.setVisible(False)
        self._toggle.toggled.connect(self._content.setVisible)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._toggle)
        layout.addWidget(self._content)

    def setContentLayout(self, layout):
        self._content.setLayout(layout)

    def setTitle(self, title):
        self._toggle.setText(title)


def _jp_holiday_days(year, month):
    """Days of the month (1-indexed) that are official Japanese national holidays, per the
    `jpholiday` package -- used to seed the Holidays calendar's default selection."""
    _, n_days = calendar.monthrange(year, month)
    return [day for day in range(1, n_days + 1)
            if jpholiday.is_holiday(datetime.date(year, month, day))]


def _day_button_style(col):
    """Stylesheet for one day-toggle button in a _CalendarSelector, colored by weekday column
    (Sunday red, Saturday blue, weekdays neutral) -- matches common Japanese calendar
    convention. `:checked` gets a filled highlight; `:disabled` (locked weekend cells in the
    Holidays calendar) keeps its weekday color but flattens into the background."""
    color = '#c0392b' if col == 0 else ('#2c6fbb' if col == 6 else '#333')
    return (
        'QPushButton { border: 1px solid #ccc; border-radius: 4px; background: white;'
        ' color: ' + color + '; padding: 2px; }'
        'QPushButton:checked { background: #fbe27a; border-color: #d9a520; color: #333; font-weight: bold; }'
        'QPushButton:disabled { background: #f2f2f2; border-color: #eee; color: ' + color + '; }'
    )


class _CalendarSelector(QWidget):
    """A week-per-row calendar of day-toggle buttons for one month -- used for the Holidays and
    ECT-cancel pickers in the Create Form tab. Sun-Sat header, Sunday-first weeks (standard
    Japanese calendar layout).

    lock_weekend=True (used for Holidays) renders Saturday/Sunday cells as permanently-checked,
    disabled buttons rather than toggles: weekends are always holidays regardless of this
    selection (script/helper.py::prep_calendar), so leaving them clickable here would just
    invite a meaningless click -- they're excluded from selected_days()."""

    def __init__(self, lock_weekend=False, parent=None):
        super().__init__(parent)
        self._lock_weekend = lock_weekend
        self._dict_button = {}
        self._grid = QGridLayout(self)
        # Zero out Qt's default layout margin (otherwise the grid renders indented a good
        # ~10px from its own top-left, making it look like it has drifted away from the
        # "Holidays"/"ECT cancel" QLabel caption sitting flush above it in _labeled()).
        self._grid.setContentsMargins(0, 2, 0, 0)
        self._grid.setSpacing(3)
        for col, label in enumerate(['日', '月', '火', '水', '木', '金', '土']):
            lbl = QLabel(label)
            lbl.setAlignment(Qt.AlignCenter)
            color = '#c0392b' if col == 0 else ('#2c6fbb' if col == 6 else '#666')
            lbl.setStyleSheet('font-weight: bold; color: ' + color + ';')
            self._grid.addWidget(lbl, 0, col)

    def rebuild(self, year, month, l_default_selected=()):
        """Rebuild for (year, month), pre-checking l_default_selected (day-of-month ints).
        Always resets the selection -- there is no meaningful "same selection" to carry over
        across a month change."""
        for button in self._dict_button.values():
            self._grid.removeWidget(button)
            button.deleteLater()
        self._dict_button = {}

        set_default = set(l_default_selected)
        _, n_days = calendar.monthrange(year, month)
        col_first = (datetime.date(year, month, 1).weekday() + 1) % 7  # Sun=0 .. Sat=6
        for day in range(1, n_days + 1):
            position = col_first + day - 1
            row, col = 1 + position // 7, position % 7
            btn = QPushButton(str(day))
            btn.setCheckable(True)
            btn.setFixedSize(34, 26)
            btn.setStyleSheet(_day_button_style(col))
            is_weekend = col in (0, 6)
            if is_weekend and self._lock_weekend:
                btn.setChecked(True)
                btn.setEnabled(False)
            else:
                btn.setChecked(day in set_default)
                self._dict_button[day] = btn
            self._grid.addWidget(btn, row, col)

    def selected_days(self):
        return sorted(day for day, button in self._dict_button.items() if button.isChecked())


###############################################################################
# Common parameters panel (replaces the pre-GUI notebook's cell 0)
###############################################################################
def build_common_params_panel(state):
    today = datetime.date.today()
    state.w_year = QComboBox()
    for year in range(today.year - 1, today.year + 3):
        state.w_year.addItem(str(year), year)
    state.w_year.setCurrentIndex(state.w_year.findData(today.year))

    state.w_month = QComboBox()
    for month in range(1, 13):
        state.w_month.addItem(str(month), month)
    state.w_month.setCurrentIndex(state.w_month.findData(today.month))

    label_year = QLabel('Year:')
    label_year.setStyleSheet('font-weight: bold;')
    label_month = QLabel('Month:')
    label_month.setStyleSheet('font-weight: bold;')

    row_dropdown = QHBoxLayout()
    row_dropdown.addWidget(label_year)
    row_dropdown.addWidget(state.w_year)
    row_dropdown.addWidget(label_month)
    row_dropdown.addWidget(state.w_month)
    row_dropdown.addStretch()

    widget = QWidget()
    widget.setLayout(row_dropdown)
    line = QFrame()
    line.setFrameShape(QFrame.HLine)
    line.setStyleSheet('color: #ddd;')

    container = QWidget()
    layout = QVBoxLayout(container)
    layout.setContentsMargins(8, 6, 8, 0)
    layout.addWidget(widget)
    layout.addWidget(line)
    return container


###############################################################################
# Create Google form (replaces the pre-GUI notebook's cell 1)
###############################################################################
def _format_deadline(qdate):
    d = qdate.toPyDate()
    return str(d.month) + '/' + str(d.day) + '(' + dict_jpnday[d.weekday()] + ')'


def _save_deadline(config, year_plan, month_plan, str_deadline):
    """Best-effort: record this month's response deadline on Drive so build_collect_panel can
    automatically pick it up for its reminder-email draft, without the user re-entering it."""
    try:
        services = get_services(config, SCOPE_DRIVE_FORMS)
        id_month = resolve_folder_id(services.drive, month_folder_path(year_plan, month_plan), create=True)
        write_json(services.drive, id_month, 'deadline.json', {'str_deadline': str_deadline})
    except Exception:
        print('[WARNING] Could not save the response deadline for later reuse:')
        print(traceback.format_exc())


def _load_deadline(config, year_plan, month_plan):
    """Best-effort load of this month's response deadline, as recorded by the 'Create Google
    Form' step above -- returns None on any failure (nothing recorded yet, network issue), never
    raises. Safe to call from a worker thread."""
    try:
        services = get_services(config, SCOPE_DRIVE_FORMS)
        id_month = resolve_folder_id(services.drive, month_folder_path(year_plan, month_plan), create=False)
        dict_deadline = read_json(services.drive, id_month, 'deadline.json', default=None)
        return dict_deadline['str_deadline'] if dict_deadline else None
    except Exception:
        return None


def build_form_panel(state):
    w_deadline = QDateEdit(QDate.currentDate())
    w_deadline.setCalendarPopup(True)

    # Holidays/ECT-cancel only ever matter to this stage (script/form.py::prepare_form), so they
    # live here rather than in the common params bar above the tabs.
    state.w_holiday = _CalendarSelector(lock_weekend=True)
    state.w_ect_cancel = _CalendarSelector(lock_weekend=False)

    def _refresh_calendars():
        year, month = state.year_plan, state.month_plan
        state.w_holiday.rebuild(year, month, _jp_holiday_days(year, month))
        state.w_ect_cancel.rebuild(year, month)
    _refresh_calendars()
    state.w_year.currentIndexChanged.connect(_refresh_calendars)
    state.w_month.currentIndexChanged.connect(_refresh_calendars)

    button = QPushButton('Create Google Form')
    status = _make_status_label()
    output = _make_output()
    state.l_button.append(button)

    def on_click():
        year_plan, month_plan = state.year_plan, state.month_plan
        l_holiday, l_date_ect_cancel = state.l_holiday, state.l_date_ect_cancel
        str_deadline = _format_deadline(w_deadline.date())

        def run():
            prepare_form(state.config, year_plan, month_plan, l_holiday, l_date_ect_cancel,
                         l_day_ect, day_em, l_week_em, dict_score_duty,
                         dict_title_duty, dict_class_duty, str_deadline)
            _save_deadline(state.config, year_plan, month_plan, str_deadline)
        _run_async(state, output, run, status=status)
    button.clicked.connect(on_click)

    label_deadline = QLabel('Response deadline:')
    label_deadline.setStyleSheet('font-weight: bold;')
    row_deadline = QHBoxLayout()
    row_deadline.addWidget(label_deadline)
    row_deadline.addWidget(w_deadline)
    row_deadline.addStretch()

    row_calendar = QHBoxLayout()
    row_calendar.addWidget(_labeled('Holidays', state.w_holiday), 0, Qt.AlignTop)
    row_calendar.addWidget(_labeled('ECT cancel', state.w_ect_cancel), 0, Qt.AlignTop)
    row_calendar.addStretch()

    return _panel(row_deadline, row_calendar, _action_row(button, status), output)


###############################################################################
# Collect Google form response (replaces the pre-GUI notebook's cell 2)
###############################################################################
def build_collect_panel(state):
    button = QPushButton('Collect Availability')
    status = _make_status_label()
    output = _make_output()
    state.l_button.append(button)

    def on_click():
        year_plan, month_plan = state.year_plan, state.month_plan

        def run():
            # The response deadline set on the Create Form tab is reused automatically here
            # (script/gui.py::_save_deadline / _load_deadline via dutyshift/result/<year>/
            # <month>/deadline.json) -- collect_availability itself only drafts a reminder email
            # when there is at least one not-yet-answered doctor, so this stays a no-op the rest
            # of the time.
            str_deadline = _load_deadline(state.config, year_plan, month_plan)
            collect_availability(state.config, year_plan, month_plan, dict_jpnday, str_deadline)
        _run_async(state, output, run, status=status)
    button.clicked.connect(on_click)

    return _panel(_action_row(button, status), output)


###############################################################################
# Solver-tuning preset persistence, shared by build_assign_panel below
#
# "Presets" (named, saved on demand) and the per-month "audit record" (auto-saved on every
# successful run) share one schema and one Drive-backed store per kind:
#   dutyshift/config/solver_presets.json           -- {"<name>": {...params...}, ...}
#   dutyshift/result/<year>/<month>/solver_params.json  -- {...params...} (this month's own)
###############################################################################
def _pack_solver_params(dict_w_current, dict_w_total, dict_w_closeduty,
                        w_c_assign_suboptimal, w_c_cnt_deviation, w_c_closeduty,
                        w_type_limit, w_fulltime, w_skip):
    """Read the Assign panel's current widget values into the JSON shape saved as a preset or
    per-month audit record."""
    return {
        'dict_c_diff_score_current': {axis: w.value() for axis, w in dict_w_current.items()},
        'dict_c_diff_score_total': {axis: w.value() for axis, w in dict_w_total.items()},
        'dict_closeduty_thresholds': {group: {'thr_hard': w['thr_hard'].value(), 'thr_soft': w['thr_soft'].value()}
                                      for group, w in dict_w_closeduty.items()},
        'c_assign_suboptimal': w_c_assign_suboptimal.value(),
        'c_cnt_deviation': w_c_cnt_deviation.value(),
        'c_closeduty': w_c_closeduty.value(),
        'type_limit': w_type_limit.currentText(),
        'l_date_duty_fulltime': [s.strip() for s in w_fulltime.text().split(',') if s.strip()],
        'l_date_duty_skip_manual': [s.strip() for s in w_skip.text().split(',') if s.strip()],
    }


def _apply_solver_params(dict_params, dict_w_current, dict_w_total, dict_w_closeduty,
                         w_c_assign_suboptimal, w_c_cnt_deviation, w_c_closeduty,
                         w_type_limit, w_fulltime, w_skip):
    """Set the Assign panel's widget values from a loaded preset/audit-record dict. Missing keys
    (e.g. an older record saved before a field existed) are left at whatever the widgets already
    hold, rather than raising. Must only be called from the GUI thread."""
    for axis, w in dict_w_current.items():
        if axis in dict_params.get('dict_c_diff_score_current', {}):
            w.setValue(dict_params['dict_c_diff_score_current'][axis])
    for axis, w in dict_w_total.items():
        if axis in dict_params.get('dict_c_diff_score_total', {}):
            w.setValue(dict_params['dict_c_diff_score_total'][axis])
    for group, w in dict_w_closeduty.items():
        thr = dict_params.get('dict_closeduty_thresholds', {}).get(group)
        if thr:
            w['thr_hard'].setValue(thr['thr_hard'])
            w['thr_soft'].setValue(thr['thr_soft'])
    if 'c_assign_suboptimal' in dict_params:
        w_c_assign_suboptimal.setValue(dict_params['c_assign_suboptimal'])
    if 'c_cnt_deviation' in dict_params:
        w_c_cnt_deviation.setValue(dict_params['c_cnt_deviation'])
    if 'c_closeduty' in dict_params:
        w_c_closeduty.setValue(dict_params['c_closeduty'])
    if 'type_limit' in dict_params:
        w_type_limit.setCurrentText(dict_params['type_limit'])
    if 'l_date_duty_fulltime' in dict_params:
        w_fulltime.setText(', '.join(dict_params['l_date_duty_fulltime']))
    if 'l_date_duty_skip_manual' in dict_params:
        w_skip.setText(', '.join(dict_params['l_date_duty_skip_manual']))


def _load_last_month_solver_params(state):
    """Best-effort load of the previous month's recorded solver_params.json -- used both to
    seed the Assign panel's default widget values at build time and by the explicit 'Load Last
    Month's Config' button. Returns None on any failure (missing credentials, no prior month,
    network issue, nothing recorded) -- never raises, since the panel-build call site must not
    be able to break build_app(). Pure data fetch, safe to call from a worker thread."""
    try:
        services = get_services(state.config, SCOPE_DRIVE_FORMS)
        id_root = resolve_folder_id(services.drive, 'dutyshift', create=False)
        l_dir_before_current = sorted(d for d in list_month_folders(services.drive, id_root)
                                      if d < '{:04d}{:02d}'.format(state.year_plan, state.month_plan))
        if not l_dir_before_current:
            return None
        dir_previous = l_dir_before_current[-1]
        id_month_previous = resolve_folder_id(
            services.drive, month_folder_path(int(dir_previous[:4]), int(dir_previous[4:6])), create=False)
        return read_json(services.drive, id_month_previous, 'solver_params.json', default=None)
    except Exception:
        return None


###############################################################################
# Optimize assignment count and assign members (replaces the pre-GUI notebook's cell 3)
###############################################################################
def build_assign_panel(state):
    l_score_axis = ['ampm', 'daynight', 'ampmdaynight', 'oc', 'ect']
    dict_default_current = {'ampm': 0.001, 'daynight': 0.001, 'ampmdaynight': 0.001, 'oc': 0.001, 'ect': 0.01}
    dict_default_total = {'ampm': 0.01, 'daynight': 0.01, 'ampmdaynight': 0.01, 'oc': 0.01, 'ect': 0.1}
    dict_w_current = {axis: _float_spin(dict_default_current[axis]) for axis in l_score_axis}
    dict_w_total = {axis: _float_spin(dict_default_total[axis]) for axis in l_score_axis}

    # Close-duty groups: l_duty membership is structural (fixed in code), only the thresholds
    # are exposed as widgets.
    dict_closeduty_default = {'daynight': {'l_duty': ['day', 'ocday', 'night', 'emnight', 'ocnight'], 'thr_hard': 3, 'thr_soft': 5},
                              'ect':      {'l_duty': ['ect'], 'thr_hard': 1, 'thr_soft': 4},
                              'ampm':     {'l_duty': ['am', 'pm'], 'thr_hard': 1, 'thr_soft': 2}}
    dict_w_closeduty = {}
    for group, default in dict_closeduty_default.items():
        dict_w_closeduty[group] = {
            'thr_hard': _int_spin(default['thr_hard']),
            'thr_soft': _int_spin(default['thr_soft']),
        }

    w_c_assign_suboptimal = _float_spin(0.00001, step=0.00001)
    w_c_cnt_deviation = _float_spin(0.1, step=0.01)
    w_c_closeduty = _float_spin(0.00001, step=0.00001)

    w_type_limit = QComboBox()
    w_type_limit.addItems(['soft', 'hard', 'ignore'])
    w_fulltime = QLineEdit()
    w_fulltime.setPlaceholderText('e.g. 8_night, 21_night')
    w_skip = QLineEdit()
    w_skip.setPlaceholderText('e.g. 23_am, 23_')

    def _closeduty_box(group):
        box = QGroupBox(group)
        layout = QVBoxLayout()
        layout.addWidget(_labeled('thr_hard', dict_w_closeduty[group]['thr_hard']))
        layout.addWidget(_labeled('thr_soft', dict_w_closeduty[group]['thr_soft']))
        box.setLayout(layout)
        return box

    # Seed the widgets above from the previous month's recorded configuration, if any -- falls
    # back to the hardcoded defaults just set above on any failure (see
    # _load_last_month_solver_params's docstring for why this must never raise). Runs
    # synchronously at build time, before the window is shown / any event loop is running, so
    # there is no GUI to freeze.
    _dict_solver_defaults = _load_last_month_solver_params(state)
    if _dict_solver_defaults:
        _apply_solver_params(_dict_solver_defaults, dict_w_current, dict_w_total, dict_w_closeduty,
                             w_c_assign_suboptimal, w_c_cnt_deviation, w_c_closeduty,
                             w_type_limit, w_fulltime, w_skip)

    row_current = QHBoxLayout()
    for axis in l_score_axis:
        row_current.addWidget(_labeled(axis, dict_w_current[axis]))
    row_total = QHBoxLayout()
    for axis in l_score_axis:
        row_total.addWidget(_labeled(axis, dict_w_total[axis]))
    row_closeduty = QHBoxLayout()
    for group in dict_closeduty_default:
        row_closeduty.addWidget(_closeduty_box(group))
    row_objective = QHBoxLayout()
    row_objective.addWidget(_labeled('c_assign_suboptimal', w_c_assign_suboptimal))
    row_objective.addWidget(_labeled('c_cnt_deviation', w_c_cnt_deviation))
    row_objective.addWidget(_labeled('c_closeduty', w_c_closeduty))

    advanced_content = QVBoxLayout()
    advanced_content.addWidget(QLabel('<b>Score-deviation weight, current month (dict_c_diff_score_current)</b>'))
    advanced_content.addLayout(row_current)
    advanced_content.addWidget(QLabel('<b>Score-deviation weight, cumulative (dict_c_diff_score_total)</b>'))
    advanced_content.addLayout(row_total)
    advanced_content.addWidget(QLabel('<b>Close-duty thresholds (dict_closeduty)</b>'))
    advanced_content.addLayout(row_closeduty)
    advanced_content.addWidget(QLabel('<b>Objective weights</b>'))
    advanced_content.addLayout(row_objective)
    advanced_content.addWidget(QLabel('<b>Other</b>'))
    advanced_content.addWidget(_labeled('type_limit', w_type_limit))
    advanced_content.addWidget(_labeled('fulltime date_duty', w_fulltime))
    advanced_content.addWidget(_labeled('skip date_duty', w_skip))

    advanced = _CollapsibleBox(
        'Advanced solver parameters' + ('' if _dict_solver_defaults else ' (hardcoded defaults -- no prior month found)'))
    advanced.setContentLayout(advanced_content)

    # --- Solver-parameter preset / last-month-config controls ---
    w_preset_name = QLineEdit()
    w_preset_name.setPlaceholderText('e.g. strict-fairness')
    btn_save_preset = QPushButton('Save as Preset')
    w_preset_select = QComboBox()
    btn_load_preset = QPushButton('Load Preset')
    btn_load_last_month = QPushButton("Load Last Month's Config")
    output_preset = _make_output(min_height=80)
    state.l_button += [btn_save_preset, btn_load_preset, btn_load_last_month]

    def _refresh_preset_options():
        """Best-effort, synchronous (runs at panel-build time, before the window is shown)."""
        try:
            services = get_services(state.config, SCOPE_DRIVE_FORMS)
            id_config = resolve_folder_id(services.drive, 'dutyshift/config', create=False)
            dict_presets = read_json(services.drive, id_config, 'solver_presets.json', default={})
            w_preset_select.clear()
            w_preset_select.addItems(sorted(dict_presets.keys()))
        except Exception:
            pass  # leave whatever options already exist; a passive refresh must not block the panel
    _refresh_preset_options()

    def _current_params():
        return _pack_solver_params(dict_w_current, dict_w_total, dict_w_closeduty,
                                   w_c_assign_suboptimal, w_c_cnt_deviation, w_c_closeduty,
                                   w_type_limit, w_fulltime, w_skip)

    def on_save_preset():
        name = w_preset_name.text().strip()
        current_params = _current_params()

        def run():
            if not name:
                print('Enter a preset name first.')
                return None
            services = get_services(state.config, SCOPE_DRIVE_FORMS)
            id_config = resolve_folder_id(services.drive, 'dutyshift/config', create=True)
            dict_presets = read_json(services.drive, id_config, 'solver_presets.json', default={})
            dict_presets[name] = current_params
            write_json(services.drive, id_config, 'solver_presets.json', dict_presets)
            print('Saved preset "' + name + '".')
            return sorted(dict_presets.keys())

        def apply(l_name):
            if l_name is None:
                return
            w_preset_select.clear()
            w_preset_select.addItems(l_name)
            w_preset_select.setCurrentText(name)
        _run_async(state, output_preset, run, apply)
    btn_save_preset.clicked.connect(on_save_preset)

    def on_load_preset():
        name = w_preset_select.currentText()

        def run():
            if not name:
                print('No preset selected.')
                return None
            services = get_services(state.config, SCOPE_DRIVE_FORMS)
            id_config = resolve_folder_id(services.drive, 'dutyshift/config', create=False)
            dict_presets = read_json(services.drive, id_config, 'solver_presets.json', default={})
            dict_params = dict_presets.get(name)
            if dict_params is None:
                print('Preset "' + name + '" not found.')
            return dict_params

        def apply(dict_params):
            if dict_params is None:
                return
            _apply_solver_params(dict_params, dict_w_current, dict_w_total, dict_w_closeduty,
                                 w_c_assign_suboptimal, w_c_cnt_deviation, w_c_closeduty,
                                 w_type_limit, w_fulltime, w_skip)
            _append_text(output_preset, 'Loaded preset "' + name + '".\n')
        _run_async(state, output_preset, run, apply)
    btn_load_preset.clicked.connect(on_load_preset)

    def on_load_last_month():
        def run():
            dict_params = _load_last_month_solver_params(state)
            if dict_params is None:
                print('No recorded configuration found for a previous month.')
            return dict_params

        def apply(dict_params):
            if dict_params is None:
                return
            _apply_solver_params(dict_params, dict_w_current, dict_w_total, dict_w_closeduty,
                                 w_c_assign_suboptimal, w_c_cnt_deviation, w_c_closeduty,
                                 w_type_limit, w_fulltime, w_skip)
            _append_text(output_preset, "Loaded last month's configuration.\n")
        _run_async(state, output_preset, run, apply)
    btn_load_last_month.clicked.connect(on_load_last_month)

    # --- Manual assignment (assign_manual.csv) controls ---
    # Lets the user fix specific date_duty -> member designations from the GUI instead of
    # hand-editing assign_manual.csv on Drive. l_manual_designation (a plain list of
    # {'date_duty', 'id_member'} dicts) is the in-memory staging area the assign/remove buttons
    # edit; it's only written to Drive (write_manual_assign, script/helper.py) right before 'Run
    # Optimization' actually runs, so optimize_count_and_assign's read of assign_manual.csv picks
    # up whatever is staged at that moment.
    dict_duty_jpn_full = duty_jpn_labels(dict_duty_info, include_ect=True)
    dict_duty = duty_order(dict_duty_info)
    l_manual_designation = []
    dict_manual_date_duty = {}    # date (int) -> [duty, ...] valid that date, from date_duty.csv
    dict_manual_member_name = {}  # id_member (int) -> name_jpn_full

    w_manual_date = QComboBox()
    w_manual_duty = QComboBox()
    w_manual_member = QComboBox()
    btn_manual_load = QPushButton('Load Duties / Members')
    btn_manual_assign = QPushButton('assign')
    btn_manual_unassign = QPushButton('remove')
    w_manual_list = QListWidget()
    w_manual_list.setSelectionMode(QAbstractItemView.ExtendedSelection)  # allow batch remove
    output_manual = _make_output(min_height=60)
    state.l_button += [btn_manual_load, btn_manual_assign, btn_manual_unassign]

    def _manual_item_label(date_duty, id_member):
        date, duty = date_duty.split('_', 1)
        return (date + '日 ' + dict_duty_jpn_full.get(duty, duty) + ' (' + date_duty + ')  →  '
                + dict_manual_member_name.get(id_member, str(id_member)))

    def _refresh_manual_list():
        w_manual_list.clear()
        for designation in l_manual_designation:
            item = QListWidgetItem(_manual_item_label(designation['date_duty'], designation['id_member']))
            item.setData(Qt.UserRole, designation['date_duty'])
            w_manual_list.addItem(item)

    def _refresh_manual_duty_options():
        w_manual_duty.clear()
        for duty in dict_manual_date_duty.get(w_manual_date.currentData(), []):
            w_manual_duty.addItem(dict_duty_jpn_full.get(duty, duty), duty)
    w_manual_date.currentIndexChanged.connect(lambda _: _refresh_manual_duty_options())

    def on_manual_load():
        year_plan, month_plan = state.year_plan, state.month_plan

        def run():
            return load_manual_assign_options(state.config, year_plan, month_plan)

        def apply(result):
            l_date_duty, dict_member_name, l_manual = result

            dict_manual_member_name.clear()
            dict_manual_member_name.update(dict_member_name)

            dict_manual_date_duty.clear()
            for date_duty in l_date_duty:
                str_date, duty = date_duty.split('_', 1)
                dict_manual_date_duty.setdefault(int(str_date), []).append(duty)
            for date in dict_manual_date_duty:
                dict_manual_date_duty[date].sort(key=lambda duty: dict_duty.get(duty, 99))

            w_manual_date.clear()
            for date in sorted(dict_manual_date_duty.keys()):
                w_manual_date.addItem(str(date) + '日', date)
            _refresh_manual_duty_options()

            w_manual_member.clear()
            for id_member in sorted(dict_manual_member_name.keys()):
                w_manual_member.addItem(dict_manual_member_name[id_member], id_member)

            l_manual_designation.clear()
            l_manual_designation.extend(l_manual)
            _refresh_manual_list()
            _append_text(output_manual, 'Loaded ' + str(len(l_date_duty)) + ' date_duty options, '
                        + str(len(dict_member_name)) + ' members, ' + str(len(l_manual)) + ' existing designation(s).\n')
        _run_async(state, output_manual, run, apply)
    btn_manual_load.clicked.connect(on_manual_load)

    def on_manual_assign():
        date, duty, id_member = w_manual_date.currentData(), w_manual_duty.currentData(), w_manual_member.currentData()
        if date is None or duty is None or id_member is None:
            _append_text(output_manual, "Click 'Load Duties / Members' first, then pick a date, duty and member.\n")
            return
        date_duty = str(date) + '_' + duty
        for designation in l_manual_designation:
            if designation['date_duty'] == date_duty:
                designation['id_member'] = id_member
                break
        else:
            l_manual_designation.append({'date_duty': date_duty, 'id_member': id_member})
        _refresh_manual_list()
    btn_manual_assign.clicked.connect(on_manual_assign)

    def on_manual_unassign():
        l_date_duty_selected = [item.data(Qt.UserRole) for item in w_manual_list.selectedItems()]
        l_manual_designation[:] = [d for d in l_manual_designation if d['date_duty'] not in l_date_duty_selected]
        _refresh_manual_list()
    btn_manual_unassign.clicked.connect(on_manual_unassign)

    manual_controls = QGroupBox('Manual Assignment (assign_manual.csv)')
    manual_layout = QVBoxLayout()
    row_manual_load = QHBoxLayout()
    row_manual_load.addWidget(btn_manual_load)
    row_manual_load.addStretch()
    row_manual_pick = QHBoxLayout()
    row_manual_pick.addWidget(QLabel('Date'))
    row_manual_pick.addWidget(w_manual_date)
    row_manual_pick.addWidget(QLabel('Duty'))
    row_manual_pick.addWidget(w_manual_duty)
    row_manual_pick.addWidget(QLabel('Member'))
    row_manual_pick.addWidget(w_manual_member)
    row_manual_pick.addStretch()
    row_manual_buttons = QHBoxLayout()
    row_manual_buttons.addWidget(btn_manual_assign)
    row_manual_buttons.addWidget(btn_manual_unassign)
    row_manual_buttons.addStretch()
    manual_layout.addLayout(row_manual_load)
    manual_layout.addLayout(row_manual_pick)
    manual_layout.addLayout(row_manual_buttons)
    manual_layout.addWidget(w_manual_list)
    manual_layout.addWidget(output_manual)
    manual_controls.setLayout(manual_layout)

    button = QPushButton('Run Optimization')
    status = _make_status_label()
    output = _make_output()
    state.l_button.append(button)

    def on_click():
        year_plan, month_plan = state.year_plan, state.month_plan
        l_manual_designation_snapshot = list(l_manual_designation)
        dict_c_diff_score_current = {axis: w.value() for axis, w in dict_w_current.items()}
        dict_c_diff_score_total = {axis: w.value() for axis, w in dict_w_total.items()}
        dict_closeduty = {group: {'l_duty': dict_closeduty_default[group]['l_duty'],
                                  'thr_hard': dict_w_closeduty[group]['thr_hard'].value(),
                                  'thr_soft': dict_w_closeduty[group]['thr_soft'].value()}
                          for group in dict_closeduty_default}
        l_date_duty_fulltime = [s.strip() for s in w_fulltime.text().split(',') if s.strip()]
        l_date_duty_skip_manual = [s.strip() for s in w_skip.text().split(',') if s.strip()]
        type_limit = w_type_limit.currentText()
        c_assign_suboptimal = w_c_assign_suboptimal.value()
        c_cnt_deviation = w_c_cnt_deviation.value()
        c_closeduty = w_c_closeduty.value()
        current_params = _current_params()  # snapshot for the post-run solver_params.json audit write

        def run():
            write_manual_assign(state.config, year_plan, month_plan, l_manual_designation_snapshot)
            print('Wrote', len(l_manual_designation_snapshot), 'manual assignment(s) to assign_manual.csv')
            result = optimize_count_and_assign(state.config, year_plan, month_plan, year_start, month_start,
                                      dict_c_diff_score_current, dict_c_diff_score_total,
                                      l_date_duty_skip_manual, dict_closeduty, ll_avoid_adjacent,
                                      l_title_fulltime, l_date_duty_fulltime, type_limit,
                                      c_assign_suboptimal, c_cnt_deviation, c_closeduty,
                                      dict_score_duty, dict_class_duty,
                                      n_troubleshoot_infeasible_max)
            # result[0] (d_assign) is None on failure regardless of the differing success/failure
            # tuple lengths -- duck-typed success check, doesn't unpack the tuple.
            if result is not None and result[0] is not None:
                try:
                    services = get_services(state.config, SCOPE_DRIVE_FORMS)
                    dp = prep_drive_paths(state.config, services, year_plan, month_plan,
                                          prefix_dir='asgn', make_data_dir=False)
                    write_json(services.drive, dp.id_month, 'solver_params.json', current_params)
                except Exception:
                    print('[WARNING] Optimization succeeded but failed to record solver_params.json:')
                    print(traceback.format_exc())
        _run_async(state, output, run, status=status)
    button.clicked.connect(on_click)

    preset_controls = QGroupBox('Solver-parameter presets')
    preset_layout = QVBoxLayout()
    row_save = QHBoxLayout()
    row_save.addWidget(w_preset_name)
    row_save.addWidget(btn_save_preset)
    row_load = QHBoxLayout()
    row_load.addWidget(w_preset_select)
    row_load.addWidget(btn_load_preset)
    row_load.addWidget(btn_load_last_month)
    preset_layout.addLayout(row_save)
    preset_layout.addLayout(row_load)
    preset_layout.addWidget(output_preset)
    preset_controls.setLayout(preset_layout)

    return _panel(manual_controls, preset_controls, advanced, _action_row(button, status), output)


###############################################################################
# Notify Google calendar (replaces the pre-GUI notebook's cell 4)
###############################################################################
def build_notify_panel(state):
    button_sheet = QPushButton('Create Assignment Sheet')
    status_sheet = _make_status_label()
    output_sheet = _make_output(min_height=120)
    state.l_button.append(button_sheet)

    def on_click_sheet():
        year_plan, month_plan = state.year_plan, state.month_plan

        def run():
            create_assignment_sheet(state.config, year_plan, month_plan)
        _run_async(state, output_sheet, run, status=status_sheet)
    button_sheet.clicked.connect(on_click_sheet)

    line1 = QFrame()
    line1.setFrameShape(QFrame.HLine)
    line1.setStyleSheet('color: #ddd;')

    # Draft (never send) a notification email to active doctors linking to the assignment sheet
    # just created above -- meant for a last look before Publish to Calendar below. The
    # correction deadline next to the button is embedded in the draft's subject
    # ('【{deadline} 修正〆】...', dutyshift/template/dropin.json) -- same date-picker pattern as
    # "1. Create Form"'s response deadline (build_form_panel/_format_deadline above), but not
    # persisted to Drive: unlike the survey deadline, nothing downstream needs to reuse it.
    button_dropin = QPushButton('Draft Drop-in Notification')
    status_dropin = _make_status_label()
    output_dropin = _make_output(min_height=100)
    state.l_button.append(button_dropin)

    label_deadline_dropin = QLabel('Deadline:')
    w_deadline_dropin = QDateEdit(QDate.currentDate())
    w_deadline_dropin.setCalendarPopup(True)

    def on_click_dropin():
        year_plan, month_plan = state.year_plan, state.month_plan
        str_deadline = _format_deadline(w_deadline_dropin.date())

        def run():
            draft_dropin_notification(state.config, year_plan, month_plan, str_deadline)
        _run_async(state, output_dropin, run, status=status_dropin)
    button_dropin.clicked.connect(on_click_dropin)

    line2 = QFrame()
    line2.setFrameShape(QFrame.HLine)
    line2.setStyleSheet('color: #ddd;')

    button = QPushButton('Publish to Calendar')
    status = _make_status_label()
    output = _make_output()
    state.l_button.append(button)

    def on_click():
        year_plan, month_plan = state.year_plan, state.month_plan

        def run():
            update_calendar(state.config, year_plan, month_plan, n_retry_calendar)
        _run_async(state, output, run, status=status)
    button.clicked.connect(on_click)

    line3 = QFrame()
    line3.setFrameShape(QFrame.HLine)
    line3.setStyleSheet('color: #ddd;')

    # Draft (never send) a notification email to active doctors, plus any extra recipients
    # configured in dutyshift/config/config.json's l_email_extra_fixed, announcing the finalized
    # roster -- meant to be run once Publish to Calendar above is done.
    button_fixed = QPushButton('Draft Fixed Notification')
    status_fixed = _make_status_label()
    output_fixed = _make_output(min_height=100)
    state.l_button.append(button_fixed)

    def on_click_fixed():
        year_plan, month_plan = state.year_plan, state.month_plan

        def run():
            draft_fixed_notification(state.config, year_plan, month_plan)
        _run_async(state, output_fixed, run, status=status_fixed)
    button_fixed.clicked.connect(on_click_fixed)

    row_dropin = QHBoxLayout()
    row_dropin.addWidget(button_dropin)
    row_dropin.addWidget(status_dropin)
    row_dropin.addWidget(label_deadline_dropin)
    row_dropin.addWidget(w_deadline_dropin)
    row_dropin.addStretch()

    return _panel(_action_row(button_sheet, status_sheet), output_sheet,
                 line1,
                 row_dropin, output_dropin,
                 line2,
                 _action_row(button, status), output,
                 line3,
                 _action_row(button_fixed, status_fixed), output_fixed)


###############################################################################
# Replacement requests: check incoming swap requests, then apply the checked plan -- one tab
# (replaces the pre-GUI notebook's cells 5 and 6). Kept as two clearly-ordered steps rather than
# one button since "Apply" must run against a specific "Check" result the user has read and
# accepted (state.d_replace_checked) -- a fresh Check is required before every Apply.
###############################################################################
def build_replace_panel(state):
    button_check = QPushButton('Check Replacement Requests')
    status_check = _make_status_label()
    output_check = _make_output(min_height=120)
    state.l_button.append(button_check)

    def on_check():
        year_plan, month_plan = state.year_plan, state.month_plan

        def run():
            d_replace_checked = check_replacement(state.config, year_plan, month_plan)
            print(d_replace_checked.to_string())
            return d_replace_checked

        def apply(d_replace_checked):
            state.d_replace_checked = d_replace_checked
        _run_async(state, output_check, run, apply, status=status_check)
    button_check.clicked.connect(on_check)

    line = QFrame()
    line.setFrameShape(QFrame.HLine)
    line.setStyleSheet('color: #ddd;')

    button_apply = QPushButton('Apply Replacement')
    status_apply = _make_status_label()
    output_apply = _make_output(min_height=120)
    state.l_button.append(button_apply)

    def on_apply():
        year_plan, month_plan = state.year_plan, state.month_plan
        d_replace_checked = state.d_replace_checked

        def run():
            if d_replace_checked is None:
                print("Run 'Check Replacement Requests' first.")
                return
            replace_assignment(state.config, year_plan, month_plan, dict_score_duty, d_replace_checked)
        _run_async(state, output_apply, run, status=status_apply)
    button_apply.clicked.connect(on_apply)

    return _panel(_action_row(button_check, status_check), output_check,
                 line,
                 _action_row(button_apply, status_apply), output_apply)


###############################################################################
# Combined app: one window, all stages -- the function main.py calls
###############################################################################
def build_app(state):
    """Single combined window for the whole pipeline: common parameters pinned above a Tab
    holding one stage per tab. `state` must be a fresh AppState() -- build_common_params_panel
    populates its widgets, which every stage tab then reads from at click time."""
    window = QMainWindow()
    window.setWindowTitle('dutyshift')

    central = QWidget()
    layout = QVBoxLayout(central)
    layout.addWidget(build_common_params_panel(state))

    l_tab = [
        ('1. Create Form', build_form_panel(state)),
        ('2. Collect', build_collect_panel(state)),
        ('3. Assign', build_assign_panel(state)),
        ('4. Notify', build_notify_panel(state)),
        ('5. Replace', build_replace_panel(state)),
    ]
    tabs = QTabWidget()
    for title, panel in l_tab:
        tabs.addTab(panel, title)
    layout.addWidget(tabs)

    window.setCentralWidget(central)
    window.resize(900, 700)
    return window
