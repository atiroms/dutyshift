import numpy as np, pandas as pd
import os
from pulp import *
from ortoolpy import addvars, addbinvars

#p_test = 'D:/NICT_WS/Dropbox/dutyshift/test'
p_test = 'D:/atiro/Dropbox/dutyshift/test'

l_date_em = [6, 20]
l_date_ect = [4, 6, 7, 11, 13, 14, 18, 20, 21, 25, 27, 28]
l_type_duty = ['night_tot','night_em','night_wd','night_hd','day_hd','oc_tot','oc_hd_day','oc_other','ect']
c_outlier = 1.0
min_interval = 7
c_continuity = 1.0
c_assign_suboptimal = 0.1

# Data of doctors and their assignment limits etc...
d_member = pd.read_csv(os.path.join(p_test, 'member02.csv'))
d_member_idx = d_member[['id_dr','name_jpn','title_jpn','designation_jpn','ect_asgn_jpn','name','title_short','designation']]
s_ect_asgn = d_member['ect_asgn']
s_designation = d_member['designation']
d_limits = d_member[l_type_duty]

# Split assignment limit data into hard and soft
d_limits_hard = pd.DataFrame([[[np.nan]*2]*d_limits.shape[1]]*d_limits.shape[0], index = d_limits.index, columns = d_limits.columns)
d_limits_soft = pd.DataFrame([[[np.nan]*2]*d_limits.shape[1]]*d_limits.shape[0], index = d_limits.index, columns = d_limits.columns)
for col in l_type_duty:
    for idx in d_limits.index:
        if '(' in d_limits.loc[idx, col]:
            # If parenthesis exists, its content is hard limit
            d_limits_hard.loc[idx, col][0] = str(d_limits.loc[idx, col]).split('(')[1].split(')')[0]
            d_limits_soft.loc[idx, col][0] = str(d_limits.loc[idx, col]).split('(')[0]
        else:
            # If parenthesis does not exist it's hard limit
            d_limits_hard.loc[idx, col][0] = d_limits.loc[idx, col]
            d_limits_soft.loc[idx, col][0] = '-'

        for d_temp in [d_limits_hard, d_limits_soft]:
            if d_temp.loc[idx, col][0] == '-':
                # Convert '-' to [np.nan, np.nan]
                d_temp.loc[idx, col] = [np.nan]*2
            elif '-' in str(d_temp.loc[idx, col][0]):
                # Convert string 'a-b' to list [a, b]
                d_temp.loc[idx, col] = [int(x) for x in str(d_temp.loc[idx, col][0]).split('-')]
            else:
                # Convert string 'a' to list [a, a]
                d_temp.loc[idx, col] = [int(d_temp.loc[idx, col][0])]*2

# Data of Dr availability
d_availability = pd.read_csv(os.path.join(p_test, 'availability01.csv'))
d_availability = pd.merge(d_member_idx[['id_dr', 'name_jpn']], d_availability, on='name_jpn')
d_availability.set_index('id_dr', inplace=True)
d_availability.drop(['name_jpn'], axis = 1, inplace = True)
d_availability = d_availability.T

# Dr, date and duty lists and dataframes
l_dr = d_availability.columns.to_list()
n_dr = len(l_dr)
d_date_duty = pd.DataFrame([[date_duty] for date_duty in d_availability.index.to_list()], columns = ['date_duty'])
d_date_duty['date'] = d_date_duty['date_duty'].apply(lambda x: int(x.split('_')[0]))
d_date_duty['duty'] = d_date_duty['date_duty'].apply(lambda x: x.split('_')[1])
d_date_duty_ect = pd.DataFrame(zip([str(date)+'_ect' for date in l_date_ect], l_date_ect, ['ect']*len(l_date_ect)), columns = ['date_duty', 'date', 'duty'])
d_date_duty = pd.concat([d_date_duty, d_date_duty_ect], axis = 0)
l_date = sorted([date for date in d_date_duty['date'].unique().tolist()])
l_duty = ['day', 'night', 'am', 'pm', 'oc', 'ect']
l_date_hd = sorted(d_date_duty.loc[d_date_duty['duty'] == 'day', 'date'].unique().tolist())
l_date_wd = [date for date in l_date if date not in l_date_hd]
n_date = len(l_date)
n_duty = len(l_duty)
n_duty_date = d_date_duty.shape[0]

# Specify which type_duty's apply to each date_duty
d_date_duty['type_duty_apl'] = [[]] * n_duty_date
# night_tot
for date in l_date:
    v_in = d_date_duty.loc[(d_date_duty['date'] == date) & (d_date_duty['duty'] == 'night'), 'type_duty_apl'].to_list()[0]
    v_out = v_in + ['night_tot']
    d_date_duty.loc[(d_date_duty['date'] == date) & (d_date_duty['duty'] == 'night'), 'type_duty_apl'] = [v_out]
