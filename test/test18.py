# Create Gdrive folder, copy Forms template

from googleapiclient.discovery import build
from script.helper import *

# Parameters
year_plan, month_plan, l_holiday  = 2025, 6, []
#year_plan, month_plan, l_holiday  = 2025, 7, []
id_template_form   = '1TPqbvxc4Sgj6qhMkSE0eCciFxEaOsgNQIduu29SUwZA'  # original form
lp_root = ['/home/atiroms/Documents','D:/atiro','D:/NICT_WS','/Users/smrt']
l_scope = ['https://www.googleapis.com/auth/drive', 'https://www.googleapis.com/auth/forms.body']

# Prepare credentials and service
p_root, p_month, p_data = prep_dirs(lp_root, year_plan, month_plan, prefix_dir = None, make_data_dir = None)
creds = prep_api_creds(p_root, l_scope)
service_drive = build('drive', 'v3', credentials = creds)
service_forms = build('forms', 'v1', credentials=creds)

# Create data folder
path_new = '/dutyshift/result/' + str(year_plan) + '/' + str(month_plan).zfill(2)
result_folder = create_gdrive_path(service_drive, path_new)

# Copy forms template
id_folder_data   = result_folder[-1]
body = {
  'name':    'form_' + str(year_plan) + str(month_plan).zfill(2),
  'parents': [id_folder_data]
}
form_copied = service_drive.files().copy(
    fileId = id_template_form,
    body = body,
    fields = 'id, name, parents'
).execute()

id_form_copied = form_copied['id']

# Inspect copied forms
form = service_forms.forms().get(formId = id_form_copied).execute()
print(f"Title: {form['info']['title']}")
print("Items:")

for item in form.get('items', []):
    item_id = item['itemId']
    it = item.get('title', '<no title>')
    qtype = list(item.get('questionItem', {}).get('question', {}).keys())
    print(f" - {item_id}: {it}  (types: {qtype})")

# Overwrite form title and delete question 3fd28d79
new_title = f"{year_plan}年{month_plan}月当直希望調査"
form_requests = [
    {
        "updateFormInfo": {
            "info": {"title": new_title},
            "updateMask": "title"
        }
    },
    {
        "deleteItem": {"itemId": "3fd28d79"}
    }
]
service_forms.forms().batchUpdate(
    formId=id_form_copied,
    body={"requests": form_requests}
).execute()

# Update 
id_item = "03f37999"
row_new = ['test0', 'test1']

update_question_row(id_form_copied, service_forms, id_item, row_new)