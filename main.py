###############################################################################
# Libraries
###############################################################################
from form import *
from collect import *
from assign import *
from check import *
from replace import *


###############################################################################
# Unfixed parameters
###############################################################################
# Related to all functions
year_plan = 2024
month_plan = 3
l_holiday = [20]
l_date_ect_cancel = []

# Related to response collection
#address_response = "https://docs.google.com/spreadsheets/d/1kQ-5CSB1tyoa8tQKnXxyLJGs26O-PB6fapb_woeQOqc/edit?resourcekey#gid=85558763"
#address_response = "https://docs.google.com/spreadsheets/d/1WGJX7bzoD1EKZCXhHtNaeFHwXlA2ZtaV0Hpoz23gshQ/edit?resourcekey#gid=370013882"
address_response = "https://docs.google.com/spreadsheets/d/1-EtioCPAsdYj-2Hl_cKlM2EcFCZMqpVSRVG-BfPgGy0/edit?resourcekey#gid=1100814982"

# Related to assignment count optimization
dict_c_diff_score_current = {'ampm': 0.001, 'daynight': 0.001, 'ampmdaynight': 0.001, 'oc': 0.001, 'ect': 0.01}
#dict_c_diff_score_total = {'ampm': 0.01, 'daynight': 0.01, 'ampmdaynight': 0.01, 'oc': 0.01, 'ect': 0.1}
dict_c_diff_score_total = {'ampm': 0.01, 'daynight': 0.01, 'ampmdaynight': 1.0, 'oc': 0.01, 'ect': 0.1}

# Related to individual assignment
c_assign_suboptimal = 0.0001
#c_cnt_deviation = 0.001
c_cnt_deviation = 0.1
c_closeduty = 0.01
#c_closeduty = 0.1

l_date_duty_fulltime = []
type_limit = 'soft' # 'hard': never exceed, 'soft': outlier penalized, 'ignore': no penalty
l_date_duty_skip_manual = []
#l_date_duty_skip_manual = ['23_'] # All duties starting with 23_
#l_date_duty_skip_manual = ['23_am']

###############################################################################
# Fixed parameters
###############################################################################
# Used for assignment
year_start = 2023
month_start = 4

# Fixed parameters for optimizing assignment count
l_day_ect = [0, 2, 3] # Monday, Wednesday, Thursday
day_em = 2 # Wednesday
l_week_em = [] # 1st and 3rd weeks
l_type_score = ['ampm','daynight','ampmdaynight','oc','ect']
l_class_duty = ['ampm','daynight_tot','night_em','night_wd','daynight_hd','oc_tot','oc_day','oc_night','ect']
dict_duty = {'ect': 0, 'am': 1, 'pm': 2, 'day': 3, 'ocday': 4, 'night': 5, 'emnight':6, 'ocnight': 7}

# Fixed parameters for optimizing assignment
# Parameters for avoiding/penalizing close duties
dict_closeduty = {'daynight': {'l_duty': ['day', 'ocday', 'night', 'emnight', 'ocnight'], 'thr_hard': 1, 'thr_soft': 5},
                  'ect':      {'l_duty': ['ect'],                                         'thr_hard': 1, 'thr_soft': 4},
                  'ampm':     {'l_duty': ['am', 'pm'],                                    'thr_hard': 1, 'thr_soft': 5}}
# Parameters for avoiding overlapping duties
ll_avoid_adjacent = [[['pm', 0], ['night', 0], ['emnight', 0], ['ocnight', 0]],
                     [['night', 0], ['emnight', 0], ['ocnight', 0], ['ect', 1], ['am', 1]]]
l_title_fulltime = ['assist'] # ['limterm_instr', 'assist', 'limterm_clin']

# Parameters for replacement
sheet_id = "1glzf0fM1jyAZffFE7l7SHE26m3M4QBI5AAOsdSlmHxE"
l_scope = ['https://www.googleapis.com/auth/calendar']


###############################################################################
# Create Google form
###############################################################################

d_cal, d_date_duty, s_cnt_duty, s_cnt_class_duty, d_cal_duty, d_form =\
    prep_form(year_plan, month_plan, l_holiday, l_date_ect_cancel)


###############################################################################
# Collect google form response
###############################################################################

str_member_missing, str_mail_missing, d_availability, d_info, d_member =\
    collect_availability(year_plan, month_plan, address_response)


###############################################################################
# Optimize assignment count and assign members
###############################################################################
d_assign, d_assign_date_print, d_assign_member, d_deviation, d_score_print, d_closeduty =\
    optimize_count_and_assign(year_plan, month_plan, year_start, month_start,
                              l_type_score, l_class_duty, dict_c_diff_score_current, dict_c_diff_score_total,
                              l_date_duty_skip_manual, dict_closeduty, ll_avoid_adjacent,
                              l_title_fulltime, l_date_duty_fulltime, type_limit,
                              c_assign_suboptimal, c_cnt_deviation, c_closeduty)


###############################################################################
# Replace assignment
###############################################################################
# Load from Gforms result and check
d_replace_checked = check_replacement(year_plan, month_plan, sheet_id)

# Apply checked replacement plan
d_assign, d_assign_date_print, d_assign_member, d_deviation, d_deviation_summary, d_score_current, d_score_total, d_score_print =\
    replace_assignment(year_plan, month_plan, l_type_score, l_class_duty, d_replace_checked)

# Add new event to Gcalendar
l_result_event = add_replaced_calendar(year_plan, month_plan, d_replace_checked, l_scope)


###############################################################################
# Check availability of certain date_duty
###############################################################################
date_duty = '20_night'

check_availability_date_duty(year_plan, month_plan, date_duty)


###############################################################################
# Check availability of certain member
###############################################################################
id_member = 37

check_availability_member(year_plan, month_plan, id_member)

# 3_day from 浅井 to 古川
# 3_ocday from None to 安藤
# 24_night from 浅井 to 南拓人
# 18_night from 熊倉 to 森田進
# 12_day from 小林慧 to 星野
# 7_pm from None to 森田進
# 5_night from 星野 to 越山

# 浅井 daynight -2
# 安藤 oc +1
# 南拓人 daynight +1
# 熊倉 daynight -1
# 森田進 daynight +1
# 小林慧 daynight -1
# 星野 daynight +-0
# 越山 daynight +1




# 24_day from 古川 to 小林慧
# 11_ocday from 榊原 to None