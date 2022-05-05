# Test LpVariable

import pandas as pd, numpy as np
import itertools
from pulp import *
l_member = [x for x in range(5)]
l_class_duty = ['ampm','daynight_tot','night_em']

l_count = [str(p[0]) + '_' + p[1] for p in itertools.product(l_member, l_class_duty)]
dict_v_count = LpVariable.dicts('count', l_count, 0, None,  LpInteger)
lv_count = list(dict_v_count.values())
llv_count = [lv_count[i:i+len(l_class_duty)] for i in range(0, len(lv_count), len(l_class_duty))]
dv_count = pd.DataFrame(llv_count, index = l_member, columns = l_class_duty)
