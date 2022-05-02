import numpy as np, pandas as pd
import os
from pulp import *
from ortoolpy import addvars, addbinvars
from io import StringIO

#p_test = 'D:/NICT_WS/Dropbox/dutyshift/test'
p_test = 'D:/atiro/Dropbox/dutyshift/test'

c_outlier = 1.0
min_interval = 7
c_continuity = 1.0
c_assign_suboptimal = 0.1

# Data of Dr availability
d_availability = pd.read_csv(os.path.join(p_test, 'night01.csv'))
d_availability = d_availability.set_index('dr')
d_availability = d_availability.T

l_dr = d_availability.columns.to_list()
l_date = d_availability.index.to_list()
n_dr = len(l_dr)
n_date = len(l_date)

# Data of assignment count limits
d_count = pd.read_csv(os.path.join(p_test, 'membertest01.csv'))
d_count = d_count.set_index('dr')

# Binary assignment variables to be optimized
dv_assign = pd.DataFrame(np.array(addbinvars(n_date, n_dr)), columns = l_dr, index = l_date)

# Model to be optimized
problem = LpProblem()

# Assign one Dr per date
for date in l_date:
    problem += (lpSum(dv_assign.loc[date]) == 1)

# Do not assign to a date if not available
problem += (lpDot((d_availability == 0).to_numpy(), dv_assign.to_numpy()) <= 0)

# Penalize suboptimal assignment
dv_assign_suboptimal = lpDot((d_availability == 1).to_numpy(), dv_assign.to_numpy())

# Minimize outlier
# Penalize excess from max or shortage from min in the shape of '\__/
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

