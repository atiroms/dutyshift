
###############################################################################
# Libraries
###############################################################################
import numpy as np, pandas as pd
import os, datetime, calendar
from math import ceil
from pulp import *
from ortoolpy import addvars, addbinvars


###############################################################################
# Parameters
###############################################################################
# Unfixed parameters
#year_plan = 2022
#month_plan = 4
#l_holiday = [29]
year_plan = None
month_plan = None
l_holiday = [3, 4, 5]

#p_src = 'D:/NICT_WS/Dropbox/dutyshift/test'
#p_src = 'D:/atiro/Dropbox/dutyshift/test'
#p_dst = 'D:/atiro/Dropbox/dutyshift/test'
p_src = '/Users/smrt/Dropbox/dutyshift/test'
p_dst = '/Users/smrt/Dropbox/dutyshift/test'
f_member = 'member03.csv'
f_availability = 'availability02.csv'

# Fixed parameters
l_day_ect = [0, 2, 3] # Monday, Wednesday, Thursday
day_em = 2 # Wednesday
l_week_em = [1, 3] # 1st and 3rd weeks

l_class_duty = ['day_wd','day_hd','night_tot','night_em','night_wd','night_hd','oc_tot','oc_hd_day','oc_other','ect']
dict_duty = {'ect': 0, 'am': 1, 'pm': 2, 'day': 3, 'ocday': 4, 'night': 5, 'ocnight': 6}
c_outlier_hard = 0.7
c_outlier_soft = 0.3
thr_interval = 4
c_interval = 0.5
c_assign_suboptimal = 0.1

###############################################################################
# Script path
###############################################################################
path_script=None
for dir in ['/home/atiroms/Documents','D:/atiro','C:/Users/NICT_WS','/Users/smrt']:
    if os.path.isdir(dir):
        path_script=os.path.join(dir,'GitHub/dutyshift')
        os.chdir(path_script) 
if path_script is None:
    print('No Script directory.')

from helper import *


###############################################################################
# Load and prepare data
###############################################################################
# Prepare calendar of the month
d_cal, l_date, d_date_duty, d_duty_date_class, year_plan, month_plan \
    = prep_calendar(l_holiday, l_day_ect, day_em, l_week_em, year_plan, month_plan)

d_cal_duty = prep_forms(p_dst, d_cal, month_plan, dict_duty)

# Prepare data of member specs and assignment limits
d_member, d_lim_hard, d_lim_soft = prep_member(p_src, f_member, l_class_duty)

# Prepare data of member availability
d_availability, l_member = prep_availability(p_src, f_availability, d_date_duty, d_member, d_cal)


###############################################################################
# Initialize model and variables to be optimized
###############################################################################
# Binary assignment variables to be optimized
dv_assign = pd.DataFrame(np.array(addbinvars(len(d_date_duty), len(l_member))),
                         columns = l_member, index = d_date_duty['date_duty'].to_list())

# Initialize model to be optimized
problem = LpProblem()


###############################################################################
# Availability per member per date_duty
###############################################################################
# Do not assign to a date if not available
problem += (lpDot((d_availability == 0).to_numpy(), dv_assign.to_numpy()) <= 0)

# Penalize suboptimal assignment
v_assign_suboptimal = lpDot((d_availability == 1).to_numpy(), dv_assign.to_numpy())


###############################################################################
# Assignment per date_duty
###############################################################################
# Assign one member per date_duty for ['am', 'pm', 'day', 'night', 'ect']
for duty in ['am', 'pm', 'day', 'night', 'ect']:
    for date_duty in d_date_duty[d_date_duty['duty'] == duty]['date_duty'].to_list():
        problem += (lpSum(dv_assign.loc[date_duty]) == 1)

# Assign one member per date_duty for ['oc_day', 'oc_night'],
# if non-designated member is assigned to ['day', 'night'] for the same date/time
for duty in ['day', 'night']:
    for date in d_date_duty[d_date_duty['duty'] == duty]['date'].to_list():
        date_duty = str(date) + '_' + duty
        date_duty_oc = str(date) + '_oc' + duty
        # Sum of dot product of (normal and oc assignments) and (designation)
        # Returns number of 'designated' member assigned in the same date/time, which should be 1
        problem += (lpSum(lpDot(dv_assign.loc[[date_duty, date_duty_oc]].to_numpy(),
                                np.array([d_member.loc[d_member['id_member'].isin(l_member), 'designation']]*2))) == 1)


