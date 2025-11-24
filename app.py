from flask import Flask, jsonify, request, render_template, g
from flask_cors import CORS
import sqlite3
import logging
import time
from datetime import datetime, timedelta

app = Flask(__name__)
CORS(app)  # Allows cross-origin requests if you develop separately, but good to have.

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DATABASE = 'data/savings.db'

# --- Date Helper Functions ---

def parse_date(date_string):
    """Parse an ISO date string (YYYY-MM-DD) to a datetime.date object.
    
    Args:
        date_string: ISO format date string (YYYY-MM-DD)
        
    Returns:
        datetime.date object or None if parsing fails
    """
    if not date_string:
        return None
    try:
        return datetime.strptime(date_string, '%Y-%m-%d').date()
    except (ValueError, TypeError) as e:
        logger.warning(f"Failed to parse date '{date_string}': {e}")
        return None

def format_date(date_obj):
    """Format a date object to ISO string (YYYY-MM-DD).
    
    Args:
        date_obj: datetime.date or datetime.datetime object
        
    Returns:
        ISO format date string (YYYY-MM-DD) or None if formatting fails
    """
    if not date_obj:
        return None
    try:
        if isinstance(date_obj, datetime):
            return date_obj.strftime('%Y-%m-%d')
        return date_obj.strftime('%Y-%m-%d')
    except (ValueError, AttributeError) as e:
        logger.warning(f"Failed to format date '{date_obj}': {e}")
        return None

def get_week_range(date_obj=None):
    """Get the start (Sunday) and end (Saturday) dates for a week.
    
    Args:
        date_obj: Optional date object. If None, uses current date.
        
    Returns:
        Tuple of (start_date, end_date) as datetime.date objects
        where start_date is Sunday and end_date is Saturday
    """
    if date_obj is None:
        date_obj = datetime.now().date()
    elif isinstance(date_obj, datetime):
        date_obj = date_obj.date()
    
    # Calculate days since Sunday (Sunday = 0, Monday = 1, ..., Saturday = 6)
    # Python's weekday(): Monday = 0, Sunday = 6
    # We want Sunday = 0, so we adjust
    days_since_sunday = (date_obj.weekday() + 1) % 7
    
    start_date = date_obj - timedelta(days=days_since_sunday)
    end_date = start_date + timedelta(days=6)
    
    logger.debug(f"Week range for {date_obj}: {start_date} to {end_date}")
    return (start_date, end_date)

def is_expense_in_week(expense_date, start_date, end_date):
    """Check if an expense date falls within a week range.
    
    Args:
        expense_date: Date string (YYYY-MM-DD) or datetime.date object
        start_date: Week start date (Sunday) as datetime.date
        end_date: Week end date (Saturday) as datetime.date
        
    Returns:
        Boolean indicating if expense is within the week range
    """
    if isinstance(expense_date, str):
        expense_date = parse_date(expense_date)
    
    if not expense_date:
        return False
    
    return start_date <= expense_date <= end_date

def get_day_from_date(date_obj):
    """Get the day number (0-6, Sunday-Saturday) from a date object.
    
    Args:
        date_obj: datetime.date or datetime.datetime object
        
    Returns:
        Integer 0-6 where 0=Sunday, 6=Saturday
    """
    if isinstance(date_obj, str):
        date_obj = parse_date(date_obj)
    if not date_obj:
        return 0
    # Python's weekday(): Monday = 0, Sunday = 6
    # We want Sunday = 0, so we adjust
    return (date_obj.weekday() + 1) % 7

def get_date_from_day(day_number, reference_date=None):
    """Get the date for a specific day number within a week.
    
    Args:
        day_number: Integer 0-6 where 0=Sunday, 6=Saturday
        reference_date: Optional reference date to determine the week. Defaults to current date.
        
    Returns:
        datetime.date object for the specified day in the week
    """
    start_date, _ = get_week_range(reference_date)
    return start_date + timedelta(days=day_number)

# --- Database Functions ---

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
        
        # Migration: Add date column if it doesn't exist
        cursor.execute("PRAGMA table_info(expenses)")
        columns = [column[1] for column in cursor.fetchall()]
        
        if 'date' not in columns:
            logger.info("Adding 'date' column to expenses table...")
            cursor.execute("ALTER TABLE expenses ADD COLUMN date TEXT")
            
            # Calculate current week's Sunday as reference point
            today = datetime.now()
            days_since_sunday = today.weekday() + 1 if today.weekday() != 6 else 0
            current_week_sunday = today - timedelta(days=days_since_sunday)
            
            logger.info(f"Migrating existing records using reference date: {current_week_sunday.date()}")
            
            # Update existing records with calculated dates
            cursor.execute("SELECT id, day FROM expenses WHERE date IS NULL")
            existing_records = cursor.fetchall()
            
            for record in existing_records:
                record_id = record[0]
                day_number = record[1]  # 0-6 for Sunday-Saturday
                record_date = current_week_sunday + timedelta(days=day_number)
                date_string = record_date.strftime('%Y-%m-%d')
                cursor.execute("UPDATE expenses SET date = ? WHERE id = ?", (date_string, record_id))
                logger.info(f"Updated record {record_id}: day {day_number} -> date {date_string}")
            
            logger.info(f"Migration complete. Updated {len(existing_records)} records.")
        
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

