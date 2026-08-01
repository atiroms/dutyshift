
################################################################################
# Libraries
################################################################################
from datetime import datetime as dt
from datetime import timedelta
import pandas as pd


################################################################################
# Parameters
################################################################################
prefix_url = 'https://www.google.com/calendar/event?action=TEMPLATE&dates='
d_duty_url = pd.DataFrame([['am', '08:30', '12:30', '&text=%E5%8D%88%E5%89%8D%E6%97%A5%E7%9B%B4&location=%E6%9D%B1%E5%A4%A7%E7%97%85%E9%99%A2&details='],
                           ['pm', '12:30', '17:15', '&text=%E5%8D%88%E5%BE%8C%E6%97%A5%E7%9B%B4&location=%E6%9D%B1%E5%A4%A7%E7%97%85%E9%99%A2&details='],
                           ['day', '08:30', '17:15', '&text=%E6%97%A5%E7%9B%B4&location=%E6%9D%B1%E5%A4%A7%E7%97%85%E9%99%A2&details='],
                           ['night', '17:15', '32:30', '&text=%E5%BD%93%E7%9B%B4&location=%E6%9D%B1%E5%A4%A7%E7%97%85%E9%99%A2&details='],
                           ['night_em', '17:15', '32:30', '&text=%E6%95%91%E6%80%A5%E5%BD%93%E7%9B%B4&location=%E6%9D%B1%E5%A4%A7%E7%97%85%E9%99%A2&details='],
                           ['day_oc', '08:30', '17:15', '&text=%E6%97%A5%E7%9B%B4OC&location=%E6%9D%B1%E5%A4%A7%E7%97%85%E9%99%A2&details='],
                           ['night_oc', '17:15', '32:30', '&text=%E5%BD%93%E7%9B%B4OC&location=%E6%9D%B1%E5%A4%A7%E7%97%85%E9%99%A2&details='],
                           ['ect', '07:30', '11:00', '&text=ECT%E5%BD%93%E7%95%AA&location=%E6%9D%B1%E5%A4%A7%E7%97%85%E9%99%A2&details=']],
                           columns = ['duty','start','end','suffix'])


################################################################################
# Return Googe calendar URL
################################################################################
def get_timestamp(year, month, date, hourminute):
    str_timestamp = '{year:0>4d}/{month:0>2d}/{date:0>2d}'.format(year = year, month = month, date = date)
    str_timestamp = str_timestamp + '_' + hourminute + ':00'

    return str_timestamp


def get_duty_url(year, month, date, duty, prefix_url = prefix_url, d_duty_url = d_duty_url, timezone = -9):
    t_start = d_duty_url[d_duty_url['duty'] == duty]['start'].values[0]
    t_end = d_duty_url[d_duty_url['duty'] == duty]['end'].values[0]
    suffix = d_duty_url[d_duty_url['duty'] == duty]['suffix'].values[0]

    timestamp_start = get_timestamp(year, month, date, t_start)
    timestamp_end = get_timestamp(year, month, date, t_end)
    
    dt_start = dt.strptime(timestamp_start, '%Y/%m/%d_%H:%M:%S') + timedelta(hours = timezone)
    dt_end = dt.strptime(timestamp_end, '%Y/%m/%d_%H:%M:%S') + timedelta(hours = timezone)

    url = prefix_url \
          + dt_start.strftime('%Y%m%d') + 'T' + dt_start.strftime('%H%M%S') + 'Z%2F' \
          + dt_end.strftime('%Y%m%d') + 'T' + dt_end.strftime('%H%M%S') + 'Z' \
          + suffix

    return url


################################################################################
# Example web-generated links
################################################################################
# am(午前日直) 4/27 8:30 - 4/27 13:00
# https://www.google.com/calendar/event?action=TEMPLATE&dates=20220426T233000Z%2F20220427T040000Z&text=%E5%8D%88%E5%89%8D%E6%97%A5%E7%9B%B4&location=%E6%9D%B1%E5%A4%A7%E7%97%85%E9%99%A2&details=

# pm(午後日直)　4/27 12:00 - 4/27 17:00
# https://www.google.com/calendar/event?action=TEMPLATE&dates=20220427T030000Z%2F20220427T040000Z&text=%E5%8D%88%E5%BE%8C%E6%97%A5%E7%9B%B4&location=%E6%9D%B1%E5%A4%A7%E7%97%85%E9%99%A2&details=

# day(日直) 4/27 8:30 - 4/27 17:00
# https://www.google.com/calendar/event?action=TEMPLATE&dates=20220426T233000Z%2F20220427T080000Z&text=%E6%97%A5%E7%9B%B4&location=%E6%9D%B1%E5%A4%A7%E7%97%85%E9%99%A2&details=

# night(当直) 4/26 17:00 - 4/27 8:30
# https://www.google.com/calendar/event?action=TEMPLATE&dates=20220426T080000Z%2F20220426T233000Z&text=%E5%BD%93%E7%9B%B4&location=%E6%9D%B1%E5%A4%A7%E7%97%85%E9%99%A2&details=

# night(当直：救急) 4/26 17:00 - 4/27 8:30
# https://www.google.com/calendar/event?action=TEMPLATE&dates=20220426T080000Z%2F20220426T233000Z&text=%E6%95%91%E6%80%A5%E5%BD%93%E7%9B%B4&location=%E6%9D%B1%E5%A4%A7%E7%97%85%E9%99%A2&details=

# day_oc(日直OC) 4/27 8:30 - 4/27 17:00
# https://www.google.com/calendar/event?action=TEMPLATE&dates=20220426T233000Z%2F20220427T080000Z&text=%E6%97%A5%E7%9B%B4OC&location=%E6%9D%B1%E5%A4%A7%E7%97%85%E9%99%A2&details=

# night_oc(当直OC) 4/26 17:00 - 4/27 8:30
# https://www.google.com/calendar/event?action=TEMPLATE&dates=20220426T080000Z%2F20220426T233000Z&text=%E5%BD%93%E7%9B%B4OC&location=%E6%9D%B1%E5%A4%A7%E7%97%85%E9%99%A2&details=

# ect(ECT当番) 4/27 07:30 - 4/27 11:00
# https://www.google.com/calendar/event?action=TEMPLATE&dates=20220426T223000Z%2F20220427T020000Z&text=ECT%E5%BD%93%E7%95%AA&location=%E6%9D%B1%E5%A4%A7%E7%97%85%E9%99%A2&details=

