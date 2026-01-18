from flask import Flask, jsonify, request
from flask_jwt_extended import JWTManager, create_access_token, jwt_required, get_jwt_identity
from flask_cors import CORS
from datetime import timedelta
import math

# Import your brains!
from logic.leaderboard import top50_leaderboard
from logic.manage_queue import view_queue, join_queue
from logic.auth import register_user, login_user
from logic.record_match import record_match_result, start_new_session
from database import get_db_connection

app = Flask(__name__)

# --- JWT CONFIG ---
app.config["JWT_SECRET_KEY"] = "super-secret-pool-key-change-in-production"
app.config["JWT_ACCESS_TOKEN_EXPIRES"] = timedelta(hours=24)  # Token lasts 24 hours

jwt = JWTManager(app)

# CORS configuration
CORS(app, origins=["http://localhost:5173", "http://127.0.0.1:5173"])

# 1. LEADERBOARD (Public)
@app.route('/leaderboard', methods=['GET'])
def get_leaderboard():
    data = top50_leaderboard()
    return jsonify(data)

# 2. QUEUE (Public)
@app.route('/queue/<int:table_id>', methods=['GET'])
def get_queue(table_id):
    data = view_queue(table_id)
    return jsonify(data)

# 3. JOIN QUEUE (Protected) - FIXED TO CREATE MATCH
@app.route('/queue/join', methods=['POST'])
@jwt_required()  # Requires JWT token
def join_table_queue():
    user_id = get_jwt_identity()  # Gets user ID from token
    
    data = request.json or {}
    table_id = data.get('table_id', 1)  # Default to table 1

    # Join the queue
    join_queue(user_id, table_id)
    
    # After joining, check if we should start a match
    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    
    try:
        # Check how many players are in the queue now
        cursor.execute("SELECT COUNT(*) as count FROM Queue WHERE table_id = %s", (table_id,))
        queue_count = cursor.fetchone()['count']
        
        # Check if there's already an active match for this table
        cursor.execute("""
            SELECT match_id FROM Matches 
            WHERE table_id = %s AND match_status = 'Active'
            LIMIT 1
        """, (table_id,))
        active_match = cursor.fetchone()
        
        # Only create a new match if no active match exists AND we have at least 2 players
        if not active_match and queue_count >= 2:
            # Get the first 2 players from queue
            cursor.execute("""
                SELECT q.user_id, p.username 
                FROM Queue q 
                JOIN Players p ON q.user_id = p.user_id 
                WHERE q.table_id = %s 
                ORDER BY q.queue_position ASC 
                LIMIT 2
            """, (table_id,))
            
            players = cursor.fetchall()
            
            if len(players) == 2:
                player1_id = players[0]['user_id']
                player2_id = players[1]['user_id']
                
                # Remove both players from queue
                cursor.execute("DELETE FROM Queue WHERE table_id = %s AND user_id IN (%s, %s)", 
                              (table_id, player1_id, player2_id))
                
                # Create a new active match
                cursor.execute("""
                    INSERT INTO Matches (table_id, winner_id, loser_id, match_status) 
                    VALUES (%s, %s, %s, 'Active')
                """, (table_id, player1_id, player2_id))
                
                db.commit()
                return jsonify({"message": "Joined queue and match started!"})
        
        db.commit()
        return jsonify({"message": "Joined queue successfully!"})
                
    except Exception as e:
        db.rollback()
        return jsonify({"message": f"Error: {str(e)}"}), 500
    finally:
        cursor.close()
        db.close()

# 4. LOGIN (Token Generator)
@app.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    
    if not data or not data.get('username') or not data.get('password'):
        return jsonify({"message": "Username and password required"}), 400
    
    user = login_user(data['username'], data['password'])

    if user:
        # Create JWT token with user_id as identity
        access_token = create_access_token(identity=str(user['user_id']))
        return jsonify({
            "message": "Login successful",
            "access_token": access_token,
            "user_id": user['user_id'],
            "username": user['username']
        }), 200
    
    return jsonify({"message": "Invalid credentials"}), 401

