from database import get_db_connection


def join_queue(user_id, table_id):
    db = get_db_connection()
    cursor = db.cursor()

    try:
        # Check if user is already in the queue for the table
        cursor.execute("SELECT * FROM Queue WHERE user_id = %s AND table_id = %s", (user_id, table_id))
        if cursor.fetchone():
            print(f"User {user_id} is already in the queue for Table {table_id}!")
            return
        
        cursor.execute("SELECT * FROM Matches WHERE table_id = %s AND (winner_id =%s OR loser_id = %s) AND match_status = 'Active'", (table_id, user_id, user_id))
        if cursor.fetchone():
            print(f"User {user_id} is currently playing at this table {table_id}!")
            return
        
        cursor.execute("SELECT MAX(queue_position) FROM Queue WHERE table_id = %s", (table_id,))
        max_position = cursor.fetchone()[0]
        new_position = (max_position + 1) if max_position is not None else 1

        sql = "INSERT INTO Queue (user_id, table_id, queue_position) VALUES (%s, %s, %s)"
        cursor.execute(sql, (user_id, table_id, new_position))

        db.commit()
        print(f"User {user_id} joined at position {new_position}")
    
    except Exception as e:
        db.rollback()
        print(f"Error joining queue: {e}")
    finally:
        cursor.close()
        db.close()

def view_queue(table_id):
    db = get_db_connection()
    cursor = db.cursor()

    sql = "SELECT q.queue_position, p.username FROM Queue q JOIN Players p ON q.user_id = p.user_id WHERE q.table_id = %s ORDER BY q.queue_position ASC"

    cursor.execute(sql, (table_id,))
    results = cursor.fetchall()

    # Convert results to a readable format lists of dictionaries for Flask
    queue_data = [{ "queue_position": row[0], "username": row[1]} for row in results]

    cursor.close()
    db.close()

    return queue_data # Returns the data so Flask can use it