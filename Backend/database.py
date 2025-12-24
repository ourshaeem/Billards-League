import mysql.connector
# Connects to the MYSQL Database
def get_db_connection():
    connection = mysql.connector.connect(
        host="127.0.0.1",
        user="root",
        password="Skythekidrs679op",
        database="ranked_billards"
    )
    return connection
