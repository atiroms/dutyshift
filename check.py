###############################################################################
# Libraries
###############################################################################
import pandas as pd
import os


###############################################################################
# Parameters
###############################################################################
# Unfixed parameters
year_plan = 2024
month_plan = 1


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


###############################################################################
# Check available member of a certain date_duty
###############################################################################
date_duty = '23_night'

d_member = pd.read_csv(os.path.join(p_month, 'member.csv'), index_col = 0)
d_availability = pd.read_csv(os.path.join(p_month, 'availability.csv'))
d_availability.index = d_availability['date_duty']
d_availability = d_availability.iloc[:,1:]

d_availability_t = d_availability.T
l_id_member_available = d_availability_t.index[d_availability_t[date_duty] > 0].tolist()
l_id_member_available = [int(id_member) for id_member in l_id_member_available]

l_name_member_available = d_member.loc[d_member['id_member'].isin(l_id_member_available), 'name_jpn_full'].tolist()
l_name_member_available = [name.replace('　',' ') for name in l_name_member_available]
d_check_availability = pd.DataFrame({'id_member': l_id_member_available, 'name_member': l_name_member_available})
print(d_check_availability)


###############################################################################
# Check available date_duty of a certain member
###############################################################################
id_member = 10

d_availability = pd.read_csv(os.path.join(p_month, 'availability.csv'))
d_availability.index = d_availability['date_duty']
d_availability = d_availability.iloc[:,1:]

l_date_duty_available = d_availability.loc[d_availability[str(id_member)] > 0,:].index.tolist()

print(l_date_duty_available)
