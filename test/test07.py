
# Include score columns in April result

import pandas as pd
d_assign_date_duty_april = pd.read_csv('D:/atiro/Dropbox/dutyshift/202204/assign_date_duty.csv')
d_score_duty = pd.read_csv('D:/atiro/Dropbox/dutyshift/config/score_duty.csv')
d_assign_date_duty_april = pd.merge(d_assign_date_duty_april, d_score_duty, on = 'duty', how = 'left')
d_assign_date_duty_april.to_csv('D:/atiro/Dropbox/dutyshift/202204/assign_date_duty.csv', index = False)
