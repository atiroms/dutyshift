
###############################################################################
# Libraries
###############################################################################
import numpy as np, pandas as pd
import os


###############################################################################
# Parameters
###############################################################################
f_member = 'member04.csv'
l_class_duty = ['ampm','daynight_tot','night_em','night_wd','day_hd','night_hd','oc_tot','oc_hd_day','oc_other','ect']
d_src = '202205'
d_dst = '202205'


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
# Collect data
###############################################################################
lf_result = os.listdir(p_src)
lf_result = [f for f in lf_result if '（回答）' in f]
l_member_ans = []

ld_availability = []

for f_result in lf_result:
    ld_availability.append(pd.read_csv(os.path.join(p_src, f_result)))

d_availability = pd.concat(ld_availability, axis = 0)
d_availability.index = range(len(d_availability))

col_ans = [col for col in d_availability.columns if 'ご希望' in col]
col_date = [col.split('/')[1].split('(')[0] for col in col_ans]
col_duty = []
for col in col_ans:
    if '午前' in col:
        col_duty.append('am')
    elif '午後' in col:
        col_duty.append('pm')
    elif '日直OC' in col:
        col_duty.append('ocday')
    elif '当直OC' in col:
        col_duty.append('ocnight')
    elif '日直' in col:
        col_duty.append('day')
    elif '当直' in col:
        col_duty.append('night')
    else:
        col_duty.append('')
col_date_duty = [col_date[i] + '_' + col_duty[i] for i in range(len(col_duty))]

d_availability = d_availability[['お名前（敬称略）'] + col_ans]
d_availability.columns = ['name_jpn'] + col_date_duty
d_availability = d_availability.fillna(0)
d_availability = d_availability.replace('不可', 0)
d_availability = d_availability.replace('可', 1)
d_availability = d_availability.replace('希望', 2)
d_availability.dtype = 'int64'

d_availability.to_csv(os.path.join(p_dst, 'availability.csv'), index = False)

# List of members who have answered
l_member_ans = list(set(d_availability['name_jpn'].tolist()))

# Prepare data of member specs and assignment limits
d_member, d_lim_hard, d_lim_soft = prep_member(p_src, f_member, l_class_duty)

# List of all members
l_member_all = d_member['name_jpn'].tolist()
# List of members who have not answered
l_member_missing = [m for m in l_member_all if m not in l_member_ans]

