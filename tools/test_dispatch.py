import requests
url='http://127.0.0.1:8000/api/dispatches'
body={'deal_id':1,'vehicle_number':'TEST-123','dispatch_date':'2026-03-23','qty_mt':1.5,'plant_id':1}
try:
    r=requests.post(url,json=body)
    print(r.status_code)
    print(r.text)
except Exception as e:
    print('ERR',e)
