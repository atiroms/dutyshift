import numpy as np, pandas as pd
from pulp import *
from ortoolpy import addvars, addbinvars
from io import StringIO

p_availability = 'D:/NICT_WS/Dropbox/dutyshift/test/night01.csv'
#p_in = 'D:/atiro/Dropbox/dutyshift/test/night01.csv'
d_availability = pd.read_csv(p_availability)
d_availability = d_availability.set_index('dr')
d_availability = d_availability.T

l_dr = d_availability.columns
l_date = d_availability.index
n_dr = len(l_dr)
n_date = len(l_date)

dv_assign = pd.DataFrame(np.array(addbinvars(n_date, n_dr)), columns = l_dr, index = l_date)

m = LpProblem()

d_ng = d_availability == 0
for (_, r_ng),(_, r_assign) in zip(d_ng.iterrows(),dv_assign.iterrows()):
    # One doctor per day
    m += (lpSum(r_assign) == 1)
    # Do not assign to a day if not available
    m += (lpDot(r_ng, r_assign) <= 0)

m.solve()

d_result = pd.DataFrame(np.vectorize(value)(dv_assign), columns = l_dr, index = l_date)
#d_result.to_csv('D:/NICT_WS/Dropbox/dutyshift/test/night01_result.csv')

sn_assign_dr = pd.Series(d_result.sum(axis = 0), index = l_dr)
sn_assign_day = pd.Series(d_result.sum(axis = 1), index = l_date)
