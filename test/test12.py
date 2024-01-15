# Test loading excel data (member data)

import pandas as pd

d_bshift_src = pd.read_excel("/Users/smrt/Library/CloudStorage/Dropbox/dutyshift/202311/2023年11月B当直表.xlsx", sheet_name = '2023.11B')
d_bshift = d_bshift_src.iloc[2:,2]