# 5. MATCH STATUS (Protected) - FIXED to find opponent correctly
@app.route('/match/status', methods=['GET'])
@jwt_required()
def get_match_status():
    user_id = int(get_jwt_identity())

    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    
    try:
        # Check if user is in an active match
        cursor.execute("""
            SELECT m.match_id, m.table_id, m.winner_id, m.loser_id
            FROM Matches m
            WHERE (m.winner_id = %s OR m.loser_id = %s) 
            AND m.match_status = 'Active'
            LIMIT 1
        """, (user_id, user_id))
        
        match = cursor.fetchone()
        
        if not match:
            return jsonify({"status": "idle"})
        
        # Determine opponent
        if match['winner_id'] == user_id:
            opponent_id = match['loser_id']
        else:
            opponent_id = match['winner_id']
        
        # Get opponent name
        cursor.execute("SELECT username FROM Players WHERE user_id = %s", (opponent_id,))
        opponent = cursor.fetchone()
        
        if opponent:
            return jsonify({
                "status": "playing", 
                "opponent": opponent['username'],
                "opponent_id": opponent_id,
                "match_id": match['match_id'],
                "table_id": match['table_id']
            })
        else:
            return jsonify({"status": "idle"})
            
    except Exception as e:
        print(f"Error in match status: {e}")
        return jsonify({"status": "idle"}), 500
    finally:
        cursor.close()
        db.close()

# 6. RECORD MATCH ENDPOINT (Protected) - SIMPLIFIED
@app.route('/match/record', methods=['POST'])
@jwt_required()
def record_match():
    user_id = int(get_jwt_identity())
    
    data = request.json or {}
    my_balls = data.get('my_balls', 0)
    opp_balls = data.get('opp_balls', 0)
    
    if my_balls is None or opp_balls is None:
        return jsonify({"message": "Both scores are required"}), 400
    
    # Simple ELO calculation for now
    elo_change = 20
    
    # Find the active match
    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    
    try:
        cursor.execute("""
            SELECT match_id, table_id, winner_id, loser_id 
            FROM Matches 
            WHERE (winner_id = %s OR loser_id = %s) 
            AND match_status = 'Active'
            LIMIT 1
        """, (user_id, user_id))
        
        match = cursor.fetchone()
        
        if not match:
            return jsonify({"message": "No active match found"}), 404
        
        # Determine winner based on scores
        if my_balls > opp_balls:
            winner_id = user_id
            loser_id = match['winner_id'] if match['winner_id'] != user_id else match['loser_id']
        elif opp_balls > my_balls:
            winner_id = match['winner_id'] if match['winner_id'] != user_id else match['loser_id']
            loser_id = user_id
        else:
            return jsonify({"message": "Scores cannot be equal"}), 400
        
        # Call record_match_result function
        record_match_result(match['table_id'], winner_id, loser_id, elo_change)
        
        return jsonify({
            "message": "Match recorded successfully!",
            "elo_change": elo_change,
            "winner_id": winner_id
        })
        
    except Exception as e:
        return jsonify({"message": f"Error: {str(e)}"}), 500
    finally:
        cursor.close()
        db.close()

# 7. REGISTER (Public)
@app.route('/register', methods=['POST'])
def register():
    data = request.json
    
    if not data or not all(key in data for key in ['username', 'first_name', 'last_name', 'password']):
        return jsonify({"message": "All fields are required"}), 400
    
    success = register_user(
        data['username'], 
        data['first_name'], 
        data['last_name'], 
        data['password']
    )
    
    return jsonify({"message": "User registered successfully" if success else "Registration failed"}), 201 if success else 400

# 8. HEALTH CHECK (Public)
@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({"status": "healthy", "service": "billiards-league-api"})

# 9. FORCE MATCH START (Debug endpoint - remove in production)
@app.route('/debug/start-match', methods=['POST'])
def debug_start_match():
    table_id = request.json.get('table_id', 1)
    
    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    
    try:
        # Get first 2 players from queue
        cursor.execute("""
            SELECT q.user_id, p.username 
            FROM Queue q 
            JOIN Players p ON q.user_id = p.user_id 
            WHERE q.table_id = %s 
            ORDER BY q.queue_position ASC 
            LIMIT 2
        """, (table_id,))
        
        players = cursor.fetchall()
        
        if len(players) < 2:
            return jsonify({"message": f"Need 2 players, only {len(players)} in queue"}), 400
        
        player1_id = players[0]['user_id']
        player2_id = players[1]['user_id']
        
        # Remove from queue
        cursor.execute("DELETE FROM Queue WHERE table_id = %s AND user_id IN (%s, %s)", 
                      (table_id, player1_id, player2_id))
        
        # Create match
        cursor.execute("""
            INSERT INTO Matches (table_id, winner_id, loser_id, match_status) 
            VALUES (%s, %s, %s, 'Active')
        """, (table_id, player1_id, player2_id))
        
        db.commit()
        
        return jsonify({
            "message": "Match created!",
            "player1": players[0]['username'],
            "player2": players[1]['username'],
            "match_id": cursor.lastrowid
        })
        
    except Exception as e:
        db.rollback()
        return jsonify({"message": f"Error: {str(e)}"}), 500
    finally:
        cursor.close()
        db.close()

if __name__ == "__main__":
    app.run(debug=True, port=5000)