
###############################################################################
# Libraries
###############################################################################
import numpy as np, pandas as pd
import os, datetime


###############################################################################
# Parameters
###############################################################################
year_plan = 2023
month_plan = 3


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
    d_data = datetime.datetime.now().strftime('replace_%Y%m%d_%H%M%S')
    p_result = os.path.join(p_month, 'result')
    p_data = os.path.join(p_result, d_data)
    for p_dir in [p_result, p_data]:
        if not os.path.exists(p_dir):
            os.makedirs(p_dir)

from helper import *


###############################################################################
# Read and clean data
###############################################################################
d_member = pd.read_csv(os.path.join(p_month, 'member.csv'))
d_member['name_jpn_full'] = d_member['name_jpn_full'].str.replace('　',' ')

f_answer = os.listdir(os.path.join(p_month, 'src'))
f_answer = [f for f in f_answer if '当直交代申請' in f][0]
d_replace = pd.read_csv(os.path.join(p_month, 'src',f_answer))
d_replace = d_replace[['交代する日付','交代する業務','交代後の担当者（敬称略）']]
d_replace = d_replace.rename(columns={'交代する日付':'ymd','交代する業務':'duty','交代後の担当者（敬称略）':'name_jpn_full'})
d_replace['year'] = [int(ymd.split('/')[0]) for ymd in d_replace['ymd']]
d_replace['month'] = [int(ymd.split('/')[1]) for ymd in d_replace['ymd']]
d_replace['date'] = [int(ymd.split('/')[2]) for ymd in d_replace['ymd']]
d_replace = d_replace[(d_replace['year'] == year_plan) & (d_replace['month'] == month_plan)]
d_replace = pd.merge(d_replace, d_member[['name_jpn_full','id_member','name','name_jpn']], on='name_jpn_full', how='left')

#d_time_duty = pd.read_csv(os.path.join(p_root, 'Dropbox/dutyshift/config/time_duty.csv'))
# TODO: replace 当直 as emnight
dict_replace = {'午前日直':'am', '午後日直':'pm', '休日日直':'day', '当直':'night', '日直オンコール':'ocday','当直オンコール':'ocnight','ECT当番':'ect'}
d_replace['duty'] = [dict_replace[duty] for duty in d_replace['duty']]

#d_replace['duty'] = [d_time_duty[d_time_duty['duty_jpn'] == duty]['duty'].values[0] for duty in d_replace['duty'].tolist()]

d_assign_date_duty = pd.read_csv(os.path.join(p_month, 'assign_date_duty.csv'))

d_cal = pd.read_csv(os.path.join(p_month, 'calendar.csv'))


###############################################################################
# Replace data
###############################################################################
# TODO: consider desiganation status difference
for id, row in d_replace.iterrows():
    d_assign_date_duty.loc[(d_assign_date_duty['date'] == row['date']) & (d_assign_date_duty['duty'] == row['duty']), ['id_member','name','name_jpn']] = row[['id_member','name','name_jpn']].tolist()

# Assignments with date as row for printing
d_assign_date_print = d_cal.loc[:,['title_date','date', 'em']].copy()
d_assign_date_print[['am','pm','night','ocday','ocnight','ect']] = ''
for _, row in d_assign_date_duty.loc[d_assign_date_duty['cnt'] > 0].iterrows():
    date = row['date']
    duty = row['duty']
    name_jpn = row['name_jpn']
    if duty == 'day':
        d_assign_date_print.loc[d_assign_date_print['date'] == date, 'am'] = name_jpn
        d_assign_date_print.loc[d_assign_date_print['date'] == date, 'pm'] = name_jpn
    elif duty == 'emnight':
        d_assign_date_print.loc[d_assign_date_print['date'] == date, 'night'] = name_jpn
    else:
        d_assign_date_print.loc[d_assign_date_print['date'] == date, duty] = name_jpn
for date in d_assign_date_print.loc[d_assign_date_print['em'] == True, 'date'].tolist():
    d_assign_date_print.loc[d_assign_date_print['date'] == date, 'night'] += '(救急)'
d_assign_date_print = d_assign_date_print.loc[:,['title_date','am','pm','night','ocday','ocnight','ect']]
d_assign_date_print.columns = ['日付', '午前日直', '午後日直', '当直', '日直OC', '当直OC', 'ECT']

# TODO: replace other csv files
for p_save in [p_month, p_data]:
    d_assign_date_duty.to_csv(os.path.join(p_save, 'assign_date_duty.csv'), index = False)
    d_assign_date_print.to_csv(os.path.join(p_save, 'assign_date.csv'), index = False)


###############################################################################
# Replace GCalencar
###############################################################################
# TODO: repalce Google Calendar