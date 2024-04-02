import pandas as pd, datetime as dt
import os
from time import sleep
from script.helper import *

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

lp_root = ['/home/atiroms/Documents','D:/atiro','D:/NICT_WS','/Users/smrt']
year_plan, month_plan = 2024, 4

l_scope = ['https://www.googleapis.com/auth/calendar']


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
# List events
###############################################################################
service = build('calendar', 'v3', credentials = creds)
l_event = service.events().list(
    calendarId = id_calendar_duty,
    timeMin = '2024-04-01T00:00:00Z',
    timeMax = '2024-04-30T23:59:00Z',
    maxResults = 1000,
    singleEvents = True,
    orderBy = 'startTime'
).execute()

d_event = pd.DataFrame(l_event.get('items', []))


###############################################################################
# Modify extracted event to be compared
###############################################################################
dict_time_duty = {'duty': ['am', 'pm', 'day', 'night', 'emnight', 'ocday', 'ocnight', 'ect'],
                  'duty_jpn': ['午前日直', '午後日直', '日直', '当直', '救急当直', '日直OC', '当直OC', 'ECT当番'],
                  'start': ['08:30', '12:30', '08:30', '17:15', '17:15', '08:30', '17:15', '07:30'],
                  'end': ['12:30', '17:15', '17:15', '32:30', '32:30', '17:15', '32:30', '11:00']}
d_time_duty = pd.DataFrame(dict_time_duty)

d_member = pd.read_csv(os.path.join(p_month, 'member.csv'), index_col = 0)

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

###############################################################################
# Compare up-to-date assignment and calendar extraction
###############################################################################

d_assign_date_duty = pd.read_csv(os.path.join(p_month, 'assign_date_duty.csv'))

l_date_duty_assigned = d_assign_date_duty.loc[~np.isnan(d_assign_date_duty['id_member']), 'date_duty'].tolist()

l_date_duty_delete = [dd for dd in d_assign_calendar['date_duty'].tolist() if dd not in l_date_duty_assigned]

l_date_duty_change = []
l_date_duty_add = []
for id, row in d_assign_date_duty.loc[~np.isnan(d_assign_date_duty['id_member']), :].iterrows():
    date_duty = row['date_duty']
    id_member = int(row['id_member'])
    id_member_calendar = d_assign_calendar.loc[d_assign_calendar['date_duty'] == date_duty, 'id_member'].tolist()
    if len(id_member_calendar) > 0:
        if id_member_calendar[0] != id_member:
            l_date_duty_change.append(date_duty)
    else:
        l_date_duty_add.append(date_duty)


###############################################################################
# Delete events
###############################################################################

l_id_event_delete = []
for date_duty in l_date_duty_delete:
    id_event = d_assign_calendar.loc[d_assign_calendar['date_duty'] == date_duty, 'id_event'].tolist()[0]
    l_id_event_delete.append(id_event)
for item in l_date_duty_change:
    id_event = d_assign_calendar.loc[d_assign_calendar['date_duty'] == item['date_duty'], 'id_event'].tolist()[0]
    l_id_event_delete.append(id_event)

l_result_delete = []
for id_event in l_id_event_delete:
    result_delete = service.events().delete(calendarId = id_calendar_duty, eventId = id_event).execute()
    l_result_delete.append(result_delete)


###############################################################################
# Add events
###############################################################################

d_availability = pd.read_csv(os.path.join(p_month, 'availability.csv'))
d_date_duty = pd.merge(d_assign_date_duty, d_member[['id_member','name_jpn_full','email']], on = 'id_member', how = 'left')
d_date_duty = pd.merge(d_date_duty, d_time_duty, on = 'duty', how = 'left')


d_date_duty = d_date_duty.loc[d_date_duty['date_duty'].isin(l_date_duty_add)]

for id, row in d_date_duty.iterrows():
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
