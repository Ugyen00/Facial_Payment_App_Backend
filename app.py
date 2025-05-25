from flask import Flask, render_template, Response, request, redirect, jsonify
from flask_cors import CORS
import os
from datetime import datetime
from face_utils import VideoCamera
from face_utils import db
from shared_state import last_detected_user

app = Flask(__name__)
CORS(app)

os.makedirs('static/faces', exist_ok=True)

# Globals
camera = None
current_name = None
mode = None

@app.route('/')
def home():
    return jsonify({"message": "Flask backend for face recognition is running."})

@app.route('/register', methods=['POST'])
def register():
    global camera, current_name, mode
    current_name = request.form.get('name')
    cid = request.form.get('cid')
    dob = request.form.get('dob')
    password = request.form.get('password')
    phone = request.form.get('phone')

    if not all([current_name, cid, dob, phone, password]):
        return jsonify({"error": "All fields (name, cid, dob, phone, password) are required"}), 400

    mode = 'register'
    try:
        camera = VideoCamera(mode, current_name, cid, dob, phone, password)
        print(f"Camera initialized for registration: {current_name}")
        return jsonify({"status": "Camera started for registration."})
    except Exception as e:
        print(f"Error initializing camera for registration: {e}")
        return jsonify({"error": f"Failed to initialize camera: {str(e)}"}), 500

@app.route('/detect', methods=['GET'])
def detect():
    global camera, current_name, mode
    print("=== DETECT ROUTE CALLED ===")
    mode = 'detect'
    current_name = None
    
    try:
        camera = VideoCamera(mode)
        print(f"Camera initialized for detection. Mode: {mode}")
        print(f"Camera object: {camera}")
        return jsonify({"status": "Camera started for detection."})
    except Exception as e:
        print(f"ERROR initializing camera for detection: {e}")
        return jsonify({"error": f"Failed to initialize camera: {str(e)}"}), 500

@app.route('/video_feed')
def video_feed():
    global camera
    print(f"Video feed requested. Camera: {camera}")
    
    if not camera:
        print("ERROR: Camera not initialized for video feed")
        return jsonify({"error": "Camera not initialized"}), 400
    
    try:
        return Response(camera.get_frame_stream(),
                        mimetype='multipart/x-mixed-replace; boundary=frame')
    except Exception as e:
        print(f"ERROR in video feed: {e}")
        return jsonify({"error": f"Video feed error: {str(e)}"}), 500

@app.route('/user_detected', methods=['GET'])
def user_detected():
    global last_detected_user
    
    print(f"=== USER_DETECTED ROUTE CALLED ===")
    print(f"last_detected_user: {last_detected_user}")
    
    # Check if a user was detected
    if not last_detected_user:
        print("last_detected_user is None or empty")
        return jsonify({"message": "No user detected - last_detected_user is None"}), 404
    
    if not last_detected_user.get("userId"):
        print(f"No userId in last_detected_user: {last_detected_user}")
        return jsonify({"message": "No user detected - no userId"}), 404

    # Find user details from MongoDB using the detected user ID
    user_id = last_detected_user["userId"]
    print(f"Looking for user with ID: {user_id}")
    
    # Try different query methods based on how your detection stores the ID
    user = None
    
    # First try by name (if detection stores name)
    user = db.faces.find_one({"name": user_id})
    print(f"Query by name '{user_id}': {user}")
    
    # If not found, try by cid
    if not user:
        user = db.faces.find_one({"cid": user_id})
        print(f"Query by cid '{user_id}': {user}")
    
    # If still not found, try by phone
    if not user:
        user = db.faces.find_one({"phone": user_id})
        print(f"Query by phone '{user_id}': {user}")
    
    if not user:
        print(f"User not found in database with ID: {user_id}")
        # Let's also check what users exist in the database
        all_users = list(db.faces.find({}, {"name": 1, "cid": 1, "phone": 1}))
        print(f"All users in database: {all_users}")
        return jsonify({"message": "User not found in database", "searched_id": user_id, "available_users": all_users}), 404

    print(f"Found user: {user}")
    return jsonify({
        "userId": user.get("cid") or user.get("name"),
        "name": user.get("name"),
        "balance": float(user.get("balance", 0)),
        "phone": user.get("phone")
    })

def save_transaction(user_id, user_name, amount, order_items, payment_status="completed"):
    """Save transaction details to database"""
    try:
        # Calculate order summary
        subtotal = sum(item.get('price', 0) * item.get('quantity', 1) for item in order_items)
        tax = subtotal * 0.1
        discount = subtotal * 0.2
        total = subtotal + tax - discount
        
        transaction = {
            "transaction_id": f"TXN_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{user_id}",
            "user_id": user_id,
            "user_name": user_name,
            "timestamp": datetime.now(),
            "amount": float(amount),
            "payment_status": payment_status,
            "order_summary": {
                "items": order_items,
                "subtotal": float(subtotal),
                "tax": float(tax),
                "discount": float(discount),
                "total": float(total),
                "item_count": len(order_items),
                "total_quantity": sum(item.get('quantity', 1) for item in order_items)
            },
            "payment_method": "face_recognition_wallet"
        }
        
        # Insert into transactions collection
        result = db.transactions.insert_one(transaction)
        print(f"Transaction saved with ID: {result.inserted_id}")
        return True, str(result.inserted_id)
    except Exception as e:
        print(f"Error saving transaction: {e}")
        return False, str(e)

