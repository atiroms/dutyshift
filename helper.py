import datetime, calendar
import pandas as pd
from math import ceil

def prep_calendar(l_holiday, l_day_ect, day_em, l_emweek,
                  year_plan = None, month_plan = None):
    dict_jpnday = {0: '月', 1: '火', 2: '水', 3: '木', 4: '金', 5: '土', 6: '日'}
    if month_plan is None:
        # Prepare next month
        year_plan = datetime.date.today().year
        month_plan = datetime.date.today().month + 1
        if month_plan > 12:
            month_plan = 1
            year_plan = year_plan + 1

    day_start, date_end = calendar.monthrange(year_plan, month_plan)
    d_cal = pd.DataFrame([[date] for date in range(1, date_end + 1)], columns=['date'])
    d_cal['wday'] = d_cal['date'].apply(lambda x: datetime.date(year_plan, month_plan, x).weekday())
    d_cal['wday_jpn'] = d_cal['wday'].apply(lambda x: dict_jpnday[x])
    d_cal['week'] = d_cal['date'].apply(lambda x: ceil(x/7))
    d_cal['holiday'] = d_cal['wday'].apply(lambda x: x in [5, 6])
    for date in l_holiday:
        d_cal.loc[d_cal['date'] == date, 'holiday'] = True
    d_cal[['em', 'am', 'pm', 'day', 'night', 'bday', 'bnight', 'ocday', 'ocnight', 'ect']] = False
    d_cal.loc[(d_cal['wday'] == day_em) & (d_cal['week'].isin(l_emweek)) & (d_cal['holiday'] == False), 'em'] = True
    d_cal.loc[d_cal['holiday'] == False, ['am', 'pm', 'night', 'bnight', 'ocnight']] = True
    d_cal.loc[d_cal['holiday'] == True, ['day', 'night', 'bday', 'bnight', 'ocday', 'ocnight']] = True
    d_cal.loc[(d_cal['wday'].isin(l_day_ect)) & (d_cal['holiday'] == False), 'ect'] = True

    return d_cal