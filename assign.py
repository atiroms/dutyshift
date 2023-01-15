
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
year_plan = 2023
month_plan = 2
l_holiday = [23]
l_date_ect_cancel = []
f_member = 'member.csv'

# Fixed parameters for optimizing assignment count
l_day_ect = [0, 2, 3] # Monday, Wednesday, Thursday
day_em = 2 # Wednesday
l_week_em = [] # 1st and 3rd weeks

l_type_score = ['ampm','daynight','ampmdaynight','oc','ect']
l_class_duty = ['ampm','daynight_tot','night_em','night_wd','daynight_hd','oc_tot','oc_day','oc_night','ect']
dict_duty = {'ect': 0, 'am': 1, 'pm': 2, 'day': 3, 'ocday': 4, 'night': 5, 'emnight':6, 'ocnight': 7}

dict_c_diff_score_current = {'ampm': 0.001, 'daynight': 0.001, 'ampmdaynight': 0.01, 'oc': 0.001, 'ect': 0.01}
dict_c_diff_score_total = {'ampm': 0.01, 'daynight': 0.01, 'ampmdaynight': 0.1, 'oc': 0.01, 'ect': 0.1}

# Fixed parameters for optimizing assignment
c_assign_suboptimal = 0.001
c_cnt_deviation = 0.1
thr_interval_daynight = 5
thr_interval_ect = 2
thr_interval_ampm = 2

#thr_interval_daynight = 2
#thr_interval_ect = 2
#thr_interval_ampm = 2

#thr_interval_daynight = 1
#thr_interval_ect = 1
#thr_interval_ampm = 1

l_date_duty_fulltime = []
ignore_limit = False


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
# Optimize exact assignment count
###############################################################################

s_cnt_class_duty = pd.read_csv(os.path.join(p_month, 'cnt_class_duty.csv'), index_col=0).squeeze(1)

# Prepare data of member specs and assignment limits
d_member, d_score_past, d_lim_hard, d_lim_soft, d_grp_score \
    = prep_member2(p_root, p_month, p_data, f_member, l_class_duty, year_plan, month_plan)


# TODO: equilize 3 continous holidays assignment count
d_score_class = pd.read_csv(os.path.join(p_root, 'Dropbox/dutyshift/config/score_class.csv'))

# Optimize assignment counts except OC
d_lim_exact_notoc, d_score_current_notoc, d_score_total_notoc,\
d_sigma_diff_score_current_notoc, d_sigma_diff_score_total_notoc = \
    optimize_count(d_member, s_cnt_class_duty, d_lim_hard, d_score_past,
                   d_score_class, d_grp_score, dict_c_diff_score_current, dict_c_diff_score_total,
                   l_type_score = ['ampm', 'daynight', 'ampmdaynight', 'ect'],
                   l_class_duty = ['ampm', 'daynight_tot', 'night_em', 'ect'])

# Optimize assignment counts of OC
# TODO: consider past OC assignments for assistant professors
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
    d_score_current.to_csv(os.path.join(p_save, 'score_current_plan.csv'), index = False)
    d_score_total.to_csv(os.path.join(p_save, 'score_total_plan.csv'), index = False)


###############################################################################
# Load and prepare data for duty assignment
###############################################################################
# Prepare data of member availability
d_date_duty = pd.read_csv(os.path.join(p_month, 'date_duty.csv'))
d_cal = pd.read_csv(os.path.join(p_month, 'calendar.csv'))
d_member = pd.read_csv(os.path.join(p_month, 'member.csv'))
d_lim_exact = pd.read_csv(os.path.join(p_month, 'lim_exact.csv'))
d_lim_hard = pd.read_csv(os.path.join(p_month, 'lim_hard.csv'))
d_availability, l_member, d_availability_ratio = prep_availability(p_month, p_data, d_date_duty, d_cal)
d_assign_previous = prep_assign_previous(p_root, year_plan, month_plan)
d_date_duty, d_availability, l_date_duty_unavailable = skip_unavailable(d_date_duty, d_availability, d_availability_ratio)


###############################################################################
# Initialize assignment problem and model
###############################################################################
# Initialize model to be optimized
prob_assign = LpProblem()

# Binary assignment variables to be optimized
dv_assign = pd.DataFrame(np.array(addbinvars(len(d_date_duty), len(l_member))),
                         index = d_date_duty['date_duty'].to_list(), columns = l_member)


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

# If non-designated member is assigned to ['day', 'night'] for the same date/time,
# assign one member per date_duty for ['oc_day', 'oc_night']
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
# Force full-time doctor assignment
###############################################################################
l_fulltime = d_member.loc[d_member['id_member'].isin(l_member), 'title_short']
l_fulltime = [(title in ['limterm_instr', 'assist', 'limterm_clin']) for title in l_fulltime]
#l_fulltime = [(title in ['limterm_instr', 'assist']) for title in l_fulltime]
for date_duty_fulltime in l_date_duty_fulltime:
    prob_assign += (lpSum(lpDot(dv_assign.loc[date_duty_fulltime].to_numpy(),
                                np.array(l_fulltime))) == 1)


###############################################################################
# Penalize limit outliers per member per class_duty
###############################################################################
dv_deviation = pd.DataFrame(np.array(addvars(len(l_member), len(l_class_duty))),
                            index = l_member, columns = l_class_duty)

