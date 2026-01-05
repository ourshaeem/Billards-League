import bcrypt
from database import get_db_connection

def register_user(username, first_name, last_name, password_hash):
    db = get_db_connection()
    cursor = db.cursor()

    # Hashing the password for security
    hashed_pw = bcrypt.hashpw(password_hash.encode('utf-8'), bcrypt.gensalt())

    sql = "INSERT INTO Players (username, first_name, last_name, password_hash) VALUES (%s, %s, %s, %s)"
    user_data = (username, first_name, last_name, hashed_pw)

    try:
        cursor.execute(sql, user_data)
        db.commit()
        return True # Indicate success of registration
    except Exception as e:
        return False # Indicate failure of registration
    finally:
        cursor.close()
        db.close()

def login_user(username, password_text):
    db = get_db_connection()
    cursor = db.cursor(dictionary=True)

    sql = "SELECT user_id, username, password_hash FROM Players WHERE username = %s"
    cursor.execute (sql, (username,))
    user = cursor.fetchone()

    cursor.close()
    db.close()

    if user and bcrypt.checkpw(password_text.encode('utf-8'), user['password_hash'].encode('utf-8')):
        return user # Login successful, return user info
    return None # Login failed