
###############################################################################
# Fixed parameters
###############################################################################
import numpy as np, pandas as pd

# General
year_start, month_start = 2026, 4
# lp_root (a hardcoded list of every machine's personal Dropbox-folder path) used to live here.
# It's gone: data now lives on Google Drive, resolved by name (see script/drive_io.py), which is
# identical from every machine/account with access -- there's no per-machine path to configure.
# The one remaining machine-specific value (where local OAuth credential files live) is in each
# machine's own config.local.json (see config.local.example.json), not in this versioned file.

# Form
# Duty master table: single source of truth for duty sort order, Japanese label, and clock
# times. dict_duty / dict_duty_jpn / dict_time_duty below are derived views, kept so existing
# call sites (script/form.py, script/collect.py, script/notify.py) don't need to change.
_dict_duty_info = {'duty':     ['ect', 'am', 'pm', 'day', 'ocday', 'night', 'emnight', 'ocnight'],
                   'order':    [0, 1, 2, 3, 4, 5, 6, 7],
                   'duty_jpn': ['ECT当番', '午前日直', '午後日直', '日直', '日直OC', '当直', '救急当直', '当直OC'],
                   'start':    ['07:30', '08:30', '12:30', '08:30', '08:30', '17:15', '17:15', '17:15'],
                   'end':      ['11:00', '12:30', '17:15', '17:15', '17:15', '32:30', '32:30', '32:30']}
dict_duty = dict(zip(_dict_duty_info['duty'], _dict_duty_info['order']))
# ECT has no dedicated availability question on the Google Form -- its availability is instead
# inferred from the 'am' question on ECT days (see script/collect.py). Excluding 'ect' here is
# what makes script/form.py skip generating a form question/column for it, so keep the exclusion.
dict_duty_jpn = {duty: jpn for duty, jpn in zip(_dict_duty_info['duty'], _dict_duty_info['duty_jpn']) if duty != 'ect'}
dict_time_duty = {'duty': _dict_duty_info['duty'], 'duty_jpn': _dict_duty_info['duty_jpn'],
                  'start': _dict_duty_info['start'], 'end': _dict_duty_info['end']}

