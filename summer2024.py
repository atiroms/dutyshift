###############################################################################
# Parameers
###############################################################################
business_year = 2024
season = 'summer'
fname_availability = '2024年度夏季休暇希望調査 (Responses) - Form Responses 1.csv'
l_scope = ['https://www.googleapis.com/auth/calendar']

###############################################################################
# Libraries
###############################################################################
import pandas as pd, numpy as np, datetime as dt
import os, datetime
from pulp import *
from ortoolpy import addbinvars
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError


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
    d_month = '{year:0>4d}'.format(year = business_year) + season
    p_month = os.path.join(p_root, 'Dropbox/dutyshift', d_month)
    d_data = datetime.datetime.now().strftime('asgn_%Y%m%d_%H%M%S')
    p_result = os.path.join(p_month, 'result')
    p_data = os.path.join(p_result, d_data)
    for p_dir in [p_result, p_data]:
        if not os.path.exists(p_dir):
            os.makedirs(p_dir)

#from helper import *


###############################################################################
# Load and modify data
###############################################################################
d_availability = pd.read_csv(os.path.join(p_month, fname_availability))
d_availability = d_availability.iloc[:,2:]

l_week = d_availability.columns[1:]
l_week = [col.split('[')[1].split(' - ')[0] for col in l_week]
d_availability.columns = ['name_jpn_full'] + l_week

d_member = pd.read_csv(os.path.join(p_month, 'member.csv'))
d_team = d_member.drop(['name_jpn', 'name_jpn_full'], axis = 1)
d_team = d_team.replace('-', '')
l_team = [team for team in sorted(list(set(d_team.iloc[:,1:].values.flatten().tolist()))) if team != '']
d_member = d_member[['id_member','name_jpn_full','email']]
d_member['name_jpn_full'] = [name.replace('　',' ') for name in d_member['name_jpn_full']]

d_availability = pd.merge(d_availability, d_member, on = 'name_jpn_full')
d_availability = d_availability[['id_member'] + l_week]
d_availability = d_availability.sort_values(by = ['id_member'])
d_availability.index = d_availability['id_member'].tolist()
l_member = d_availability['id_member'].tolist()

d_absence = d_availability.iloc[:,1:] == '学会・出張'
d_absence['id_member'] = l_member
d_absence = d_absence[['id_member'] + l_week]

d_availability = d_availability.replace('第１希望', 1)
d_availability = d_availability.replace('第２希望', 2)
d_availability = d_availability.replace('第３希望', 3)
d_availability = d_availability.replace('第４希望', 4)
d_availability = d_availability.replace('学会・出張', np.nan)


###############################################################################
# Initialize assignment problem and model
###############################################################################
# Initialize model to be optimized
prob_assign = LpProblem()

# Binary assignment variables to be optimized
dv_assign = pd.DataFrame(np.array(addbinvars(len(l_member), len(l_week))),
                         index = l_member, columns = l_week)


###############################################################################
# One assignment per member
###############################################################################
for member in l_member:
    prob_assign += (lpSum(dv_assign.loc[member,:]) == 1)

###############################################################################
# Do not assign to unavailable week
###############################################################################
prob_assign += (lpDot(np.isnan(d_availability.iloc[:,1:]).to_numpy(), dv_assign.to_numpy()) <= 0)


###############################################################################
# Maximum of 3 members per week
###############################################################################
for week in l_week:
    prob_assign += (lpSum(dv_assign[week]) + d_absence[week]) <= 4


###############################################################################
# Avoid members from the same team
###############################################################################
for week in l_week:
    for team in l_team:
        lv_assign = dv_assign[week].tolist()
        l_absence = d_absence[week].tolist()
        l_team_week = d_team.loc[d_team['id_member'].isin(l_member), week].tolist()
        l_team_week = [t == team for t in l_team_week]
        prob_assign += (lpDot(lv_assign, l_team_week) + np.dot(l_absence, l_team_week) <= 1)


###############################################################################
# Define objective function to be minimized
###############################################################################
d_optimality = d_availability.replace(np.nan, 0)
# Convert [1,2,3,4] to [1,2,4,7]
d_optimality.iloc[:,1:] = d_optimality.iloc[:,1:].replace(4,7).replace(3,4)
l_rank = [[x / d_optimality.shape[0]] * (d_optimality.shape[1] - 1) for x in range(d_optimality.shape[0])]
d_rank = pd.DataFrame(l_rank, index = d_optimality.index, columns = d_optimality.columns[1:])
d_optimality.iloc[:,1:] = d_optimality.iloc[:,1:] - d_rank
prob_assign += (lpDot(dv_assign.to_numpy(), d_optimality.iloc[:,1:].to_numpy()))


###############################################################################
# Solve problem
###############################################################################
# Print problem
#print('Problem: ', problem)

# Solve problem
prob_assign.solve()
v_objective = value(prob_assign.objective)
print('Solved: ' + str(LpStatus[prob_assign.status]) + ', ' + str(round(v_objective, 2)))


