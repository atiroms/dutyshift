
###############################################################################
# Libraries
###############################################################################
import numpy as np, pandas as pd
import os, datetime


###############################################################################
# Parameters
###############################################################################
#f_member = 'member.csv'
#l_class_duty = ['ampm','daynight_tot','night_em','night_wd','day_hd','night_hd','oc_tot','oc_hd_day','oc_other','ect']
year_plan = 2022
month_plan = 6
#d_src = '202205'
#d_dst = '202205'


###############################################################################
# Script path
###############################################################################
p_root = None
for p_test in ['/home/atiroms/Documents','D:/atiro','D:/NICT_WS','/Users/smrt']:
    if os.path.isdir(p_test):
        p_root = p_test

if p_root is None:
    print('No root directory.')
else:
    p_script=os.path.join(p_root,'GitHub/dutyshift')
    os.chdir(p_script)
    # Set paths and directories
    d_month = '{year:0>4d}{month:0>2d}'.format(year = year_plan, month = month_plan)
    p_month = os.path.join(p_root, 'Dropbox/dutyshift', d_month)
    d_data = datetime.datetime.now().strftime('collect_%Y%m%d_%H%M%S')
    p_result = os.path.join(p_month, 'result')
    p_data = os.path.join(p_result, d_data)
    for p_dir in [p_result, p_data]:
        if not os.path.exists(p_dir):
            os.makedirs(p_dir)

from helper import *


###############################################################################
# Read data
###############################################################################
f_answer = os.listdir(os.path.join(p_month, 'src'))
f_answer = [f for f in f_answer if '（回答）' in f][0]
d_availability_src = pd.read_csv(os.path.join(p_month, 'src',f_answer))

d_member = pd.read_csv(os.path.join(p_month, 'member.csv'))
d_member['name_jpn_full'] = d_member['name_jpn_full'].str.replace('　',' ')


###############################################################################
# Check missing members
###############################################################################
l_member_ans = d_availability_src['お名前（敬称略）'].tolist()
l_member_all = d_member['name_jpn_full'].tolist()
#l_member_all = [m.replace('\u3000',' ') for m in l_member_all]
l_member_missing = [m for m in l_member_all if m not in l_member_ans]
str_member_missing = ', '.join(l_member_missing)
l_mail_missing = d_member[d_member['name_jpn_full'].isin(l_member_missing)]['email'].tolist()
str_mail_missing = ', '.join(l_mail_missing)

print('Missing members/emails:')
print(str_member_missing)
print(str_mail_missing)


###############################################################################
# Format answer
###############################################################################
d_cal_duty = pd.read_csv(os.path.join(p_month, 'duty.csv'))
l_col = d_availability_src.columns.tolist()

dict_l_availability = {}

for idx, row in d_cal_duty.iterrows():
    title_dateduty = row['title_dateduty']
    dateduty = str(row['date']) + '_' + row['duty']
    l_col_dateduty = [col for col in l_col if ('[' + title_dateduty + ']') in col]
    l_availability = [np.nan] * d_availability_src.shape[0]
    for col in l_col_dateduty:
        l_availbility_src = d_availability_src[col].tolist()
        for idx, availability_src in enumerate(l_availbility_src):
            if availability_src == '不可':
                l_availability[idx] = 0
            elif availability_src == '可':
                l_availability[idx] = 1
            elif availability_src == '希望':
                l_availability[idx] = 2
    dict_l_availability[dateduty] = l_availability

d_availability = pd.DataFrame(dict_l_availability)
d_availability = pd.concat([pd.DataFrame({'id_member':[d_member.loc[d_member['name_jpn_full'] == n, 'id_member'].values[0] for n in l_member_ans],
                                         'name_jpn_full':l_member_ans}),
                           d_availability], axis = 1)
d_availability.sort_values(by = ['id_member'], inplace = True)
d_availability.index = d_availability['id_member'].tolist()

for p_save in [p_month, p_data]:
    d_availability.to_csv(os.path.join(p_save, 'availability.csv'), index = False)
