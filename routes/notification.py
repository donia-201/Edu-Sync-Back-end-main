from flask import Blueprint, request, jsonify
from firebase_admin import firestore
from datetime import datetime
from utils.firebase_config import db
from utils.auth import require_auth

notifications_bp = Blueprint('notifications', __name__, url_prefix='/api/notifications')


# ===================================
# GET all notifications
# ===================================
@notifications_bp.get("")
@require_auth
def get_notifications():
    """Get all notifications for the authenticated user"""
    try:
        user_id = request.user_data["user_id"]

        notifications_ref = db.collection("notifications")
        docs = notifications_ref.where("user_id", "==", user_id)\
            .order_by("created_at", direction=firestore.Query.DESCENDING)\
            .stream()

        notifications = []
        for doc in docs:
            data = doc.to_dict()
            data["id"] = doc.id
            notifications.append(data)

        return jsonify({
            "success": True,
            "notifications": notifications,
            "count": len(notifications)
        })

    except Exception as e:
        print(f"Get notifications error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"success": False, "msg": str(e)}), 500


# ===================================
# FIX: POST — Save notification (Pomodoro or Event)
# ===================================
@notifications_bp.post("")
@require_auth
def create_notification():
    """Save a new notification (called from frontend pomo.js or calendar)"""
    try:
        user_id = request.user_data["user_id"]
        data = request.get_json()

        if not data or not data.get("title") or not data.get("message"):
            return jsonify({"success": False, "msg": "title and message are required"}), 400

        now = datetime.utcnow().isoformat() + "Z"

        notif_data = {
            "user_id": user_id,
            "title": data.get("title"),
            "message": data.get("message"),
            "type": data.get("type", "general"),        # pomodoro | event | general
            "category": data.get("category", ""),       # focus | break
            "is_read": False,
            "created_at": data.get("created_at", now)
        }

        doc_ref = db.collection("notifications").add(notif_data)[1]
        notif_data["id"] = doc_ref.id

        print(f" Notification saved for user {user_id}: {notif_data['title']}")
        return jsonify({"success": True, "notification": notif_data}), 201

    except Exception as e:
        print(f"Create notification error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"success": False, "msg": str(e)}), 500


# ===================================
# PUT — Mark as read
# ===================================
@notifications_bp.put("/<notification_id>/read")
@require_auth
def mark_notification_read(notification_id):
    """Mark a notification as read"""
    try:
        user_id = request.user_data["user_id"]
        notif_ref = db.collection("notifications").document(notification_id)
        notif_doc = notif_ref.get()

        if not notif_doc.exists:
            return jsonify({"success": False, "msg": "Notification not found"}), 404

        # FIX: verify ownership before marking read
        notif_data = notif_doc.to_dict()
        if notif_data.get("user_id") != user_id:
            return jsonify({"success": False, "msg": "Unauthorized"}), 403

        notif_ref.update({"is_read": True})
        return jsonify({"success": True, "msg": "Notification marked as read"})

    except Exception as e:
        print(f"Mark notification read error: {e}")
        return jsonify({"success": False, "msg": str(e)}), 500


# ===================================
# FIX: DELETE — Delete a notification
# ===================================
@notifications_bp.delete("/<notification_id>")
@require_auth
def delete_notification(notification_id):
    """Delete a notification"""
    try:
        user_id = request.user_data["user_id"]
        notif_ref = db.collection("notifications").document(notification_id)
        notif_doc = notif_ref.get()

        if not notif_doc.exists:
            return jsonify({"success": False, "msg": "Notification not found"}), 404

        # Verify ownership
        notif_data = notif_doc.to_dict()
        if notif_data.get("user_id") != user_id:
            return jsonify({"success": False, "msg": "Unauthorized"}), 403

        notif_ref.delete()
        print(f" Notification {notification_id} deleted")
        return jsonify({"success": True, "msg": "Notification deleted successfully"})

    except Exception as e:
        print(f"Delete notification error: {e}")
        return jsonify({"success": False, "msg": str(e)}), 500


# ===================================
# FIX: process_event_reminders — now actually creates notifications correctly
# Called by scheduler (APScheduler or cron)
# ===================================
def process_event_reminders():
    """
    Check events whose remindAt time has passed and create a notification.
    Call this from a scheduler every minute.
    """
    try:
        now_dt = datetime.utcnow()
        now_iso = now_dt.isoformat() + "Z"

        events_ref = db.collection("events")

        # FIX: query events where reminder_sent is False and remindAt exists
        query = events_ref.where("reminder_sent", "==", False).stream()

        count = 0
        for doc in query.stream():
            event = doc.to_dict()
            remind_at = event.get("remindAt")

            if not remind_at:
                continue

            # Normalize remindAt to comparable datetime
            try:
                remind_dt = datetime.fromisoformat(remind_at.replace("Z", "+00:00")).replace(tzinfo=None)
            except Exception:
                continue

            if remind_dt <= now_dt:
                title_text = event.get("title", "Event")

                # Create notification in Firestore
                db.collection("notifications").add({
                    "user_id": event["user_id"],
                    "title": f" Reminder: {title_text}",
                    "message": f'Your event "{title_text}" is starting soon!',
                    "type": "event",
                    "is_read": False,
                    "created_at": now_iso
                })

                # Mark reminder as sent so it doesn't fire again
                events_ref.document(doc.id).update({"reminder_sent": True})
                count += 1
                print(f" Reminder sent for event: {title_text}")

        if count:
            print(f" Processed {count} event reminder(s)")

    except Exception as e:
        print(f" Process reminders error: {e}")
        import traceback
        traceback.print_exc()