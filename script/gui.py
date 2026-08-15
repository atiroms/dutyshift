
###############################################################################
# ipywidgets GUI layer, launched via main.py
#
# build_app(state) is the one entry point main.py's generated notebook needs: it combines every
# stage below into a single panel -- common parameters pinned on top (relevant to every stage),
# one Tab per pipeline stage underneath:
#   common params -> [form | collect | assign | notify | replace check | replace apply]
#
# Each build_*_panel() function returns a widgets.VBox for one stage and can still be
# display()'d on its own if useful (e.g. while debugging just one stage).
#
# This module only wires widgets to the existing script/*.py functions -- it does not change
# any pipeline logic. AppState carries the one thing that genuinely has to flow between panels
# in memory (d_replace_checked, produced by the "check replacement" panel and consumed by the
# "apply replacement" panel); every other stage re-reads its inputs from Google Drive via
# script/drive_io.py (state.config, loaded once at AppState() construction time), so panels only
# need state.year_plan / state.month_plan / state.l_holiday / state.l_date_ect_cancel at click
# time.
###############################################################################

import calendar, datetime, traceback
import ipywidgets as widgets
from IPython.display import display

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

_STYLE = {'description_width': 'initial'}


###############################################################################
# Shared state and helpers
###############################################################################
class AppState:
    """Holds the widgets built by build_common_params_panel() plus d_replace_checked, the one
    value that has to flow in memory from the 'check replacement' panel to the 'apply
    replacement' panel. Construct once per notebook session, pass to every build_*_panel().

    Also loads config.local.json once (self.config) -- failing fast and visibly here, at
    AppState() construction time, rather than deep inside some button's on_click handler if
    config.local.json is missing or malformed."""

    def __init__(self):
        self.config = load_config()
        self.w_year = None
        self.w_month = None
        self.w_holiday = None
        self.w_ect_cancel = None
        self.d_replace_checked = None

    @property
    def year_plan(self):
        return self.w_year.value

    @property
    def month_plan(self):
        return self.w_month.value

    @property
    def l_holiday(self):
        return list(self.w_holiday.value)

    @property
    def l_date_ect_cancel(self):
        return list(self.w_ect_cancel.value)


def _run_in_output(output, fn):
    """Clear output, run fn() with stdout/display captured into it, print a traceback on
    failure instead of losing the error silently (a bare raise inside an ipywidgets on_click
    handler is easy to miss)."""
    output.clear_output(wait=True)
    with output:
        try:
            fn()
        except Exception:
            print(traceback.format_exc())


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
    state.w_year = widgets.Dropdown(options=list(range(today.year - 1, today.year + 3)),
                                    value=today.year, description='Year:')
    state.w_month = widgets.Dropdown(options=list(range(1, 13)),
                                     value=today.month, description='Month:')
    state.w_holiday = widgets.SelectMultiple(options=_day_options(state.w_year.value, state.w_month.value),
                                             value=(), description='Holidays:', style=_STYLE)
    state.w_ect_cancel = widgets.SelectMultiple(options=_day_options(state.w_year.value, state.w_month.value),
                                                value=(), description='ECT cancel:', style=_STYLE)

    def _refresh_days(*_):
        options = _day_options(state.w_year.value, state.w_month.value)
        state.w_holiday.options = options
        state.w_ect_cancel.options = options
    state.w_year.observe(_refresh_days, names='value')
    state.w_month.observe(_refresh_days, names='value')

    return widgets.VBox([
        widgets.HTML('<h3>Common parameters</h3>'),
        widgets.HBox([state.w_year, state.w_month]),
        widgets.HBox([state.w_holiday, state.w_ect_cancel]),
    ])


