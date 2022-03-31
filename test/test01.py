import numpy as np, pandas as pd
from pulp import *
from ortoolpy import addvars, addbinvars
from io import StringIO

# Data of Dr availability
p_availability = 'D:/NICT_WS/Dropbox/dutyshift/test/night01.csv'
#p_in = 'D:/atiro/Dropbox/dutyshift/test/night01.csv'
d_availability = pd.read_csv(p_availability)
d_availability = d_availability.set_index('dr')
d_availability = d_availability.T

l_dr = d_availability.columns
l_date = d_availability.index
n_dr = len(l_dr)
n_date = len(l_date)

# Data of assignment count limits
p_count = 'D:/NICT_WS/Dropbox/dutyshift/test/membertest01.csv'
d_count = pd.read_csv(p_count)
d_count = d_count.set_index('dr')

# Binary assignment variables to be optimized
dv_assign = pd.DataFrame(np.array(addbinvars(n_date, n_dr)), columns = l_dr, index = l_date)

# Model to be optimized
m = LpProblem()

# Iterate over days
for (_, r_availability),(_, r_assign) in zip(d_availability.iterrows(),dv_assign.iterrows()):
    r_ng = (r_availability == 0)
    # One member per day
    m += (lpSum(r_assign) == 1)
    # Do not assign to a day if not available
    m += (lpDot(r_ng, r_assign) <= 0)

v_excess = pd.Series(np.array(addvars(n_dr)), index = l_dr)
v_shortage = pd.Series(np.array(addvars(n_dr)), index = l_dr)

# Iterate over members
for dr in l_dr:
    # Excess of assignment count
    m += (v_excess[dr] == d_count.loc[dr, 'max'] - lpSum(dv_assign[dr]))
    # Shortage of assignment count
    m += (v_shortage[dr] == lpSum(dv_assign[dr]) - d_count.loc[dr, 'min'])
    # Excess of assignment count must be 0
    m += (v_excess[dr] == 0)
    # Shortage of assignment count must be 0
    m += (v_shortage[dr] == 0)


# Optimize model
m.solve()

# Extract values from variable
d_result = pd.DataFrame(np.vectorize(value)(dv_assign), columns = l_dr, index = l_date)
#d_result.to_csv('D:/NICT_WS/Dropbox/dutyshift/test/night01_result.csv')

sn_assign_dr = pd.Series(d_result.sum(axis = 0), index = l_dr)
sn_assign_day = pd.Series(d_result.sum(axis = 1), index = l_date)
