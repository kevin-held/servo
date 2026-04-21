import sqlite3

db_path = r'state\state.db'
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

print("Dumping last 10 assistant turns...")
cursor.execute("SELECT id, content FROM conversation WHERE role='assistant' ORDER BY id DESC LIMIT 10")
rows = cursor.fetchall()
for r in rows:
    print(f"--- ID: {r[0]} ---")
    print(r[1])
    print("-" * 20)

conn.close()