# night_em
for date in l_date_em:
    v_in = d_date_duty.loc[(d_date_duty['date'] == date) & (d_date_duty['duty'] == 'night'), 'type_duty_apl'].to_list()[0]
    v_out = v_in + ['night_em']
    d_date_duty.loc[(d_date_duty['date'] == date) & (d_date_duty['duty'] == 'night'), 'type_duty_apl'] = [v_out]
# night_wd
for date in l_date_wd:
    v_in = d_date_duty.loc[(d_date_duty['date'] == date) & (d_date_duty['duty'] == 'night'), 'type_duty_apl'].to_list()[0]
    v_out = v_in + ['night_wd']
    d_date_duty.loc[(d_date_duty['date'] == date) & (d_date_duty['duty'] == 'night'), 'type_duty_apl'] = [v_out]


# Binary assignment variables to be optimized
dv_assign = pd.DataFrame(np.array(addbinvars(n_duty_date, n_dr)), columns = l_dr, index = d_date_duty['date_duty'].to_list())

# Initialize model to be optimized
problem = LpProblem()

# Assign one Dr per date_duty for ['night', 'day', 'am', 'pm']
for duty in ['night', 'day', 'am', 'pm']:
    for duty_date in d_date_duty[d_date_duty['duty'] == duty]['date_duty'].to_list():
        problem += (lpSum(dv_assign.loc[duty_date]) == 1)

# 


# Do not assign to a date if not available
problem += (lpDot((d_availability == 0).to_numpy(), dv_assign.to_numpy()) <= 0)

# Penalize suboptimal assignment
dv_assign_suboptimal = lpDot((d_availability == 1).to_numpy(), dv_assign.to_numpy())

# Minimize outlier
# Penalize excess from max or shortage from min in the shape of '\__/'
sv_outlier = pd.Series(np.array(addvars(n_dr)), index = l_dr)
for dr in l_dr:
    # Define sv_outlier for each dr
    problem += (sv_outlier[dr] >= lpSum(dv_assign[dr]) - d_count.loc[dr, 'max'])
    problem += (sv_outlier[dr] >= d_count.loc[dr, 'min'] - lpSum(dv_assign[dr]))
    problem += (sv_outlier[dr] >= 0)

# Avoid continuous assignment
# Penalize assignments in continuous [min_interval] days
dv_continuity = pd.DataFrame(np.array(addvars(n_date - min_interval + 1, n_dr)), index = l_date[:(-min_interval + 1)], columns = l_dr)
for dr in l_dr:
    # Define dv_continuity for each dr
    for i_date in range(n_date - min_interval + 1):
        sv_assign_win = dv_assign[dr].iloc[i_date:(i_date + min_interval)]
        problem += (dv_continuity[dr].iloc[i_date] >= (lpSum(sv_assign_win) - 1))
        problem += (dv_continuity[dr].iloc[i_date] >= 0)

# Define objective function to be minimized
problem += (c_outlier * lpSum(sv_outlier) \
          + c_continuity * lpSum(dv_continuity.to_numpy()) \
          + c_assign_suboptimal * dv_assign_suboptimal)

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
d_assign = pd.DataFrame(np.vectorize(value)(dv_assign), columns = l_dr, index = l_date).astype(bool)
d_assign_optimal = pd.DataFrame((d_availability == 2) & d_assign, columns = l_dr, index = l_date)                         
d_assign_suboptimal = pd.DataFrame((d_availability == 1) & d_assign, columns = l_dr, index = l_date)
d_assign_date = pd.concat([pd.Series(d_assign.sum(axis = 1), index = l_date, name = 'c'),
                           pd.Series(d_assign.apply(lambda row: str(row[row].index.to_list()[0]), axis = 1), index = l_date, name = 'dr')],
                           axis = 1)                      
d_assign_dr = pd.concat([pd.Series(d_assign.sum(axis = 0), index = l_dr, name = 'c_all'),
                         pd.Series(d_assign.apply(lambda col: col[col].index.to_list(), axis = 0), index = l_dr, name = 'date_all'),
                         pd.Series(d_assign_optimal.sum(axis = 0), index = l_dr, name = 'c_opt'),
                         pd.Series(d_assign_optimal.apply(lambda col: col[col].index.to_list(), axis = 0), index = l_dr, name = 'date_opt'),
                         pd.Series(d_assign_suboptimal.sum(axis = 0), index = l_dr, name = 'c_sub'),
                         pd.Series(d_assign_suboptimal.apply(lambda col: col[col].index.to_list(), axis = 0), index = l_dr, name = 'date_sub')],
                         axis = 1)

d_continuity = pd.DataFrame(np.vectorize(value)(dv_continuity), index = l_date[:(-min_interval + 1)], columns = l_dr)

