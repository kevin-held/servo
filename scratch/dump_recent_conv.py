import sqlite3

db_path = r'c:\Users\kevin\OneDrive\Desktop\ai\state.db'
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

cursor.execute("SELECT role, content FROM conversation ORDER BY id DESC LIMIT 5")
rows = cursor.fetchall()

for role, content in rows:
    print(f"[{role.upper()}]\n{content}\n")

conn.close()
