from flask import Blueprint, request, jsonify
from datetime import datetime
from werkzeug.security import check_password_hash, generate_password_hash
from utils.firebase_config import db, users_ref
from utils.auth import require_auth

setting_bp = Blueprint('setting', __name__)


# ===================================
# GET User Profile & Settings
# ===================================
@setting_bp.route("/api/user/profile", methods=["GET"])
@require_auth
def get_user_profile():
    """Get user profile and settings"""
    try:
        user_id = request.user_data["user_id"]

        user_doc = users_ref.document(user_id).get()
        if not user_doc.exists:
            return jsonify({"success": False, "msg": "User not found"}), 404

        user_data = user_doc.to_dict()

        # FIX: was using "name" only — now falls back to "username" correctly
        display_name = user_data.get("name") or user_data.get("username", "")

        profile_data = {
            "user_id": user_id,
            "name": display_name,
            "username": user_data.get("username", ""),
            "email": user_data.get("email", ""),
            "photo_url": user_data.get("photo_url", ""),
            "study_field": user_data.get("study_field", ""),
            "created_at": user_data.get("created_at", ""),
            "auth_provider": user_data.get("auth_provider", "email"),
            "settings": {
                "theme": user_data.get("theme", "light"),
                "language": user_data.get("language", "en"),
                "font_size": user_data.get("font_size", "medium"),
                "pomodoro_duration": user_data.get("pomodoro_duration", 25),
                "short_break": user_data.get("short_break", 5),
                "long_break": user_data.get("long_break", 15),
                "notifications_enabled": user_data.get("notifications_enabled", True),
                "sound_enabled": user_data.get("sound_enabled", True)
            },
            "google_calendar_connected": user_data.get("google_calendar_connected", False)
        }

        return jsonify({"success": True, "user": profile_data})

    except Exception as e:
        print(f" [SETTINGS] Get profile error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"success": False, "msg": str(e)}), 500


# ===================================
# GET Settings only (faster)
# ===================================
@setting_bp.route("/api/user/settings", methods=["GET"])
@require_auth
def get_user_settings():
    """Get only settings (faster than full profile)"""
    try:
        user_id = request.user_data["user_id"]
        user_doc = users_ref.document(user_id).get()

        if not user_doc.exists:
            return jsonify({"success": False, "msg": "User not found"}), 404

        user_data = user_doc.to_dict()

        settings = {
            "theme": user_data.get("theme", "light"),
            "language": user_data.get("language", "en"),
            "font_size": user_data.get("font_size", "medium"),
            "pomodoro_duration": user_data.get("pomodoro_duration", 25),
            "short_break": user_data.get("short_break", 5),
            "long_break": user_data.get("long_break", 15),
            "notifications_enabled": user_data.get("notifications_enabled", True),
            "sound_enabled": user_data.get("sound_enabled", True)
        }

        return jsonify({"success": True, "settings": settings})

    except Exception as e:
        print(f" [SETTINGS] Get settings error: {e}")
        return jsonify({"success": False, "msg": str(e)}), 500


# ===================================
# PUT Update Settings
# ===================================
@setting_bp.route("/api/user/settings", methods=["PUT"])
@require_auth
def update_user_settings():
    """Update user settings — applied site-wide via shared.js"""
    try:
        user_id = request.user_data["user_id"]
        data = request.get_json()

        update_data = {}

        if "theme" in data:
            if data["theme"] in ["light", "dark", "auto"]:
                update_data["theme"] = data["theme"]
            else:
                return jsonify({"success": False, "msg": "Invalid theme. Use: light, dark, or auto"}), 400

        if "language" in data:
            if data["language"] in ["en", "ar", "fr"]:
                update_data["language"] = data["language"]
            else:
                return jsonify({"success": False, "msg": "Invalid language. Use: en, ar, or fr"}), 400

        if "font_size" in data:
            if data["font_size"] in ["small", "medium", "large", "xlarge" ,"extra-large"]:
                update_data["font_size"] = data["font_size"]
            else:
                return jsonify({"success": False, "msg": "Invalid font_size. Use: small, medium, large, or xlarge"}), 400

        if "pomodoro_duration" in data:
            duration = int(data["pomodoro_duration"])
            if 1 <= duration <= 60:
                update_data["pomodoro_duration"] = duration
            else:
                return jsonify({"success": False, "msg": "Pomodoro duration must be 1–60 minutes"}), 400

        if "short_break" in data:
            val = int(data["short_break"])
            if 1 <= val <= 30:
                update_data["short_break"] = val
            else:
                return jsonify({"success": False, "msg": "Short break must be 1–30 minutes"}), 400

        if "long_break" in data:
            val = int(data["long_break"])
            if 1 <= val <= 60:
                update_data["long_break"] = val
            else:
                return jsonify({"success": False, "msg": "Long break must be 1–60 minutes"}), 400

        if "notifications_enabled" in data:
            update_data["notifications_enabled"] = bool(data["notifications_enabled"])

        if "sound_enabled" in data:
            update_data["sound_enabled"] = bool(data["sound_enabled"])

        update_data["settings_updated_at"] = datetime.utcnow().isoformat() + "Z"

        users_ref.document(user_id).update(update_data)
        print(f"✅ [SETTINGS] Updated for user {user_id}: {list(update_data.keys())}")

        return jsonify({
            "success": True,
            "msg": "Settings updated successfully",
            "updated_fields": list(update_data.keys())
        })

    except ValueError as e:
        return jsonify({"success": False, "msg": f"Invalid data format: {str(e)}"}), 400
    except Exception as e:
        print(f"❌ [SETTINGS] Update settings error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"success": False, "msg": str(e)}), 500


# ===================================
# PUT Update Profile (name / photo)
# ===================================
@setting_bp.route("/api/user/profile", methods=["PUT"])
@require_auth
def update_user_profile():
    """Update user profile name and photo"""
    try:
        user_id = request.user_data["user_id"]
        data = request.get_json()

        update_data = {}

        if "name" in data:
            name = data["name"].strip()
            if not name:
                return jsonify({"success": False, "msg": "Name cannot be empty"}), 400
            update_data["name"] = name
            # FIX: keep username in sync with name update
            update_data["username"] = name

        if "photo_url" in data:
            update_data["photo_url"] = data["photo_url"]

        update_data["profile_updated_at"] = datetime.utcnow().isoformat() + "Z"

        users_ref.document(user_id).update(update_data)
        print(f"✅ [SETTINGS] Profile updated for user {user_id}")

        return jsonify({"success": True, "msg": "Profile updated successfully"})

    except Exception as e:
        print(f"❌ [SETTINGS] Update profile error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"success": False, "msg": str(e)}), 500


# ===================================
# FIX: PUT Change Password (email users only)
# ===================================
@setting_bp.route("/api/user/change-password", methods=["PUT"])
@require_auth
def change_password():
    """Change password for email-registered users"""
    try:
        user_id = request.user_data["user_id"]
        data = request.get_json()

        current_password = data.get("current_password", "").strip()
        new_password = data.get("new_password", "").strip()

        if not current_password or not new_password:
            return jsonify({"success": False, "msg": "Both current and new password are required"}), 400

        if len(new_password) < 6:
            return jsonify({"success": False, "msg": "New password must be at least 6 characters"}), 400

        user_doc = users_ref.document(user_id).get()
        if not user_doc.exists:
            return jsonify({"success": False, "msg": "User not found"}), 404

        user_data = user_doc.to_dict()

        # Google users can't change password here
        if user_data.get("auth_provider") == "google":
            return jsonify({"success": False, "msg": "Google accounts cannot change password here"}), 400

        stored_hash = user_data.get("password")
        if not stored_hash or not check_password_hash(stored_hash, current_password):
            return jsonify({"success": False, "msg": "Current password is incorrect"}), 401

        new_hash = generate_password_hash(new_password)
        users_ref.document(user_id).update({
            "password": new_hash,
            "password_updated_at": datetime.utcnow().isoformat() + "Z"
        })

        print(f"✅ [SETTINGS] Password changed for user {user_id}")
        return jsonify({"success": True, "msg": "Password changed successfully"})

    except Exception as e:
        print(f" [SETTINGS] Change password error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"success": False, "msg": str(e)}), 500