
import numpy as np, pandas as pd
import os, datetime
from pulp import *
from ortoolpy import *

prob = LpProblem()

dv_assign = pd.DataFrame(np.array(addvars(1, 2)))
d_fixed = pd.DataFrame([[1,2],[3,4]])

dv_mixed = pd.concat([dv_assign,d_fixed], axis = 0)

prob += (lpSum(dv_mixed.iloc[:,0]) == 5)
prob += (lpSum(dv_mixed.iloc[:,1]) == 8)

prob.solve()

dv_mixed.iloc[0,0].value()
dv_mixed.iloc[0,1].value()
