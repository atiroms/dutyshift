
###############################################################################
# PyQt5 GUI layer, launched via main.py
#
# build_app(state) is the one entry point main.py needs: it combines every stage below into a
# single window -- common parameters pinned on top (relevant to every stage), one Tab per
# pipeline stage underneath:
#   common params -> [form | collect | assign | notify | replace check | replace apply]
#
# Each build_*_panel() function returns a QWidget for one stage.
#
# This module only wires widgets to the existing script/*.py functions -- it does not change
# any pipeline logic. AppState carries the one thing that genuinely has to flow between panels
# in memory (d_replace_checked, produced by the "check replacement" panel and consumed by the
# "apply replacement" panel); every other stage re-reads its inputs from Google Drive via
# script/drive_io.py (state.config, loaded once at AppState() construction time), so panels only
# need state.year_plan / state.month_plan / state.l_holiday / state.l_date_ect_cancel at click
# time.
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

from PyQt5.QtCore import Qt, QDate, QThread, pyqtSignal
from PyQt5.QtGui import QFontDatabase, QTextCursor
from PyQt5.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDateEdit, QDoubleSpinBox, QGroupBox, QHBoxLayout,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QPushButton, QSpinBox,
    QTabWidget, QTextEdit, QVBoxLayout, QWidget,
)

from script.parameter import (
    dict_jpnday, dict_duty, dict_duty_jpn, dict_title_duty, dict_class_duty, dict_score_duty,
    dict_score_class, dict_time_duty, dict_itemid_form, id_template_form, str_email_template,
    l_day_ect, day_em, l_week_em, l_class_duty, ll_avoid_adjacent, l_title_fulltime,
    n_troubleshoot_infeasible_max, id_calendar, n_retry_calendar, year_start, month_start,
)
from script.drive_io import (
    load_config, get_services, prep_drive_paths, resolve_folder_id,
    read_json, write_json, month_folder_path, list_month_folders, SCOPE_DRIVE_FORMS,
)
from script.form import prepare_form
from script.collect import collect_availability
from script.assign import optimize_count_and_assign
from script.notify import update_calendar
from script.replace import check_replacement, replace_assignment


###############################################################################
# Shared state and helpers
###############################################################################
class AppState:
    """Holds the widgets built by build_common_params_panel() plus d_replace_checked, the one
    value that has to flow in memory from the 'check replacement' panel to the 'apply
    replacement' panel. Construct once per app session, pass to every build_*_panel().

    Also loads config.local.json once (self.config) -- failing fast and visibly here, at
    AppState() construction time, rather than deep inside some button's click handler if
    config.local.json is missing or malformed."""

    def __init__(self):
        self.config = load_config()
        self.w_year = None
        self.w_month = None
        self.w_holiday = None
        self.w_ect_cancel = None
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
        return sorted(item.data(Qt.UserRole) for item in self.w_holiday.selectedItems())

    @property
    def l_date_ect_cancel(self):
        return sorted(item.data(Qt.UserRole) for item in self.w_ect_cancel.selectedItems())


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


def _run_async(state, output, fn, on_success=None):
    """Run fn() on a background QThread so a long Google API call or the MILP solve doesn't
    freeze the GUI, streaming its stdout into `output` live. Disables every action button in the
    app for the duration (state.l_button). If given, on_success(result) runs back on the GUI
    thread once fn() returns successfully -- use it for anything that needs to write back to a
    widget; fn() itself must never touch widgets, since it runs on the background thread."""
    output.clear()
    for button in state.l_button:
        button.setEnabled(False)

    worker = _Worker(fn)
    worker.output.connect(lambda text: _append_text(output, text), Qt.QueuedConnection)
    worker.failed.connect(lambda tb: _append_text(output, tb), Qt.QueuedConnection)
    if on_success is not None:
        worker.succeeded.connect(on_success, Qt.QueuedConnection)

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


