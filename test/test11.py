# Test direct loading of availability form from g spreadsheet

import pandas as pd

sheet_address = "https://docs.google.com/spreadsheets/d/1zfubUfk7_fs3O-u0HFFH1yVlqonfeMjrccNu4ubgbbg/edit?resourcekey#gid=1662573061"
sheet_name = "FormResponses1"

sheet_id = sheet_address.split('/')[5]

d_availability = pd.read_csv(f"https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?tqx=out:csv&sheet={sheet_name}")


# Test loading excel data (member data)

import pandas as pd

d_member_src = pd.read_excel("/Users/smrt/Library/CloudStorage/Dropbox/dutyshift/config/member.xlsx", sheet_name = 'member_202311')
d_member = d_member_src.iloc[3:,:]
d_member.columns = d_member_src.iloc[2,:].tolist()
d_member.index = [i for i in range(len(d_member))]
