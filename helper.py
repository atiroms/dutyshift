import datetime, calendar, os
import numpy as np
import pandas as pd
from math import ceil


################################################################################
# Prepare calendar for google forms
################################################################################
def prep_forms(p_dst, d_cal, month_plan, dict_duty):
    #l_duty = ['am', 'pm', 'day', 'ocday', 'night', 'ocnight']
    dict_duty_jpn = {'am': '午前日直', 'pm': '午後日直', 'day': '日直', 'ocday': '日直OC', 'night': '当直', 'ocnight': '当直OC'}
    d_cal['holiday_wday'] = ''
    d_cal.loc[(d_cal['holiday'] == True) & (d_cal['wday'].isin([0,1,2,3,4])), 'holiday_wday'] = '・祝'
    d_cal['title_date'] = [str(month_plan) + '/' + str(date) + '(' + wday_jpn + holiday_wday + ')' for [date, wday_jpn, holiday_wday] in zip(d_cal['date'], d_cal['wday_jpn'], d_cal['holiday_wday'])]

    l_cal_duty = []
    for duty in dict_duty_jpn.keys():
        d_cal_duty = d_cal.loc[d_cal[duty] == True, ['date', 'title_date', 'em', 'holiday']].copy()
        d_cal_duty['duty'] = duty
        l_cal_duty.append(d_cal_duty)
    d_cal_duty = pd.concat(l_cal_duty, axis = 0)
    d_cal_duty['duty_sort'] = d_cal_duty['duty'].map(dict_duty)
    d_cal_duty = d_cal_duty.sort_values(by = ['date', 'duty_sort'])
    d_cal_duty.index = range(len(d_cal_duty))

    d_cal_duty['title_em'] = ''
    d_cal_duty.loc[(d_cal_duty['em'] == True) & (d_cal_duty['duty'].isin(['night', 'ocnight'])), 'title_em'] = '救急'
    d_cal_duty['duty_jpn'] = d_cal_duty['duty'].map(dict_duty_jpn)
    d_cal_duty['title_dateduty'] = d_cal_duty['title_date'] + d_cal_duty['title_em'] + d_cal_duty['duty_jpn']

    d_cal_duty = d_cal_duty[['date','holiday','duty','em','title_dateduty']]

    # All duties
    d_cal_duty.to_csv(os.path.join(p_dst, 'cal_duty_all.csv'), index = False)
    # Associate professor
    d_cal_duty_assoc = d_cal_duty[d_cal_duty['duty'].isin(['ocday','ocnight'])]
    d_cal_duty_assoc.to_csv(os.path.join(p_dst, 'cal_duty_assoc.csv'), index = False, columns = ['title_dateduty'])  
    # Instructor
    d_cal_duty_instr = d_cal_duty[d_cal_duty['duty'].isin(['am','pm','ocday','ocnight'])]
    d_cal_duty_instr.to_csv(os.path.join(p_dst, 'cal_duty_instr.csv'), index = False, columns = ['title_dateduty'])  
    # Limited-term instructor and assistant professor
    d_cal_duty_assist = d_cal_duty[d_cal_duty['duty'].isin(['am','pm','day','night','ocday','ocnight'])]
    d_cal_duty_assist.to_csv(os.path.join(p_dst, 'cal_duty_assist.csv'), index = False, columns = ['title_dateduty'])  
    # Limited-term clinician
    d_cal_duty_limtermclin = d_cal_duty[d_cal_duty['duty'].isin(['am','pm','day','night']) & (d_cal_duty['em'] == False)]
    d_cal_duty_limtermclin.to_csv(os.path.join(p_dst, 'cal_duty_limtermclin.csv'), index = False, columns = ['title_dateduty'])  
    # Graduate student
    d_cal_duty_stud = d_cal_duty[d_cal_duty['duty'].isin(['day','night']) & (d_cal_duty['em'] == False)]
    d_cal_duty_stud.to_csv(os.path.join(p_dst, 'cal_duty_stud.csv'), index = False, columns = ['title_dateduty'])  
    
    return d_cal_duty

################################################################################
# Prepare data of member availability
################################################################################
def prep_availability(p_src, f_availability, d_date_duty, d_member, d_cal):
    d_availability = pd.read_csv(os.path.join(p_src, f_availability))
    d_availability = pd.merge(d_member[['id_member', 'name_jpn']], d_availability, on='name_jpn')
    d_availability.set_index('id_member', inplace=True)
    d_availability.drop(['name_jpn'], axis = 1, inplace = True)
    d_availability = d_availability.T
    l_date_ect = d_cal.loc[d_cal['ect'] == True, 'date'].tolist()
    d_availability_ect = d_availability.loc[[str(date_ect) + '_am' for date_ect in l_date_ect], :]
    d_availability_ect.index = ([str(date_ect) + '_ect' for date_ect in l_date_ect])
    d_availability = pd.concat([d_availability, d_availability_ect], axis = 0)
    d_availability = d_availability.loc[d_date_duty['date_duty'],:]
    l_member = d_availability.columns.to_list()
    
    return d_availability, l_member


