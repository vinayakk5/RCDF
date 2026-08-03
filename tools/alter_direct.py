import pymysql
conn = pymysql.connect(host='localhost', user='root', password='password', db='rcdf_supply', charset='utf8mb4')
cur = conn.cursor()
cur.execute("ALTER TABLE dispatches MODIFY bill_id INT NULL;")
conn.commit()
print('OK')
cur.close()
conn.close()
