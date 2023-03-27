
###############################################################################
# Libraries
###############################################################################
import pandas as pd
import os, datetime


###############################################################################
# Parameters
###############################################################################
# Unfixed parameters
year_plan = 2023
month_plan = 4
l_holiday = []
l_date_ect_cancel = []

# Fixed parameters
l_day_ect = [0, 2, 3] # Monday, Wednesday, Thursday
day_em = 2 # Wednesday
l_week_em = [] # 1st and 3rd weeks

l_class_duty = ['ampm','daynight_tot','night_em','night_wd','daynight_hd','oc_tot','oc_day','oc_night','ect']
dict_duty = {'ect': 0, 'am': 1, 'pm': 2, 'day': 3, 'ocday': 4, 'night': 5, 'emnight':6, 'ocnight': 7}


###############################################################################
# Script path
###############################################################################
p_root = None
for p_test in ['/home/atiroms/Documents','D:/atiro','D:/NICT_WS','/Users/smrt']:
    if os.path.isdir(p_test):
        p_root = p_test

if p_root is None:
    print('No root directory.')
else:
    p_script=os.path.join(p_root,'GitHub/dutyshift')
    os.chdir(p_script)
    # Set paths and directories
    d_month = '{year:0>4d}{month:0>2d}'.format(year = year_plan, month = month_plan)
    p_month = os.path.join(p_root, 'Dropbox/dutyshift', d_month)
    d_data = datetime.datetime.now().strftime('form_%Y%m%d_%H%M%S')
    p_result = os.path.join(p_month, 'result')
    p_data = os.path.join(p_result, d_data)
    for p_dir in [p_result, p_data]:
        if not os.path.exists(p_dir):
            os.makedirs(p_dir)

from helper import *


###############################################################################
# Load and prepare data
###############################################################################
# Prepare calendar and all duties of the month
d_cal, d_date_duty, s_cnt_duty, s_cnt_class_duty \
    = prep_calendar(p_root, p_month, p_data, l_class_duty, l_holiday, l_day_ect, l_date_ect_cancel,
                    day_em, l_week_em, year_plan, month_plan)

# Prepare calendar for google forms
d_cal_duty, d_form = prep_forms(p_month, p_data, d_cal, dict_duty)
