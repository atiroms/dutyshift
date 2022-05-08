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

####

prob_cnt = LpProblem()

# Exact assignment counts to be optimized
l_lim_exact = [str(p[0]) + '_' + p[1] for p in itertools.product(l_member, l_class_duty)]
dict_v_lim_exact = LpVariable.dicts('count', l_lim_exact, 0, None,  LpInteger)
lv_lim_exact = list(dict_v_lim_exact.values())
llv_lim_exact = [lv_lim_exact[i:i+len(l_class_duty)] for i in range(0, len(lv_lim_exact), len(l_class_duty))]
dv_lim_exact = pd.DataFrame(llv_lim_exact, index = l_member, columns = l_class_duty)

# TODO: innate condition for class_duty

# Condition on sum of class_duty
for class_duty in l_class_duty:
    prob_cnt += (lpSum(dv_lim_exact.loc[:,class_duty]) == s_cnt_class_duty[class_duty])

# Condition using hard limits
for member in l_member:
    for class_duty in l_class_duty:
        lim_hard = d_lim_hard.loc[member, class_duty]
        if ~np.isnan(lim_hard[0]):
            prob_cnt += (dv_lim_exact.loc[member, class_duty] <= lim_hard[1])
            prob_cnt += (lim_hard[0] <= dv_lim_exact.loc[member, class_duty])

# Convert variables in dv_lim_exact to dv_score (current + past scores)
dv_score = pd.DataFrame(np.array(addvars(len(l_member), len(l_type_score))),
                        index = l_member, columns = l_type_score)
d_score_class = pd.read_csv(os.path.join(p_root, 'Dropbox/dutyshift/config/score_class.csv'))
for type_score in l_type_score:
    d_score_class_temp = d_score_class.loc[d_score_class['score'] == type_score,:].copy()
    l_class_duty_tmp = d_score_class_temp['class'].tolist()
    l_constant_tmp = d_score_class_temp['constant'].tolist()
    for member in l_member:
        lv_lim_exact_tmp = dv_lim_exact.loc[member, l_class_duty_tmp].tolist()
        prob_cnt += (dv_score.loc[member, type_score] == lpDot(lv_lim_exact_tmp, l_constant_tmp) + d_score_past.loc[d_score_past['id_member'] == member, type_score].values[0])
