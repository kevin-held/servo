import sqlite3

db_path = r'state\state.db'
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

print("Checking conversation table for 'Context Loss'...")
cursor.execute("SELECT id, role, content FROM conversation WHERE content LIKE '%Context Loss%' LIMIT 20")
rows = cursor.fetchall()
for r in rows:
    print(f"ID: {r[0]} | Role: {r[1]} | Content Preview: {r[2][:100]}...")

print("\nChecking trace table for 'Context Loss'...")
cursor.execute("SELECT id, step, message FROM trace WHERE message LIKE '%Context Loss%' LIMIT 20")
rows = cursor.fetchall()
for r in rows:
    print(f"ID: {r[0]} | Step: {r[1]} | Message: {r[2]}")

conn.close()
