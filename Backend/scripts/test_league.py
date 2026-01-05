from database import get_db_connection

def setup_league():
    db = get_db_connection()
    cursor = db.cursor()

    try:
        cursor.execute("INSERT INTO Leagues (league_name) VALUES ('Friday Night Pool')")
        league_id = cursor.lastrowid #This grabs the ID of the league we just made 

        cursor.execute("INSERT INTO Pool_tables (league_id, table_name) VALUES (%s, 'Blue Felt')", (league_id,))
        table_id = cursor.lastrowid #This grabs the ID of the table we just made

        db.commit()
        print(f"League ID {league_id} and Table ID {table_id} created sucesfully.")


    except Exception as e:
        print(f"Error setting up league: {e}")
        db.rollback()
    finally:
        cursor.close()
        db.close()

        

setup_league()