################################################################################
# Prepare data of member specs and  assignment limits
################################################################################
def prep_member(p_member, f_member, l_class_duty):
    l_col_member = ['id_member','name_jpn','title_jpn','designation_jpn','ect_asgn_jpn','name','title_short','designation', 'team', 'ect_leader', 'ect_subleader']

    d_src = pd.read_csv(os.path.join(p_member, f_member))
    d_member = d_src[l_col_member]
    d_lim = d_src[l_class_duty]

    # Split assignment limit data into hard and soft
    d_lim_hard = pd.DataFrame([[[np.nan]*2]*d_lim.shape[1]]*d_lim.shape[0], index = d_lim.index, columns = d_lim.columns)
    d_lim_soft = pd.DataFrame([[[np.nan]*2]*d_lim.shape[1]]*d_lim.shape[0], index = d_lim.index, columns = d_lim.columns)
    for col in l_class_duty:
        for idx in d_lim.index:
            if '(' in d_lim.loc[idx, col]:
                # If parenthesis exists, its content is hard limit
                d_lim_hard.loc[idx, col][0] = str(d_lim.loc[idx, col]).split('(')[1].split(')')[0]
                d_lim_soft.loc[idx, col][0] = str(d_lim.loc[idx, col]).split('(')[0]
            else:
                # If parenthesis does not exist it's hard limit
                d_lim_hard.loc[idx, col][0] = d_lim.loc[idx, col]
                d_lim_soft.loc[idx, col][0] = '-'

            for d_temp in [d_lim_hard, d_lim_soft]:
                if d_temp.loc[idx, col][0] == '-':
                    # Convert '-' to [np.nan, np.nan]
                    d_temp.loc[idx, col] = [np.nan]*2
                elif '-' in str(d_temp.loc[idx, col][0]):
                    # Convert string 'a-b' to list [a, b]
                    d_temp.loc[idx, col] = [int(x) for x in str(d_temp.loc[idx, col][0]).split('--')]
                else:
                    # Convert string 'a' to list [a, a]
                    d_temp.loc[idx, col] = [int(d_temp.loc[idx, col][0])]*2
    
    return d_member, d_lim_hard, d_lim_soft


################################################################################
# Prepare calendar of the month
################################################################################
def prep_calendar(l_holiday, l_day_ect, day_em, l_week_em,
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
    d_cal.loc[(d_cal['wday'] == day_em) & (d_cal['week'].isin(l_week_em)) & (d_cal['holiday'] == False), 'em'] = True
    d_cal.loc[d_cal['holiday'] == False, ['am', 'pm', 'night', 'bnight', 'ocnight']] = True
    d_cal.loc[d_cal['em'] == True, 'ocnight'] = False
    d_cal.loc[d_cal['holiday'] == True, ['day', 'night', 'bday', 'bnight', 'ocday', 'ocnight']] = True
    d_cal.loc[(d_cal['wday'].isin(l_day_ect)) & (d_cal['holiday'] == False), 'ect'] = True
    d_cal.loc[d_cal['em'] == True, 'ocnight'] = False

    # Prepare d_date_duty
    l_date_duty, l_date, l_duty = [], [], []
    for duty in ['am', 'pm', 'day', 'night', 'ocday', 'ocnight', 'ect']:
        l_date_append = d_cal.loc[d_cal[duty] == True, 'date'].tolist()
        l_date += l_date_append
        l_duty_append = [duty]*len(l_date_append)
        l_duty += l_duty_append
        l_date_duty_append = [str(date) + '_' + duty for date in l_date_append]
        l_date_duty += l_date_duty_append
    d_date_duty = pd.DataFrame({'date_duty': l_date_duty, 'date': l_date, 'duty': l_duty})

    # d_duty_date_class
    # Specify which class_duty's apply to each date_duty
    l_date_all = d_cal['date'].tolist()
    l_date_em = d_cal.loc[d_cal['em'] == True, 'date'].tolist()
    l_date_wd = d_cal.loc[d_cal['holiday'] == False, 'date'].tolist()
    l_date_hd = d_cal.loc[d_cal['holiday'] == True, 'date'].tolist()
    l_date_ect = d_cal.loc[d_cal['ect'] == True, 'date'].tolist()

    l_class_duty = {
        'day_wd': [[l_date_wd, 'am'], [l_date_wd, 'pm']],'day_hd': [[l_date_hd, 'day']],
        'night_tot': [[l_date_all, 'night']], 'night_em': [[l_date_em, 'night']],
        'night_wd': [[l_date_wd, 'night']], 'night_hd': [[l_date_hd, 'night']],
        'oc_tot': [[l_date_hd, 'ocday'], [l_date_all, 'ocnight']],'oc_hd_day': [[l_date_hd, 'ocday']],
        'oc_other': [[l_date_all, 'ocnight']],'ect': [[l_date_ect, 'ect']]}
    
    d_duty_date_class = pd.DataFrame([[False]*len(l_class_duty)]*len(d_date_duty), index = d_date_duty['date_duty'], columns = l_class_duty)
    for class_duty in l_class_duty:
        ll_date_duty= l_class_duty[class_duty]
        for l_date_duty in ll_date_duty:
            l_date = l_date_duty[0]
            duty =  l_date_duty[1]
            idx_temp = d_date_duty.loc[(d_date_duty['date'].isin(l_date)) & (d_date_duty['duty'] == duty), 'date_duty'].tolist()
            d_duty_date_class.loc[idx_temp, class_duty] = True

    l_date = d_date_duty['date'].tolist()

    return d_cal, l_date, d_date_duty, d_duty_date_class, year_plan, month_plan
