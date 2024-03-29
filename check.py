
import pandas as pd
import os
from helper import *

def check_availability_all(lp_root, year_plan, month_plan):
    p_root, p_month, p_data = prep_dirs(lp_root, year_plan, month_plan, prefix_dir = '', make_data_dir = False)

    d_member = pd.read_csv(os.path.join(p_month, 'member.csv'), index_col = 0)
    d_availability = pd.read_csv(os.path.join(p_month, 'availability.csv'))
    d_availability.index = d_availability['date_duty']
    d_availability = d_availability.iloc[:,1:]
    d_availability = d_availability.T

    d_availability_member = pd.DataFrame(index = d_availability.columns.tolist())

    for date_duty in d_availability.columns:
        l_member_available = d_availability.loc[d_availability[date_duty] > 0, :].index.tolist()
        str_member_available = ', '.join(l_member_available)
        l_member_available_jpn = [d_member.loc[d_member['id_member'] == int(member), 'name_jpn'].tolist()[0] for member in l_member_available]
        str_member_available_jpn = ', '.join(l_member_available_jpn)
        l_member_available_mail = [d_member.loc[d_member['id_member'] == int(member), 'email'].tolist()[0] for member in l_member_available]
        str_member_available_mail = ', '.join(l_member_available_mail)
        d_availability_member.loc[date_duty, 'l_member'] = str_member_available
        d_availability_member.loc[date_duty, 'l_member_jpn'] = str_member_available_jpn
        d_availability_member.loc[date_duty, 'l_member_mail'] = str_member_available_mail

    return(d_availability_member)

def check_availability_date_duty(lp_root, year_plan, month_plan, date_duty):
    p_root, p_month, p_data = prep_dirs(lp_root, year_plan, month_plan, prefix_dir = '', make_data_dir = False)

    d_member = pd.read_csv(os.path.join(p_month, 'member.csv'), index_col = 0)
    d_availability = pd.read_csv(os.path.join(p_month, 'availability.csv'))
    d_availability.index = d_availability['date_duty']
    d_availability = d_availability.iloc[:,1:]

    d_availability_t = d_availability.T
    l_id_member_available = d_availability_t.index[d_availability_t[date_duty] > 0].tolist()
    l_id_member_available = [int(id_member) for id_member in l_id_member_available]

    l_name_member_available = d_member.loc[d_member['id_member'].isin(l_id_member_available), 'name_jpn_full'].tolist()
    l_name_member_available = [name.replace('　',' ') for name in l_name_member_available]
    d_check_availability = pd.DataFrame({'id_member': l_id_member_available, 'name_member': l_name_member_available})
    print(d_check_availability)

def check_availability_member(lp_root, year_plan, month_plan, id_member):
    p_root, p_month, p_data = prep_dirs(lp_root, year_plan, month_plan, prefix_dir = '', make_data_dir = False)

    d_availability = pd.read_csv(os.path.join(p_month, 'availability.csv'))
    d_availability.index = d_availability['date_duty']
    d_availability = d_availability.iloc[:,1:]

    l_date_duty_available = d_availability.loc[d_availability[str(id_member)] > 0,:].index.tolist()

    print(l_date_duty_available)
