from flask import Blueprint, request, jsonify, redirect
from datetime import datetime, timedelta
from firebase_admin import firestore
from urllib.parse import urlencode
import requests
from config import (
    GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET,
    REDIRECT_URI_CALENDAR, CALENDAR_SCOPE, FRONTEND_ORIGIN
)
from utils.firebase_config import db, users_ref
from utils.auth import require_auth
from utils.calendar import get_calendar_service, convert_to_google_calendar_format

calendar_bp = Blueprint('calendar', __name__)

def validate_iso_datetime(date_str):
    if not date_str:
        return None
    try:
        dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
        iso_str = dt.isoformat()
        if '+00:00' in iso_str:
            iso_str = iso_str.replace('+00:00', 'Z')
        return iso_str
    except (ValueError, AttributeError):
        try:
            dt = datetime.strptime(date_str, '%Y-%m-%d')
            return dt.isoformat() + 'Z'
        except (ValueError, AttributeError):
            return None

# ===================================
# Google Calendar OAuth
# ===================================
@calendar_bp.get("/connect-google-calendar")
@require_auth
def connect_google_calendar():
    try:
        user_id = request.user_data["user_id"]
        params = {
            "client_id": GOOGLE_CLIENT_ID,
            "redirect_uri": REDIRECT_URI_CALENDAR,
            "response_type": "code",
            "scope": CALENDAR_SCOPE,
            "access_type": "offline",
            "prompt": "consent",
            "state": user_id
        }
        auth_url = "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params)
        return redirect(auth_url)
    except Exception as e:
        return jsonify({"success": False, "msg": str(e)}), 500

@calendar_bp.get("/google-calendar-callback")
def google_calendar_callback():
    try:
        code    = request.args.get("code")
        user_id = request.args.get("state")
        if not code or not user_id:
            return redirect(f"{FRONTEND_ORIGIN}/?error=calendar_auth_failed")

        r = requests.post("https://oauth2.googleapis.com/token", data={
            "code": code, "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "redirect_uri": REDIRECT_URI_CALENDAR, "grant_type": "authorization_code"
        })
        if not r.ok:
            return redirect(f"{FRONTEND_ORIGIN}/?error=calendar_token_failed")

        refresh_token = r.json().get("refresh_token")
        if not refresh_token:
            return redirect(f"{FRONTEND_ORIGIN}/?error=no_refresh_token")

        users_ref.document(user_id).update({
            "google_calendar_refresh_token": refresh_token,
            "google_calendar_connected": True
        })
        return redirect(f"{FRONTEND_ORIGIN}/pages/home.html?calendar=connected")
    except Exception as e:
        return redirect(f"{FRONTEND_ORIGIN}/?error=calendar_auth_failed")

@calendar_bp.get("/disconnect-google-calendar")
@require_auth
def disconnect_google_calendar():
    try:
        user_id = request.user_data["user_id"]
        users_ref.document(user_id).update({
            "google_calendar_refresh_token": firestore.DELETE_FIELD,
            "google_calendar_connected": False
        })
        return jsonify({"success": True, "msg": "Calendar disconnected"})
    except Exception as e:
        return jsonify({"success": False, "msg": str(e)}), 500

@calendar_bp.get("/calendar-status")
@require_auth
def calendar_status():
    try:
        user_id  = request.user_data["user_id"]
        user_doc = users_ref.document(user_id).get()
        if not user_doc.exists:
            return jsonify({"success": False, "msg": "User not found"}), 404
        is_connected = user_doc.to_dict().get("google_calendar_connected", False)
        return jsonify({"success": True, "connected": is_connected})
    except Exception as e:
        return jsonify({"success": False, "msg": str(e)}), 500

