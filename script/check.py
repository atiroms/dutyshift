
import pandas as pd
#import os
from script.helper import *

def check_availability_duty(d_member, d_availability):
    d_availability = d_availability.T

    d_availability_duty = pd.DataFrame(index = d_availability.columns.tolist())

    for date_duty in d_availability.columns:
        l_member_available = d_availability.loc[d_availability[date_duty] > 0, :].index.tolist()
        l_member_available = [str(idx) for idx in l_member_available]
        if len(l_member_available) > 0:
            str_member_available = ', '.join(l_member_available)
        else:
            str_member_available = ''
        l_member_available_jpn = [d_member.loc[d_member['id_member'] == int(member), 'name_jpn'].tolist()[0] for member in l_member_available]
        if len(l_member_available_jpn) > 0:
            str_member_available_jpn = ', '.join(l_member_available_jpn)
        else:
            str_member_available_jpn = ''
        l_member_available_mail = [d_member.loc[d_member['id_member'] == int(member), 'email'].tolist()[0] for member in l_member_available]
        if len(l_member_available_mail) > 0:
            str_member_available_mail = ', '.join(l_member_available_mail)
        else:
            str_member_available_mail = ''
        d_availability_duty.loc[date_duty, 'l_member'] = str_member_available
        d_availability_duty.loc[date_duty, 'l_member_jpn'] = str_member_available_jpn
        d_availability_duty.loc[date_duty, 'l_member_mail'] = str_member_available_mail

    return d_availability_duty

def check_availability_member(d_member, d_availability):

    l_availability_member = []

    for id_member, name_jpn_full in zip(d_member['id_member'].tolist(), d_member['name_jpn'].tolist()):
        if id_member in d_availability.columns.tolist():
            l_date_duty_available = d_availability.loc[d_availability[id_member] > 0,:].index.tolist()
            str_date_duty_available = ', '.join(l_date_duty_available)

            l_availability_member.append([id_member, name_jpn_full, str_date_duty_available])

    d_availability_member = pd.DataFrame(l_availability_member, columns = ['id_member', 'name_jpn', 'l_date_duty'])

    return d_availability_member
