
###############################################################################
# Libraries
###############################################################################
import numpy as np, pandas as pd
import os, datetime
from pulp import *
from ortoolpy import addbinvars


###############################################################################
# Parameters
###############################################################################
# Unfixed parameters
year_plan = 2022
month_plan = 6
#month_plan = 5
#month_plan = 4

f_availability = 'availability.csv'
#f_availability = 'availability2.csv'
#f_availability = 'availability3.csv'

# Fixed parameters
l_class_duty = ['ampm','daynight_tot','night_em','night_wd','daynight_hd','oc_tot','oc_day','oc_night','ect']

c_assign_suboptimal = 0.1
thr_interval_daynight = 4
thr_interval_ect = 3
thr_interval_ampm = 2


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
    d_data = datetime.datetime.now().strftime('assign_%Y%m%d_%H%M%S')
    p_result = os.path.join(p_month, 'result')
    p_data = os.path.join(p_result, d_data)
    for p_dir in [p_result, p_data]:
        if not os.path.exists(p_dir):
            os.makedirs(p_dir)

from helper import *


###############################################################################
# Load and prepare data
###############################################################################
# Prepare data of member availability
d_date_duty = pd.read_csv(os.path.join(p_month, 'date_duty.csv'))
d_cal = pd.read_csv(os.path.join(p_month, 'calendar.csv'))
d_member = pd.read_csv(os.path.join(p_month, 'member.csv'))
d_availability, l_member = prep_availability(p_month, p_data, f_availability, d_date_duty, d_cal)


###############################################################################
# Initialize assignment problem and model
###############################################################################
# Initialize model to be optimized
prob_assign = LpProblem()

# Binary assignment variables to be optimized
dv_assign = pd.DataFrame(np.array(addbinvars(len(d_date_duty), len(l_member))),
                         columns = l_member, index = d_date_duty['date_duty'].to_list())


###############################################################################
# Availability per member per date_duty
###############################################################################
# Do not assign to a date if not available
prob_assign += (lpDot((d_availability == 0).to_numpy(), dv_assign.to_numpy()) <= 0)

# Penalize suboptimal assignment
v_assign_suboptimal = lpDot((d_availability == 1).to_numpy(), dv_assign.to_numpy())


###############################################################################
# Assignment per date_duty
###############################################################################
# Assign one member per date_duty for ['am', 'pm', 'day', 'night', 'emnight', 'ect']
for duty in ['am', 'pm', 'day', 'night', 'emnight', 'ect']:
    for date_duty in d_date_duty[d_date_duty['duty'] == duty]['date_duty'].to_list():
        prob_assign += (lpSum(dv_assign.loc[date_duty]) == 1)

# Assign one member per date_duty for ['oc_day', 'oc_night'],
# if non-designated member is assigned to ['day', 'night'] for the same date/time
for duty in ['day', 'night']:
    for date in d_date_duty[d_date_duty['duty'] == duty]['date'].to_list():
        date_duty = str(date) + '_' + duty
        date_duty_oc = str(date) + '_oc' + duty
        if date_duty_oc in d_date_duty['date_duty'].to_list():
            # Sum of dot product of (normal and oc assignments) and (designation)
            # Returns number of 'designated' member assigned in the same date/time, which should be 1
            prob_assign += (lpSum(lpDot(dv_assign.loc[[date_duty, date_duty_oc]].to_numpy(),
                                    np.array([d_member.loc[d_member['id_member'].isin(l_member), 'designation']]*2))) == 1)


###############################################################################
# Penalize limit outliers per member per class_duty
###############################################################################
d_lim_exact = pd.read_csv(os.path.join(p_month, 'lim_exact.csv'))
for member in l_member:
    for class_duty in l_class_duty:
        cnt_assign = d_lim_exact.loc[member, class_duty]
        if ~np.isnan(cnt_assign):
            prob_assign += (lpDot(dv_assign.loc[:, member], d_date_duty.loc[:, 'class_' + class_duty]) == cnt_assign)
            