@app.route('/charge_user', methods=['POST'])
def charge_user():
    data = request.json
    user_id = data.get('userId')
    amount = data.get('amount')
    order_items = data.get('orderItems', [])  # Get order items from request

    print(f"=== CHARGE_USER CALLED ===")
    print(f"User ID: {user_id}, Amount: {amount}")
    print(f"Order Items: {order_items}")

    if not user_id or amount is None:
        return jsonify({"success": False, "message": "User ID and amount are required"}), 400

    try:
        amount = float(amount)
        if amount <= 0:
            return jsonify({"success": False, "message": "Amount must be positive"}), 400
    except (ValueError, TypeError):
        return jsonify({"success": False, "message": "Invalid amount"}), 400

    # Find user by different possible ID fields
    user = None
    
    # Try by cid first
    user = db.faces.find_one({"cid": user_id})
    
    # If not found, try by name
    if not user:
        user = db.faces.find_one({"name": user_id})
    
    # If still not found, try by phone
    if not user:
        user = db.faces.find_one({"phone": user_id})
    
    if not user:
        print(f"User not found for charging with ID: {user_id}")
        return jsonify({"success": False, "message": "User not found"}), 404

    current_balance = float(user.get("balance", 0))
    print(f"Current balance: {current_balance}, Required: {amount}")
    
    if amount > current_balance:
        # Save failed transaction
        save_transaction(user_id, user.get("name"), amount, order_items, "failed_insufficient_funds")
        return jsonify({
            "success": False, 
            "message": f"Insufficient funds. Current balance: ${current_balance:.2f}, Required: ${amount:.2f}"
        }), 400

    new_balance = current_balance - amount
    
    # Update using the same field that was found
    query_field = None
    if user.get("cid") == user_id:
        query_field = "cid"
    elif user.get("name") == user_id:
        query_field = "name"
    elif user.get("phone") == user_id:
        query_field = "phone"
    
    if query_field:
        result = db.faces.update_one(
            {query_field: user_id}, 
            {"$set": {"balance": new_balance}}
        )
        
        if result.modified_count > 0:
            # Save successful transaction
            transaction_saved, transaction_id = save_transaction(
                user_id, 
                user.get("name"), 
                amount, 
                order_items, 
                "completed"
            )
            
            print(f"Payment successful. New balance: {new_balance}")
            print(f"Transaction saved: {transaction_saved}, ID: {transaction_id}")
            
            return jsonify({
                "success": True, 
                "message": f"Payment successful. New balance: ${new_balance:.2f}",
                "new_balance": new_balance,
                "transaction_id": transaction_id,
                "transaction_saved": transaction_saved
            })
        else:
            # Save failed transaction
            save_transaction(user_id, user.get("name"), amount, order_items, "failed_update_error")
            return jsonify({"success": False, "message": "Failed to update balance"}), 500
    else:
        # Save failed transaction
        save_transaction(user_id, user.get("name"), amount, order_items, "failed_user_identification")
        return jsonify({"success": False, "message": "Could not identify user field"}), 500

@app.route('/login', methods=['POST'])
def login():
    data = request.json
    phone = data.get('phone')
    password = data.get('password')

    if not phone or not password:
        return jsonify({"success": False, "message": "Phone and password required"}), 400

    user = db.faces.find_one({"phone": phone})
    if not user:
        return jsonify({"success": False, "message": "Phone number not registered"}), 404

    if password != user.get('password'):
        return jsonify({"success": False, "message": "Incorrect password"}), 401

    return jsonify({
        "success": True, 
        "message": "Login successful", 
        "name": user["name"], 
        "profile_pic": user.get("image_url")
    })

@app.route('/add_fund', methods=['POST'])
def add_fund():
    data = request.json
    phone = data.get('phone')
    amount = data.get('amount')

    if not phone or amount is None:
        return jsonify({"success": False, "message": "Phone and amount required"}), 400

    try:
        amount = float(amount)
        if amount <= 0:
            raise ValueError
    except ValueError:
        return jsonify({"success": False, "message": "Invalid amount"}), 400

    user = db.faces.find_one({"phone": phone})
    if not user:
        return jsonify({"success": False, "message": "User not found"}), 404

    new_balance = float(user.get('balance', 0)) + amount
    db.faces.update_one({"phone": phone}, {"$set": {"balance": new_balance}})

    return jsonify({"success": True, "new_balance": new_balance})

