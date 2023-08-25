# test reading from public google sheet

import pandas as pd

d_replace = pd.read_csv('https://docs.google.com/spreadsheets/d/e/1glzf0fM1jyAZffFE7l7SHE26m3M4QBI5AAOsdSlmHxE/pub?output=csv')


import pandas as pd
sheet_id = "1glzf0fM1jyAZffFE7l7SHE26m3M4QBI5AAOsdSlmHxE"
sheet_name = "response"
#url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?tqx=out:csv&sheet={sheet_name}"

d_replace = pd.read_csv(f"https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?tqx=out:csv&sheet={sheet_name}")