
###############################################################################
# Libraries
###############################################################################
import numpy as np, pandas as pd
import os, datetime


###############################################################################
# Parameters
###############################################################################
year_plan = 2023
month_plan = 7


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
f_answer = [f for f in f_answer if 'dutyshift' in f][0]
d_availability_src = pd.read_csv(os.path.join(p_month, 'src',f_answer))

d_member = pd.read_csv(os.path.join(p_month,'src', 'member.csv'))
d_member['name_jpn_full'] = d_member['name_jpn_full'].str.replace('　',' ')


###############################################################################
# Check missing members
###############################################################################
l_member_ans = list(set(d_availability_src['お名前（敬称略）'].tolist()))
#l_member_all = d_member['name_jpn_full'].tolist()
#l_member_all = [m.replace('\u3000',' ') for m in l_member_all]
l_member_active = d_member.loc[d_member['active'] == True, 'name_jpn_full'].tolist()
l_member_missing = [m for m in l_member_active if m not in l_member_ans]
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
#d_availability = d_availability.fillna(0)

d_availability_head = d_availability_src[['お名前（敬称略）', 'Timestamp']].copy()
d_availability_head.columns = ['name_jpn_full', 'timestamp']
#d_availability_head = pd.merge(d_availability_head, d_member[['name_jpn_full', 'id_member']], on = 'name_jpn_full')
d_availability_head['unixtime'] = d_availability_head['timestamp'].apply(lambda x: datetime.datetime.strptime(x, '%m/%d/%Y %H:%M:%S').timestamp())

# Designation
l_designation = [np.nan] * d_availability_src.shape[0]
for col in [col for col in l_col if '指定医' in col]:
    l_designation_src = d_availability_src[col].tolist()
    for idx, designation_src in enumerate(l_designation_src):
        if designation_src == '指定医':
            l_designation[idx] = True
        elif designation_src == '非指定医':
            l_designation[idx] = False
d_availability_head['designation'] = l_designation

# Two assignments per month
l_assign_twice = [np.nan] * d_availability_src.shape[0]
col = [col for col in l_col if '月2回' in col][0]
l_assign_twice_src = d_availability_src[col].tolist()
for idx, assign_twice_src in enumerate(l_assign_twice_src):
    if assign_twice_src == '可':
        l_assign_twice[idx] = True
    elif assign_twice_src == '不可':
        l_assign_twice[idx] = False
d_availability_head['assign_twice'] = l_assign_twice

# Request
col = [col for col in l_col if 'ご要望' in col][0]
l_request = d_availability_src[col].tolist()
d_availability_head['request'] = l_request

# Concatenate
d_availability = pd.concat([d_availability_head, d_availability], axis = 1)
d_availability = pd.merge(d_availability, d_member[['name_jpn_full', 'id_member']], on = 'name_jpn_full')

# Pick up newest of each member
l_id_member = sorted(list(set(d_availability['id_member'].tolist())))
l_d_availability = []
for id_member in l_id_member:
    d_availability_member = d_availability[d_availability['id_member'] == id_member]
    d_availability_member = d_availability_member.sort_values(by = ['unixtime'], ascending = False)
    d_availability_member = d_availability_member.iloc[0]
    l_d_availability.append(d_availability_member)
d_availability = pd.DataFrame(l_d_availability)

# Index
d_availability.index = d_availability['id_member'].tolist()
d_info = d_availability[['id_member','name_jpn_full','designation','assign_twice','request']].copy()
d_availability = d_availability[['id_member','name_jpn_full'] + list(dict_l_availability.keys())]

for p_save in [p_month, p_data]:
    d_availability.to_csv(os.path.join(p_save, 'availability_src.csv'), index = False)
    d_info.to_csv(os.path.join(p_save, 'info.csv'), index = False)
