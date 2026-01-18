from database import get_db_connection

def update_player_rank(user_id, cursor):
    """Update player's rank based on their current ELO rating"""
    find_rank_sql = """
        SELECT rank_id 
        FROM Ranks 
        WHERE min_elo <= (SELECT elo_rating FROM Players WHERE user_id = %s) 
        ORDER BY min_elo DESC 
        LIMIT 1
    """
    
    cursor.execute(find_rank_sql, (user_id,))
    result = cursor.fetchone()
    if result:
        new_rank_id = result[0]
        update_rank_sql = "UPDATE Players SET rank_id = %s WHERE user_id = %s"
        cursor.execute(update_rank_sql, (new_rank_id, user_id,))

def start_new_session(table_id):
    """Start a new match session after a match ends"""
    db = get_db_connection()
    cursor = db.cursor()

    try:
        # Check if there's already a winner at the table
        cursor.execute("""
            SELECT winner_id 
            FROM Matches 
            WHERE table_id = %s AND match_status = 'Active' AND loser_id IS NULL
        """, (table_id,))
        
        king_match = cursor.fetchone()

        if king_match:
            # King of the hill mode
            king_id = king_match[0]
            
            # Get next player from queue
            cursor.execute("""
                SELECT user_id 
                FROM Queue 
                WHERE table_id = %s 
                ORDER BY queue_position ASC 
                LIMIT 1
            """, (table_id,))
            
            challenger = cursor.fetchone()

            if challenger:
                challenger_id = challenger[0]
                
                # Remove challenger from queue
                cursor.execute("DELETE FROM Queue WHERE table_id = %s AND user_id = %s", (table_id, challenger_id))
                
                # Create new match
                cursor.execute("""
                    UPDATE Matches 
                    SET loser_id = %s 
                    WHERE table_id = %s AND winner_id = %s AND match_status = 'Active' AND loser_id IS NULL
                """, (challenger_id, table_id, king_id))
                
                db.commit()
                return True
        else:
            # Regular match - get next 2 players from queue
            cursor.execute("""
                SELECT user_id 
                FROM Queue 
                WHERE table_id = %s 
                ORDER BY queue_position ASC 
                LIMIT 2
            """, (table_id,))
            
            players = cursor.fetchall()

            if len(players) >= 2:
                player_1, player_2 = players[0][0], players[1][0]
                
                # Remove from queue
                cursor.execute("DELETE FROM Queue WHERE table_id = %s AND user_id IN (%s, %s)", (table_id, player_1, player_2))
                
                # Create new match
                cursor.execute("""
                    INSERT INTO Matches (table_id, winner_id, loser_id, match_status) 
                    VALUES (%s, %s, %s, 'Active')
                """, (table_id, player_1, player_2))
                
                db.commit()
                return True
        
        return False
        
    except Exception as e:
        db.rollback()
        print(f"Error starting a new session: {e}")
        return False
    finally:
        cursor.close()
        db.close()

def record_match_result(table_id, winner_id, loser_id, elo_change):
    """Record match result and update ELO ratings"""
    db = get_db_connection()
    cursor = db.cursor()

    try:
        # 1. Update the match to finished
        cursor.execute("""
            UPDATE Matches 
            SET match_status = 'Finished', 
                elo_change = %s
            WHERE table_id = %s 
                AND match_status = 'Active'
                AND ((winner_id = %s AND loser_id = %s) OR (winner_id = %s AND loser_id = %s))
        """, (elo_change, table_id, winner_id, loser_id, loser_id, winner_id))
        
        # 2. Update winner's stats
        cursor.execute("""
            UPDATE Players 
            SET total_wins = total_wins + 1, 
                elo_rating = elo_rating + %s
            WHERE user_id = %s
        """, (elo_change, winner_id))
        
        # 3. Update loser's stats
        cursor.execute("""
            UPDATE Players 
            SET total_losses = total_losses + 1, 
                elo_rating = elo_rating - %s
            WHERE user_id = %s
        """, (elo_change, loser_id))
        
        # 4. Update ranks
        update_player_rank(winner_id, cursor)
        update_player_rank(loser_id, cursor)
        
        # 5. Winner becomes king (stays at table)
        cursor.execute("""
            INSERT INTO Matches (table_id, winner_id, match_status) 
            VALUES (%s, %s, 'Active')
        """, (table_id, winner_id))
        
        db.commit()
        
        # 6. Start a new session (find challenger for king)
        start_new_session(table_id)
        
    except Exception as e:
        db.rollback()
        print(f"Error recording match result: {e}")
        raise
    finally:
        cursor.close()
        db.close()