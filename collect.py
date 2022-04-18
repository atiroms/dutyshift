
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
# List member
###############################################################################
lf_result = os.listdir(p_src)
lf_result = [f for f in lf_result if '（回答）' in f]
l_member_ans = []

for f_result in lf_result:
    d_result = pd.read_csv(os.path.join(p_src, f_result))
    l_member_ans += d_result['お名前（敬称略）'].values.tolist()

# List of members who have answered
l_member_ans = list(set(l_member_ans))

# Prepare data of member specs and assignment limits
d_member, d_lim_hard, d_lim_soft = prep_member(p_src, f_member, l_class_duty)

# List of all members
l_member_all = d_member['name_jpn'].tolist()
# List of members who have not answered
l_member_missing = [m for m in l_member_all if m not in l_member_ans]
