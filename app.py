from flask import Flask, jsonify, request, make_response
from flask_cors import CORS
import os

os.environ["TZ"] = "Africa/Cairo"
import time
time.tzset()

from config import FRONTEND_ORIGIN, PORT
from utils.firebase_config import initialize_firebase
initialize_firebase()

app = Flask(__name__)
CORS(app, resources={
    r"/*": {
        "origins": [FRONTEND_ORIGIN, "https://edu-sync-gold.vercel.app", "http://localhost:5000", "http://127.0.0.1:5000"],
        "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        "allow_headers": ["Content-Type", "Authorization"],
        "supports_credentials": True,
        "max_age": 3600
    }
})

# Register Blueprints
from routes.auth_routes import auth_bp
from routes.notes import notes_bp
from routes.events import events_bp
from routes.calendar import calendar_bp
from routes.notification import notifications_bp
from routes.youtube import youtube_bp
from routes.setting import setting_bp

app.register_blueprint(auth_bp)
app.register_blueprint(notes_bp)
app.register_blueprint(events_bp)
app.register_blueprint(calendar_bp)
app.register_blueprint(notifications_bp)
app.register_blueprint(youtube_bp)
app.register_blueprint(setting_bp)

# =============================================
# FIX: APScheduler — runs process_event_reminders every minute
# This is what actually sends event reminder notifications
# =============================================
from apscheduler.schedulers.background import BackgroundScheduler
from routes.notification import process_event_reminders

scheduler = BackgroundScheduler()
scheduler.add_job(
    func=process_event_reminders,
    trigger="interval",
    minutes=1,
    id="event_reminders",
    replace_existing=True
)
scheduler.start()
print("✅ Scheduler started — checking event reminders every minute")

import atexit
atexit.register(lambda: scheduler.shutdown())

# Root route
@app.get("/")
def home():
    return jsonify({
        "status": "online",
        "message": "EduSync Backend API is running! 🚀",
        "version": "2.0",
        "scheduler": "running",
        "endpoints": {
            "auth": ["/signup", "/login", "/logout", "/verify-session", "/google-callback"],
            "notes": ["/api/notes"],
            "events": ["/api/events", "/connect-google-calendar", "/calendar-status"],
            "notifications": ["/api/notifications"],
            "youtube": ["/youtube-search"]
        }
    })

@app.get("/health")
def health_check():
    return jsonify({
        "status": "healthy",
        "scheduler": scheduler.running,
        "timestamp": "2025-12-16"
    })

@app.errorhandler(404)
def not_found(error):
    return jsonify({"success": False, "msg": "Endpoint not found"}), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify({"success": False, "msg": "Internal server error"}), 500

if __name__ == "__main__":
    print("=" * 50)
    print("🚀 Starting EduSync Backend Server")
    print(f"📡 PORT: {PORT}")
    print(f"🌐 Frontend Origin: {FRONTEND_ORIGIN}")
    print("=" * 50)
    app.run(host="0.0.0.0", port=PORT, debug=False)