# --- Frontend Route ---
@app.route('/')
def index():
    """Serves the main HTML page"""
    return render_template('index.html')

# --- API Routes ---

@app.route('/api/data', methods=['GET'])
def get_data():
    """Get all initial data (settings + expenses).
    
    Query Parameters:
        start_date (optional): ISO date string for week start (Sunday)
        end_date (optional): ISO date string for week end (Saturday)
        
    If no dates provided, returns current week's expenses.
    """
    start_time = time.time()
    logger.info("Handling GET /api/data")
    
    # Parse query parameters for week filtering
    start_date_str = request.args.get('start_date')
    end_date_str = request.args.get('end_date')
    
    # Determine week range
    if start_date_str:
        start_date = parse_date(start_date_str)
        if not start_date:
            return jsonify({"error": f"Invalid start_date format: {start_date_str}. Use YYYY-MM-DD."}), 400
        
        if end_date_str:
            end_date = parse_date(end_date_str)
            if not end_date:
                return jsonify({"error": f"Invalid end_date format: {end_date_str}. Use YYYY-MM-DD."}), 400
        else:
            # Calculate end_date as start_date + 6 days
            end_date = start_date + timedelta(days=6)
    else:
        # Use current week
        start_date, end_date = get_week_range()
    
    logger.info(f"Filtering expenses for week: {start_date} to {end_date}")
    
    db = get_db()
    cursor = db.cursor()

    settings = cursor.execute("SELECT daily_max, house_goal, current_savings FROM settings").fetchone()
    
    # Fetch expenses filtered by date range
    expenses = cursor.execute(
        "SELECT id, desc, amount, who, day, category, date FROM expenses WHERE date >= ? AND date <= ?",
        (format_date(start_date), format_date(end_date))
    ).fetchall()

    duration = time.time() - start_time
    logger.info(f"Completed GET /api/data in {duration:.2f} seconds. Found {len(expenses)} expenses.")
    
    return jsonify({
        "settings": dict(settings) if settings else {},
        "expenses": [dict(expense) for expense in expenses],
        "week_range": {
            "start_date": format_date(start_date),
            "end_date": format_date(end_date)
        }
    })

@app.route('/api/expenses/by-week', methods=['GET'])
def get_expenses_by_week():
    """Get expenses filtered by week range.
    
    Query Parameters:
        start_date (optional): ISO date string for week start (Sunday). 
                              If not provided, uses current week.
        end_date (optional): ISO date string for week end (Saturday).
                            If not provided, calculates from start_date + 6 days.
    
    Returns:
        JSON object with expenses array and week_range metadata
    """
    start_time = time.time()
    logger.info("Handling GET /api/expenses/by-week")
    
    # Parse query parameters
    start_date_str = request.args.get('start_date')
    end_date_str = request.args.get('end_date')
    
    # Determine week range
    if start_date_str:
        start_date = parse_date(start_date_str)
        if not start_date:
            return jsonify({
                "error": f"Invalid start_date format: {start_date_str}. Use YYYY-MM-DD.",
                "expected_format": "YYYY-MM-DD"
            }), 400
        
        if end_date_str:
            end_date = parse_date(end_date_str)
            if not end_date:
                return jsonify({
                    "error": f"Invalid end_date format: {end_date_str}. Use YYYY-MM-DD.",
                    "expected_format": "YYYY-MM-DD"
                }), 400
        else:
            # Calculate end_date as start_date + 6 days
            end_date = start_date + timedelta(days=6)
    else:
        # Use current week
        start_date, end_date = get_week_range()
    
    logger.info(f"Week-based filter: {start_date} to {end_date}")
    
    db = get_db()
    cursor = db.cursor()
    
    # Fetch expenses filtered by date range
    expenses = cursor.execute(
        "SELECT id, desc, amount, who, day, category, date FROM expenses WHERE date >= ? AND date <= ? ORDER BY date ASC, id ASC",
        (format_date(start_date), format_date(end_date))
    ).fetchall()
    
    # Calculate totals
    total_amount = sum(expense['amount'] for expense in expenses)
    expenses_by_day = {}
    for expense in expenses:
        day = expense['day']
        if day not in expenses_by_day:
            expenses_by_day[day] = []
        expenses_by_day[day].append(dict(expense))
    
    duration = time.time() - start_time
    logger.info(f"Completed GET /api/expenses/by-week in {duration:.2f} seconds. Found {len(expenses)} expenses.")
    
    return jsonify({
        "expenses": [dict(expense) for expense in expenses],
        "week_range": {
            "start_date": format_date(start_date),
            "end_date": format_date(end_date)
        },
        "summary": {
            "total_expenses": len(expenses),
            "total_amount": round(total_amount, 2),
            "expenses_by_day": expenses_by_day
        }
    })

