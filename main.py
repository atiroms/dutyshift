
###############################################################################
# Libraries
###############################################################################
import numpy as np, pandas as pd
import os, datetime
from pulp import *
from ortoolpy import addvars, addbinvars


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
#f_availability = 'availability.csv'
#f_availability = 'availability2.csv'
f_availability = 'availability3.csv'

# Fixed parameters
l_day_ect = [0, 2, 3] # Monday, Wednesday, Thursday
day_em = 2 # Wednesday
l_week_em = [1, 3] # 1st and 3rd weeks

l_type_score = ['ampm','daynight','ampmdaynight','oc','ect']
l_class_duty = ['ampm','daynight_tot','night_em','night_wd','daynight_hd','oc_tot','oc_day','oc_night','ect']
dict_duty = {'ect': 0, 'am': 1, 'pm': 2, 'day': 3, 'ocday': 4, 'night': 5, 'emnight':6, 'ocnight': 7}
l_title_scoregroup = [['assoc'], ['instr'], ['limterm_instr','assist'], ['limterm_clin'], ['stud']]

c_outlier_soft = 0.0001
c_assign_suboptimal = 0.0001
dict_c_diff_score_current = {'ampm': 0.001, 'daynight': 0.001, 'ampmdaynight': 0.01, 'oc': 0.001, 'ect': 0.01}
dict_c_diff_score_total = {'ampm': 0.01, 'daynight': 0.01, 'ampmdaynight': 0.1, 'oc': 0.01, 'ect': 0.1}

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
    d_src = '{year:0>4d}{month:0>2d}'.format(year = year_plan, month = month_plan)
    p_src = os.path.join(p_root, 'Dropbox/dutyshift', d_src)
    d_dst = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    p_dst = os.path.join(p_src, d_dst)
    if ~os.path.exists(p_dst):
        os.makedirs(p_dst)

from helper import *


###############################################################################
# Load and prepare data
###############################################################################
# Prepare calendar and all duties of the month
d_cal, d_date_duty, s_cnt_duty, s_cnt_class_duty \
    = prep_calendar(p_root, l_class_duty, l_holiday, l_day_ect, l_date_ect_cancel,
                    day_em, l_week_em, year_plan, month_plan)

# Prepare calendar for google forms
# TODO: output in one file
# TODO: split assistant professor into team leader and subleader
#d_cal_duty = prep_forms(p_dst, d_cal, month_plan, dict_duty)

# Prepare data of member specs and assignment limits
#d_member, d_lim_hard, d_lim_soft = prep_member(p_src, f_member, l_class_duty)
d_member, d_score_past, d_lim_hard, d_lim_soft, d_grp_score \
    = prep_member2(p_root, f_member, l_class_duty, year_plan, month_plan)

# Prepare data of member availability
d_availability, l_member = prep_availability(p_src, f_availability, d_date_duty, d_member, d_cal)


###############################################################################
# Optimize exact assignment count
###############################################################################
d_score_class = pd.read_csv(os.path.join(p_root, 'Dropbox/dutyshift/config/score_class.csv'))

# Optimize assignment counts except OC
d_lim_exact_notoc, d_score_current_notoc, d_score_total_notoc,\
d_sigma_diff_score_current_notoc, d_sigma_diff_score_total_notoc = \
    optimize_count(l_member, s_cnt_class_duty, d_lim_hard, d_score_past,
                   d_score_class, d_grp_score, dict_c_diff_score_current, dict_c_diff_score_total,
                   l_type_score = ['ampm', 'daynight', 'ampmdaynight', 'ect'],
                   l_class_duty = ['ampm', 'daynight_tot', 'night_em', 'ect'])

# Optimize assignment counts of OC
ln_daynight = d_lim_exact_notoc['daynight_tot'].tolist()
l_designation = d_member.loc[d_member['id_member'].isin(l_member), 'designation'].tolist()
n_oc_required = int(sum([x * (y == False) for x, y in zip(ln_daynight, l_designation)]))
s_cnt_class_duty['oc_tot'] = n_oc_required

d_lim_exact_oc, d_score_current_oc, d_score_total_oc,\
d_sigma_diff_score_current_oc, d_sigma_diff_score_total_oc = \
    optimize_count(l_member, s_cnt_class_duty, d_lim_hard, d_score_past,
                   d_score_class, d_grp_score, dict_c_diff_score_current, dict_c_diff_score_total,
                   l_type_score = ['oc'],
                   l_class_duty = ['oc_tot'])

d_lim_exact = pd.concat([d_lim_exact_notoc, d_lim_exact_oc], axis = 1)
for col in d_lim_hard.columns:
    if not col in d_lim_exact.columns:
        d_lim_exact[col] = [x[0] for x in d_lim_hard.loc[l_member, col].tolist()]
d_lim_exact = d_lim_exact[d_lim_hard.columns]

d_score_current = pd.concat([d_score_current_notoc, d_score_current_oc], axis = 1)
d_score_total = pd.concat([d_score_total_notoc, d_score_total_oc], axis = 1)


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
# Assign one member per date_duty for ['am', 'pm', 'day', 'night', 'ect']
for duty in ['am', 'pm', 'day', 'night', 'ect']:
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
# Penalize excess from max or shortage from min in the shape of '\__/'
dv_outlier_soft = pd.DataFrame(np.array(addvars(len(l_member), len(l_class_duty))),
                               index = l_member, columns = l_class_duty)