###############################################################################
# Avoid overlapping / adjacent / close assignments
###############################################################################
# Penalize ['day', 'ocday', 'night', 'ocnight'] in N(thr_interval_daynight) continuous days
# Penalize 'ect' in N(thr_interval_ect) continuous days
# Penalize ['am','pm'] in N(thr_interval_ampm) continuous days
# TODO: consider previous month assignment
l_closeduty = [[thr_interval_daynight, ['day', 'ocday', 'night', 'ocnight']],
               [thr_interval_ect, ['ect']],
               [thr_interval_ampm, ['am', 'pm']]]

for closeduty in l_closeduty:
    thr_interval = closeduty[0]
    l_duty = closeduty[1]
    for date_start in [d for d in range(-thr_interval + 2, 1)] + d_cal['date'].tolist():
        # Create list of continuous date_duty's
        l_date_duty_temp = []
        for date in range(date_start, date_start + thr_interval):
            for duty in l_duty:
                date_duty_temp = str(date) + '_' + duty
                if date_duty_temp in dv_assign.index:
                    l_date_duty_temp.append(date_duty_temp)
        if len(l_date_duty_temp) >= 2:
            for member in l_member:
                prob_assign += (lpSum(dv_assign.loc[l_date_duty_temp, member]) <= 1)

# Avoid [same-date 'pm', 'night' and 'ocnight'],
#   and ['night', 'ocnight' and following-date 'ect','am']
# TODO: consider previous month assignment
# TODO: consider team leader ECT assignment (defined elsewhere)
for date in [0] + d_cal['date'].tolist():
    date_duty_am = str(date) + '_am'
    date_duty_pm = str(date) + '_pm'
    date_duty_night = str(date) + '_night'
    date_duty_ocnight = str(date) + '_ocnight'
    date_duty_ect_next = str(date+1) + '_ect'
    date_duty_am_next = str(date+1) + '_am'
    # List of lists of date_duty groups to avoid
    ll_avoid = [[date_duty_pm, date_duty_night, date_duty_ocnight],
                [date_duty_night, date_duty_ocnight, date_duty_ect_next, date_duty_am_next]]
    for l_avoid in ll_avoid:
        # Check if date_duty exists
        l_date_duty_temp = []
        for date_duty in l_avoid:
            if date_duty in dv_assign.index:
                l_date_duty_temp.append(date_duty)
        if len(l_date_duty_temp) >= 2:
            for member in l_member:
                prob_assign += (lpSum(dv_assign.loc[l_date_duty_temp, member]) <= 1)


###############################################################################
# Avoid ECT from the leader's team
###############################################################################
l_date_ect = d_cal.loc[d_cal['ect'] == True, 'date'].to_list()
l_team = sorted(list(set(d_member['team'].to_list())))
for date in l_date_ect:
    wday = d_cal.loc[d_cal['date'] == date, 'wday'].to_list()[0]
    team_leader = d_member.loc[d_member['ect_leader'] == str(wday), 'team'].to_list()[0]
    if team_leader != '-':
        l_id_member_team = d_member.loc[d_member['team'] == team_leader, 'id_member'].to_list()
        for id_member in l_id_member_team:
            prob_assign += (dv_assign.loc[str(date) + '_ect', id_member] == 0)


###############################################################################
# Define objective function to be minimized
###############################################################################
prob_assign += (c_assign_suboptimal * v_assign_suboptimal)

          
###############################################################################
# Solve problem
###############################################################################
# Print problem
#print('Problem: ', problem)

# Solve problem
prob_assign.solve()
v_objective = value(prob_assign.objective)
print('Solved: ' + str(LpStatus[prob_assign.status]) + ', ' + str(round(v_objective, 2)))


###############################################################################
# Extract data
###############################################################################
d_assign_date_duty, d_assign_date_print, d_assign_member =\
    prep_assign2(p_month, p_data, dv_assign, d_availability, d_member, l_member, d_date_duty, d_cal)