@app.route('/api/expenses', methods=['POST'])
def add_expense():
    """Add a new expense.
    
    Request Body:
        desc (required): Description of the expense
        amount (required): Amount of the expense
        who (required): Who made the expense
        day (required): Day number (0-6, Sunday-Saturday)
        category (optional): Category of the expense
        date (optional): ISO date string (YYYY-MM-DD). If not provided, 
                        calculates from day number using current week.
    
    Returns:
        JSON object with the created expense
    """
    start_time = time.time()
    logger.info("Handling POST /api/expenses")
    data = request.json
    
    # Validate required fields
    required_fields = ['desc', 'amount', 'who', 'day']
    missing_fields = [field for field in required_fields if field not in data or data[field] is None]
    if missing_fields:
        return jsonify({"error": f"Missing required fields: {', '.join(missing_fields)}"}), 400
    
    # Parse and validate date
    date_str = data.get('date')
    day_number = int(data.get('day'))
    
    if date_str:
        # Validate provided date
        parsed_date = parse_date(date_str)
        if not parsed_date:
            return jsonify({"error": f"Invalid date format: {date_str}. Use YYYY-MM-DD."}), 400
        expense_date = format_date(parsed_date)
        # Update day number to match the date
        day_number = get_day_from_date(parsed_date)
    else:
        # Calculate date from day number using current week
        expense_date = format_date(get_date_from_day(day_number))
    
    logger.info(f"Creating expense: day={day_number}, date={expense_date}")
    
    db = get_db()
    cursor = db.cursor()
    cursor.execute(
        "INSERT INTO expenses (desc, amount, who, day, category, date) VALUES (?, ?, ?, ?, ?, ?)",
        (data.get('desc'), float(data.get('amount')), data.get('who'), day_number, data.get('category', 'Pending'), expense_date)
    )
    db.commit()
    new_expense_id = cursor.lastrowid
    new_expense = cursor.execute(
        "SELECT id, desc, amount, who, day, category, date FROM expenses WHERE id = ?", 
        (new_expense_id,)
    ).fetchone()
    
    duration = time.time() - start_time
    logger.info(f"Completed POST /api/expenses in {duration:.2f} seconds. Created expense ID: {new_expense_id}")
    return jsonify(dict(new_expense)), 201

@app.route('/api/expenses/<int:expense_id>', methods=['PATCH'])
def update_expense(expense_id):
    """Update an existing expense.
    
    Request Body (all optional):
        desc: Description of the expense
        amount: Amount of the expense
        who: Who made the expense
        day: Day number (0-6, Sunday-Saturday)
        category: Category of the expense
        date: ISO date string (YYYY-MM-DD)
    
    Returns:
        JSON object with the updated expense
    """
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
    if 'date' in data:
        # Validate and parse date
        parsed_date = parse_date(data['date'])
        if not parsed_date:
            return jsonify({"error": f"Invalid date format: {data['date']}. Use YYYY-MM-DD."}), 400
        updates.append("date = ?")
        params.append(format_date(parsed_date))
        # Also update day number to match the date
        if 'day' not in data:
            updates.append("day = ?")
            params.append(get_day_from_date(parsed_date))

    if not updates:
        duration = time.time() - start_time
        logger.info(f"Completed PATCH /api/expenses/{expense_id} (no updates) in {duration:.2f} seconds")
        return jsonify({"error": "No fields provided for update"}), 400

    params.append(expense_id)
    
    cursor.execute(f"UPDATE expenses SET {', '.join(updates)} WHERE id = ?", tuple(params))
    db.commit()
    
    expense = cursor.execute(
        "SELECT id, desc, amount, who, day, category, date FROM expenses WHERE id = ?", 
        (expense_id,)
    ).fetchone()
    
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

@app.route('/api/week-info', methods=['GET'])
def get_week_info():
    """Get information about the current week or a specified week.
    
    Query Parameters:
        date (optional): ISO date string to get week info for. Defaults to current date.
    
    Returns:
        JSON object with week range and day information
    """
    start_time = time.time()
    logger.info("Handling GET /api/week-info")
    
    date_str = request.args.get('date')
    if date_str:
        date_obj = parse_date(date_str)
        if not date_obj:
            return jsonify({"error": f"Invalid date format: {date_str}. Use YYYY-MM-DD."}), 400
    else:
        date_obj = None
    
    start_date, end_date = get_week_range(date_obj)
    
    # Generate day information
    days = []
    day_names = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']
    for i in range(7):
        day_date = start_date + timedelta(days=i)
        days.append({
            "day_number": i,
            "day_name": day_names[i],
            "date": format_date(day_date)
        })
    
    duration = time.time() - start_time
    logger.info(f"Completed GET /api/week-info in {duration:.2f} seconds")
    
    return jsonify({
        "week_range": {
            "start_date": format_date(start_date),
            "end_date": format_date(end_date)
        },
        "days": days,
        "current_date": format_date(datetime.now().date())
    })

if __name__ == '__main__':
    app.run(debug=True, port=5000)