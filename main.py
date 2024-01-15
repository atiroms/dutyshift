###############################################################################
# Libraries
###############################################################################
from form import *
from collect import *


###############################################################################
# Unfixed parameters
###############################################################################
# Related to all functions
year_plan = 2024
month_plan = 2
l_holiday = [12, 23]
l_date_ect_cancel = []

# Related to response collection
address_response = "https://docs.google.com/spreadsheets/d/1kQ-5CSB1tyoa8tQKnXxyLJGs26O-PB6fapb_woeQOqc/edit?resourcekey#gid=85558763"

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

