
import numpy as np, pandas as pd
import os
import datetime as dt
from script.helper import *
from script.notify import *

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError


def check_replacement(lp_root, year_plan, month_plan, sheet_id):
    p_root, p_month, p_data = prep_dirs(lp_root, year_plan, month_plan, prefix_dir = '', make_data_dir = False)


    ###############################################################################
    # Read and convert data
    ###############################################################################
    d_member = pd.read_csv(os.path.join(p_month, 'member.csv'))
    d_member['name_jpn_full'] = d_member['name_jpn_full'].str.replace('　',' ')
    d_assign_date_duty = pd.read_csv(os.path.join(p_month, 'assign_date_duty.csv'))

    #f_answer = os.listdir(os.path.join(p_month, 'src'))
    #f_answer = [f for f in f_answer if '当直交代申請' in f][0]
    #d_replace = pd.read_csv(os.path.join(p_month, 'src',f_answer))
    sheet_name = "response"
    d_replace = pd.read_csv(f"https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?tqx=out:csv&sheet={sheet_name}")

    d_replace = d_replace[['交代する日付','交代する業務','交代後の担当者（敬称略）']]
    d_replace = d_replace.rename(columns={'交代する日付':'ymd','交代する業務':'duty','交代後の担当者（敬称略）':'name_jpn_full'})
    d_replace['year'] = [int(ymd.split('/')[0]) for ymd in d_replace['ymd']]
    d_replace['month'] = [int(ymd.split('/')[1]) for ymd in d_replace['ymd']]
    d_replace['date'] = [int(ymd.split('/')[2]) for ymd in d_replace['ymd']]
    d_replace = d_replace[(d_replace['year'] == year_plan) & (d_replace['month'] == month_plan)]
    d_replace = pd.merge(d_replace, d_member[['name_jpn_full','id_member','name','name_jpn']], on='name_jpn_full', how='left')
    dict_replace = {'午前日直':'am', '午後日直':'pm', '休日日直':'day', '当直':'night', '日直オンコール':'ocday','当直オンコール':'ocnight','ECT当番':'ect'}
    d_replace['duty'] = [dict_replace[duty] for duty in d_replace['duty']]


    ###############################################################################
    # Check data and delete duplication
    # d_replace_checked as result
    ###############################################################################
    # Delete duplicate data in d_replace
    d_replace_checked = pd.DataFrame(columns = d_replace.columns)
    for id, row in d_replace.iterrows():
        row_duplicate = d_replace_checked.loc[(d_replace_checked['ymd'] == row['ymd']) & (d_replace_checked['duty'] == row['duty']), :]
        if len(row_duplicate) > 0: # Overwirte if duplicate
            d_replace_checked.loc[(d_replace_checked['ymd'] == row['ymd']) & (d_replace_checked['duty'] == row['duty']), :] = row.to_list()
        else:
            d_replace_checked.loc[len(d_replace_checked), :] = row

    # Delete already replaced data
    for id, row in d_replace_checked.iterrows():
        member_src = d_assign_date_duty.loc[(d_assign_date_duty['date'] == row['date']) & (d_assign_date_duty['duty'] == row['duty']), ['id_member', 'name_jpn']]
        if row['id_member'] == member_src['id_member'].tolist()[0]: # already replaced
            d_replace_checked = d_replace_checked.drop(id)
        elif np.isnan(row['id_member']) and np.isnan(member_src['id_member'].tolist()[0]):
            d_replace_checked = d_replace_checked.drop(id)
        else:
            d_replace_checked.loc[id, 'name_jpn_src'] = member_src['name_jpn'].tolist()[0]

    d_replace_checked.index = [i for i in range(len(d_replace_checked))]

    if len(d_replace_checked) > 0:
        d_replace_print = d_replace_checked[['month', 'date', 'duty', 'name_jpn_src', 'name_jpn']]
        d_replace_print.columns = ['month', 'date', 'duty', 'before', 'after']

        print('Replacing:')
        print(d_replace_print)
    else:
        print('No new data detected')

    return d_replace_checked


