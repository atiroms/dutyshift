# Include year and month columns in date_duty.csv

import pandas as pd
import os

year_plan = 2023
month_plan = 1

l_dir_pastdata = os.listdir('D:/atiro/Dropbox/dutyshift')
l_dir_pastdata = [dir for dir in l_dir_pastdata if dir.startswith('20')]
l_dir_pastdata = [dir for dir in l_dir_pastdata if len(dir) == 6]
l_dir_pastdata = sorted(l_dir_pastdata)
for dir in l_dir_pastdata:
    year_dir = int(dir[:4])
    month_dir = int(dir[4:6])
    if year_dir < year_plan or (year_dir == year_plan and month_dir < month_plan):
        d_assign_date_duty = pd.read_csv(os.path.join('D:/atiro/Dropbox/dutyshift', dir, 'assign_date_duty.csv'))
        d_assign_date_duty['year'] = year_dir
        d_assign_date_duty['month'] = month_dir
        d_assign_date_duty.to_csv(os.path.join('D:/atiro/Dropbox/dutyshift/', dir, 'assign_date_duty.csv'), index = False)