dict_jpnday = {0: '月', 1: '火', 2: '水', 3: '木', 4: '金', 5: '土', 6: '日'}
dict_score_duty = {'duty':         ['am', 'pm', 'day', 'night', 'emnight', 'ocday', 'ocnight', 'ect'],
                   'ampm':         [0.5, 0.5, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
                   'daynight':     [0.0, 0.0, 1.0, 1.0, 1.5, 0.0, 0.0, 0.0],
                   'ampmdaynight': [0.5, 0.5, 1.0, 1.0, 1.5, 0.0, 0.0, 0.0],
                   'oc':           [0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 0.0],
                   'ect':          [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0]}
dict_title_duty = {'assoc':            ['ocday', 'ocnight'],
                   'instr':            ['am', 'pm', 'ocday', 'ocnight'],
                   'assist_leader':    ['am', 'pm', 'day', 'night', 'ocday', 'ocnight'],
                   'assist_subleader': ['am', 'pm', 'day', 'night'],
                   'limtermclin':      ['am', 'pm', 'day', 'night'],
                   'stud':             ['day', 'night']}
                   #'assist_child':     ['am', 'pm']}
dict_class_duty = {'class': ['ampm', 'ampm', 'daynight_tot', 'daynight_tot', 'daynight_tot', 'night_em', 'night_wd', 'night_wd', 'daynight_hd', 'daynight_hd', 'oc_tot', 'oc_tot', 'oc_day', 'oc_night', 'ect'],
                   'date':  ['all', 'all', 'all', 'all', 'all', 'all', 'wd', 'all', 'all', 'hd', 'all', 'all', 'all', 'all', 'all'],
                   'duty':  ['am', 'pm', 'day', 'night', 'emnight', 'emnight', 'night', 'emnight', 'day', 'night', 'ocday', 'ocnight', 'ocday', 'ocnight', 'ect']}
id_template_form   = '1JweYEQfU93Ts2k2ZCvfezj01MYYtdyeyRiZ2I99zbjo'
dict_itemid_form = {'assoc_holiday': '3fd28d79', 'assoc_others': '03f37999',
                    'instr_holiday': '49978020', 'instr_others': '015bf8cf',
                    'assist_leader_holiday': '6f8a4c28', 'assist_leader_others': '5a3e91e3',
                    'assist_subleader_holiday': '3f06625b', 'assist_subleader_others': '5301996a',
                    'limtermclin_holiday': '02401b89', 'limtermclin_others': '0e55b20f',
                    'stud_holiday': '48b9378b', 'stud_others': '32b66da2'}

# Notification email drafted (never auto-sent) by script/form.py::prepare_form once a month's
# Google Form is created. {form_url} and {deadline} are filled in per month; everything else
# stays fixed.
str_email_template = '''東大精神科の日当直をご担当される先生方

平素より大変お世話になっております。
下記のフォームより、来月分の日当直の希望のご入力をお願いいたします。
{form_url}

締切は{deadline}とさせていただきます。
よろしくお願いいたします。

当直係　森田　進
調整用プログラム：https://github.com/atiroms/dutyshift'''

# Optimizing assignment count
l_day_ect = [0, 2, 3] # Monday, Wednesday, Thursday
day_em, l_week_em = 2, [] # Wednesday, 1st and 3rd weeks

# Unique class_duty names, in first-appearance order of dict_class_duty (order matters for
# output column ordering, e.g. in member.xlsx / lim_*.csv). Derived rather than hand-listed a
# second time -- script/helper.py::date_duty2class already had a commented-out line doing the
# same thing (`sorted(list(set(d_class_duty['class'].tolist())))`), just not order-preserving.
l_class_duty = list(dict.fromkeys(dict_class_duty['class']))

# Optimizing assignment, parameters for avoiding overlapping duties
ll_avoid_adjacent = [[['pm', 0], ['night', 0], ['emnight', 0], ['ocnight', 0]],
                     [['night', 0], ['emnight', 0], ['ocnight', 0], ['ect', 1], ['am', 1]]]
#l_title_fulltime = ['assist'] # ['limterm_instr', 'assist', 'limtermclin']
l_title_fulltime = ['assist', 'limtermclin'] # ['limterm_instr', 'assist', 'limtermclin']

# Troubleshooting an infeasible assignment problem (script/assign.py::optimize_count_and_assign):
# the random-subset-reduction phase keeps sampling differently-skipped subsets of a given size
# until one succeeds (narrowing the suspect set) or this many consecutive samples of that same
# size all come back infeasible -- at which point it stops trying to reduce further and moves on
# to testing the remaining suspected duties one by one.
n_troubleshoot_infeasible_max = 10

# Notification
id_calendar = 'ht4svlr03krt7jcqho5guou32c@group.calendar.google.com'
t_sleep = 600.0

# Score weight per class_duty, per score axis. This is the same underlying weighting as
# dict_score_duty (per-duty weights), just projected onto class_duty groups because the
# count-optimization stage (script/helper.py::optimize_count) only knows target *counts* per
# class_duty, not which specific duty a doctor will end up with.
#
# The 'constant' column used to be hand-solved and hand-maintained separately from
# dict_score_duty, with nothing tying the two together -- so an edit to one could silently
# desync assignment-count fairness (stage 1) from actual assignment scoring (stage 2). It's now
# derived from dict_score_duty + dict_class_duty below, with a consistency check that raises if
# the decomposition ever stops being exact.
def _derive_score_class_constants(dict_score_duty, dict_class_duty, ll_score_class):
    """For each (score_axis, class_duty) pair in ll_score_class, solve the constant such that
    summing constants over the classes each duty belongs to reproduces dict_score_duty's
    per-duty weight for that axis. Only dict_class_duty rows with date == 'all' participate:
    weekday/holiday-qualified classes (night_wd, daynight_hd, ...) exist purely for per-doctor
    count limits and never carry score weight.
    """
    d_score_duty = pd.DataFrame(dict_score_duty).set_index('duty')
    d_class_duty_all = pd.DataFrame(dict_class_duty)
    d_class_duty_all = d_class_duty_all[d_class_duty_all['date'] == 'all']

    l_constant = []
    for score in dict.fromkeys(score for score, _ in ll_score_class):
        l_class = [class_duty for s, class_duty in ll_score_class if s == score]
        l_duty = sorted(set(d_class_duty_all.loc[d_class_duty_all['class'].isin(l_class), 'duty']))
        m_incidence = np.array([[duty in set(d_class_duty_all.loc[d_class_duty_all['class'] == class_duty, 'duty'])
                                  for class_duty in l_class] for duty in l_duty], dtype = float)
        v_target = d_score_duty.loc[l_duty, score].to_numpy(dtype = float)
        v_constant, _, _, _ = np.linalg.lstsq(m_incidence, v_target, rcond = None)
        v_constant = np.round(v_constant, 6)
        if not np.allclose(m_incidence @ v_constant, v_target):
            raise ValueError(
                "dict_class_duty can't exactly reproduce dict_score_duty['" + score + "'] via classes " +
                str(l_class) + " -- dict_score_duty and dict_class_duty have drifted out of sync, or " +
                "the (score, class) structure in _ll_score_class needs updating to match.")
        l_constant.extend(v_constant.tolist())
    return l_constant

_ll_score_class = [('ampm', 'ampm'),
                   ('daynight', 'daynight_tot'), ('daynight', 'night_em'),
                   ('ampmdaynight', 'ampm'), ('ampmdaynight', 'daynight_tot'), ('ampmdaynight', 'night_em'),
                   ('oc', 'oc_tot'),
                   ('ect', 'ect')]
dict_score_class = {'score': [score for score, _ in _ll_score_class],
                    'class': [class_duty for _, class_duty in _ll_score_class],
                    'constant': _derive_score_class_constants(dict_score_duty, dict_class_duty, _ll_score_class)}

# Parameters for replacement
#sheet_id = "1glzf0fM1jyAZffFE7l7SHE26m3M4QBI5AAOsdSlmHxE"
#l_scope = ['https://www.googleapis.com/auth/calendar']