# ===================================
# POST — Add Event
# ===================================
@calendar_bp.route("/api/calendar/events", methods=["POST"])
@require_auth
def add_calendar_event():
    try:
        user_id = request.user_data["user_id"]
        data    = request.get_json()

        title     = data.get("title", "").strip()
        start_raw = data.get("start")
        end_raw   = data.get("end")

        if not title:
            return jsonify({"success": False, "msg": "Title is required"}), 400
        if not start_raw:
            return jsonify({"success": False, "msg": "Start time is required"}), 400
        if not end_raw:
            return jsonify({"success": False, "msg": "End time is required"}), 400

        start = validate_iso_datetime(start_raw)
        end   = validate_iso_datetime(end_raw)

        if not start:
            return jsonify({"success": False, "msg": f"Invalid start datetime: {start_raw}"}), 400
        if not end:
            return jsonify({"success": False, "msg": f"Invalid end datetime: {end_raw}"}), 400

        try:
            start_dt = datetime.fromisoformat(start.replace('Z', '+00:00'))
            end_dt   = datetime.fromisoformat(end.replace('Z', '+00:00'))
            if end_dt <= start_dt:
                return jsonify({"success": False, "msg": "End time must be after start time"}), 400
        except Exception:
            return jsonify({"success": False, "msg": "Invalid date format"}), 400

        description = data.get("description", "")
        reminder    = data.get("reminder")
        remind_at   = data.get("remindAt")
        if remind_at:
            remind_at = validate_iso_datetime(remind_at)

        now_iso = datetime.utcnow().isoformat() + "Z"

        event_data = {
            "user_id":        user_id,
            "title":          title,
            "start":          start,
            "end":            end,
            "description":    description,
            "reminder":       reminder if reminder else {},
            "remindAt":       remind_at,
            "created_at":     now_iso,
            "updated_at":     now_iso,
            "synced_to_google": False,
            # FIX: reminder_sent must be False so process_event_reminders picks it up
            "reminder_sent":  False
        }

        events_ref = db.collection("events")
        doc_ref    = events_ref.add(event_data)[1]
        event_id   = doc_ref.id
        event_data["id"] = event_id

        print(f"✅ [CALENDAR] Event saved: {event_id} - {title} | remindAt: {remind_at}")

        # Try Google Calendar sync
        user_doc = users_ref.document(user_id).get()
        if user_doc.exists:
            refresh_token = user_doc.to_dict().get("google_calendar_refresh_token")
            if refresh_token:
                try:
                    service      = get_calendar_service(refresh_token)
                    g_event_body = convert_to_google_calendar_format(event_data)
                    g_event      = service.events().insert(calendarId='primary', body=g_event_body).execute()
                    google_id    = g_event.get("id")
                    events_ref.document(event_id).update({
                        "google_event_id": google_id,
                        "synced_to_google": True
                    })
                    event_data["google_event_id"]  = google_id
                    event_data["synced_to_google"] = True
                    print(f"✅ [CALENDAR] Synced to Google: {google_id}")
                except Exception as e:
                    print(f"⚠️ [CALENDAR] Google sync failed: {e}")

        return jsonify({"success": True, "event": event_data, "msg": "Event created successfully"}), 201

    except Exception as e:
        print(f"❌ [CALENDAR] Create error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"success": False, "msg": f"Server error: {str(e)}"}), 500

# ===================================
# GET — All Events
# ===================================
@calendar_bp.route("/api/calendar/events", methods=["GET"])
@require_auth
def get_calendar_events():
    try:
        user_id = request.user_data["user_id"]

        docs   = db.collection("events").where("user_id", "==", user_id).stream()
        events = []
        for doc in docs:
            d = doc.to_dict()
            d["id"] = doc.id
            events.append(d)
        events.sort(key=lambda x: x.get("start", ""))

        # Merge Google Calendar events
        user_doc = users_ref.document(user_id).get()
        if user_doc.exists:
            refresh_token = user_doc.to_dict().get("google_calendar_refresh_token")
            if refresh_token:
                try:
                    service = get_calendar_service(refresh_token)
                    now     = datetime.utcnow().isoformat() + 'Z'
                    future  = (datetime.utcnow() + timedelta(days=30)).isoformat() + 'Z'
                    g_events = service.events().list(
                        calendarId='primary', timeMin=now, timeMax=future,
                        singleEvents=True, orderBy='startTime'
                    ).execute().get('items', [])

                    for g in g_events:
                        gid = g.get('id')
                        if not any(e.get('google_event_id') == gid for e in events):
                            start = g['start'].get('dateTime', g['start'].get('date'))
                            end   = g['end'].get('dateTime',   g['end'].get('date'))
                            events.append({
                                "id": f"google_{gid}", "title": g.get('summary', 'No Title'),
                                "start": start, "end": end,
                                "description": g.get('description', ''),
                                "reminder": {}, "synced_to_google": True,
                                "google_event_id": gid, "source": "google_calendar",
                                "reminder_sent": True  # Google events don't need our reminders
                            })
                except Exception as e:
                    print(f" [CALENDAR] Google fetch failed: {e}")

        return jsonify({"success": True, "events": events, "count": len(events)})

    except Exception as e:
        print(f" [CALENDAR] Get events error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"success": False, "msg": str(e)}), 500