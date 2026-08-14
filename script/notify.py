
import pandas as pd, datetime as dt
from time import sleep
from script.helper import *
from script.drive_io import get_services, prep_drive_paths, read_csv, SCOPE_DRIVE_CALENDAR


def compare_event(d_assign_date_duty, d_event_exist):
    l_date_duty_assigned = d_assign_date_duty.loc[~np.isnan(d_assign_date_duty['id_member']), 'date_duty'].tolist()
    l_date_duty_delete = [dd for dd in d_event_exist['date_duty'].tolist() if dd not in l_date_duty_assigned]
    l_date_duty_change = []
    l_date_duty_add = []
    for id, row in d_assign_date_duty.loc[~np.isnan(d_assign_date_duty['id_member']), :].iterrows():
        date_duty = row['date_duty']
        id_member = int(row['id_member'])
        id_member_calendar = d_event_exist.loc[d_event_exist['date_duty'] == date_duty, 'id_member'].tolist()
        if len(id_member_calendar) > 0:
            if id_member_calendar[0] != id_member:
                l_date_duty_change.append(date_duty)
        else:
            l_date_duty_add.append(date_duty)

    return l_date_duty_delete, l_date_duty_change, l_date_duty_add


def update_calendar(config, year_plan, month_plan, id_calendar, dict_time_duty, t_sleep = 0.0):
    services = get_services(config, SCOPE_DRIVE_CALENDAR)
    dp = prep_drive_paths(config, services.drive, year_plan, month_plan, prefix_dir = '', make_data_dir = False)
    d_member = read_csv(services.drive, dp.id_month, 'member.csv')

    # Access calendar
    service_calendar = services.calendar

    # Read events on G calendar
    d_assign_calendar = list_duty(service_calendar, id_calendar, year_plan, month_plan, d_member, dict_time_duty)

    # Read target assignment
    d_assign_date_duty = read_csv(services.drive, dp.id_month, 'assign_date_duty.csv')

    # Compare existing and target events
    l_date_duty_delete, l_date_duty_change, l_date_duty_add = compare_event(d_assign_date_duty, d_assign_calendar)

    # Delete events
    l_result_delete = delete_duty(service_calendar, id_calendar, l_date_duty_delete + l_date_duty_change, d_assign_calendar)

    # Add events
    d_date_duty_add = d_assign_date_duty.loc[d_assign_date_duty['date_duty'].isin(l_date_duty_add + l_date_duty_change), :]
    d_member = read_csv(services.drive, dp.id_month, 'member.csv')
    d_availability = read_csv(services.drive, dp.id_month, 'availability.csv', index_col = 0)
    d_time_duty = pd.DataFrame(dict_time_duty)

    if len(d_date_duty_add) > 10: # member-wise addition
        l_result_add = []
        l_member = sorted(list(set(d_date_duty_add['id_member'])))
        for id_member in l_member:
            print('Adding member:', str(id_member))
            d_date_duty_member = d_date_duty_add[d_date_duty_add['id_member'] == id_member]
            l_result_add_add = add_duty(service_calendar, id_calendar, d_date_duty_member, d_member, d_time_duty, d_availability)
            l_result_add += l_result_add_add
            sleep(t_sleep)
    else: # at-once addition
        l_result_add = add_duty(service_calendar, id_calendar, d_date_duty_add, d_member, d_time_duty, d_availability)

    # Assert result
    d_assign_calendar = list_duty(service_calendar, id_calendar, year_plan, month_plan, d_member, dict_time_duty)
    l_date_duty_delete, l_date_duty_change, l_date_duty_add = compare_event(d_assign_date_duty, d_assign_calendar)
    if len(l_date_duty_delete) > 0:
        print('Duty not deleted ', l_date_duty_delete)
    if len(l_date_duty_change) > 0:
        print('Duty not changed ', l_date_duty_change)
    if len(l_date_duty_add) > 0:
        print('Duty not added ', l_date_duty_add)
    if len(l_date_duty_delete) + len(l_date_duty_change) + len(l_date_duty_add) == 0:
        print('Confirmed update')


