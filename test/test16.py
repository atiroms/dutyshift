# Read Google forms

from googleapiclient.discovery import build
from script.helper import *

# Parameters
year_plan, month_plan, l_holiday  = 2025, 6, []
lp_root = ['/home/atiroms/Documents','D:/atiro','D:/NICT_WS','/Users/smrt']
l_scope = ['https://www.googleapis.com/auth/forms.body']

# Prepare credentials and service
p_root, p_month, p_data = prep_dirs(lp_root, year_plan, month_plan, prefix_dir = None, make_data_dir = None)
creds = prep_api_creds(p_root, l_scope)

# 3. Build the Drive API client:
service = build('forms', 'v1', credentials=creds)

# 4) Retrieve the form definition

id_form = '1TPqbvxc4Sgj6qhMkSE0eCciFxEaOsgNQIduu29SUwZA'
form = service.forms().get(formId = id_form).execute()

# 5) Inspect the form
print(f"Title: {form['info']['title']}")
print("Items:")
for item in form.get('items', []):
    item_id = item['itemId']
    it = item.get('title', '<no title>')
    qtype = list(item.get('questionItem', {}).get('question', {}).keys())
    print(f" - {item_id}: {it}  (types: {qtype})")