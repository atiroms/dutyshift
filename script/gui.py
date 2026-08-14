
###############################################################################
# ipywidgets GUI layer for main.ipynb
#
# build_app(state) is the one entry point main.ipynb needs: it combines every stage below into
# a single panel -- common parameters pinned on top (relevant to every stage), one Tab per
# pipeline stage underneath:
#   common params -> [form | collect | assign | notify | replace check | replace apply]
#
# Each build_*_panel() function returns a widgets.VBox for one stage and can still be
# display()'d on its own if useful (e.g. while debugging just one stage).
#
# This module only wires widgets to the existing script/*.py functions -- it does not change
# any pipeline logic. AppState carries the one thing that genuinely has to flow between panels
# in memory (d_replace_checked, produced by the "check replacement" panel and consumed by the
# "apply replacement" panel); every other stage re-reads its inputs from disk via prep_dirs, so
# panels only need state.year_plan / state.month_plan / state.l_holiday / state.l_date_ect_cancel
# at click time.
###############################################################################

import calendar, datetime, traceback
import ipywidgets as widgets
from IPython.display import display

from script.parameter import *
from script.form import *
from script.collect import *
from script.assign import *
from script.notify import *
from script.replace import *

_STYLE = {'description_width': 'initial'}


###############################################################################
# Shared state and helpers
###############################################################################
class AppState:
    """Holds the widgets built by build_common_params_panel() plus d_replace_checked, the one
    value that has to flow in memory from the 'check replacement' panel to the 'apply
    replacement' panel. Construct once per notebook session, pass to every build_*_panel()."""

    def __init__(self):
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
    output.clear_output(wait = True)
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
# Common parameters panel (replaces main.ipynb cell 0)
###############################################################################
def build_common_params_panel(state):
    today = datetime.date.today()
    state.w_year = widgets.Dropdown(options = list(range(today.year - 1, today.year + 3)),
                                    value = today.year, description = 'Year:')
    state.w_month = widgets.Dropdown(options = list(range(1, 13)),
                                     value = today.month, description = 'Month:')
    state.w_holiday = widgets.SelectMultiple(options = _day_options(state.w_year.value, state.w_month.value),
                                             value = (), description = 'Holidays:', style = _STYLE)
    state.w_ect_cancel = widgets.SelectMultiple(options = _day_options(state.w_year.value, state.w_month.value),
                                                value = (), description = 'ECT cancel:', style = _STYLE)

    def _refresh_days(*_):
        options = _day_options(state.w_year.value, state.w_month.value)
        state.w_holiday.options = options
        state.w_ect_cancel.options = options
    state.w_year.observe(_refresh_days, names = 'value')
    state.w_month.observe(_refresh_days, names = 'value')

    return widgets.VBox([
        widgets.HTML('<h3>Common parameters</h3>'),
        widgets.HBox([state.w_year, state.w_month]),
        widgets.HBox([state.w_holiday, state.w_ect_cancel]),
    ])


###############################################################################
# Create Google form (replaces main.ipynb cell 1)
###############################################################################
def build_form_panel(state):
    button = widgets.Button(description = 'Create Google Form', button_style = 'primary')
    output = widgets.Output()

    def on_click(_):
        def run():
            prepare_form(lp_root, state.year_plan, state.month_plan, state.l_holiday, state.l_date_ect_cancel,
                         l_day_ect, day_em, l_week_em, l_class_duty, dict_duty, dict_score_duty, dict_duty_jpn,
                         dict_title_duty, dict_class_duty, id_template_form, dict_itemid_form)
        _run_in_output(output, run)
    button.on_click(on_click)

    return widgets.VBox([widgets.HTML('<h3>Create Google Form</h3>'), button, output])


###############################################################################
# Collect Google form response (replaces main.ipynb cell 2)
###############################################################################
def build_collect_panel(state):
    button = widgets.Button(description = 'Collect Availability', button_style = 'primary')
    output = widgets.Output()

    def on_click(_):
        def run():
            collect_availability(lp_root, state.year_plan, state.month_plan, dict_jpnday, dict_duty_jpn)
        _run_in_output(output, run)
    button.on_click(on_click)

    return widgets.VBox([widgets.HTML('<h3>Collect Availability</h3>'), button, output])


