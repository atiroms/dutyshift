import numpy as np, pandas as pd
import os
from pulp import *
from ortoolpy import addvars, addbinvars

#p_test = 'D:/NICT_WS/Dropbox/dutyshift/test'
p_test = 'D:/atiro/Dropbox/dutyshift/test'

l_date_em = [6, 20]
l_date_ect = [4, 6, 7, 11, 13, 14, 18, 20, 21, 25, 27, 28]
l_type_duty = ['night_tot','night_em','night_wd','night_hd','day_hd','oc_tot','oc_hd_day','oc_other','ect']
#l_duty = ['ect', 'am', 'pm','day', 'ocday', 'night', 'ocnight']
dict_duty = {'ect': 0, 'am': 1, 'pm': 2, 'day': 3, 'ocday': 4, 'night': 5, 'ocnight': 6}
c_outlier = 1.0
thr_interval = 3
c_interval = 1.0
c_assign_suboptimal = 0.1

# Data of doctors and their assignment limits etc...
d_member = pd.read_csv(os.path.join(p_test, 'member02.csv'))
d_member_idx = d_member[['id_member','name_jpn','title_jpn','designation_jpn','ect_asgn_jpn','name','title_short','designation']]
s_ect_asgn = d_member['ect_asgn']
s_designation = d_member['designation']
d_lim = d_member[l_type_duty]

# Split assignment limit data into hard and soft
d_lim_hard = pd.DataFrame([[[np.nan]*2]*d_lim.shape[1]]*d_lim.shape[0], index = d_lim.index, columns = d_lim.columns)
d_lim_soft = pd.DataFrame([[[np.nan]*2]*d_lim.shape[1]]*d_lim.shape[0], index = d_lim.index, columns = d_lim.columns)
for col in l_type_duty:
    for idx in d_lim.index:
        if '(' in d_lim.loc[idx, col]:
            # If parenthesis exists, its content is hard limit
            d_lim_hard.loc[idx, col][0] = str(d_lim.loc[idx, col]).split('(')[1].split(')')[0]
            d_lim_soft.loc[idx, col][0] = str(d_lim.loc[idx, col]).split('(')[0]
        else:
            # If parenthesis does not exist it's hard limit
            d_lim_hard.loc[idx, col][0] = d_lim.loc[idx, col]
            d_lim_soft.loc[idx, col][0] = '--'

        for d_temp in [d_lim_hard, d_lim_soft]:
            if d_temp.loc[idx, col][0] == '--':
                # Convert '-' to [np.nan, np.nan]
                d_temp.loc[idx, col] = [np.nan]*2
            elif '-' in str(d_temp.loc[idx, col][0]):
                # Convert string 'a-b' to list [a, b]
                d_temp.loc[idx, col] = [int(x) for x in str(d_temp.loc[idx, col][0]).split('--')]
            else:
                # Convert string 'a' to list [a, a]
                d_temp.loc[idx, col] = [int(d_temp.loc[idx, col][0])]*2

# Data of member availability
d_availability = pd.read_csv(os.path.join(p_test, 'availability02.csv'))
d_availability = pd.merge(d_member_idx[['id_member', 'name_jpn']], d_availability, on='name_jpn')
d_availability.set_index('id_member', inplace=True)
d_availability.drop(['name_jpn'], axis = 1, inplace = True)
d_availability = d_availability.T
d_availability_ect = d_availability.loc[[str(date_ect) + '_am' for date_ect in l_date_ect], :]
d_availability_ect.index = ([str(date_ect) + '_ect' for date_ect in l_date_ect])
d_availability = pd.concat([d_availability, d_availability_ect], axis = 0)

# Lists and dataframes of member, date and duty
l_member = d_availability.columns.to_list()
n_member = len(l_member)
d_date_duty = pd.DataFrame([[date_duty] for date_duty in d_availability.index.to_list()], columns = ['date_duty'])
d_date_duty['date'] = d_date_duty['date_duty'].apply(lambda x: int(x.split('_')[0]))
d_date_duty['duty'] = d_date_duty['date_duty'].apply(lambda x: x.split('_')[1])
#d_date_duty_ect = pd.DataFrame(zip([str(date)+'_ect' for date in l_date_ect], l_date_ect, ['ect']*len(l_date_ect)), columns = ['date_duty', 'date', 'duty'])
#d_date_duty = pd.concat([d_date_duty, d_date_duty_ect], axis = 0)
l_date = sorted([date for date in d_date_duty['date'].unique().tolist()])

