import numpy as np, pandas as pd
import os
from pulp import *
from ortoolpy import addvars, addbinvars
from io import StringIO

#p_test = 'D:/NICT_WS/Dropbox/dutyshift/test'
p_test = 'D:/atiro/Dropbox/dutyshift/test'

c_outlier = 1.0

# Data of Dr availability
d_availability = pd.read_csv(os.path.join(p_test, 'night01.csv'))
d_availability = d_availability.set_index('dr')
d_availability = d_availability.T

l_dr = d_availability.columns
l_date = d_availability.index
n_dr = len(l_dr)
n_date = len(l_date)

# Data of assignment count limits
d_count = pd.read_csv(os.path.join(p_test, 'membertest01.csv'))
d_count = d_count.set_index('dr')

# Binary assignment variables to be optimized
dv_assign = pd.DataFrame(np.array(addbinvars(n_date, n_dr)), columns = l_dr, index = l_date)

# Model to be optimized
problem = LpProblem()

# Iterate over date
for date in l_date:
    s_availability = d_availability.loc[date]
    s_ng = (s_availability == 0)
    sv_assign = dv_assign.loc[date]
    # One member per date
    problem += (lpSum(sv_assign) == 1)
    # Do not assign to a date if not available
    problem += (lpDot(s_ng, sv_assign) <= 0)

# v_outlier represents excess from max or shortage from min in the shape of '\__/
# Iterate over members
v_outlier = pd.Series(np.array(addvars(n_dr)), index = l_dr)
for dr in l_dr:
    problem += (v_outlier[dr] >= lpSum(dv_assign[dr]) - d_count.loc[dr, 'max'])
    problem += (v_outlier[dr] >= d_count.loc[dr, 'min'] - lpSum(dv_assign[dr]))
    problem += (v_outlier[dr] >= 0)

# Minimize outlier
problem += c_outlier * lpSum(v_outlier)

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
d_result = pd.DataFrame(np.vectorize(value)(dv_assign), columns = l_dr, index = l_date)
#d_result.to_csv('D:/NICT_WS/Dropbox/dutyshift/test/night01_result.csv')

sn_assign_dr = pd.Series(d_result.sum(axis = 0), index = l_dr)
sn_assign_day = pd.Series(d_result.sum(axis = 1), index = l_date)