###############################################################################
# Penalize limit outliers per member per class_duty
###############################################################################
# Penalize excess from max or shortage from min in the shape of '\__/'
dv_outlier_hard = pd.DataFrame(np.array(addvars(len(l_member), len(l_class_duty))),
                               columns = l_class_duty, index = l_member)
dv_outlier_soft = pd.DataFrame(np.array(addvars(len(l_member), len(l_class_duty))),
                               columns = l_class_duty, index = l_member)
for member in l_member:
    for class_duty in l_class_duty:
        lim_hard = d_lim_hard.loc[member, class_duty]
        if ~np.isnan(lim_hard[0]):
            problem += (dv_outlier_hard.loc[member, class_duty] >= \
                        lpDot(dv_assign.loc[:, member], d_duty_date_class.loc[:, class_duty]) - lim_hard[1])
            problem += (dv_outlier_hard.loc[member, class_duty] >= \
                        lim_hard[0] - lpDot(dv_assign.loc[:, member], d_duty_date_class.loc[:, class_duty]))
            problem += (dv_outlier_hard.loc[member, class_duty] >= 0)

        lim_soft = d_lim_soft.loc[member, class_duty]
        if ~np.isnan(lim_soft[0]):
            problem += (dv_outlier_soft.loc[member, class_duty] >= \
                        lpDot(dv_assign.loc[:, member], d_duty_date_class.loc[:, class_duty]) - lim_soft[1])
            problem += (dv_outlier_soft.loc[member, class_duty] >= \
                        lim_soft[0] - lpDot(dv_assign.loc[:, member], d_duty_date_class.loc[:, class_duty]))
            problem += (dv_outlier_soft.loc[member, class_duty] >= 0)


###############################################################################
# Avoid overlapping / adjacent / close assignments
###############################################################################
# Penalize ['day', 'ocday', 'night', 'ocnight'] in N(thr_interval) continuous days
# TODO: consider previous month assignment
for date_start in [d for d in range(-thr_interval + 2, 1)] + l_date:
    # Create list of continuous date_duty's
    l_date_duty_temp = []
    for date in range(date_start, date_start + thr_interval):
        for duty in ['day', 'ocday', 'night', 'ocnight']:
            date_duty_temp = str(date) + '_' + duty
            if date_duty_temp in dv_assign.index:
                l_date_duty_temp.append(date_duty_temp)
    if len(l_date_duty_temp) >= 2:
        for member in l_member:
            problem += (lpSum(dv_assign.loc[l_date_duty_temp, member]) <= 1)

# Penalize 'ect' in N(thr_interval) continuous days
# TODO: consider previous month assignment
for date_start in [d for d in range(-thr_interval + 2, 1)] + l_date:
    # Create list of continuous date_duty's
    l_date_duty_temp = []
    for date in range(date_start, date_start + thr_interval):
        for duty in ['ect']:
            date_duty_temp = str(date) + '_' + duty
            if date_duty_temp in dv_assign.index:
                l_date_duty_temp.append(date_duty_temp)
    if len(l_date_duty_temp) >= 2:
        for member in l_member:
            problem += (lpSum(dv_assign.loc[l_date_duty_temp, member]) <= 1)

