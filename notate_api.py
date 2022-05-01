
###############################################################################
# Libraries
###############################################################################
import numpy as np, pandas as pd
#from datetime import datetime as datetime
#from datetime import timedelta
import os, datetime

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError


###############################################################################
# Parameters
###############################################################################
year = 2022
month = 5

#f_member = 'member.csv'
f_member = 'member4.csv'
l_class_duty = ['ampm','daynight_tot','night_em','night_wd','day_hd','night_hd','oc_tot','oc_hd_day','oc_other','ect']

# If modifying these scopes, delete the file token.json.
l_scope = ['https://www.googleapis.com/auth/calendar']

d_type_duty = pd.DataFrame([['am', '午前日直', '08:30', '12:30'],
                            ['pm', '午後日直', '12:30', '17:15'],
                            ['day', '日直', '08:30', '17:15'],
                            ['night', '当直', '17:15', '32:30'],
                            ['ocday', '日直OC', '08:30', '17:15'],
                            ['ocnight', '当直OC', '17:15', '32:30'],
                            ['ect', 'ECT当番', '07:30', '11:00']],
                           columns = ['duty','duty_jpn','start','end'])


###############################################################################
# Script path
###############################################################################
p_root = None
for p_test in ['/home/atiroms/Documents','D:/atiro','D:/NICT_WS','/Users/smrt']:
    if os.path.isdir(p_test):
        p_root = p_test
        #p_src = os.path.join(p_test, 'Dropbox/dutyshift', d_src)
        #p_dst = os.path.join(p_test, 'Dropbox/dutyshift', d_dst)
if p_root is None:
    print('No root directory.')
else:
    p_script=os.path.join(p_root,'GitHub/dutyshift')
    os.chdir(p_script)

from helper import *

# Set paths and directories
d_src = '{year:0>4d}{month:0>2d}'.format(year = year, month = month)
p_src = os.path.join(p_root, 'Dropbox/dutyshift', d_src)

d_member, d_lim_hard, d_lim_soft = prep_member(p_src, f_member, l_class_duty)

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
        flow = InstalledAppFlow.from_client_secrets_file(
               p_cred, l_scope)
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
# Handle Credentials and token
###############################################################################
d_src = '{year:0>4d}{month:0>2d}'.format(year = year, month = month)
d_date_duty = pd.read_csv(os.path.join(p_root, 'Dropbox/dutyshift', d_src, 'assign_date_duty_edited.csv'))
d_date_duty = d_date_duty.loc[d_date_duty['cnt'] > 0, :]
####
#d_date_duty = d_date_duty.loc[d_date_duty['id_member'] == 11,:]
####
d_date_duty = pd.merge(d_date_duty, d_member[['id_member','name_jpn_full','email']], on = 'id_member', how = 'left')
d_date_duty = pd.merge(d_date_duty, d_type_duty, on = 'duty', how = 'left')

service = build('calendar', 'v3', credentials=creds)

l_result_event = []

for id, row in d_date_duty.iterrows():
    title_duty = row['duty_jpn']
    date = int(row['date'])
    type_duty = row['duty']
    #id_member = int(row['id_member'])
    name_member = row['name_jpn_full'] + '先生'
    email = row['email']
    str_start = row['start']
    str_end = row['end']
    t_start = (datetime.datetime(year = year, month = month, day = date) +\
               datetime.timedelta(hours = int(str_start[0:2]), minutes = int(str_start[3:5]))).isoformat()
    t_end = (datetime.datetime(year = year, month = month, day = date) +\
             datetime.timedelta(hours = int(str_end[0:2]), minutes = int(str_end[3:5]))).isoformat()

    body_event = {'summary': title_duty,
                'location': '東大病院',
                'start': {'dateTime': t_start, 'timeZone': 'Asia/Tokyo'},
                'end': {'dateTime': t_end, 'timeZone': 'Asia/Tokyo'},
                'attendees': [{'email': email}],
                #'attendees': [{'email': email, 'displayName':name_member}],
                #'attendees': [{'email': email, 'responseStatus':'accepted'}],
                'description': 'https://github.com/atiroms/dutyshift で自動生成'
                }
    result_event = service.events().insert(calendarId=id_calendar_duty,body=body_event).execute()
    l_result_event.append(result_event)


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
try:
    service = build('calendar', 'v3', credentials=creds)

    # Call the Calendar API
    now = datetime.datetime.utcnow().isoformat() + 'Z'  # 'Z' indicates UTC time
    print('Getting the upcoming 10 events')
    events_result = service.events().list(calendarId = id_calendar_duty, timeMin = now,
                                          maxResults = 10, singleEvents = True,
                                          orderBy = 'startTime').execute()
    events = events_result.get('items', [])

    if not events:
        print('No upcoming events found.')
    
    else:
        # Prints the start and name of the next 10 events
        for event in events:
            start = event['start'].get('dateTime', event['start'].get('date'))
            print(start, event['summary'])

except HttpError as error:
    print('An error occurred: %s' % error)


###############################################################################
# Print Calendar IDs
###############################################################################
#service.calendarList().list().execute()