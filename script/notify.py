
import pandas as pd, datetime as dt
import os
from time import sleep
from script.helper import *

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError


def access_calendar(p_root, l_scope):
    # Handle Credentials and token
    p_token = os.path.join(p_root, 'Dropbox/dutyshift/config/credentials/token.json')
    p_cred = os.path.join(p_root, 'Dropbox/dutyshift/config/credentials/credentials.json')

    flow = InstalledAppFlow.from_client_secrets_file(p_cred, l_scope)
    creds = flow.run_local_server(port=0)
    #print('credentials.json used.')
    # Save the credentials for the next run
    with open(p_token, 'w') as token:
        token.write(creds.to_json())

    service = build('calendar', 'v3', credentials = creds)

    # Read Calendar ID of psydutyshift
    p_id_calendar = os.path.join(p_root, 'Dropbox/dutyshift/config/calendarid/id_psydutyshift.txt')
    if os.path.exists(p_id_calendar):
        with open(p_id_calendar, 'r') as f:
            id_calendar = f.read()
        #print('Read Calendar ID: ', id_calendar_duty)

    return service, id_calendar


def compare_event(d_assign_date_duty, d_event_exist):
    l_date_duty_assigned = d_assign_date_duty.loc[~np.isnan(d_assign_date_duty['id_member']), 'date_duty'].tolist()
    l_date_duty_delete = [dd for dd in d_event_exist['date_duty'].tolist() if dd not in l_date_duty_assigned]
    l_date_duty_change = []
    l_date_duty_add = []
    for id, row in d_assign_date_duty.loc[~np.isnan(d_assign_date_duty['id_member']), :].iterrows():
        date_duty = row['date_duty']
        id_member = int(row['id_member'])
        id_member_calendar = d_event_exist.loc[d_event_exist['date_duty'] == date_duty, 'id_member'].tolist()
        if len(id_member_calendar) > 0:
            if id_member_calendar[0] != id_member:
                l_date_duty_change.append(date_duty)
        else:
            l_date_duty_add.append(date_duty)

    return l_date_duty_delete, l_date_duty_change, l_date_duty_add


def update_calendar(lp_root, year_plan, month_plan, l_scope, dict_time_duty, mode_add = 'all', t_sleep = 0.0):
    p_root, p_month, p_data = prep_dirs(lp_root, year_plan, month_plan, prefix_dir = '', make_data_dir = False)
    d_member = pd.read_csv(os.path.join(p_month, 'member.csv'), index_col = 0)

    # Access calendar
    service_calendar, id_calendar = access_calendar(p_root, l_scope)

    # Read events on G calendar
    d_assign_calendar = list_duty(service_calendar, id_calendar, year_plan, month_plan, d_member, dict_time_duty)

    # Read target assignment
    d_assign_date_duty = pd.read_csv(os.path.join(p_month, 'assign_date_duty.csv'))

    # Compare existing and target events
    l_date_duty_delete, l_date_duty_change, l_date_duty_add = compare_event(d_assign_date_duty, d_assign_calendar)

    # Delete events
    l_result_delete = delete_duty(service_calendar, id_calendar, l_date_duty_delete + l_date_duty_change, d_assign_calendar)

    # Add events
    d_date_duty_add = d_assign_date_duty.loc[d_assign_date_duty['date_duty'].isin(l_date_duty_add + l_date_duty_change), :]
    d_member = pd.read_csv(os.path.join(p_month, 'member.csv'), index_col = 0)
    d_availability = pd.read_csv(os.path.join(p_month, 'availability.csv'))
    d_time_duty = pd.DataFrame(dict_time_duty)

    if mode_add == 'all':
        l_result_add = add_duty(service_calendar, id_calendar, d_date_duty_add, d_member, d_time_duty, d_availability)
    elif mode_add == 'member':
        l_result_add = []
        l_member = sorted(list(set(d_date_duty_add['id_member'])))
        for id_member in l_member:
            print('Adding member:', str(id_member))
            d_date_duty_member = d_date_duty_add[d_date_duty_add['id_member'] == id_member]
            l_result_add_add = add_duty(service_calendar, id_calendar, d_date_duty_member, d_member, d_time_duty, d_availability)
            l_result_add += l_result_add_add
            sleep(t_sleep)

    # Assert result
    d_assign_calendar = list_duty(service_calendar, id_calendar, year_plan, month_plan, d_member, dict_time_duty)
    l_date_duty_delete, l_date_duty_change, l_date_duty_add = compare_event(d_assign_date_duty, d_assign_calendar)
    if len(l_date_duty_delete) > 0:
        print('Duty not deleted ', l_date_duty_delete)
    if len(l_date_duty_change) > 0:
        print('Duty not changed ', l_date_duty_change)
    if len(l_date_duty_add) > 0:
        print('Duty not added ', l_date_duty_add)
    if len(l_date_duty_delete) + len(l_date_duty_change) + len(l_date_duty_add) == 0:
        print('Confirmed update')


