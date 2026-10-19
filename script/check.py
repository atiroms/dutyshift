
import pandas as pd
#import os

def check_availability_duty(d_member, d_availability):
    d_availability = d_availability.T
    dict_name_jpn = d_member.set_index('id_member')['name_jpn'].to_dict()
    dict_email = d_member.set_index('id_member')['email'].to_dict()

    d_availability_duty = pd.DataFrame(index=d_availability.columns.tolist())
    for date_duty in d_availability.columns:
        l_member = d_availability.index[d_availability[date_duty] > 0].tolist()
        d_availability_duty.loc[date_duty, 'str_member'] = ', '.join(str(m) for m in l_member)
        d_availability_duty.loc[date_duty, 'str_member_jpn'] = ', '.join(dict_name_jpn[int(m)] for m in l_member)
        d_availability_duty.loc[date_duty, 'str_member_mail'] = ', '.join(dict_email[int(m)] for m in l_member)

    return d_availability_duty

def check_availability_member(d_member, d_availability):
    l_row = [[id_member, name_jpn_full, ', '.join(d_availability.index[d_availability[id_member] > 0])]
             for id_member, name_jpn_full in zip(d_member['id_member'].tolist(), d_member['name_jpn'].tolist())
             if id_member in d_availability.columns.tolist()]

    return pd.DataFrame(l_row, columns=['id_member', 'name_jpn', 'str_date_duty'])