###############################################################################
# Create Google form (replaces the pre-GUI notebook's cell 1)
###############################################################################
def build_form_panel(state):
    w_deadline = widgets.DatePicker(description='Response deadline', style=_STYLE)
    button = widgets.Button(description='Create Google Form', button_style='primary')
    output = widgets.Output()

    def on_click(_):
        def run():
            if w_deadline.value is None:
                str_deadline = None
            else:
                d = w_deadline.value
                str_deadline = str(d.month) + '/' + str(d.day) + '(' + dict_jpnday[d.weekday()] + ')'
            prepare_form(state.config, state.year_plan, state.month_plan, state.l_holiday, state.l_date_ect_cancel,
                         l_day_ect, day_em, l_week_em, l_class_duty, dict_duty, dict_score_duty, dict_duty_jpn,
                         dict_title_duty, dict_class_duty, id_template_form, dict_itemid_form,
                         str_email_template, str_deadline)
        _run_in_output(output, run)
    button.on_click(on_click)

    return widgets.VBox([widgets.HTML('<h3>Create Google Form</h3>'), w_deadline, button, output])


###############################################################################
# Collect Google form response (replaces the pre-GUI notebook's cell 2)
###############################################################################
def build_collect_panel(state):
    button = widgets.Button(description='Collect Availability', button_style='primary')
    output = widgets.Output()

    def on_click(_):
        def run():
            collect_availability(state.config, state.year_plan, state.month_plan, dict_jpnday, dict_duty_jpn)
        _run_in_output(output, run)
    button.on_click(on_click)

    return widgets.VBox([widgets.HTML('<h3>Collect Availability</h3>'), button, output])


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
        'dict_c_diff_score_current': {axis: w.value for axis, w in dict_w_current.items()},
        'dict_c_diff_score_total': {axis: w.value for axis, w in dict_w_total.items()},
        'dict_closeduty_thresholds': {group: {'thr_hard': w['thr_hard'].value, 'thr_soft': w['thr_soft'].value}
                                      for group, w in dict_w_closeduty.items()},
        'c_assign_suboptimal': w_c_assign_suboptimal.value,
        'c_cnt_deviation': w_c_cnt_deviation.value,
        'c_closeduty': w_c_closeduty.value,
        'type_limit': w_type_limit.value,
        'l_date_duty_fulltime': [s.strip() for s in w_fulltime.value.split(',') if s.strip()],
        'l_date_duty_skip_manual': [s.strip() for s in w_skip.value.split(',') if s.strip()],
    }


def _apply_solver_params(dict_params, dict_w_current, dict_w_total, dict_w_closeduty,
                         w_c_assign_suboptimal, w_c_cnt_deviation, w_c_closeduty,
                         w_type_limit, w_fulltime, w_skip):
    """Set the Assign panel's widget values from a loaded preset/audit-record dict. Missing keys
    (e.g. an older record saved before a field existed) are left at whatever the widgets already
    hold, rather than raising."""
    for axis, w in dict_w_current.items():
        if axis in dict_params.get('dict_c_diff_score_current', {}):
            w.value = dict_params['dict_c_diff_score_current'][axis]
    for axis, w in dict_w_total.items():
        if axis in dict_params.get('dict_c_diff_score_total', {}):
            w.value = dict_params['dict_c_diff_score_total'][axis]
    for group, w in dict_w_closeduty.items():
        thr = dict_params.get('dict_closeduty_thresholds', {}).get(group)
        if thr:
            w['thr_hard'].value = thr['thr_hard']
            w['thr_soft'].value = thr['thr_soft']
    if 'c_assign_suboptimal' in dict_params:
        w_c_assign_suboptimal.value = dict_params['c_assign_suboptimal']
    if 'c_cnt_deviation' in dict_params:
        w_c_cnt_deviation.value = dict_params['c_cnt_deviation']
    if 'c_closeduty' in dict_params:
        w_c_closeduty.value = dict_params['c_closeduty']
    if 'type_limit' in dict_params:
        w_type_limit.value = dict_params['type_limit']
    if 'l_date_duty_fulltime' in dict_params:
        w_fulltime.value = ', '.join(dict_params['l_date_duty_fulltime'])
    if 'l_date_duty_skip_manual' in dict_params:
        w_skip.value = ', '.join(dict_params['l_date_duty_skip_manual'])