def _day_options(year, month):
    _, n_days = calendar.monthrange(year, month)
    l_options = []
    for day in range(1, n_days + 1):
        wday = datetime.date(year, month, day).weekday()
        l_options.append((str(day) + ' (' + dict_jpnday[wday] + ')', day))
    return l_options


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

    state.w_holiday = QListWidget()
    state.w_holiday.setSelectionMode(QAbstractItemView.MultiSelection)
    state.w_ect_cancel = QListWidget()
    state.w_ect_cancel.setSelectionMode(QAbstractItemView.MultiSelection)

    def _refresh_days():
        for w in (state.w_holiday, state.w_ect_cancel):
            l_selected = {item.data(Qt.UserRole) for item in w.selectedItems()}
            w.clear()
            for label, day in _day_options(state.w_year.currentData(), state.w_month.currentData()):
                item = QListWidgetItem(label)
                item.setData(Qt.UserRole, day)
                w.addItem(item)
                if day in l_selected:
                    item.setSelected(True)
    _refresh_days()
    state.w_year.currentIndexChanged.connect(_refresh_days)
    state.w_month.currentIndexChanged.connect(_refresh_days)

    row_dropdown = QHBoxLayout()
    row_dropdown.addWidget(QLabel('Year:'))
    row_dropdown.addWidget(state.w_year)
    row_dropdown.addWidget(QLabel('Month:'))
    row_dropdown.addWidget(state.w_month)
    row_dropdown.addStretch()

    row_list = QHBoxLayout()
    row_list.addWidget(_labeled('Holidays:', state.w_holiday))
    row_list.addWidget(_labeled('ECT cancel:', state.w_ect_cancel))

    box = QGroupBox('Common parameters')
    layout = QVBoxLayout()
    layout.addLayout(row_dropdown)
    layout.addLayout(row_list)
    box.setLayout(layout)
    return box


###############################################################################
# Create Google form (replaces the pre-GUI notebook's cell 1)
###############################################################################
def build_form_panel(state):
    w_set_deadline = QCheckBox('Set response deadline')
    w_deadline = QDateEdit(QDate.currentDate())
    w_deadline.setCalendarPopup(True)
    w_deadline.setEnabled(False)
    w_set_deadline.toggled.connect(w_deadline.setEnabled)

    button = QPushButton('Create Google Form')
    output = _make_output()
    state.l_button.append(button)

    def on_click():
        year_plan, month_plan = state.year_plan, state.month_plan
        l_holiday, l_date_ect_cancel = state.l_holiday, state.l_date_ect_cancel
        if w_set_deadline.isChecked():
            d = w_deadline.date().toPyDate()
            str_deadline = str(d.month) + '/' + str(d.day) + '(' + dict_jpnday[d.weekday()] + ')'
        else:
            str_deadline = None

        def run():
            prepare_form(state.config, year_plan, month_plan, l_holiday, l_date_ect_cancel,
                         l_day_ect, day_em, l_week_em, l_class_duty, dict_duty, dict_score_duty, dict_duty_jpn,
                         dict_title_duty, dict_class_duty, id_template_form, dict_itemid_form,
                         str_email_template, str_deadline)
        _run_async(state, output, run)
    button.clicked.connect(on_click)

    row_deadline = QHBoxLayout()
    row_deadline.addWidget(w_set_deadline)
    row_deadline.addWidget(w_deadline)
    row_deadline.addStretch()

    box = QGroupBox('Create Google Form')
    layout = QVBoxLayout()
    layout.addLayout(row_deadline)
    layout.addWidget(button)
    layout.addWidget(output)
    box.setLayout(layout)
    return box