###############################################################################
# Optimize assignment count and assign members (replaces main.ipynb cell 3)
###############################################################################
def build_assign_panel(state):
    l_score_axis = ['ampm', 'daynight', 'ampmdaynight', 'oc', 'ect']
    dict_default_current = {'ampm': 0.001, 'daynight': 0.001, 'ampmdaynight': 0.001, 'oc': 0.001, 'ect': 0.01}
    dict_default_total = {'ampm': 0.01, 'daynight': 0.01, 'ampmdaynight': 0.01, 'oc': 0.01, 'ect': 0.1}
    dict_w_current = {axis: widgets.FloatText(value = dict_default_current[axis], description = axis,
                                              step = 0.001, style = _STYLE) for axis in l_score_axis}
    dict_w_total = {axis: widgets.FloatText(value = dict_default_total[axis], description = axis,
                                            step = 0.001, style = _STYLE) for axis in l_score_axis}

    # Close-duty groups: l_duty membership is structural (fixed in code), only the thresholds
    # are exposed as widgets.
    dict_closeduty_default = {'daynight': {'l_duty': ['day', 'ocday', 'night', 'emnight', 'ocnight'], 'thr_hard': 3, 'thr_soft': 5},
                              'ect':      {'l_duty': ['ect'], 'thr_hard': 1, 'thr_soft': 4},
                              'ampm':     {'l_duty': ['am', 'pm'], 'thr_hard': 1, 'thr_soft': 2}}
    dict_w_closeduty = {}
    for group, default in dict_closeduty_default.items():
        dict_w_closeduty[group] = {
            'thr_hard': widgets.IntText(value = default['thr_hard'], description = 'thr_hard', style = _STYLE),
            'thr_soft': widgets.IntText(value = default['thr_soft'], description = 'thr_soft', style = _STYLE),
        }

    w_c_assign_suboptimal = widgets.FloatText(value = 0.00001, description = 'c_assign_suboptimal', style = _STYLE)
    w_c_cnt_deviation = widgets.FloatText(value = 0.1, description = 'c_cnt_deviation', style = _STYLE)
    w_c_closeduty = widgets.FloatText(value = 0.00001, description = 'c_closeduty', style = _STYLE)

    w_type_limit = widgets.Dropdown(options = ['soft', 'hard', 'ignore'], value = 'soft',
                                    description = 'type_limit', style = _STYLE)
    w_fulltime = widgets.Text(value = '', description = 'fulltime date_duty',
                              placeholder = 'e.g. 8_night, 21_night', style = _STYLE)
    w_skip = widgets.Text(value = '', description = 'skip date_duty',
                          placeholder = 'e.g. 23_am, 23_', style = _STYLE)

    def _closeduty_box(group):
        return widgets.VBox([widgets.HTML('<b>' + group + '</b>'),
                             dict_w_closeduty[group]['thr_hard'], dict_w_closeduty[group]['thr_soft']])

    advanced = widgets.Accordion(children = [widgets.VBox([
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
    advanced.set_title(0, 'Advanced solver parameters')
    advanced.selected_index = None  # collapsed by default

    button = widgets.Button(description = 'Run Optimization', button_style = 'primary')
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
            optimize_count_and_assign(lp_root, state.year_plan, state.month_plan, year_start, month_start,
                                      l_class_duty, dict_c_diff_score_current, dict_c_diff_score_total,
                                      l_date_duty_skip_manual, dict_closeduty, ll_avoid_adjacent,
                                      l_title_fulltime, l_date_duty_fulltime, w_type_limit.value,
                                      w_c_assign_suboptimal.value, w_c_cnt_deviation.value, w_c_closeduty.value,
                                      dict_score_duty, dict_score_class, dict_class_duty)
        _run_in_output(output, run)
    button.on_click(on_click)

    return widgets.VBox([widgets.HTML('<h3>Optimize Assignment</h3>'), advanced, button, output])


###############################################################################
# Notify Google calendar (replaces main.ipynb cell 4)
###############################################################################
def build_notify_panel(state):
    button = widgets.Button(description = 'Publish to Calendar', button_style = 'primary')
    output = widgets.Output()

    def on_click(_):
        def run():
            update_calendar(lp_root, state.year_plan, state.month_plan, id_calendar, dict_time_duty, t_sleep)
        _run_in_output(output, run)
    button.on_click(on_click)

    return widgets.VBox([widgets.HTML('<h3>Publish to Calendar</h3>'), button, output])


###############################################################################
# Collect replacement application (replaces main.ipynb cell 5)
###############################################################################
def build_replace_check_panel(state):
    button = widgets.Button(description = 'Check Replacement Requests', button_style = 'primary')
    output = widgets.Output()

    def on_click(_):
        def run():
            state.d_replace_checked = check_replacement(lp_root, state.year_plan, state.month_plan)
            display(state.d_replace_checked)
        _run_in_output(output, run)
    button.on_click(on_click)

    return widgets.VBox([widgets.HTML('<h3>Check Replacement Requests</h3>'), button, output])


###############################################################################
# Apply checked replacement plan (replaces main.ipynb cell 6)
###############################################################################
def build_replace_apply_panel(state):
    button = widgets.Button(description = 'Apply Replacement', button_style = 'primary')
    output = widgets.Output()

    def on_click(_):
        def run():
            if state.d_replace_checked is None:
                print("Run 'Check Replacement Requests' first.")
                return
            replace_assignment(lp_root, state.year_plan, state.month_plan, dict_score_duty, l_class_duty,
                               state.d_replace_checked)
        _run_in_output(output, run)
    button.on_click(on_click)

    return widgets.VBox([widgets.HTML('<h3>Apply Replacement</h3>'), button, output])


###############################################################################
# Combined app: one panel, all stages -- the function main.ipynb calls
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
    tab = widgets.Tab(children = [panel for _, panel in l_tab])
    for i, (title, _) in enumerate(l_tab):
        tab.set_title(i, title)

    return widgets.VBox([params_panel, tab])