l_date_hd = sorted(d_date_duty.loc[d_date_duty['duty'] == 'day', 'date'].unique().tolist())
l_date_wd = [date for date in l_date if date not in l_date_hd]
n_date = len(l_date)
n_duty = len(dict_duty)
n_date_duty = d_date_duty.shape[0]

# Specify which type_duty's apply to each date_duty
d_duty_date_type = pd.DataFrame([[False]*len(l_type_duty)]*n_date_duty, index = d_date_duty['date_duty'], columns = l_type_duty)
# night_tot
for date in l_date:
    idx_temp = d_date_duty.loc[(d_date_duty['date'] == date) & (d_date_duty['duty'] == 'night'), 'date_duty'].to_list()
    d_duty_date_type.loc[idx_temp, 'night_tot'] = True
# night_em
for date in l_date_em:
    idx_temp = d_date_duty.loc[(d_date_duty['date'] == date) & (d_date_duty['duty'] == 'night'), 'date_duty'].to_list()
    d_duty_date_type.loc[idx_temp, 'night_em'] = True
# night_wd
for date in l_date_wd:
    idx_temp = d_date_duty.loc[(d_date_duty['date'] == date) & (d_date_duty['duty'] == 'night'), 'date_duty'].to_list()
    d_duty_date_type.loc[idx_temp, 'night_wd'] = True
# night_hd
for date in l_date_hd:
    idx_temp = d_date_duty.loc[(d_date_duty['date'] == date) & (d_date_duty['duty'] == 'night'), 'date_duty'].to_list()
    d_duty_date_type.loc[idx_temp, 'night_hd'] = True
# day_hd
for date in l_date_hd:
    idx_temp = d_date_duty.loc[(d_date_duty['date'] == date) & (d_date_duty['duty'] == 'day'), 'date_duty'].to_list()
    d_duty_date_type.loc[idx_temp, 'day_hd'] = True
# oc_tot, oc_hd_day, oc_other
for date in l_date:
    idx_temp = d_date_duty.loc[(d_date_duty['date'] == date) & (d_date_duty['duty'] == 'ocnight'), 'date_duty'].to_list()
    d_duty_date_type.loc[idx_temp, 'oc_tot'] = True
    d_duty_date_type.loc[idx_temp, 'oc_other'] = True
for date in l_date_hd:
    idx_temp = d_date_duty.loc[(d_date_duty['date'] == date) & (d_date_duty['duty'] == 'ocday'), 'date_duty'].to_list()
    d_duty_date_type.loc[idx_temp, 'oc_tot'] = True
    d_duty_date_type.loc[idx_temp, 'oc_hd_day'] = True
# ect
for date in l_date_ect:
    idx_temp = d_date_duty.loc[(d_date_duty['date'] == date) & (d_date_duty['duty'] == 'ect'), 'date_duty'].to_list()
    d_duty_date_type.loc[idx_temp, 'ect'] = True

# Binary assignment variables to be optimized
dv_assign = pd.DataFrame(np.array(addbinvars(n_date_duty, n_member)), columns = l_member, index = d_date_duty['date_duty'].to_list())

# Initialize model to be optimized
problem = LpProblem()

# Assign one member per date_duty for ['night', 'day', 'am', 'pm', 'ect']
for duty in ['night', 'day', 'am', 'pm', 'ect']:
    for date_duty in d_date_duty[d_date_duty['duty'] == duty]['date_duty'].to_list():
        problem += (lpSum(dv_assign.loc[date_duty]) == 1)

# Assign one member per date_duty for ['oc_night', 'oc_day'],
# if non-designated member is assigned to ['night', 'day'] for the same date/time
for duty in ['night', 'day']:
    for date in d_date_duty[d_date_duty['duty'] == duty]['date'].to_list():
        date_duty = str(date) + '_' + duty
        date_duty_oc = str(date) + '_oc' + duty
        # Sum of dot product of (normal and oc assignments) and (designation)
        # Returns number of 'designated' member assigned in the same date/time, which should be 1
        problem += (lpSum(lpDot(dv_assign.loc[[date_duty, date_duty_oc]].to_numpy(),
                                np.array([s_designation.loc[l_member]]*2))) == 1)

