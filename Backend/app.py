from flask import Flask, jsonify, request
from flask_jwt_extended import JWTManager, create_access_token, jwt_required, get_jwt_identity
from flask_cors import CORS

# Import your brains!
from logic.leaderboard import top50_leaderboard
from logic.manage_queue import view_queue, join_queue
from logic.auth import register_user, login_user
from logic.record_match import record_match_result
from database import get_db_connection

app = Flask(__name__)

# --- JWT CONFIG ---
# This is the "Key" that signs your tokens
app.config["JWT_SECRET_KEY"] = "super-secret-pool-key" 
jwt = JWTManager(app)

# CORS must allow the Authorization header
CORS(app, supports_credentials=True, origins=["http://localhost:5173", "http://127.0.0.1:5173"], allow_headers=["Authorization", "Content-Type"])

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

# 3. JOIN QUEUE (Protected)
@app.route('/queue/join', methods=['POST'])
@jwt_required() # <--- Requires the token from React
def join_table_queue():
    user_id = get_jwt_identity() # <--- Gets ID from the token
    
    data = request.json or {}
    table_id = data.get('table_id')
    if table_id is None:
        return jsonify({"message": "table_id is required"}), 400

    join_queue(user_id, table_id)

    current_queue = view_queue(table_id)
    if len(current_queue) >= 2:
        p1_id = current_queue[0]['user_id']
        p2_id = current_queue[1]['user_id']
        
        db = get_db_connection()
        cursor = db.cursor()
        try:
            cursor.execute("""
                INSERT INTO Matches (table_id, winner_id, loser_id, match_status) 
                VALUES (%s, %s, %s, 'Active')
            """, (table_id, p1_id, p2_id))
            cursor.execute("DELETE FROM Queue WHERE table_id = %s", (table_id,))
            db.commit()
        except Exception as e:
            db.rollback()
        finally:
            cursor.close()
            db.close()

    return jsonify({"message": "Joined!"})

# 4. LOGIN (The Token Generator)
@app.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    user = login_user(data.get('username'), data.get('password'))

    if user:
        # Stringify the user_id for JWT compatibility
        access_token = create_access_token(identity=str(user['user_id']))
        return jsonify({
            "message": "Login successful",
            "access_token": access_token,
            "user_id": user['user_id'],
            "username": user['username']
        }), 200
    
    return jsonify({"message": "Invalid credentials"}), 401

# 5. MATCH STATUS (Protected)
@app.route('/match/status', methods=['GET'])
@jwt_required() # <--- This stops the 401 error!
def get_match_status():
    user_id = get_jwt_identity() # Identifies exactly who is asking

    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    try:
        query = """
            SELECT p.username as opponent_name 
            FROM Matches m
            JOIN Players p ON (p.user_id = m.winner_id OR p.user_id = m.loser_id)
            WHERE (m.winner_id = %s OR m.loser_id = %s) 
            AND m.match_status = 'Active' 
            AND p.user_id != %s
            LIMIT 1
        """
        cursor.execute(query, (user_id, user_id, user_id))
        match = cursor.fetchone()
    finally:
        cursor.close()
        db.close()

    if match:
        return jsonify({"status": "playing", "opponent": match['opponent_name']})
    return jsonify({"status": "idle"})

# 6. REGISTER (Public)
@app.route('/register', methods=['POST'])
def register():
    data = request.json
    success = register_user(data['username'], data['first_name'], data['last_name'], data['password'])
    return jsonify({"message": "Success" if success else "Failed"}), 201 if success else 400

if __name__ == "__main__":
    app.run(debug=True, port=5000)