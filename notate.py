
###############################################################################
# Libraries
###############################################################################
import pandas as pd, datetime as dt
import os
from time import sleep

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError


###############################################################################
# Parameters
###############################################################################
year_plan = 2022
month_plan = 6
#month = 5

t_sleep = 600

l_class_duty = ['ampm','daynight_tot','night_em','night_wd','daynight_hd','oc_tot','oc_day','oc_night','ect']
l_scope = ['https://www.googleapis.com/auth/calendar']


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
    d_data = dt.datetime.now().strftime('notate_%Y%m%d_%H%M%S')
    p_result = os.path.join(p_month, 'result')
    p_data = os.path.join(p_result, d_data)
    for p_dir in [p_result, p_data]:
        if not os.path.exists(p_dir):
            os.makedirs(p_dir)

from helper import *


###############################################################################
# Handle Credentials and token
###############################################################################
creds = None
# The file token.json stores the user's access and refresh tokens, and is
# created automatically when the authorization flow completes for the first
# time.
p_token = os.path.join(p_root, 'Dropbox/dutyshift/config/credentials/token.json')
p_cred = os.path.join(p_root, 'Dropbox/dutyshift/config/credentials/credentials.json')
if os.path.exists(p_token):
    creds = Credentials.from_authorized_user_file(p_token, l_scope)
    print('token.json found.')
# If there are no (valid) credentials available, let the user log in.
if not creds or not creds.valid:
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        print('token.json required refreshment.')
    else:
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

l_member = sorted(list(set(d_date_duty['id_member'])))

for id_member in l_member:
    d_date_duty_member = d_date_duty[d_date_duty['id_member'] == id_member]

    for _, row in d_date_duty_member.iterrows():
        date_duty = row['date_duty']
        title_duty = row['duty_jpn']
        date = int(row['date'])
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
        l_member_proxy = d_member.loc[d_member['id_member'].isin(l_id_member_proxy),'name_jpn_full'].tolist()
        l_member_proxy = [name.replace('　',' ') for name in l_member_proxy]
        #l_member_proxy = d_availability.loc[d_availability[date_duty] > 0,'name_jpn_full'].tolist()
        l_member_proxy = [m for m in l_member_proxy]
        if len(l_member_proxy) > 0:
            str_member_proxy = ', '.join(l_member_proxy)
        else:
            str_member_proxy = 'なし'
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


#print("created event")
#print("id: ", event_result['id'])
#print("summary: ", event_result['summary'])
#print("starts at: ", event_result['start']['dateTime'])
#print("ends at: ", event_result['end']['dateTime'])

#d = datetime.now().date()
#tomorrow = datetime(d.year, d.month, d.day, 10)+timedelta(days=1)
#start = tomorrow.isoformat()
#end = (tomorrow + timedelta(hours=1)).isoformat()

###############################################################################
# Print events (test)
###############################################################################
#try:
#    service = build('calendar', 'v3', credentials=creds)
#
#    # Call the Calendar API
#    now = datetime.datetime.utcnow().isoformat() + 'Z'  # 'Z' indicates UTC time
#    print('Getting the upcoming 10 events')
#    events_result = service.events().list(calendarId = id_calendar_duty, timeMin = now,
#                                          maxResults = 10, singleEvents = True,
#                                          orderBy = 'startTime').execute()
#    events = events_result.get('items', [])
#
#    if not events:
#        print('No upcoming events found.')
#    
#    else:
#        # Prints the start and name of the next 10 events
#        for event in events:
#            start = event['start'].get('dateTime', event['start'].get('date'))
#            print(start, event['summary'])
#
#except HttpError as error:
#    print('An error occurred: %s' % error)


###############################################################################
# Print Calendar IDs
###############################################################################
#service.calendarList().list().execute()