# Penalize excess from max or shortage from min in the shape of '\__/'
dv_outlier_hard = pd.DataFrame(np.array(addvars(n_member, len(l_type_duty))), columns = l_type_duty, index = l_member)
dv_outlier_soft = pd.DataFrame(np.array(addvars(n_member, len(l_type_duty))), columns = l_type_duty, index = l_member)
for member in l_member:
    for type_duty in l_type_duty:
        lim_hard = d_lim_hard.loc[member, type_duty]
        if ~np.isnan(lim_hard[0]):
            problem += (dv_outlier_hard.loc[member, type_duty] >= lpDot(dv_assign.loc[:, member], d_duty_date_type.loc[:, type_duty]) - lim_hard[1])
            problem += (dv_outlier_hard.loc[member, type_duty] >= lim_hard[0] - lpDot(dv_assign.loc[:, member], d_duty_date_type.loc[:, type_duty]))
            problem += (dv_outlier_hard.loc[member, type_duty] >= 0)

        lim_soft = d_lim_soft.loc[member, type_duty]
        if ~np.isnan(lim_soft[0]):
            problem += (dv_outlier_soft.loc[member, type_duty] >= lpDot(dv_assign.loc[:, member], d_duty_date_type.loc[:, type_duty]) - lim_soft[1])
            problem += (dv_outlier_soft.loc[member, type_duty] >= lim_soft[0] - lpDot(dv_assign.loc[:, member], d_duty_date_type.loc[:, type_duty]))
            problem += (dv_outlier_soft.loc[member, type_duty] >= 0)

# Do not assign to a date if not available
problem += (lpDot((d_availability == 0).to_numpy(), dv_assign.to_numpy()) <= 0)

# Penalize suboptimal assignment
v_assign_suboptimal = lpDot((d_availability == 1).to_numpy(), dv_assign.to_numpy())

# Avoid overlapping / adjacent / close assignment
# Sort ['ect', 'am', 'pm', 'day', 'ocday', 'night', 'ocnight'] in temporal order
#d_date_duty_ord = d_date_duty.copy()
#d_date_duty_ord['duty_sort'] = d_date_duty_ord['duty'].map(dict_duty)
#d_date_duty_ord = d_date_duty_ord.sort_values(by = ['date', 'duty_sort'])
#d_date_duty_ord.index = range(len(d_date_duty_ord))

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

# Avoid continuous assignment
# Penalize assignments in continuous [thr_interval] days
dv_continuity = pd.DataFrame(np.array(addvars(n_date - thr_interval + 1, n_member)), index = l_date[:(-thr_interval + 1)], columns = l_member)
for member in l_member:
    # Define dv_continuity for each member
    for i_date in range(n_date - thr_interval + 1):
        sv_assign_win = dv_assign[member].iloc[i_date:(i_date + thr_interval)]
        problem += (dv_continuity[member].iloc[i_date] >= (lpSum(sv_assign_win) - 1))
        problem += (dv_continuity[member].iloc[i_date] >= 0)

# Define objective function to be minimized
problem += (c_outlier * lpSum(sv_outlier) \
          + c_interval * lpSum(dv_continuity.to_numpy()) \
          + c_assign_suboptimal * v_assign_suboptimal)

# Print problem
#print('Problem')
#print(problem)

# Optimize model
problem.solve()

# Print solution status
print('Status')
print(LpStatus[problem.status])
# Problem function value
v_objective = value(problem.objective)
print(v_objective)

# Extract values from variable
d_assign = pd.DataFrame(np.vectorize(value)(dv_assign), columns = l_member, index = l_date).astype(bool)
d_assign_optimal = pd.DataFrame((d_availability == 2) & d_assign, columns = l_member, index = l_date)                         
d_assign_suboptimal = pd.DataFrame((d_availability == 1) & d_assign, columns = l_member, index = l_date)
d_assign_date = pd.concat([pd.Series(d_assign.sum(axis = 1), index = l_date, name = 'c'),
                           pd.Series(d_assign.apply(lambda row: str(row[row].index.to_list()[0]), axis = 1), index = l_date, name = 'member')],
                           axis = 1)                      
d_assign_member = pd.concat([pd.Series(d_assign.sum(axis = 0), index = l_member, name = 'c_all'),
                         pd.Series(d_assign.apply(lambda col: col[col].index.to_list(), axis = 0), index = l_member, name = 'date_all'),
                         pd.Series(d_assign_optimal.sum(axis = 0), index = l_member, name = 'c_opt'),
                         pd.Series(d_assign_optimal.apply(lambda col: col[col].index.to_list(), axis = 0), index = l_member, name = 'date_opt'),
                         pd.Series(d_assign_suboptimal.sum(axis = 0), index = l_member, name = 'c_sub'),
                         pd.Series(d_assign_suboptimal.apply(lambda col: col[col].index.to_list(), axis = 0), index = l_member, name = 'date_sub')],
                         axis = 1)

d_continuity = pd.DataFrame(np.vectorize(value)(dv_continuity), index = l_date[:(-thr_interval + 1)], columns = l_member)

