from database import get_db_connection
# Records a match result, updates ELO ratings, and adjusts player ranks as needed in the data
        

def update_player_rank(user_id, cursor):
    find_rank_sql = " SELECT rank_id FROM ranks WHERE min_elo <= (SELECT elo_rating FROM Players WHERE user_id = %s) ORDER BY min_elo DESC LIMIT 1"
    
    cursor.execute(find_rank_sql, (user_id,))
    result = cursor.fetchone()
    if result:
        new_rank_id = result[0]
        update_rank_sql = "UPDATE Players SET rank_id = %s WHERE user_id = %s"
        cursor.execute(update_rank_sql,(new_rank_id, user_id,))


def start_new_session(table_id):
    db = get_db_connection()
    cursor = db.cursor()

    try:
        cursor.execute("SELECT winner_id FROM Matches WHERE table_id = %s AND match_status = 'Active'", (table_id,))
        active_match = cursor.fetchone()

        if active_match:
            king_id = active_match[0]
            print("There is already a winner at the Table. Finding a challenger")
            
            cursor.execute("SELECT user_id FROM Queue WHERE table_id = %s AND queue_position = 1", (table_id,))
            challenger = cursor.fetchone()

            if challenger:
                challenger_id = challenger[0]
                cursor.execute("DELETE FROM Queue WHERE table_id = %s AND queue_position = 1", (table_id,))
                cursor.execute("UPDATE Queue SET queue_position = queue_position - 1 WHERE table_id = %s", (table_id,))

                cursor.execute("UPDATE Matches SET loser_id = %s WHERE table_id = %s AND match_status = 'Active' AND loser_id IS NULL", (challenger_id, table_id,))


                print(f"Challenger {challenger_id} is up next to face Winner {king_id} at Table {table_id}")
        
        else:
            print(f" No players are currently at Table {table_id}. Ready for new match and wating for 2 Players.")
            cursor.execute("SELECT user_id FROM Queue WHERE table_id = %s ORDER BY queue_position ASC LIMIT 2", (table_id,))
            players = cursor.fetchall()

            if len(players) == 2:
                player_1, player_2= players[0][0], players[1][0]

                cursor.execute("DELETE FROM Queue WHERE table_id = %s AND (queue_position <= 2)", (table_id,))
                cursor.execute("UPDATE Queue SET queue_position = queue_position - 2 WHERE table_id = %s", (table_id,))
                cursor.execute("INSERT INTO Matches (table_id, winner_id, loser_id, elo_change, match_status) VALUES (%s,%s,%s,0, 'Active')", (table_id, player_1,player_2))

                print(f"Players {player_1} AND {player_2} have filled the table {table_id} and have started a new match.")
                
        db.commit()
    
    except Exception as e:
        db.rollback()
        print(f"Error starting a new session {e}")
    finally:
        cursor.close()
        db.close()


def record_match_result(table_id, winner_id , loser_id, elo_change):
    db = get_db_connection()
    cursor = db.cursor()

    try:
        Update_match = "UPDATE Matches SET match_status = 'Finished', elo_change = %s WHERE table_id = %s AND match_status = 'Active'"
        sql_winner = "UPDATE Players SET total_wins = total_wins + 1, elo_rating = elo_rating + %s WHERE user_id = %s"
        sql_loser = "UPDATE Players SET total_losses = total_losses + 1, elo_rating = elo_rating - %s WHERE user_id = %s"
        return_king = "INSERT INTO Matches (table_id, winner_id, loser_id, elo_change, match_status) VALUES (%s, %s, NULL, 0, 'Active')"

        cursor.execute(Update_match, (elo_change, table_id))
        cursor.execute(sql_winner, (elo_change, winner_id))
        cursor.execute(sql_loser, (elo_change, loser_id))
        cursor.execute(return_king, (table_id, winner_id))

        update_player_rank(winner_id, cursor)
        update_player_rank(loser_id, cursor)

        db.commit()

        print("Match , ELO, and Ranks were all updated successfully.")

        start_new_session(table_id)

    except Exception as e:
        db.rollback() # Undo everything if this part fails and you get a eception
        print(f"Error happened fix. {e}")
    finally:
        cursor.close()
        db.close()



