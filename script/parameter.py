
###############################################################################
# Fixed parameters
###############################################################################
# General
year_start, month_start = 2025, 4
lp_root = ['/home/atiroms/Documents','D:/atiro','D:/NICT_WS','/Users/smrt']
# Form
dict_duty = {'ect': 0, 'am': 1, 'pm': 2, 'day': 3, 'ocday': 4, 'night': 5, 'emnight':6, 'ocnight': 7}
dict_duty_jpn = {'am': '午前日直', 'pm': '午後日直', 'day': '日直', 'ocday': '日直OC', 'night': '当直', 'emnight': '救急当直', 'ocnight': '当直OC'}
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
id_template_form   = '1TPqbvxc4Sgj6qhMkSE0eCciFxEaOsgNQIduu29SUwZA'
dict_itemid_form = {'assoc_holiday': '3fd28d79', 'assoc_others': '03f37999',
                    'instr_holiday': '49978020', 'instr_others': '015bf8cf',
                    'assist_leader_holiday': '6f8a4c28', 'assist_leader_others': '5a3e91e3',
                    'assist_subleader_holiday': '3f06625b', 'assist_subleader_others': '5301996a',
                    'limtermclin_holiday': '02401b89', 'limtermclin_others': '0e55b20f',
                    'stud_holiday': '48b9378b', 'stud_others': '32b66da2'}

# Optimizing assignment count
l_day_ect = [0, 2, 3] # Monday, Wednesday, Thursday
day_em, l_week_em = 2, [] # Wednesday, 1st and 3rd weeks
l_class_duty = ['ampm','daynight_tot','night_em','night_wd','daynight_hd','oc_tot','oc_day','oc_night','ect']
dict_score_class = {'score': ['ampm', 'daynight', 'daynight', 'ampmdaynight', 'ampmdaynight', 'ampmdaynight', 'oc', 'ect'],
                    'class': ['ampm', 'daynight_tot', 'night_em', 'ampm', 'daynight_tot', 'night_em', 'oc_tot', 'ect'],
                    'constant': [0.5, 1, 0.5, 0.5, 1, 0.5, 1, 1]}
# Optimizing assignment, parameters for avoiding overlapping duties
ll_avoid_adjacent = [[['pm', 0], ['night', 0], ['emnight', 0], ['ocnight', 0]],
                     [['night', 0], ['emnight', 0], ['ocnight', 0], ['ect', 1], ['am', 1]]]
l_title_fulltime = ['assist'] # ['limterm_instr', 'assist', 'limterm_clin']
# Notification
id_calendar = 'ht4svlr03krt7jcqho5guou32c@group.calendar.google.com'
t_sleep = 600.0
dict_time_duty = {'duty': ['am', 'pm', 'day', 'night', 'emnight', 'ocday', 'ocnight', 'ect'],
                  'duty_jpn': ['午前日直', '午後日直', '日直', '当直', '救急当直', '日直OC', '当直OC', 'ECT当番'],
                  'start': ['08:30', '12:30', '08:30', '17:15', '17:15', '08:30', '17:15', '07:30'],
                  'end':   ['12:30', '17:15', '17:15', '32:30', '32:30', '17:15', '32:30', '11:00']}
# Parameters for replacement
#sheet_id = "1glzf0fM1jyAZffFE7l7SHE26m3M4QBI5AAOsdSlmHxE"
#l_scope = ['https://www.googleapis.com/auth/calendar']