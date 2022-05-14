
###############################################################################
# Libraries
###############################################################################
import pandas as pd
import os, datetime


###############################################################################
# Parameters
###############################################################################
# Unfixed parameters
#year_plan = 2022
#month_plan = 4
#l_holiday = [29]
year_plan = 2022
month_plan = 5
l_holiday = [3, 4, 5]
l_date_ect_cancel = [25]
#l_date_ect_cancel = []

#f_member = 'member.csv'
f_member = 'member6.csv'

# Fixed parameters
l_day_ect = [0, 2, 3] # Monday, Wednesday, Thursday
day_em = 2 # Wednesday
l_week_em = [1, 3] # 1st and 3rd weeks

l_type_score = ['ampm','daynight','ampmdaynight','oc','ect']
l_class_duty = ['ampm','daynight_tot','night_em','night_wd','daynight_hd','oc_tot','oc_day','oc_night','ect']
dict_duty = {'ect': 0, 'am': 1, 'pm': 2, 'day': 3, 'ocday': 4, 'night': 5, 'emnight':6, 'ocnight': 7}

dict_c_diff_score_current = {'ampm': 0.001, 'daynight': 0.001, 'ampmdaynight': 0.01, 'oc': 0.001, 'ect': 0.01}
dict_c_diff_score_total = {'ampm': 0.01, 'daynight': 0.01, 'ampmdaynight': 0.1, 'oc': 0.01, 'ect': 0.1}


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
    d_data = datetime.datetime.now().strftime('plan_%Y%m%d_%H%M%S')
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

# Prepare data of member specs and assignment limits
d_member, d_score_past, d_lim_hard, d_lim_soft, d_grp_score \
    = prep_member2(p_root, p_month, p_data, f_member, l_class_duty, year_plan, month_plan)


###############################################################################
# Optimize exact assignment count
###############################################################################
d_score_class = pd.read_csv(os.path.join(p_root, 'Dropbox/dutyshift/config/score_class.csv'))

# Optimize assignment counts except OC
d_lim_exact_notoc, d_score_current_notoc, d_score_total_notoc,\
d_sigma_diff_score_current_notoc, d_sigma_diff_score_total_notoc = \
    optimize_count(d_member, s_cnt_class_duty, d_lim_hard, d_score_past,
                   d_score_class, d_grp_score, dict_c_diff_score_current, dict_c_diff_score_total,
                   l_type_score = ['ampm', 'daynight', 'ampmdaynight', 'ect'],
                   l_class_duty = ['ampm', 'daynight_tot', 'night_em', 'ect'])

# Optimize assignment counts of OC
ln_daynight = d_lim_exact_notoc['daynight_tot'].tolist()
#l_designation = d_member.loc[d_member['id_member'].isin(l_member), 'designation'].tolist()
l_designation = d_member['designation'].tolist()
n_oc_required = int(sum([x * (y == False) for x, y in zip(ln_daynight, l_designation)]))
s_cnt_class_duty['oc_tot'] = n_oc_required

d_lim_exact_oc, d_score_current_oc, d_score_total_oc,\
d_sigma_diff_score_current_oc, d_sigma_diff_score_total_oc = \
    optimize_count(d_member, s_cnt_class_duty, d_lim_hard, d_score_past,
                   d_score_class, d_grp_score, dict_c_diff_score_current, dict_c_diff_score_total,
                   l_type_score = ['oc'],
                   l_class_duty = ['oc_tot'])

d_lim_exact = pd.concat([d_lim_exact_notoc, d_lim_exact_oc], axis = 1)
for col in d_lim_hard.columns:
    if not col in d_lim_exact.columns:
        d_lim_exact[col] = [x[0] for x in d_lim_hard[col].tolist()]
d_lim_exact = d_lim_exact[d_lim_hard.columns]

d_score_current = pd.concat([d_score_current_notoc, d_score_current_oc], axis = 1)
d_score_total = pd.concat([d_score_total_notoc, d_score_total_oc], axis = 1)

# Save data
for p_save in [p_month, p_data]:
    d_lim_exact.to_csv(os.path.join(p_save, 'lim_exact.csv'), index = False)
    d_score_current.to_csv(os.path.join(p_save, 'score_current.csv'), index = False)
    d_score_total.to_csv(os.path.join(p_save, 'score_total.csv'), index = False)
