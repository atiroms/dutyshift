
###############################################################################
# Fixed parameters
###############################################################################

# General
year_start, month_start = 2026, 4

# Form
# Duty master table: single source of truth for duty sort order, Japanese label, and clock
# times. Base data only -- script/helper.py::duty_order / duty_jpn_labels / duty_time_table
# derive the views each call site actually needs (script/form.py, script/collect.py,
# script/notify.py, script/gui.py).
dict_duty_info = {'duty':     ['ect', 'am', 'pm', 'day', 'ocday', 'night', 'emnight', 'ocnight'],
                  'order':    [0, 1, 2, 3, 4, 5, 6, 7],
                  'duty_jpn': ['ECT当番', '午前日直', '午後日直', '日直', '日直OC', '当直', '救急当直', '当直OC'],
                  'start':    ['07:30', '08:30', '12:30', '08:30', '08:30', '17:15', '17:15', '17:15'],
                  'end':      ['11:00', '12:30', '17:15', '17:15', '17:15', '32:30', '32:30', '32:30']}

dict_jpnday = {0: '月', 1: '火', 2: '水', 3: '木', 4: '金', 5: '土', 6: '日'}

# Per-duty score weight, along several scoring axes -- drives the fairness/equity objective in
# the count-optimization stage (script/helper.py::optimize_count).
dict_score_duty = {'duty':         ['am', 'pm', 'day', 'night', 'emnight', 'ocday', 'ocnight', 'ect'],
                   'ampm':         [0.5, 0.5, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
                   'daynight':     [0.0, 0.0, 1.0, 1.0, 1.5, 0.0, 0.0, 0.0],
                   'ampmdaynight': [0.5, 0.5, 1.0, 1.0, 1.5, 0.0, 0.0, 0.0],
                   'oc':           [0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 0.0],
                   'ect':          [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0]}

# Which duty types each doctor title is eligible for.
dict_title_duty = {'assoc':            ['ocday', 'ocnight'],
                   'instr':            ['am', 'pm', 'ocday', 'ocnight'],
                   'assist_leader':    ['am', 'pm', 'day', 'night', 'ocday', 'ocnight'],
                   'assist_subleader': ['am', 'pm', 'day', 'night'],
                   'limtermclin':      ['am', 'pm', 'day', 'night'],
                   'stud':             ['day', 'night']}

# class_duty aggregation rules: for each class_duty, the (weekday/holiday qualifier, raw duty)
# pairs that count toward it -- used for per-doctor count limits (config/member) and, via
# dict_score_classes below, for scoring. script/helper.py::class_duty_names derives the unique
# class_duty name list on demand from this table.
dict_class_duty = {'class': ['ampm', 'ampm', 'daynight_tot', 'daynight_tot', 'daynight_tot', 'night_em', 'night_wd', 'night_wd', 'daynight_hd', 'daynight_hd', 'oc_tot', 'oc_tot', 'oc_day', 'oc_night', 'ect'],
                   'date':  ['all', 'all', 'all', 'all', 'all', 'all', 'wd', 'all', 'all', 'hd', 'all', 'all', 'all', 'all', 'all'],
                   'duty':  ['am', 'pm', 'day', 'night', 'emnight', 'emnight', 'night', 'emnight', 'day', 'night', 'ocday', 'ocnight', 'ocday', 'ocnight', 'ect']}

# HTML button embedded in every notification email drafted by script/form.py, script/collect.py
# and script/notify.py, in place of a bare URL. {url} and {label} are filled in per email --
# {label} comes from that email's Drive template (dutyshift/template/<name>.json's
# 'button_label'), {url} from whatever the email is linking to (the Google Form's responder URL,
# or the assignment Google Sheet's URL). Stays a fixed, hand-edited style constant rather than
# moving to Drive with the email wording -- it's visual styling, not "email text".
str_email_button_html = ('<a href="{url}" style="display:inline-block;padding:10px 24px;'
                         'background-color:#1a73e8;color:#ffffff;text-decoration:none;'
                         'border-radius:4px;font-weight:bold;">{label}</a>')

# Optimizing assignment count
l_day_ect = [0, 2, 3] # Monday, Wednesday, Thursday
day_em, l_week_em = 2, [] # Wednesday, 1st and 3rd weeks

# Optimizing assignment, parameters for avoiding overlapping duties
ll_avoid_adjacent = [[['pm', 0], ['night', 0], ['emnight', 0], ['ocnight', 0]],
                     [['night', 0], ['emnight', 0], ['ocnight', 0], ['ect', 1], ['am', 1]]]
l_title_fulltime = ['assist', 'limtermclin'] # ['limterm_instr', 'assist', 'limtermclin']

# Troubleshooting an infeasible assignment problem (script/assign.py::optimize_count_and_assign):
# the random-subset-reduction phase keeps sampling differently-skipped subsets of a given size
# until one succeeds (narrowing the suspect set) or this many consecutive samples of that same
# size all come back infeasible -- at which point it stops trying to reduce further and moves on
# to testing the remaining suspected duties one by one.
n_troubleshoot_infeasible_max = 10

# Notification
# Passed as num_retries to each Calendar API .execute() call: googleapiclient's built-in
# randomized-exponential-backoff retry, which already treats 403 rateLimitExceeded/
# userRateLimitExceeded (and 429/5xx) as retriable. Calendar API's real quota (600
# requests/minute/user) is far above a typical month's duty count, so no additional pacing
# between calls is needed.
n_retry_calendar = 5

# Which class_duty groups contribute to each score axis ({score axis: [class_duty, ...]}), for
# deriving score weight per class_duty -- needed because the count-optimization stage
# (script/helper.py::optimize_count) only knows target *counts* per class_duty, not which
# specific duty a doctor will end up with. script/helper.py::score_class_table derives the actual
# per-class weight on demand from this mapping + dict_score_duty + dict_class_duty, raising
# ValueError if the decomposition ever stops being exact.
dict_score_classes = {'ampm':         ['ampm'],
                      'daynight':     ['daynight_tot', 'night_em'],
                      'ampmdaynight': ['ampm', 'daynight_tot', 'night_em'],
                      'oc':           ['oc_tot'],
                      'ect':          ['ect']}