for member in l_member:
    for class_duty in l_class_duty:
        lim_hard = d_lim_hard.loc[member, class_duty]
        cnt_min = float(lim_hard[1:-1].split(', ')[0])
        cnt_max = float(lim_hard[1:-1].split(', ')[1])
        cnt_target = d_lim_exact.loc[member, class_duty]
        if ignore_limit:
            if ~np.isnan(cnt_min):
                prob_assign += (dv_deviation.loc[member, class_duty] >= (lpDot(dv_assign.loc[:, member], d_date_duty.loc[:, 'class_' + class_duty]) - cnt_target))
                prob_assign += (dv_deviation.loc[member, class_duty] >= (cnt_target - lpDot(dv_assign.loc[:, member], d_date_duty.loc[:, 'class_' + class_duty])))
        else:
            if ~np.isnan(cnt_min):
                if cnt_min == cnt_max:
                    prob_assign += (lpDot(dv_assign.loc[:, member], d_date_duty.loc[:, 'class_' + class_duty]) == cnt_min)
                    prob_assign += (dv_deviation.loc[member, class_duty] == 0)
                else:
                    prob_assign += (lpDot(dv_assign.loc[:, member], d_date_duty.loc[:, 'class_' + class_duty]) >= cnt_min)
                    prob_assign += (lpDot(dv_assign.loc[:, member], d_date_duty.loc[:, 'class_' + class_duty]) <= cnt_max)
                    prob_assign += (dv_deviation.loc[member, class_duty] >= (lpDot(dv_assign.loc[:, member], d_date_duty.loc[:, 'class_' + class_duty]) - cnt_target))
                    prob_assign += (dv_deviation.loc[member, class_duty] >= (cnt_target - lpDot(dv_assign.loc[:, member], d_date_duty.loc[:, 'class_' + class_duty])))

v_cnt_deviation = lpSum(dv_deviation.to_numpy())


###############################################################################
# Avoid overlapping / adjacent / close assignments
###############################################################################
# Avoid ['day', 'ocday', 'night', 'emnight', 'ocnight'] in N(thr_interval_daynight) continuous days
# TODO: Besides avoiding, penalize close assignment
# Avoid 'ect' in N(thr_interval_ect) continuous days
# Avoid ['am','pm'] in N(thr_interval_ampm) continuous days

l_member_missing = [m for m in l_member if m not in d_assign_previous.columns]
d_assign_previous[l_member_missing] = 0

l_closeduty = [[thr_interval_daynight, ['day', 'ocday', 'night', 'emnight', 'ocnight']],
               [thr_interval_ect, ['ect']],
               [thr_interval_ampm, ['am', 'pm']]]

for closeduty in l_closeduty:
    thr_interval = closeduty[0]
    l_duty = closeduty[1]
    for date_start in [d for d in range(-thr_interval + 2, 1)] + d_cal['date'].tolist():
        # Create list of continuous date_duty's
        l_date_duty_exist = []
        l_date_duty_exist_previous = []
        for date in range(date_start, date_start + thr_interval):
            for duty in l_duty:
                date_duty = str(date) + '_' + duty
                if date_duty in dv_assign.index:
                    l_date_duty_exist.append(date_duty)
                if date_duty in d_assign_previous.index:
                    l_date_duty_exist_previous.append(date_duty)
        
        if (len(l_date_duty_exist) + len(l_date_duty_exist_previous)) >= 2:
            for member in l_member:
                prob_assign += (lpSum(dv_assign.loc[l_date_duty_exist, member]) +\
                                sum(d_assign_previous.loc[l_date_duty_exist_previous, member]) <= 1)

# Avoid [same-date 'pm', 'night', 'emnight' and 'ocnight'],
#   and ['night', 'emnight', 'ocnight' and following-date 'ect','am']
for date in [0] + d_cal['date'].tolist():
    date_duty_am = str(date) + '_am'
    date_duty_pm = str(date) + '_pm'
    date_duty_night = str(date) + '_night'
    date_duty_emnight = str(date) + '_emnight'
    date_duty_ocnight = str(date) + '_ocnight'
    date_duty_ect_next = str(date + 1) + '_ect'
    date_duty_am_next = str(date + 1) + '_am'
    # List of lists of date_duty groups to avoid
    ll_avoid = [[date_duty_pm, date_duty_night, date_duty_emnight, date_duty_ocnight],
                [date_duty_night, date_duty_emnight, date_duty_ocnight, date_duty_ect_next, date_duty_am_next]]
    for l_avoid in ll_avoid:
        # Check if date_duty exists
        l_date_duty_exist = []
        l_date_duty_exist_previous = []
        for date_duty in l_avoid:
            if date_duty in dv_assign.index:
                l_date_duty_exist.append(date_duty)
            if date_duty in d_assign_previous.index:
                l_date_duty_exist_previous.append(date_duty)

        if (len(l_date_duty_exist) + len(l_date_duty_exist_previous)) >= 2:
            for member in l_member:
                prob_assign += (lpSum(dv_assign.loc[l_date_duty_exist, member]) +\
                                sum(d_assign_previous.loc[l_date_duty_exist_previous, member]) <= 1)


###############################################################################
# TODO: Team leader ECT assignment (defined elsewhere) 
###############################################################################


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
prob_assign += (c_assign_suboptimal * v_assign_suboptimal
                + c_cnt_deviation * v_cnt_deviation)

          
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
d_assign_date_duty, d_assign_date_print, d_assign_member,\
d_deviation, d_score_current, d_score_total, d_score_print =\
    prep_assign2(p_root, p_month, p_data, year_plan, month_plan, dv_assign, dv_deviation,
                 d_availability, d_member, l_member, d_date_duty, d_cal)
                 