def replace_assignment(lp_root, year_plan, month_plan, l_type_score, l_class_duty, d_replace_checked = None):
    p_root, p_month, p_data = prep_dirs(lp_root, year_plan, month_plan, prefix_dir = 'rplc')

    ###############################################################################
    # Replace data
    # update d_assign_duty according to d_replace_checked
    ###############################################################################

    # OPTIONAL: specify which replacement to execute
    #li_replace = [0, 1]
    #d_replace_checked = d_replace_checked.loc[li_replace, :]
                
    d_assign_date_duty = pd.read_csv(os.path.join(p_month, 'assign_date_duty.csv'))

    # TODO: consider desiganation status difference
    if d_replace_checked is not None:
        for id, row in d_replace_checked.iterrows():
            d_assign_date_duty.loc[(d_assign_date_duty['date'] == row['date']) & (d_assign_date_duty['duty'] == row['duty']), ['id_member','name','name_jpn']] = row[['id_member','name','name_jpn']].tolist()

    d_availability = pd.read_csv(os.path.join(p_month, 'availability.csv'), index_col = 0)
    d_date_duty = pd.read_csv(os.path.join(p_month, 'date_duty.csv'))
    d_lim_exact = pd.read_csv(os.path.join(p_month, 'lim_exact.csv'), index_col = 0)

    for p_save in [p_month, p_data]:
        # TODO: convert d_assign
        #d_assign.to_csv(os.path.join(p_save, 'assign.csv'), index = True)
        d_assign_date_duty.to_csv(os.path.join(p_save, 'assign_date_duty.csv'), index = False)

    d_cal = pd.read_csv(os.path.join(p_month, 'calendar.csv'))
    d_member = pd.read_csv(os.path.join(p_month, 'member.csv'))
    d_member['name_jpn_full'] = d_member['name_jpn_full'].str.replace('　',' ')

    d_assign, d_assign_date_print, d_assign_member, d_deviation, d_deviation_summary, d_score_current, d_score_total, d_score_print =\
        convert_result(p_month, p_data, d_assign_date_duty, d_availability, 
                       d_member, d_date_duty, d_cal, l_class_duty, l_type_score, d_lim_exact)
    
    return d_assign, d_assign_date_print, d_assign_member, d_deviation, d_deviation_summary, d_score_current, d_score_total, d_score_print


