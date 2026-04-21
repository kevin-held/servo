import sqlite3

db_path = r'state\state.db'
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# Make LIKE case-insensitive (default is usually case-insensitive for ASCII, but let's be sure)
cursor.execute("PRAGMA case_sensitive_like = OFF")

print("Searching conversation table for 'Loss' or 'Context' (last 50 turns)...")
cursor.execute("""
    SELECT id, role, content 
    FROM conversation 
    WHERE content LIKE '%Loss%' OR content LIKE '%Context%'
    ORDER BY id DESC LIMIT 50
""")
rows = cursor.fetchall()
for r in rows:
    print(f"ID: {r[0]} | Role: {r[1]} | Content Preview: {r[2][:150].replace('\n', ' ')}...")

print("\nSearching trace table for 'Loss' or 'Context' (last 50 entries)...")
cursor.execute("""
    SELECT id, step, message 
    FROM trace 
    WHERE message LIKE '%Loss%' OR message LIKE '%Context%'
    ORDER BY id DESC LIMIT 50
""")
rows = cursor.fetchall()
for r in rows:
    print(f"ID: {r[0]} | Step: {r[1]} | Message: {r[2]}")

conn.close()
