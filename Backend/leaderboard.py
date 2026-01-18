from database import get_db_connection

def top50_leaderboard():
    db = get_db_connection()
    cursor = db.cursor()

    sql = "SELECT p.username, p.elo_rating, p.total_wins, p.total_losses, r.rank_name FROM Players p LEFT JOIN Ranks r ON p.rank_id = r.rank_id ORDER BY p.elo_rating DESC LIMIT 50"

    try:
        cursor.execute(sql)
        results = cursor.fetchall()
          # Create a list of dictionaries to hold the Leaderboard data for Flask to talk top to the frontend
        leaderboard_data = []
        for row in results:
            leaderboard_data.append({
            "username":row[0],
            "elo_rating":row[1],
            "total_wins":row[2],
            "total_losses":row[3],
            "rank_name":row[4] if row[4] else "Unranked"
        })
            
        return leaderboard_data  # Returns the data so Flask can use it 
    
    except Exception as e:
        print(f"Error fetching leaderboard: {e}")
        return []
    finally:
        cursor.close()
        db.close()

        