# Avoid [same-date 'am' and 'pm'],
#       [same-date 'pm', 'night' and 'ocnight'],
#   and ['night', 'ocnight' and following-date 'ect','am']
# TODO: consider previous month assignment
for date in [0] + l_date:
    date_duty_am = str(date) + '_am'
    date_duty_pm = str(date) + '_pm'
    date_duty_night = str(date) + '_night'
    date_duty_ocnight = str(date) + '_ocnight'
    date_duty_ect_next = str(date+1) + '_ect'
    date_duty_am_next = str(date+1) + '_am'
    # List of lists of date_duty groups to avoid
    ll_avoid = [[date_duty_am, date_duty_pm],
                [date_duty_pm, date_duty_night, date_duty_ocnight],
                [date_duty_night, date_duty_ocnight, date_duty_ect_next, date_duty_am_next]]
    for l_avoid in ll_avoid:
        # Check if date_duty exists
        l_date_duty_temp = []
        for date_duty in l_avoid:
            if date_duty in dv_assign.index:
                l_date_duty_temp.append(date_duty)
        if len(l_date_duty_temp) >= 2:
            for member in l_member:
                problem += (lpSum(dv_assign.loc[l_date_duty_temp, member]) <= 1)


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
            problem += (dv_assign.loc[str(date) + '_ect', id_member] == 0)


###############################################################################
# TODO: Equalize points per member
###############################################################################


###############################################################################
# Define objective function to be minimized
###############################################################################
problem += (c_outlier_hard * lpSum(dv_outlier_hard.to_numpy()) \
          + c_outlier_soft * lpSum(dv_outlier_soft.to_numpy()) \
          + c_assign_suboptimal * v_assign_suboptimal)


###############################################################################
# Solve problem
###############################################################################
# Print problem
#print('Problem: ', problem)

# Solve problem
problem.solve()
v_objective = value(problem.objective)
print('Solved: ' + str(LpStatus[problem.status]) + ', ' + str(round(v_objective, 2)))


###############################################################################
# Extract data
###############################################################################

d_assign = pd.DataFrame(np.vectorize(value)(dv_assign), columns = l_member, index = dv_assign.index).astype(bool)

# Assignments with date_duty as row
d_assign_date = pd.concat([pd.Series(d_assign.index, index = d_assign.index, name = 'date_duty'),
                           pd.Series(d_assign.sum(axis = 1), name = 'cnt'),
                           pd.Series(d_assign.apply(lambda row: row[row].index.to_list(), axis = 1), name = 'id_member')],
                           axis = 1)
d_assign_date.index = range(len(d_assign_date))
d_assign_date['id_member'] = d_assign_date['id_member'].apply(lambda x: x[0] if len(x) > 0 else np.nan)
d_assign_date = pd.merge(d_assign_date, d_member.loc[:,['id_member','name_jpn','name']], on = 'id_member', how = 'left')
d_assign_date = pd.merge(d_assign_date, d_date_duty, on = 'date_duty', how = 'left')
d_assign_date = d_assign_date.loc[:,['date_duty', 'date','duty', 'id_member','name','name_jpn','cnt']]

# Assignments with date as row
d_assign_print = d_cal.loc[:,['date','wday_jpn','holiday', 'em']].copy()
d_assign_print[['am','pm','day','night','ocday','ocnight','ect']] = np.nan
for idx, row in d_assign_date.iterrows():
    date = row['date']
    duty = row['duty']
    name_jpn = row['name_jpn']
    d_assign_print.loc[d_assign_print['date'] == date, duty] = name_jpn

# Assignments with member as row
d_assign_optimal = pd.DataFrame((d_availability == 2) & d_assign, columns = l_member, index = dv_assign.index)                         
d_assign_suboptimal = pd.DataFrame((d_availability == 1) & d_assign, columns = l_member, index = dv_assign.index)
d_assign_error = pd.DataFrame((d_availability == 0) & d_assign, columns = l_member, index = dv_assign.index)
d_assign_member = pd.concat([pd.Series(d_assign.sum(axis = 0), index = l_member, name = 'cnt_all'),
                         pd.Series(d_assign.apply(lambda col: col[col].index.to_list(), axis = 0), index = l_member, name = 'date_all'),
                         pd.Series(d_assign_optimal.sum(axis = 0), index = l_member, name = 'cnt_opt'),
                         pd.Series(d_assign_optimal.apply(lambda col: col[col].index.to_list(), axis = 0), index = l_member, name = 'date_opt'),
                         pd.Series(d_assign_suboptimal.sum(axis = 0), index = l_member, name = 'cnt_sub'),
                         pd.Series(d_assign_suboptimal.apply(lambda col: col[col].index.to_list(), axis = 0), index = l_member, name = 'date_sub')],
                         axis = 1)