'''def add_replaced_calendar(lp_root, year_plan, month_plan, d_replace_checked, l_scope):
    p_root, p_month, p_data = prep_dirs(lp_root, year_plan, month_plan, prefix_dir = '', make_data_dir = False)

    ###############################################################################
    # Handle Credentials and token
    ###############################################################################
    creds = None
    p_token = os.path.join(p_root, 'Dropbox/dutyshift/config/credentials/token.json')
    p_cred = os.path.join(p_root, 'Dropbox/dutyshift/config/credentials/credentials.json')

    flow = InstalledAppFlow.from_client_secrets_file(p_cred, l_scope)
    creds = flow.run_local_server(port=0)
    print('credentials.json used.')
    # Save the credentials for the next run
    with open(p_token, 'w') as token:
        token.write(creds.to_json())


    ###############################################################################
    # Read Calendar ID of psydutyshift
    ###############################################################################
    p_id_calendar = os.path.join(p_root, 'Dropbox/dutyshift/config/calendarid/id_psydutyshift.txt')
    if os.path.exists(p_id_calendar):
        with open(p_id_calendar, 'r') as f:
            id_calendar_duty = f.read()
        print('Read Calendar ID: ', id_calendar_duty)


    ###############################################################################
    # Create and share events
    ###############################################################################
    d_time_duty = pd.read_csv(os.path.join(p_root, 'Dropbox/dutyshift/config/time_duty.csv'))
    d_member = pd.read_csv(os.path.join(p_month, 'member.csv'))
    d_availability = pd.read_csv(os.path.join(p_month, 'availability.csv'))
    d_date_duty = pd.read_csv(os.path.join(p_month, 'assign_date_duty.csv'))
    d_date_duty = d_date_duty.loc[d_date_duty['cnt'] > 0, :]
    ####
    # Used for testing
    #d_date_duty = d_date_duty.loc[d_date_duty['id_member'] == 11,:]
    #d_date_duty = d_date_duty.iloc[0:2,:]
    ####
    d_date_duty = pd.merge(d_date_duty, d_member[['id_member','name_jpn_full','email']], on = 'id_member', how = 'left')
    d_date_duty = pd.merge(d_date_duty, d_time_duty, on = 'duty', how = 'left')

    service = build('calendar', 'v3', credentials = creds)
    l_result_event = []

    l_date_duty_replace = []
    for id, row in d_replace_checked.iterrows():
        l_date_duty_replace.append(d_date_duty.loc[(d_date_duty['month'] == row['month']) & (d_date_duty['date'] == row['date']) & (d_date_duty['duty'] == row['duty']), :])
    d_date_duty_replace = pd.concat(l_date_duty_replace)

    for _, row in d_date_duty_replace.iterrows():
        date_duty = row['date_duty']
        title_duty = row['duty_jpn']
        date = int(row['date'])
        duty = row['duty']
        id_member = int(row['id_member'])
        name_member = row['name_jpn_full'].replace('　',' ')
        email = row['email']
        str_start = row['start']
        str_end = row['end']
        t_start = (dt.datetime(year = year_plan, month = month_plan, day = date) +\
                    dt.timedelta(hours = int(str_start[0:2]), minutes = int(str_start[3:5]))).isoformat()
        t_end = (dt.datetime(year = year_plan, month = month_plan, day = date) +\
                    dt.timedelta(hours = int(str_end[0:2]), minutes = int(str_end[3:5]))).isoformat()
        s_id_member_proxy = d_availability.loc[d_availability['date_duty'] == date_duty,:].reset_index(drop=True).squeeze().iloc[1:]
        l_id_member_proxy = [int(id) for id in s_id_member_proxy.loc[s_id_member_proxy > 0].index.tolist()]
        d_member_proxy = d_member.loc[d_member['id_member'].isin(l_id_member_proxy),['id_member', 'name_jpn_full', 'designation']]
        # Consider designation status for day and night
        if duty in ['day','night']:
            designation_member = d_member.loc[d_member['id_member'] == id_member, 'designation'].tolist()[0]
            l_id_member_proxy = d_member_proxy.loc[d_member_proxy['designation'] == designation_member, 'id_member'].tolist()
            l_id_member_proxy_sub = d_member_proxy.loc[d_member_proxy['designation'] != designation_member, 'id_member'].tolist()
        else:
            l_id_member_proxy_sub = []
        l_id_member_proxy = [id for id in l_id_member_proxy if id != id_member]
        if len(l_id_member_proxy) > 0:
            l_member_proxy = d_member_proxy.loc[d_member_proxy['id_member'].isin(l_id_member_proxy),'name_jpn_full'].tolist()
            l_member_proxy = [name.replace('　',' ') for name in l_member_proxy]
            str_member_proxy = ','.join(l_member_proxy)
        else:
            str_member_proxy = ''
        if len(l_id_member_proxy_sub) > 0:
            l_member_proxy_sub = d_member_proxy.loc[d_member_proxy['id_member'].isin(l_id_member_proxy_sub),'name_jpn_full'].tolist()
            l_member_proxy_sub = [name.replace('　',' ') for name in l_member_proxy_sub]
            str_member_proxy = str_member_proxy + '(,' + ','.join(l_member_proxy_sub) + ')'
        if str_member_proxy == '':
            str_member_proxy == 'なし'

        description = name_member + '先生ご担当\n代理候補(敬称略): ' + str_member_proxy +\
                        '\nhttps://github.com/atiroms/dutyshift で自動生成'

        body_event = {'summary': title_duty,
                        'location': '東大病院',
                        'start': {'dateTime': t_start, 'timeZone': 'Asia/Tokyo'},
                        'end': {'dateTime': t_end, 'timeZone': 'Asia/Tokyo'},
                        'attendees': [{'email': email}],
                        #'attendees': [{'email': email, 'displayName':name_member}],
                        #'attendees': [{'email': email, 'responseStatus':'accepted'}],
                        'description': description
                        }
        result_event = service.events().insert(calendarId=id_calendar_duty,body=body_event).execute()
        l_result_event.append(result_event)

    return l_result_event
'''