def add_duty(service, id_calendar, d_date_duty, d_member, d_time_duty, d_availability):

    d_date_duty = pd.merge(d_date_duty, d_member[['id_member','name_jpn_full','email']], on = 'id_member', how = 'left')
    d_date_duty = pd.merge(d_date_duty, d_time_duty, on = 'duty', how = 'left')

    l_result = []
    for _, row in d_date_duty.iterrows():
        date_duty = row['date_duty']
        title_duty = row['duty_jpn']
        year = int(row['year'])
        month = int(row['month'])
        date = int(row['date'])
        duty = row['duty']
        id_member = int(row['id_member'])
        name_member = row['name_jpn_full'].replace('　',' ')
        email = row['email']
        str_start = row['start']
        str_end = row['end']
        t_start = (dt.datetime(year = year, month = month, day = date) +\
                dt.timedelta(hours = int(str_start[0:2]), minutes = int(str_start[3:5]))).isoformat()
        t_end = (dt.datetime(year = year, month = month, day = date) +\
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
        result_event = service.events().insert(calendarId = id_calendar, body = body_event).execute()
        l_result.append(result_event)

    return l_result


def delete_duty(service_calendar, id_calendar, l_date_duty_delete, d_event_exist):
    l_id_event_delete = []
    for date_duty in l_date_duty_delete:
        id_event = d_event_exist.loc[d_event_exist['date_duty'] == date_duty, 'id_event'].tolist()[0]
        l_id_event_delete.append(id_event)

    l_result = []
    for id_event in l_id_event_delete:
        result_delete = service_calendar.events().delete(calendarId = id_calendar, eventId = id_event).execute()
        l_result.append(result_delete)

    return l_result


def list_duty(service_calendar, id_calendar, year, month, d_member, dict_time_duty):

    if month == 12:
        year_end = year + 1
        month_end = 1
    else:
        year_end = year
        month_end = month + 1
    
    # Extract from G calendar
    time_start = str(year) + '-' + str(month).zfill(2) + '-01T00:00:00Z'
    time_end = str(year_end) + '-' + str(month_end).zfill(2) + '-01T00:00:00Z'
    l_event = service_calendar.events().list(
        calendarId = id_calendar,
        timeMin = time_start,
        timeMax = time_end,
        maxResults = 1000,
        singleEvents = True,
        orderBy = 'startTime'
    ).execute()
    d_event = pd.DataFrame(l_event.get('items', []))

    # Convert result
    d_time_duty = pd.DataFrame(dict_time_duty)
    l_assign_calendar = []
    for id, row in d_event.iterrows():
        str_ymd = row['start']['dateTime']
        duty = d_time_duty.loc[d_time_duty['duty_jpn'] == row['summary'], 'duty'].tolist()[0]
        name_jpn_full = row['description'].split('先生')[0]
        #email = row['attendees'][0]['email']
        id_member = d_member.loc[d_member['name_jpn_full'] == name_jpn_full, 'id_member'].tolist()[0]
        name_jpn = d_member.loc[d_member['name_jpn_full'] == name_jpn_full, 'name_jpn'].tolist()[0]
        l_assign_calendar.append({'date_duty': str(int(str_ymd[8:10])) + '_' + duty,
                                'year': int(str_ymd[0:4]),
                                'month': int(str_ymd[5:7]),
                                'date': int(str_ymd[8:10]),
                                'duty': duty,
                                'id_member': id_member,
                                'name_jpn': name_jpn,
                                'id_event': row['id']})
    
    d_assign_calendar = pd.DataFrame(l_assign_calendar)

    return d_assign_calendar


'''
def add_calendar(lp_root, year_plan, month_plan, l_scope, t_sleep, dict_time_duty):
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
    #d_time_duty = pd.read_csv(os.path.join(p_root, 'Dropbox/dutyshift/config/time_duty.csv'))
    d_time_duty = pd.DataFrame(dict_time_duty)
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

    l_member = sorted(list(set(d_date_duty['id_member'])))

    for id_member in l_member:
        print('Member ID:', str(id_member))
        d_date_duty_member = d_date_duty[d_date_duty['id_member'] == id_member]

        for _, row in d_date_duty_member.iterrows():
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

        sleep(t_sleep)
'''