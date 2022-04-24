###############################################################################
# Libraries
###############################################################################
import numpy as np, pandas as pd
import os

d_src = '202204'
d_dst = '202204'

f_assign = 'assign_date.csv'
f_member = 'member.csv'
l_class_duty = ['ampm','daynight_tot','night_em','night_wd','day_hd','night_hd','oc_tot','oc_hd_day','oc_other','ect']
dict_duty = {'ect': 0, 'am': 1, 'pm': 2, 'day': 3, 'ocday': 4, 'night': 5, 'ocnight': 6}


###############################################################################
# Script path
###############################################################################
p_script = None
for p_root in ['/home/atiroms/Documents','D:/atiro','D:/NICT_WS','/Users/smrt']:
    if os.path.isdir(p_root):
        p_script=os.path.join(p_root,'GitHub/dutyshift')
        os.chdir(p_script)
        p_src = os.path.join(p_root, 'Dropbox/dutyshift', d_src)
        p_dst = os.path.join(p_root, 'Dropbox/dutyshift', d_dst)
if p_script is None:
    print('No root directory.')

from helper import *


###############################################################################
# Load data
###############################################################################
d_assign_date = pd.read_csv(os.path.join(p_src,f_assign))

# Prepare data of member specs and assignment limits
d_member, d_lim_hard, d_lim_soft = prep_member(p_src, f_member, l_class_duty)
d_member = d_member[['id_member','name_jpn','name']]

l_assign_dateduty = []
for duty in list(dict_duty.keys()):
    d_assign_date_duty = d_assign_date.loc[d_assign_date[duty].isna() == False, ['date', 'holiday', 'em',duty]]
    d_assign_date_duty.columns = ['date', 'holiday', 'em', 'name_jpn']
    d_assign_date_duty['duty'] = duty
    l_assign_dateduty.append(d_assign_date_duty)

d_assign_dateduty = pd.concat(l_assign_dateduty, axis = 0)
d_assign_dateduty.index = range(len(d_assign_dateduty))

d_assign_dateduty['date_duty'] = [str(x) + '_' + y for x,y in zip(d_assign_dateduty['date'], d_assign_dateduty['duty'])]
d_assign_dateduty = pd.merge(d_assign_dateduty, d_member, on = 'name_jpn', how = 'left')

d_assign_dateduty = d_assign_dateduty[['date_duty','date','duty','holiday','em','id_member','name_jpn','name']]
d_assign_dateduty.to_csv(os.path.join(p_dst, 'assign_date_duty.csv'), index = False)

d_duty_score = pd.DataFrame({'duty': ['am', 'pm', 'day', 'night', 'ocday', 'ocnight', 'ect'],
                             'score_ampm':        [0.5, 0.5, 0, 0, 0, 0, 0],
                             'score_daynight':    [0,   0,   1, 1, 0, 0, 0],
                             'score_ampmdaynight':[0.5, 0.5, 1, 1, 0, 0, 0],
                             'score_oc':          [0,   0,   0, 0, 1, 1, 0],
                             'score_ect':         [0,   0,   0, 0, 0, 0, 1]})

d_assign_dateduty = pd.merge(d_assign_dateduty, d_duty_score, on = 'duty', how = 'left')
d_assign_dateduty.loc[(d_assign_dateduty['duty'] == 'night') & (d_assign_dateduty['em'] == True), ['score_daynight','score_ampmdaynight']] = 1.5

l_type_score = ['ampm','daynight','ampmdaynight','oc','ect']
d_score = d_member.copy()
for id_member in d_score['id_member'].tolist():
    d_score_member = d_assign_dateduty.loc[d_assign_dateduty['id_member'] == id_member,
                                           ['score_' + type_score for type_score in l_type_score]]
    s_score_member = d_score_member.sum(axis = 0)
    d_score.loc[d_score['id_member'] == id_member,
                ['score_' + type_score for type_score in l_type_score]] = s_score_member.tolist()

d_score.to_csv(os.path.join(p_dst, 'score.csv'), index = False)