###############################################################################
# Collect Google form response (replaces the pre-GUI notebook's cell 2)
###############################################################################
def build_collect_panel(state):
    button = QPushButton('Collect Availability')
    output = _make_output()
    state.l_button.append(button)

    def on_click():
        year_plan, month_plan = state.year_plan, state.month_plan

        def run():
            collect_availability(state.config, year_plan, month_plan, dict_jpnday, dict_duty_jpn)
        _run_async(state, output, run)
    button.clicked.connect(on_click)

    box = QGroupBox('Collect Availability')
    layout = QVBoxLayout()
    layout.addWidget(button)
    layout.addWidget(output)
    box.setLayout(layout)
    return box


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

    button = QPushButton('Run Optimization')
    output = _make_output()
    state.l_button.append(button)

    def on_click():
        year_plan, month_plan = state.year_plan, state.month_plan
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
            result = optimize_count_and_assign(state.config, year_plan, month_plan, year_start, month_start,
                                      l_class_duty, dict_c_diff_score_current, dict_c_diff_score_total,
                                      l_date_duty_skip_manual, dict_closeduty, ll_avoid_adjacent,
                                      l_title_fulltime, l_date_duty_fulltime, type_limit,
                                      c_assign_suboptimal, c_cnt_deviation, c_closeduty,
                                      dict_score_duty, dict_score_class, dict_class_duty,
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
        _run_async(state, output, run)
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

    box = QGroupBox('Optimize Assignment')
    layout = QVBoxLayout()
    layout.addWidget(preset_controls)
    layout.addWidget(advanced)
    layout.addWidget(button)
    layout.addWidget(output)
    box.setLayout(layout)
    return box


###############################################################################
# Notify Google calendar (replaces the pre-GUI notebook's cell 4)
###############################################################################
def build_notify_panel(state):
    button = QPushButton('Publish to Calendar')
    output = _make_output()
    state.l_button.append(button)

    def on_click():
        year_plan, month_plan = state.year_plan, state.month_plan

        def run():
            update_calendar(state.config, year_plan, month_plan, id_calendar, dict_time_duty, n_retry_calendar)
        _run_async(state, output, run)
    button.clicked.connect(on_click)

    box = QGroupBox('Publish to Calendar')
    layout = QVBoxLayout()
    layout.addWidget(button)
    layout.addWidget(output)
    box.setLayout(layout)
    return box


###############################################################################
# Collect replacement application (replaces the pre-GUI notebook's cell 5)
###############################################################################
def build_replace_check_panel(state):
    button = QPushButton('Check Replacement Requests')
    output = _make_output()
    state.l_button.append(button)

    def on_click():
        year_plan, month_plan = state.year_plan, state.month_plan

        def run():
            d_replace_checked = check_replacement(state.config, year_plan, month_plan)
            print(d_replace_checked.to_string())
            return d_replace_checked

        def apply(d_replace_checked):
            state.d_replace_checked = d_replace_checked
        _run_async(state, output, run, apply)
    button.clicked.connect(on_click)

    box = QGroupBox('Check Replacement Requests')
    layout = QVBoxLayout()
    layout.addWidget(button)
    layout.addWidget(output)
    box.setLayout(layout)
    return box


###############################################################################
# Apply checked replacement plan (replaces the pre-GUI notebook's cell 6)
###############################################################################
def build_replace_apply_panel(state):
    button = QPushButton('Apply Replacement')
    output = _make_output()
    state.l_button.append(button)

    def on_click():
        year_plan, month_plan = state.year_plan, state.month_plan
        d_replace_checked = state.d_replace_checked

        def run():
            if d_replace_checked is None:
                print("Run 'Check Replacement Requests' first.")
                return
            replace_assignment(state.config, year_plan, month_plan, dict_score_duty, l_class_duty, d_replace_checked)
        _run_async(state, output, run)
    button.clicked.connect(on_click)

    box = QGroupBox('Apply Replacement')
    layout = QVBoxLayout()
    layout.addWidget(button)
    layout.addWidget(output)
    box.setLayout(layout)
    return box


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
        ('5. Check Replace', build_replace_check_panel(state)),
        ('6. Apply Replace', build_replace_apply_panel(state)),
    ]
    tabs = QTabWidget()
    for title, panel in l_tab:
        tabs.addTab(panel, title)
    layout.addWidget(tabs)

    window.setCentralWidget(central)
    window.resize(900, 700)
    return window
