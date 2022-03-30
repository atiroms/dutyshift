import numpy as np, pandas as pd
from pulp import *
from ortoolpy import addvars, addbinvars
from io import StringIO

#p_in = 'D:/NICT_WS/Dropbox/dutyshift/refs/dr_fujikawa/night01.csv'
p_in = 'D:/atiro/Dropbox/dutyshift/test/night01.csv'
d_in = pd.read_csv(p_in)
d_in = d_in.set_index('dr')
d_in = d_in.T

d_shift = pd.DataFrame(np.ndarray())

model = LpProblem()