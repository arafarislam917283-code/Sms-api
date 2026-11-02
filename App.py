from flask import Flask, request, jsonify
import os
import re
import time
import threading

app = Flask(__name__)

REQUIRED_FIELDS = ["datetime", "num", "cli", "sms"]

# হোস্টিংয়ের Variables-এ সেট করুন
WEBHOOK_TOKEN = os.environ.get("WEBHOOK_TOKEN")  # সাইট থেকে আসা ডেটা যাচাই (ঐচ্ছিক)
API_TOKEN = os.environ.get("API_TOKEN")          # viewstats দেখার টোকেন (আপনার নিজের)
EXPIRE_SECONDS = int(os.environ.get("EXPIRE_SECONDS", 600))  # না দেখলে ১০ মিনিট পর মুছে যাবে

pending = []          # শুধু মেমরিতে থাকবে
lock = threading.Lock()


def extract_otp(text):
    m = re.search(r"\b(\d{4,8})\b", text or "")
    return m.group(1) if m else None


def webhook_token_ok(data):
    if not WEBHOOK_TOKEN:
        return True
    candidates = [
        request.headers.get("Authorization", "").replace("Bearer ", ""),
        request.headers.get("X-Token", ""),
        request.headers.get("Token", ""),
        request.args.get("token", ""),
        str(data.get("token", "")),
    ]
    return WEBHOOK_TOKEN in candidates


def cleanup():
    now = time.time()
    pending[:] = [m for m in pending if now - m["_t"] < EXPIRE_SECONDS]


# ---------- সাইট এখানে POST করবে ----------
@app.route("/", methods=["GET", "POST"])
@app.route("/webhook", methods=["POST"])
def webhook():
    if request.method == "GET":
        return jsonify({"status": "running"}), 200

    data = request.get_json(silent=True, force=True)
    print("Received:", data, flush=True)

    if not isinstance(data, dict):
        return jsonify({"status": "error", "message": "Invalid JSON"}), 400
    if not webhook_token_ok(data):
        return jsonify({"status": "error", "message": "Invalid token"}), 401

    missing = [f for f in REQUIRED_FIELDS if f not in data]
    if missing:
        return jsonify({"status": "error",
                        "message": f"Missing fields: {', '.join(missing)}"}), 400

    with lock:
        cleanup()
        pending.append({
            "datetime": data["datetime"],
            "num": data["num"],
            "cli": data["cli"],
            "sms": data["sms"],
            "otp": extract_otp(data["sms"]),
            "_t": time.time(),
        })

    return jsonify({"status": "success",
                    "message": "Data received successfully"}), 200


# ---------- /crapi/st/viewstats?token=...&records=10 ----------
@app.route("/crapi/st/viewstats", methods=["GET"])
def viewstats():
    if API_TOKEN and request.args.get("token") != API_TOKEN:
        return jsonify({"status": "error", "message": "Invalid token"}), 401

    try:
        records = min(max(int(request.args.get("records", 10)), 1), 500)
    except ValueError:
        records = 10

    num = request.args.get("num")
    cli = request.args.get("cli")
    peek = request.args.get("peek") == "1"   # peek=1 দিলে দেখাবে কিন্তু মুছবে না

    with lock:
        cleanup()
        matched = [m for m in pending
                   if (not num or m["num"] == num) and (not cli or m["cli"] == cli)]
        selected = matched[:records]

        if not peek:
            ids = {id(m) for m in selected}
            pending[:] = [m for m in pending if id(m) not in ids]

    data = [{k: v for k, v in m.items() if k != "_t"} for m in selected]
    return jsonify({"status": "success", "total": len(data), "data": data})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
