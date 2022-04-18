
###############################################################################
# Libraries
###############################################################################
import numpy as np, pandas as pd
import os

###############################################################################
# Parameters
###############################################################################
d_src = '202205'
d_dst = '202205'


###############################################################################
# Script path
###############################################################################
p_script = None
for p_root in ['/home/atiroms/Documents','D:/atiro','C:/Users/NICT_WS','/Users/smrt']:
    if os.path.isdir(p_root):
        p_script=os.path.join(p_root,'GitHub/dutyshift')
        os.chdir(p_script)
        p_src = os.path.join(p_root, 'Dropbox/dutyshift', d_src)
        p_dst = os.path.join(p_root, 'Dropbox/dutyshift', d_dst)
if p_script is None:
    print('No root directory.')


###############################################################################
# List member
###############################################################################
l_dir_result = os.listdir(p_src)
l_member_ans = []

for dir_result in l_dir_result:
    d_result = pd.read_csv(os.path.join(p_src,dir_result))
    l_member_ans += d_result['お名前（敬称略）'].values.tolist()
