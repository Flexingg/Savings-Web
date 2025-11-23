from flask import Flask, jsonify, request, render_template, g
from flask_cors import CORS
import sqlite3
import logging
import time

app = Flask(__name__)
CORS(app)  # Allows cross-origin requests if you develop separately, but good to have.

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DATABASE = 'savings.db'

def init_db():
    with app.app_context():
        db = get_db()
        cursor = db.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS settings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                daily_max REAL,
                house_goal REAL,
                current_savings REAL
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS expenses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                desc TEXT NOT NULL,
                amount REAL NOT NULL,
                who TEXT NOT NULL,
                day INTEGER NOT NULL,
                category TEXT
            )
        ''')
        # Insert initial settings if they don't exist
        cursor.execute("SELECT COUNT(*) FROM settings")
        if cursor.fetchone()[0] == 0:
            cursor.execute("INSERT INTO settings (daily_max, house_goal, current_savings) VALUES (?, ?, ?)",
                           (50.0, 100000.0, 0.0))
        
        # Insert initial expenses if they don't exist
        cursor.execute("SELECT COUNT(*) FROM expenses")
        if cursor.fetchone()[0] == 0:
            pass # Removed initial expense data insertion
        
        db.commit()

def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row # This makes rows behave like dicts
    return db

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

# Initialize the database when the app starts
with app.app_context():
    init_db()

# --- In-Memory Data Store ---
# db = {
#     "settings": {
#         "daily_max": 50,
#         "house_goal": 50000,
#         "current_savings": 12450
#     },
#     "expenses": [
#         {"id": 1, "desc": "Morning Coffee", "amount": 5.50, "who": "Jonathan", "day": 1, "category": "Jonathan"},
#         {"id": 2, "desc": "Grocery Run", "amount": 42.00, "who": "Kathy", "day": 2, "category": "Both"},
#         {"id": 3, "desc": "Netflix Sub", "amount": 15.00, "who": "Jonathan", "day": 3, "category": "Both"},
#         {"id": 4, "desc": "Gas Station", "amount": 30.00, "who": "Kathy", "day": 5, "category": "Kathy"},
#     ]
# }

# --- Frontend Route ---
@app.route('/')
def index():
    """Serves the main HTML page"""
    return render_template('index.html')

# --- API Routes ---

@app.route('/api/data', methods=['GET'])
def get_data():
    """Get all initial data (settings + expenses)"""
    start_time = time.time()
    logger.info("Handling GET /api/data")
    db = get_db()
    cursor = db.cursor()

    settings = cursor.execute("SELECT daily_max, house_goal, current_savings FROM settings").fetchone()
    expenses = cursor.execute("SELECT id, desc, amount, who, day, category FROM expenses").fetchall()

    duration = time.time() - start_time
    logger.info(f"Completed GET /api/data in {duration:.2f} seconds")
    return jsonify({
        "settings": dict(settings) if settings else {},
        "expenses": [dict(expense) for expense in expenses]
    })

@app.route('/api/expenses', methods=['POST'])
def add_expense():
    start_time = time.time()
    logger.info("Handling POST /api/expenses")
    data = request.json
    db = get_db()
    cursor = db.cursor()
    cursor.execute("INSERT INTO expenses (desc, amount, who, day, category) VALUES (?, ?, ?, ?, ?)",
                   (data.get('desc'), float(data.get('amount')), data.get('who'), int(data.get('day')), data.get('category', 'Pending')))
    db.commit()
    new_expense_id = cursor.lastrowid
    new_expense = cursor.execute("SELECT id, desc, amount, who, day, category FROM expenses WHERE id = ?", (new_expense_id,)).fetchone()
    duration = time.time() - start_time
    logger.info(f"Completed POST /api/expenses in {duration:.2f} seconds")
    return jsonify(dict(new_expense)), 201

@app.route('/api/expenses/<int:expense_id>', methods=['PATCH'])
def update_expense(expense_id):
    start_time = time.time()
    logger.info(f"Handling PATCH /api/expenses/{expense_id}")
    data = request.json
    db = get_db()
    cursor = db.cursor()
    
    updates = []
    params = []

    if 'category' in data:
        updates.append("category = ?")
        params.append(data['category'])
    if 'who' in data:
        updates.append("who = ?")
        params.append(data['who'])
    if 'desc' in data:
        updates.append("desc = ?")
        params.append(data['desc'])
    if 'amount' in data:
        updates.append("amount = ?")
        params.append(float(data['amount']))
    if 'day' in data:
        updates.append("day = ?")
        params.append(int(data['day']))

    if not updates:
        duration = time.time() - start_time
        logger.info(f"Completed PATCH /api/expenses/{expense_id} (no updates) in {duration:.2f} seconds")
        return jsonify({"error": "No fields provided for update"}), 400

    params.append(expense_id)
    
    cursor.execute(f"UPDATE expenses SET {', '.join(updates)} WHERE id = ?", tuple(params))
    db.commit()
    
    expense = cursor.execute("SELECT id, desc, amount, who, day, category FROM expenses WHERE id = ?", (expense_id,)).fetchone()
    duration = time.time() - start_time
    if expense:
        logger.info(f"Completed PATCH /api/expenses/{expense_id} in {duration:.2f} seconds")
        return jsonify(dict(expense))
    logger.info(f"Completed PATCH /api/expenses/{expense_id} (not found) in {duration:.2f} seconds")
    return jsonify({"error": "Expense not found"}), 404

@app.route('/api/settings', methods=['POST'])
def update_settings():
    start_time = time.time()
    logger.info("Handling POST /api/settings")
    data = request.json
    db = get_db()
    cursor = db.cursor()
    
    # Fetch current settings to update
    settings = cursor.execute("SELECT daily_max, house_goal, current_savings FROM settings").fetchone()
    if not settings:
        duration = time.time() - start_time
        logger.info(f"Completed POST /api/settings (not found) in {duration:.2f} seconds")
        return jsonify({"error": "Settings not found"}), 404
    
    updated_settings = dict(settings)
    for key in ['daily_max', 'house_goal', 'current_savings']:
        if key in data:
            updated_settings[key] = float(data[key])
    
    cursor.execute("UPDATE settings SET daily_max = ?, house_goal = ?, current_savings = ?",
                   (updated_settings['daily_max'], updated_settings['house_goal'], updated_settings['current_savings']))
    db.commit()
    
    duration = time.time() - start_time
    logger.info(f"Completed POST /api/settings in {duration:.2f} seconds")
    return jsonify(updated_settings)

@app.route('/api/expenses/<int:expense_id>', methods=['DELETE'])
def delete_expense(expense_id):
    start_time = time.time()
    logger.info(f"Handling DELETE /api/expenses/{expense_id}")
    db = get_db()
    cursor = db.cursor()
    cursor.execute("DELETE FROM expenses WHERE id = ?", (expense_id,))
    db.commit()
    duration = time.time() - start_time
    logger.info(f"Completed DELETE /api/expenses/{expense_id} in {duration:.2f} seconds")
    return jsonify({"message": "Expense deleted successfully"}), 200

if __name__ == '__main__':
    app.run(debug=True, port=5000)