def _load_last_month_solver_params(state):
    """Best-effort load of the previous month's recorded solver_params.json -- used both to
    seed the Assign panel's default widget values at build time and by the explicit 'Load Last
    Month's Config' button. Returns None on any failure (missing credentials, no prior month,
    network issue, nothing recorded) -- never raises, since the panel-build call site must not
    be able to break build_app()."""
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
    dict_w_current = {axis: widgets.FloatText(value=dict_default_current[axis], description=axis,
                                              step=0.001, style=_STYLE) for axis in l_score_axis}
    dict_w_total = {axis: widgets.FloatText(value=dict_default_total[axis], description=axis,
                                            step=0.001, style=_STYLE) for axis in l_score_axis}

    # Close-duty groups: l_duty membership is structural (fixed in code), only the thresholds
    # are exposed as widgets.
    dict_closeduty_default = {'daynight': {'l_duty': ['day', 'ocday', 'night', 'emnight', 'ocnight'], 'thr_hard': 3, 'thr_soft': 5},
                              'ect':      {'l_duty': ['ect'], 'thr_hard': 1, 'thr_soft': 4},
                              'ampm':     {'l_duty': ['am', 'pm'], 'thr_hard': 1, 'thr_soft': 2}}
    dict_w_closeduty = {}
    for group, default in dict_closeduty_default.items():
        dict_w_closeduty[group] = {
            'thr_hard': widgets.IntText(value=default['thr_hard'], description='thr_hard', style=_STYLE),
            'thr_soft': widgets.IntText(value=default['thr_soft'], description='thr_soft', style=_STYLE),
        }

    w_c_assign_suboptimal = widgets.FloatText(value=0.00001, description='c_assign_suboptimal', style=_STYLE)
    w_c_cnt_deviation = widgets.FloatText(value=0.1, description='c_cnt_deviation', style=_STYLE)
    w_c_closeduty = widgets.FloatText(value=0.00001, description='c_closeduty', style=_STYLE)

    w_type_limit = widgets.Dropdown(options=['soft', 'hard', 'ignore'], value='soft',
                                    description='type_limit', style=_STYLE)
    w_fulltime = widgets.Text(value='', description='fulltime date_duty',
                              placeholder='e.g. 8_night, 21_night', style=_STYLE)
    w_skip = widgets.Text(value='', description='skip date_duty',
                          placeholder='e.g. 23_am, 23_', style=_STYLE)

    def _closeduty_box(group):
        return widgets.VBox([widgets.HTML('<b>' + group + '</b>'),
                             dict_w_closeduty[group]['thr_hard'], dict_w_closeduty[group]['thr_soft']])

    # Seed the widgets above from the previous month's recorded configuration, if any -- falls
    # back to the hardcoded defaults just set above on any failure (see
    # _load_last_month_solver_params's docstring for why this must never raise).
    _dict_solver_defaults = _load_last_month_solver_params(state)
    if _dict_solver_defaults:
        _apply_solver_params(_dict_solver_defaults, dict_w_current, dict_w_total, dict_w_closeduty,
                             w_c_assign_suboptimal, w_c_cnt_deviation, w_c_closeduty,
                             w_type_limit, w_fulltime, w_skip)

    advanced = widgets.Accordion(children=[widgets.VBox([
        widgets.HTML('<b>Score-deviation weight, current month (dict_c_diff_score_current)</b>'),
        widgets.HBox(list(dict_w_current.values())),
        widgets.HTML('<b>Score-deviation weight, cumulative (dict_c_diff_score_total)</b>'),
        widgets.HBox(list(dict_w_total.values())),
        widgets.HTML('<b>Close-duty thresholds (dict_closeduty)</b>'),
        widgets.HBox([_closeduty_box(group) for group in dict_closeduty_default]),
        widgets.HTML('<b>Objective weights</b>'),
        widgets.HBox([w_c_assign_suboptimal, w_c_cnt_deviation, w_c_closeduty]),
        widgets.HTML('<b>Other</b>'),
        w_type_limit, w_fulltime, w_skip,
    ])])
    advanced.set_title(0, 'Advanced solver parameters' + ('' if _dict_solver_defaults else ' (hardcoded defaults -- no prior month found)'))
    advanced.selected_index = None  # collapsed by default

    # --- Solver-parameter preset / last-month-config controls ---
    w_preset_name = widgets.Text(value='', description='Preset name',
                                 placeholder='e.g. strict-fairness', style=_STYLE)
    btn_save_preset = widgets.Button(description='Save as Preset')
    w_preset_select = widgets.Dropdown(options=[], description='Load preset', style=_STYLE)
    btn_load_preset = widgets.Button(description='Load Preset')
    btn_load_last_month = widgets.Button(description="Load Last Month's Config")
    output_preset = widgets.Output()

    def _refresh_preset_options():
        try:
            services = get_services(state.config, SCOPE_DRIVE_FORMS)
            id_config = resolve_folder_id(services.drive, 'dutyshift/config', create=False)
            dict_presets = read_json(services.drive, id_config, 'solver_presets.json', default={})
            w_preset_select.options = sorted(dict_presets.keys())
        except Exception:
            pass  # leave whatever options already exist; a passive refresh must not block the panel
    _refresh_preset_options()

    def _current_params():
        return _pack_solver_params(dict_w_current, dict_w_total, dict_w_closeduty,
                                   w_c_assign_suboptimal, w_c_cnt_deviation, w_c_closeduty,
                                   w_type_limit, w_fulltime, w_skip)

    def on_save_preset(_):
        def run():
            name = w_preset_name.value.strip()
            if not name:
                print('Enter a preset name first.')
                return
            services = get_services(state.config, SCOPE_DRIVE_FORMS)
            id_config = resolve_folder_id(services.drive, 'dutyshift/config', create=True)
            dict_presets = read_json(services.drive, id_config, 'solver_presets.json', default={})
            dict_presets[name] = _current_params()
            write_json(services.drive, id_config, 'solver_presets.json', dict_presets)
            _refresh_preset_options()
            w_preset_select.value = name
            print('Saved preset "' + name + '".')
        _run_in_output(output_preset, run)
    btn_save_preset.on_click(on_save_preset)

    def on_load_preset(_):
        def run():
            if not w_preset_select.value:
                print('No preset selected.')
                return
            services = get_services(state.config, SCOPE_DRIVE_FORMS)
            id_config = resolve_folder_id(services.drive, 'dutyshift/config', create=False)
            dict_presets = read_json(services.drive, id_config, 'solver_presets.json', default={})
            dict_params = dict_presets.get(w_preset_select.value)
            if dict_params is None:
                print('Preset "' + w_preset_select.value + '" not found.')
                return
            _apply_solver_params(dict_params, dict_w_current, dict_w_total, dict_w_closeduty,
                                 w_c_assign_suboptimal, w_c_cnt_deviation, w_c_closeduty,
                                 w_type_limit, w_fulltime, w_skip)
            print('Loaded preset "' + w_preset_select.value + '".')
        _run_in_output(output_preset, run)
    btn_load_preset.on_click(on_load_preset)

    def on_load_last_month(_):
        def run():
            dict_params = _load_last_month_solver_params(state)
            if dict_params is None:
                print('No recorded configuration found for a previous month.')
                return
            _apply_solver_params(dict_params, dict_w_current, dict_w_total, dict_w_closeduty,
                                 w_c_assign_suboptimal, w_c_cnt_deviation, w_c_closeduty,
                                 w_type_limit, w_fulltime, w_skip)
            print("Loaded last month's configuration.")
        _run_in_output(output_preset, run)
    btn_load_last_month.on_click(on_load_last_month)

    button = widgets.Button(description='Run Optimization', button_style='primary')
    output = widgets.Output()

    def on_click(_):
        def run():
            dict_c_diff_score_current = {axis: w.value for axis, w in dict_w_current.items()}
            dict_c_diff_score_total = {axis: w.value for axis, w in dict_w_total.items()}
            dict_closeduty = {group: {'l_duty': dict_closeduty_default[group]['l_duty'],
                                      'thr_hard': dict_w_closeduty[group]['thr_hard'].value,
                                      'thr_soft': dict_w_closeduty[group]['thr_soft'].value}
                              for group in dict_closeduty_default}
            l_date_duty_fulltime = [s.strip() for s in w_fulltime.value.split(',') if s.strip()]
            l_date_duty_skip_manual = [s.strip() for s in w_skip.value.split(',') if s.strip()]
            result = optimize_count_and_assign(state.config, state.year_plan, state.month_plan, year_start, month_start,
                                      l_class_duty, dict_c_diff_score_current, dict_c_diff_score_total,
                                      l_date_duty_skip_manual, dict_closeduty, ll_avoid_adjacent,
                                      l_title_fulltime, l_date_duty_fulltime, w_type_limit.value,
                                      w_c_assign_suboptimal.value, w_c_cnt_deviation.value, w_c_closeduty.value,
                                      dict_score_duty, dict_score_class, dict_class_duty,
                                      n_troubleshoot_infeasible_max)
            # result[0] (d_assign) is None on failure regardless of the differing success/failure
            # tuple lengths -- duck-typed success check, doesn't unpack the tuple.
            if result is not None and result[0] is not None:
                try:
                    services = get_services(state.config, SCOPE_DRIVE_FORMS)
                    dp = prep_drive_paths(state.config, services.drive, state.year_plan, state.month_plan,
                                          prefix_dir='asgn', make_data_dir=False)
                    write_json(services.drive, dp.id_month, 'solver_params.json', _current_params())
                except Exception:
                    print('[WARNING] Optimization succeeded but failed to record solver_params.json:')
                    print(traceback.format_exc())
        _run_in_output(output, run)
    button.on_click(on_click)

    preset_controls = widgets.VBox([
        widgets.HTML('<b>Solver-parameter presets</b>'),
        widgets.HBox([w_preset_name, btn_save_preset]),
        widgets.HBox([w_preset_select, btn_load_preset, btn_load_last_month]),
        output_preset,
    ])

    return widgets.VBox([widgets.HTML('<h3>Optimize Assignment</h3>'), preset_controls, advanced, button, output])