@app.route('/wallet', methods=['GET'])
def get_wallet():
    phone = request.args.get('phone')
    if not phone:
        return jsonify({"success": False, "message": "Phone required"}), 400

    user = db.faces.find_one({"phone": phone})
    if not user:
        return jsonify({"success": False, "message": "User not found"}), 404

    return jsonify({
        "success": True,
        "balance": user.get("balance", 0),
        "name": user.get("name"),
        "phone": user.get("phone")
    })

@app.route('/transactions', methods=['GET'])
def get_transactions():
    """Get transaction history for a user"""
    user_id = request.args.get('user_id')
    phone = request.args.get('phone')
    limit = int(request.args.get('limit', 50))
    
    if not user_id and not phone:
        return jsonify({"success": False, "message": "User ID or phone required"}), 400
    
    try:
        # Build query
        query = {}
        if user_id:
            query["user_id"] = user_id
        elif phone:
            # Find user by phone first
            user = db.faces.find_one({"phone": phone})
            if not user:
                return jsonify({"success": False, "message": "User not found"}), 404
            query["user_id"] = user.get("cid") or user.get("name")
        
        # Get transactions
        transactions = list(db.transactions.find(query).sort("timestamp", -1).limit(limit))
        
        # Convert ObjectId to string for JSON serialization
        for transaction in transactions:
            transaction["_id"] = str(transaction["_id"])
            if isinstance(transaction.get("timestamp"), datetime):
                transaction["timestamp"] = transaction["timestamp"].isoformat()
        
        return jsonify({
            "success": True,
            "transactions": transactions,
            "count": len(transactions)
        })
    except Exception as e:
        print(f"Error fetching transactions: {e}")
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/transaction_summary', methods=['GET'])
def get_transaction_summary():
    """Get transaction summary statistics"""
    user_id = request.args.get('user_id')
    
    try:
        if user_id:
            # User-specific summary
            pipeline = [
                {"$match": {"user_id": user_id}},
                {"$group": {
                    "_id": None,
                    "total_transactions": {"$sum": 1},
                    "total_amount": {"$sum": "$amount"},
                    "successful_transactions": {
                        "$sum": {"$cond": [{"$eq": ["$payment_status", "completed"]}, 1, 0]}
                    },
                    "failed_transactions": {
                        "$sum": {"$cond": [{"$ne": ["$payment_status", "completed"]}, 1, 0]}
                    }
                }}
            ]
        else:
            # Overall summary
            pipeline = [
                {"$group": {
                    "_id": None,
                    "total_transactions": {"$sum": 1},
                    "total_amount": {"$sum": "$amount"},
                    "unique_users": {"$addToSet": "$user_id"},
                    "successful_transactions": {
                        "$sum": {"$cond": [{"$eq": ["$payment_status", "completed"]}, 1, 0]}
                    },
                    "failed_transactions": {
                        "$sum": {"$cond": [{"$ne": ["$payment_status", "completed"]}, 1, 0]}
                    }
                }},
                {"$addFields": {
                    "unique_user_count": {"$size": "$unique_users"}
                }},
                {"$project": {
                    "unique_users": 0  # Remove the actual user list from response
                }}
            ]
        
        result = list(db.transactions.aggregate(pipeline))
        
        if result:
            summary = result[0]
            summary.pop("_id", None)  # Remove MongoDB _id field
            return jsonify({"success": True, "summary": summary})
        else:
            return jsonify({"success": True, "summary": {
                "total_transactions": 0,
                "total_amount": 0,
                "successful_transactions": 0,
                "failed_transactions": 0
            }})
            
    except Exception as e:
        print(f"Error fetching transaction summary: {e}")
        return jsonify({"success": False, "message": str(e)}), 500

# Debug routes
@app.route('/debug_detection', methods=['GET'])
def debug_detection():
    global last_detected_user, camera, mode
    
    print("=== DEBUG DETECTION CALLED ===")
    print(f"last_detected_user: {last_detected_user}")
    print(f"camera: {camera}")
    print(f"mode: {mode}")
    
    return jsonify({
        "last_detected_user": last_detected_user,
        "has_userId": bool(last_detected_user.get("userId") if last_detected_user else False),
        "camera_exists": camera is not None,
        "current_mode": mode
    })

@app.route('/debug_database', methods=['GET'])
def debug_database():
    try:
        # Get all users from database
        users = list(db.faces.find({}, {"name": 1, "cid": 1, "phone": 1, "balance": 1}))
        transactions_count = db.transactions.count_documents({})
        
        return jsonify({
            "total_users": len(users),
            "users": users,
            "total_transactions": transactions_count
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))  # default to 5000 for local dev
    print("Starting Flask app with debug mode...")
    app.run(host='0.0.0.0', port=port, debug=True)