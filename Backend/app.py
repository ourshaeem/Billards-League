from flask import Flask, jsonify, request
from flask_cors import CORS

# Import your brains!
from logic.leaderboard import top50_leaderboard
from logic.manage_queue import view_queue, join_queue
from logic.auth import register_user
from logic.record_match import record_match_result

app = Flask(__name__)
CORS(app) # Allows your frontend to talk to the backend

# 1. LEADERBOARD ENDPOINT
@app.route('/leaderboard', methods=['GET'])
def get_leaderboard():
    data = top50_leaderboard()
    return jsonify(data)

# 2. QUEUE ENDPOINT (Viewing)
@app.route('/queue/<int:table_id>', methods=['GET'])
def get_queue(table_id):
    data = view_queue(table_id)
    return jsonify(data)

# 3. JOIN QUEUE ENDPOINT
@app.route('/queue/join', methods=['POST'])
def join_table_queue():
    data = request.json # Gets user_id and table_id from the web request
    # Since join_queue currently only prints, it will work, 
    # but later we can make it return success/fail
    join_queue(data['user_id'], data['table_id'])
    return jsonify({"message": "Join request processed"})

# 4. REGISTER ENDPOINT
@app.route('/register', methods=['POST'])
def register():
    data = request.json
    success = register_user(
        data['username'], 
        data['first_name'], 
        data['last_name'], 
        data['password']
    )
    if success:
        return jsonify({"message": "User registered successfully!"}), 201
    return jsonify({"message": "Registration failed"}), 400

# 5. RECORD MATCH ENDPOINT
@app.route('/match/record', methods=['POST'])
def record_match():
    data = request.json
    # winner_id, loser_id, table_id, elo_change
    record_match_result(
        data['table_id'], 
        data['winner_id'], 
        data['loser_id'], 
        data['elo_change']
    )
    return jsonify({"message": "Match recorded and next session triggered!"})

if __name__ == "__main__":
    app.run(debug=True, port=5000)