import datetime, calendar
import pandas as pd
from math import ceil

# Unfixed parameters
l_holiday = [29]

# Fixed parameters
dict_jpnday = {0: '月', 1: '火', 2: '水', 3: '木', 4: '金', 5: '土', 6: '日'}
l_day_ect = [0, 2, 3]
emday = 2
l_emweek = [1, 3]

#l_date_em = [6, 20]
#l_date_ect = [4, 6, 7, 11, 13, 14, 18, 20, 21, 25, 27, 28]

# Calculate day of a week from a date
#year_plan = datetime.date.today().year
#month_plan = datetime.date.today().month + 1
#if month_plan > 12:
#    month_plan = 1
#    year_plan = year_plan + 1
#print('Planning for Year:', year_plan, 'Month:', month_plan)

# Temporaly values
year_plan = 2022
month_plan = 4

####
day_start, date_end = calendar.monthrange(year_plan, month_plan)
d_cal = pd.DataFrame([[date] for date in range(1, date_end + 1)], columns=['date'])
d_cal['wday'] = d_cal['date'].apply(lambda x: datetime.date(year_plan, month_plan, x).weekday())
d_cal['wday_jpn'] = d_cal['wday'].apply(lambda x: dict_jpnday[x])
d_cal['week'] = d_cal['date'].apply(lambda x: ceil(x/7))
d_cal['holiday'] = d_cal['wday'].apply(lambda x: x in [5, 6])
for date in l_holiday:
    d_cal.loc[d_cal['date'] == date, 'holiday'] = True
d_cal[['em', 'am', 'pm', 'day', 'night', 'bday', 'bnight', 'ocday', 'ocnight', 'ect']] = False
d_cal.loc[(d_cal['wday'] == emday) & (d_cal['week'].isin(l_emweek)) & (d_cal['holiday'] == False), 'em'] = True
d_cal.loc[d_cal['holiday'] == False, ['am', 'pm', 'night', 'bnight', 'ocnight']] = True
d_cal.loc[d_cal['holiday'] == True, ['day', 'night', 'bday', 'bnight', 'ocday', 'ocnight']] = True
d_cal.loc[(d_cal['wday'].isin(l_day_ect)) & (d_cal['holiday'] == False), 'ect'] = True

####