for member in l_member:
    for class_duty in l_class_duty:
        lim_hard = d_lim_hard.loc[member, class_duty]
        if ~np.isnan(lim_hard[0]):
            prob_assign += (lpDot(dv_assign.loc[:, member], d_date_duty.loc[:, class_duty]) <= lim_hard[1])
            prob_assign += (lim_hard[0] <= lpDot(dv_assign.loc[:, member], d_date_duty.loc[:, class_duty]))

        lim_soft = d_lim_soft.loc[member, class_duty]
        if ~np.isnan(lim_soft[0]):
            prob_assign += (dv_outlier_soft.loc[member, class_duty] >= \
                        lpDot(dv_assign.loc[:, member], d_date_duty.loc[:, class_duty]) - lim_soft[1])
            prob_assign += (dv_outlier_soft.loc[member, class_duty] >= \
                        lim_soft[0] - lpDot(dv_assign.loc[:, member], d_date_duty.loc[:, class_duty]))


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
# Equalize scores per member
###############################################################################
# TODO: import all-month data
# preliminary: read April score data
d_score_history = pd.read_csv(os.path.join(p_root, 'Dropbox/dutyshift/202204', 'score.csv'))

# Calculate scores
#l_type_score = ['total','dutyoc','duty','oc','ect']
l_type_score = ['ampm','daynight','ampmdaynight','oc','ect']
dv_score = pd.DataFrame(np.array(addvars(len(l_member), len(l_type_score))),
                        index = l_member, columns = l_type_score)
for type_score in l_type_score:
    a_score = d_date_duty['score_' + type_score].to_numpy()
    for id_member in l_member:
        # Single-month scores
        #problem += (dv_score.loc[id_member, type_score] ==\
        #            lpDot(a_score,dv_assign.loc[:, id_member]))
        # Past + current month scores
        score_history = d_score_history.loc[d_score_history['id_member'] == id_member, 'score_' + type_score].to_numpy()[0]
        prob_assign += (dv_score.loc[id_member, type_score] ==\
                    lpDot(a_score,dv_assign.loc[:, id_member]) + score_history)        

# Calculate score differences
dv_scorediff_sum = pd.DataFrame(np.array(addvars(len(l_title_scoregroup), len(l_type_score))),
                                index = range(len(l_title_scoregroup)), columns = l_type_score)
dict_dv_scorediff = {}
for type_score in l_type_score:
    dict_dv_scorediff[type_score] = pd.DataFrame(np.array(addvars(len(l_member),len(l_member))), index = l_member, columns = l_member)                        

for id_scoregroup, title_scoregroup in enumerate(l_title_scoregroup):
    l_member_scoregroup = d_member.loc[d_member['title_short'].isin(title_scoregroup), 'id_member'].to_list()
    l_member_scoregroup = [id_member for id_member in l_member_scoregroup if id_member in l_member]
    for type_score in l_type_score:
        for id_member_0 in l_member_scoregroup:
            for id_member_1 in l_member_scoregroup:
                prob_assign += (dict_dv_scorediff[type_score].loc[id_member_0, id_member_1] >=\
                            dv_score.loc[id_member_0, type_score] - dv_score.loc[id_member_1, type_score])
        prob_assign += (dv_scorediff_sum.loc[id_scoregroup, type_score] ==\
                    lpSum(dict_dv_scorediff[type_score].loc[l_member_scoregroup, l_member_scoregroup].to_numpy()))


###############################################################################
# Define objective function to be minimized
###############################################################################
prob_assign += (c_outlier_soft * lpSum(dv_outlier_soft.to_numpy()) \
          + c_scorediff_ampmdaynight * lpSum(dv_scorediff_sum['ampmdaynight'].to_numpy()) \
          + c_scorediff_oc * lpSum(dv_scorediff_sum['oc'].to_numpy()) \
          + c_scorediff_ect * lpSum(dv_scorediff_sum['ect'].to_numpy()) \
          + c_assign_suboptimal * v_assign_suboptimal)

          #+ c_scorediff_ampm * lpSum(dv_scorediff_sum['ampm'].to_numpy()) \
          #+ c_scorediff_ampmdaynight * lpSum(dv_scorediff_sum['ampmdaynight'].to_numpy()) \
          #+ c_scorediff_daynight * lpSum(dv_scorediff_sum['daynight'].to_numpy()) \
          #+ c_outlier_hard * lpSum(dv_outlier_hard.to_numpy()) \
          #+ c_scorediff_total * lpSum(dv_scorediff_sum['total'].to_numpy()) \
          #+ c_scorediff_dutyoc * lpSum(dv_scorediff_sum['dutyoc'].to_numpy()) \
          
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
d_assign_date_duty, d_assign_date_print, d_assign_member, d_score=\
    prep_assign(p_dst, dv_assign, dv_score, d_score_history,
                d_availability, d_member, l_member, d_date_duty, d_cal)

d_optimization = prep_optim(p_dst, dv_outlier_soft,dv_scorediff_sum, v_assign_suboptimal, c_outlier_soft,
                            c_scorediff_ampm, c_scorediff_daynight, c_scorediff_ampmdaynight,
                            c_scorediff_oc, c_scorediff_ect, c_assign_suboptimal)