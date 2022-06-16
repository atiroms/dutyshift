###############################################################################
# Parameers
###############################################################################
year = 2022


###############################################################################
# Libraries
###############################################################################
import pandas as pd, numpy as np, datetime as dt
import os
from pulp import *
from ortoolpy import addbinvars


###############################################################################
# Load and modify data
###############################################################################
d_availability = pd.read_csv(os.path.join('/Users/smrt/Dropbox/dutyshift/2022summer', '2022年度夏季休暇希望調査（回答） - フォームの回答 1.csv'))
d_availability = d_availability.iloc[:,2:]

l_week = d_availability.columns[1:]
l_week = [col.split('[')[1].split(' - ')[0] for col in l_week]
d_availability.columns = ['name_jpn_full'] + l_week

d_member = pd.read_csv(os.path.join('/Users/smrt/Dropbox/dutyshift/2022summer', 'member.csv'))
d_team = d_member.drop(['name_jpn', 'name_jpn_full'], axis = 1)
d_team = d_team.replace('-', '')
l_team = [team for team in sorted(list(set(d_team.iloc[:,1:].values.flatten().tolist()))) if team != '']
d_member = d_member[['id_member','name_jpn_full']]
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
    prob_assign += (lpSum(dv_assign[week]) + d_absence[week]) <= 3


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
d_assign_member['unix_start'] = [dt.datetime(year = year, month = month, day = date).timestamp() for month, date in zip(d_assign_member['m_start'].tolist(), d_assign_member['d_start'].tolist()) ]
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
    if len(l_id_member) == 0:
        str_member = 'なし'
    else:
        str_member = d_member.loc[d_member['id_member'].isin(l_id_member), 'name_jpn_full'].tolist()
        str_member = ', '.join(str_member)
    d_assign_week.loc[id, 'member'] = str_member


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
        # TODO: consider designation status for day and night
        s_id_member_proxy = d_availability.loc[d_availability['date_duty'] == date_duty,:].reset_index(drop=True).squeeze().iloc[1:]
        l_id_member_proxy = [int(id) for id in s_id_member_proxy.loc[s_id_member_proxy > 0].index.tolist()]
        l_member_proxy = d_member.loc[d_member['id_member'].isin(l_id_member_proxy),'name_jpn_full'].tolist()
        l_member_proxy = [name.replace('　',' ') for name in l_member_proxy]
        #l_member_proxy = d_availability.loc[d_availability[date_duty] > 0,'name_jpn_full'].tolist()
        l_member_proxy = [m for m in l_member_proxy if m != name_member]
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
