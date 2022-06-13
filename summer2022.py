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
# Create and share Google Calendar event
###############################################################################