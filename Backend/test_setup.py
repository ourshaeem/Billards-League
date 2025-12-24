from database import get_db_connection
db = get_db_connection()
cursor = db.cursor()
try:
    cursor.execute("SHOW TABLES;")
    tables = cursor.fetchall()

    print("Connection successful. Tables in the database:")
    print(f"Your tables  {tables}")
except Exception as e:
    print(f"Error connecting to database {e}")