###############################################################################
# Extract result
###############################################################################
d_assign = pd.DataFrame(np.vectorize(value)(dv_assign),
                        columns = dv_assign.columns, index = dv_assign.index).astype(bool)
l_assign = d_assign.apply(lambda row: row[row == True].index.tolist()[0], axis=1)
d_assign_member = pd.DataFrame({'id_member': l_member, 'md_start': l_assign})
d_assign_member = pd.merge(d_assign_member, d_member, on = 'id_member')
d_assign_member['m_start'] = d_assign_member['md_start'].apply(lambda x: int(x.split('/')[0]))
d_assign_member['d_start'] = d_assign_member['md_start'].apply(lambda x: int(x.split('/')[1]))
d_assign_member['y_start'] = business_year
d_assign_member.loc[d_assign_member['m_start'] < 4, 'y_start'] = business_year + 1
d_assign_member['unix_start'] = [dt.datetime(year = year, month = month, day = date).timestamp() for year, month, date in zip(d_assign_member['y_start'].tolist(),d_assign_member['m_start'].tolist(), d_assign_member['d_start'].tolist()) ]
d_assign_member['unix_end'] = d_assign_member['unix_start'] + dt.timedelta(days = 5).total_seconds() - 60
d_assign_member['m_end'] = d_assign_member['unix_end'].apply(lambda x: dt.datetime.fromtimestamp(x).month)
d_assign_member['d_end'] = d_assign_member['unix_end'].apply(lambda x: dt.datetime.fromtimestamp(x).day)
d_assign_member['md_end'] = [str(month) + '/' + str(date) for month, date in zip(d_assign_member['m_end'].tolist(), d_assign_member['d_end'].tolist()) ]
d_assign_member['duration'] = [start + ' - ' + end for start, end in zip(d_assign_member['md_start'].tolist(), d_assign_member['md_end'].tolist())]
d_assign_member['optimality'] = [int(x) for x in (d_availability.iloc[:,1:] * d_assign).sum(axis = 1).tolist()]

d_assign_week = pd.DataFrame({'week': l_week, 'id_member': d_assign.apply(lambda row: row[row].index.to_list(), axis = 0)})
d_assign_week.index = range(len(d_assign_week))
for id, row in d_assign_week.iterrows():
    l_id_member = row['id_member']
    week = row['week']
    s_id_member_absence = d_absence[week]
    l_id_member_absence = s_id_member_absence[s_id_member_absence].index
    if len(l_id_member) == 0:
        str_member = 'なし'
    else:
        l_str_member = d_member.loc[d_member['id_member'].isin(l_id_member), 'name_jpn_full'].tolist()
        str_member = ', '.join(l_str_member)
    d_assign_week.loc[id, 'member'] = str_member
    if len(l_id_member_absence) == 0:
        str_member_absence = 'なし'
    else:
        l_str_member_absence = d_member.loc[d_member['id_member'].isin(l_id_member_absence), 'name_jpn_full'].tolist()
        str_member_absence = ', '.join(l_str_member_absence)
    d_assign_week.loc[id, 'member_absence'] = str_member_absence

for p_save in [p_month, p_data]:
    d_assign.to_csv(os.path.join(p_save, 'assign.csv'), index = False)
    d_assign_member.to_csv(os.path.join(p_save, 'assign_member.csv'), index = False)
    d_assign_week.to_csv(os.path.join(p_save, 'assign_week.csv'), index = False)


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
####
# Used for testing
#d_assign_member = d_assign_member.loc[d_assign_member['id_member'] == 7]
####
service = build('calendar', 'v3', credentials = creds)
l_result_event = []

####
#d_assign_member = pd.read_csv(os.path.join(p_root, 'Dropbox/dutyshift/2023summer/assign_member.csv'))
####

for _, row in d_assign_member.iterrows():
    name_member = row['name_jpn_full'].replace('　',' ')
    email = row['email']
    t_start = dt.datetime(year = row['y_start'], month = row['m_start'], day = row['d_start'], hour = 0, minute = 0).isoformat()
    t_end = dt.datetime(year = row['y_start'], month = row['m_end'], day = row['d_end'], hour = 23, minute = 59).isoformat()
    description = name_member + '先生東大病院夏季休暇' +\
                '\nhttps://github.com/atiroms/dutyshift で自動生成'
    body_event = {'summary': '東大病院夏季休暇',
                  'start': {'dateTime': t_start, 'timeZone': 'Asia/Tokyo'},
                  'end': {'dateTime': t_end, 'timeZone': 'Asia/Tokyo'},
                  'attendees': [{'email': email}],
                  #'attendees': [{'email': email, 'displayName':name_member}],
                  #'attendees': [{'email': email, 'responseStatus':'accepted'}],
                  'description': description
                  }
    result_event = service.events().insert(calendarId=id_calendar_duty,body=body_event).execute()
    l_result_event.append(result_event)