###############################################################################
# Notify Google calendar (replaces the pre-GUI notebook's cell 4)
###############################################################################
def build_notify_panel(state):
    button = widgets.Button(description='Publish to Calendar', button_style='primary')
    output = widgets.Output()

    def on_click(_):
        def run():
            update_calendar(state.config, state.year_plan, state.month_plan, id_calendar, dict_time_duty, n_retry_calendar)
        _run_in_output(output, run)
    button.on_click(on_click)

    return widgets.VBox([widgets.HTML('<h3>Publish to Calendar</h3>'), button, output])


###############################################################################
# Collect replacement application (replaces the pre-GUI notebook's cell 5)
###############################################################################
def build_replace_check_panel(state):
    button = widgets.Button(description='Check Replacement Requests', button_style='primary')
    output = widgets.Output()

    def on_click(_):
        def run():
            state.d_replace_checked = check_replacement(state.config, state.year_plan, state.month_plan)
            display(state.d_replace_checked)
        _run_in_output(output, run)
    button.on_click(on_click)

    return widgets.VBox([widgets.HTML('<h3>Check Replacement Requests</h3>'), button, output])


###############################################################################
# Apply checked replacement plan (replaces the pre-GUI notebook's cell 6)
###############################################################################
def build_replace_apply_panel(state):
    button = widgets.Button(description='Apply Replacement', button_style='primary')
    output = widgets.Output()

    def on_click(_):
        def run():
            if state.d_replace_checked is None:
                print("Run 'Check Replacement Requests' first.")
                return
            replace_assignment(state.config, state.year_plan, state.month_plan, dict_score_duty, l_class_duty,
                               state.d_replace_checked)
        _run_in_output(output, run)
    button.on_click(on_click)

    return widgets.VBox([widgets.HTML('<h3>Apply Replacement</h3>'), button, output])


###############################################################################
# Combined app: one panel, all stages -- the function main.py's generated notebook calls
###############################################################################
def build_app(state):
    """Single combined panel for the whole pipeline: common parameters pinned above a Tab
    holding one stage per tab. `state` must be a fresh AppState() -- build_common_params_panel
    populates its widgets, which every stage tab then reads from at click time."""
    params_panel = build_common_params_panel(state)

    l_tab = [
        ('1. Create Form', build_form_panel(state)),
        ('2. Collect', build_collect_panel(state)),
        ('3. Assign', build_assign_panel(state)),
        ('4. Notify', build_notify_panel(state)),
        ('5. Check Replace', build_replace_check_panel(state)),
        ('6. Apply Replace', build_replace_apply_panel(state)),
    ]
    tab = widgets.Tab(children=[panel for _, panel in l_tab])
    for i, (title, _) in enumerate(l_tab):
        tab.set_title(i, title)

    return widgets.VBox([params_panel, tab])