def add_duty(service, id_calendar, d_date_duty, d_member, d_time_duty, d_availability):

    #d_member['id_member'] = d_member.index
    #d_member = d_member.reset_index()
    d_date_duty = pd.merge(d_date_duty, d_member[['id_member','name_jpn_full','email']], on = 'id_member', how = 'left')
    d_date_duty = pd.merge(d_date_duty, d_time_duty, on = 'duty', how = 'left')

    l_result = []
    for _, row in d_date_duty.iterrows():
        date_duty = row['date_duty']
        title_duty = row['duty_jpn']
        year = int(row['year'])
        month = int(row['month'])
        date = int(row['date'])
        duty = row['duty']
        id_member = int(row['id_member'])
        name_member = row['name_jpn_full'].replace('　',' ')
        email = row['email']
        str_start = row['start']
        str_end = row['end']
        t_start = (dt.datetime(year = year, month = month, day = date) +\
                dt.timedelta(hours = int(str_start[0:2]), minutes = int(str_start[3:5]))).isoformat()
        t_end = (dt.datetime(year = year, month = month, day = date) +\
                dt.timedelta(hours = int(str_end[0:2]), minutes = int(str_end[3:5]))).isoformat()
        s_id_member_proxy = d_availability.loc[d_availability.index == date_duty,:].reset_index(drop = True).squeeze().iloc[1:]

        l_id_member_proxy = [int(id) for id in s_id_member_proxy.loc[s_id_member_proxy > 0].index.tolist()]
        d_member_proxy = d_member.loc[d_member['id_member'].isin(l_id_member_proxy),['id_member', 'name_jpn_full', 'designation']]
        # Consider designation status for day and night
        if duty in ['day','night']:
            designation_member = d_member.loc[d_member['id_member'] == id_member, 'designation'].tolist()[0]
            l_id_member_proxy = d_member_proxy.loc[d_member_proxy['designation'] == designation_member, 'id_member'].tolist()
            l_id_member_proxy_sub = d_member_proxy.loc[d_member_proxy['designation'] != designation_member, 'id_member'].tolist()
        else:
            l_id_member_proxy_sub = []
        l_id_member_proxy = [id for id in l_id_member_proxy if id != id_member]
        if len(l_id_member_proxy) > 0:
            l_member_proxy = d_member_proxy.loc[d_member_proxy['id_member'].isin(l_id_member_proxy),'name_jpn_full'].tolist()
            l_member_proxy = [name.replace('　',' ') for name in l_member_proxy]
            str_member_proxy = ','.join(l_member_proxy)
        else:
            str_member_proxy = ''
        if len(l_id_member_proxy_sub) > 0:
            l_member_proxy_sub = d_member_proxy.loc[d_member_proxy['id_member'].isin(l_id_member_proxy_sub),'name_jpn_full'].tolist()
            l_member_proxy_sub = [name.replace('　',' ') for name in l_member_proxy_sub]
            str_member_proxy = str_member_proxy + '(,' + ','.join(l_member_proxy_sub) + ')'
        if str_member_proxy == '':
            str_member_proxy == 'なし'

        description = name_member + '先生ご担当\n代理候補(敬称略): ' + str_member_proxy +\
                    '\n変更申請: https://forms.gle/oxvdt8CNkW6iPPFm6' +\
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
        result_event = service.events().insert(calendarId = id_calendar, body = body_event).execute()
        l_result.append(result_event)

    return l_result


def delete_duty(service_calendar, id_calendar, l_date_duty_delete, d_event_exist):
    l_id_event_delete = []
    for date_duty in l_date_duty_delete:
        id_event = d_event_exist.loc[d_event_exist['date_duty'] == date_duty, 'id_event'].tolist()[0]
        l_id_event_delete.append(id_event)

    l_result = []
    for id_event in l_id_event_delete:
        result_delete = service_calendar.events().delete(calendarId = id_calendar, eventId = id_event).execute()
        l_result.append(result_delete)

    return l_result


def list_duty(service_calendar, id_calendar, year, month, d_member, dict_time_duty):
    #d_member = d_member.reset_index()

    if month == 12:
        year_end = year + 1
        month_end = 1
    else:
        year_end = year
        month_end = month + 1

    # Extract from G calendar
    time_start = str(year) + '-' + str(month).zfill(2) + '-01T00:00:00Z'
    time_end = str(year_end) + '-' + str(month_end).zfill(2) + '-01T00:00:00Z'
    l_event = service_calendar.events().list(
        calendarId = id_calendar,
        timeMin = time_start,
        timeMax = time_end,
        maxResults = 1000,
        singleEvents = True,
        orderBy = 'startTime'
    ).execute()
    d_event = pd.DataFrame(l_event.get('items', []))

    # Convert result
    d_time_duty = pd.DataFrame(dict_time_duty)
    l_assign_calendar = []
    for id, row in d_event.iterrows():
        str_ymd = row['start']['dateTime']
        #duty = d_time_duty.loc[d_time_duty['duty_jpn'] == row['summary'], 'duty'].tolist()[0]
        duty = d_time_duty.loc[d_time_duty['duty_jpn'] == row['summary'], 'duty'].tolist()
        if len(duty) > 0:
            duty = duty[0]
            name_jpn_full = row['description'].split('先生')[0]
            #email = row['attendees'][0]['email']
            id_member = d_member.loc[d_member['name_jpn_full'] == name_jpn_full, 'id_member'].tolist()[0]
            name_jpn = d_member.loc[d_member['name_jpn_full'] == name_jpn_full, 'name_jpn'].tolist()[0]
            l_assign_calendar.append({'date_duty': str(int(str_ymd[8:10])) + '_' + duty,
                                    'year': int(str_ymd[0:4]),
                                    'month': int(str_ymd[5:7]),
                                    'date': int(str_ymd[8:10]),
                                    'duty': duty,
                                    'id_member': id_member,
                                    'name_jpn': name_jpn,
                                    'id_event': row['id']})

    if len(l_assign_calendar) > 0:
        d_assign_calendar = pd.DataFrame(l_assign_calendar)
    else:
        d_assign_calendar = pd.DataFrame(columns = ['date_duty', 'year', 'month', 'date', 'duty', 'id_member', 'name_jpn', 'id_event'])

    return d_assign_calendar
