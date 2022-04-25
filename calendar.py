
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


################################################################################
# Libraries
################################################################################
from datetime import datetime as dt
import pandas as pd


################################################################################
# Parameters
################################################################################
prefix_gca = 'https://www.google.com/calendar/event?action=TEMPLATE&dates='
d_duty_url = pd.DataFrame([['am', '0830', '13:00', 'Z&text=%E5%8D%88%E5%89%8D%E6%97%A5%E7%9B%B4&location=%E6%9D%B1%E5%A4%A7%E7%97%85%E9%99%A2&details='],
                           ['pm', '1200', '17:00', 'Z&text=%E5%8D%88%E5%BE%8C%E6%97%A5%E7%9B%B4&location=%E6%9D%B1%E5%A4%A7%E7%97%85%E9%99%A2&details='],
                           ['day', '0830', '17:00', 'Z&text=%E6%97%A5%E7%9B%B4&location=%E6%9D%B1%E5%A4%A7%E7%97%85%E9%99%A2&details='],
                           ['night', '1700', '32:30', 'Z%2F20220426T233000Z&text=%E5%BD%93%E7%9B%B4&location=%E6%9D%B1%E5%A4%A7%E7%97%85%E9%99%A2&details='],
                           ['night_em', '1700', '32:30', 'Z&text=%E6%95%91%E6%80%A5%E5%BD%93%E7%9B%B4&location=%E6%9D%B1%E5%A4%A7%E7%97%85%E9%99%A2&details='],
                           ['day_oc', '0830', '17:00', 'Z&text=%E6%97%A5%E7%9B%B4OC&location=%E6%9D%B1%E5%A4%A7%E7%97%85%E9%99%A2&details='],
                           ['night_oc', '1700', '32:30', 'Z&text=%E5%BD%93%E7%9B%B4OC&location=%E6%9D%B1%E5%A4%A7%E7%97%85%E9%99%A2&details='],
                           ['ect', '0730', '11:00', 'Z&text=ECT%E5%BD%93%E7%95%AA&location=%E6%9D%B1%E5%A4%A7%E7%97%85%E9%99%A2&details=']],
                           columns = ['duty','start','end','suffix'])


################################################################################
# Return Googe calendar URL
################################################################################
def get_gca_url(year, month, date, duty, d_duty_url):
    str_start = '{year:0>4d}{month:0>2d}{date:0>2d}_{hourminute:0>4d}00'.format(year = year, month = month, date = date, hourminute = )
    dt_start = dt.strptime(date_time_str, '%d/%m/%y %H:%M:%S')