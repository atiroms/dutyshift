
###############################################################################
# Fixed parameters
###############################################################################

# General
year_start, month_start = 2026, 4
# lp_root (a hardcoded list of every machine's personal Dropbox-folder path) used to live here.
# It's gone: data now lives on Google Drive, resolved by name (see script/drive_io.py), which is
# identical from every machine/account with access -- there's no per-machine path to configure.
# The one remaining machine-specific value (where local OAuth credential files live) is in each
# machine's own config.local.json (see config.local.example.json), not in this versioned file.

# Form
# Duty master table: single source of truth for duty sort order, Japanese label, and clock
# times. This is base data only -- the derived views (duty->order, duty->Japanese label,
# duty->clock-time table) used to be precomputed here as dict_duty/dict_duty_jpn/dict_time_duty;
# each is now derived on demand, right where it's needed, via script/helper.py::duty_order /
# duty_jpn_labels / duty_time_table (called from script/form.py, script/collect.py,
# script/notify.py, script/gui.py).
dict_duty_info = {'duty':     ['ect', 'am', 'pm', 'day', 'ocday', 'night', 'emnight', 'ocnight'],
                  'order':    [0, 1, 2, 3, 4, 5, 6, 7],
                  'duty_jpn': ['ECT当番', '午前日直', '午後日直', '日直', '日直OC', '当直', '救急当直', '当直OC'],
                  'start':    ['07:30', '08:30', '12:30', '08:30', '08:30', '17:15', '17:15', '17:15'],
                  'end':      ['11:00', '12:30', '17:15', '17:15', '17:15', '32:30', '32:30', '32:30']}

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
# id_template_form, dict_itemid_form (the Google Form template to copy each month and that
# template's grid-question item IDs) used to be hardcoded here. They're now stored on Drive at
# dutyshift/config/config.json, edited without a code change, and read fresh on every "1. Create
# Form" click -- see script/helper.py::load_drive_config (which also seeds that file with this
# codebase's original values the first time it's read). Same for id_calendar (below,
# dutyshift/config/config.json's id_calendar) and every email-notification template (below,
# dutyshift/template/<name>.json -- see script/helper.py::load_email_template).

# HTML button embedded in every notification email drafted by script/form.py, script/collect.py
# and script/notify.py, in place of a bare URL. {url} and {label} are filled in per email --
# {label} comes from that email's Drive template (dutyshift/template/<name>.json's
# 'button_label'), {url} from whatever the email is linking to (the Google Form's responder URL,
# or the assignment Google Sheet's URL). This stays a fixed, hand-edited style constant rather
# than moving to Drive with the email wording -- it's visual styling, not "email text".
str_email_button_html = ('<a href="{url}" style="display:inline-block;padding:10px 24px;'
                         'background-color:#1a73e8;color:#ffffff;text-decoration:none;'
                         'border-radius:4px;font-weight:bold;">{label}</a>')

# Optimizing assignment count
l_day_ect = [0, 2, 3] # Monday, Wednesday, Thursday
day_em, l_week_em = 2, [] # Wednesday, 1st and 3rd weeks

# The unique class_duty names, in first-appearance order of dict_class_duty (order matters for
# output column ordering, e.g. in the member Google Sheet / lim_*.csv), used to be precomputed
# here as l_class_duty. It's now derived on demand via script/helper.py::class_duty_names,
# called from each function that needs it.

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
# id_calendar (target Google Calendar for "4. Notify") now lives in dutyshift/config/config.json
# on Drive -- see the id_template_form/dict_itemid_form comment above.
# Passed as num_retries to each Calendar API .execute() call: googleapiclient's built-in
# randomized-exponential-backoff retry, which already treats 403 rateLimitExceeded/
# userRateLimitExceeded (and 429/5xx) as retriable. Replaces a previous fixed 600s sleep
# between per-member update batches, which was the actual cause of multi-hour calendar
# publishes -- Calendar API's real quota (600 requests/minute/user) is far above a typical
# month's duty count, so a preventive multi-minute pause per member was never necessary.
n_retry_calendar = 5

# Which class_duty groups contribute to each score axis, for deriving score weight per
# class_duty (dict_score_class, needed because the count-optimization stage --
# script/helper.py::optimize_count -- only knows target *counts* per class_duty, not which
# specific duty a doctor will end up with). This is the base mapping; the actual per-class
# weight used to be hand-solved and hand-maintained separately from dict_score_duty here as
# dict_score_class, with nothing tying the two together -- so an edit to one could silently
# desync assignment-count fairness (stage 1) from actual assignment scoring (stage 2). It's now
# derived on demand from dict_score_duty + dict_class_duty + this mapping via
# script/helper.py::score_class_table (which raises if the decomposition ever stops being
# exact) -- see script/assign.py::optimize_count_and_assign for the one call site.
dict_score_classes = {'ampm':         ['ampm'],
                      'daynight':     ['daynight_tot', 'night_em'],
                      'ampmdaynight': ['ampm', 'daynight_tot', 'night_em'],
                      'oc':           ['oc_tot'],
                      'ect':          ['ect']}

# Parameters for replacement
#sheet_id = "1glzf0fM1jyAZffFE7l7SHE26m3M4QBI5AAOsdSlmHxE"
#l_scope = ['https://www.googleapis.com/auth/calendar']
