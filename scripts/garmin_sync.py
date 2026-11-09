"""Pull recent Garmin Connect activities and publish them as an encrypted file.

Env: GARMIN_EMAIL, GARMIN_PASSWORD, SYNC_PASSPHRASE; optional DAYS (default 30),
GARMIN_TOKEN_DIR (default .garmin-tokens). The output is AES-256-GCM encrypted so
the public repo never exposes the activity data; Daybook decrypts it in the browser.
"""
import base64, json, os, sys
from datetime import date, datetime, timedelta, timezone

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from garminconnect import Garmin

OUT = "daybook/garmin-activities.enc.json"
ITER = 200000
b64 = lambda b: base64.b64encode(b).decode()
unb64 = lambda s: base64.b64decode(s)


def derive(pw, salt, iters):
    return PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=iters).derive(pw.encode())


def encrypt(pw, obj):
    salt, iv = os.urandom(16), os.urandom(12)
    ct = AESGCM(derive(pw, salt, ITER)).encrypt(iv, json.dumps(obj, separators=(",", ":")).encode(), None)
    return {"v": 1, "iter": ITER, "salt": b64(salt), "iv": b64(iv), "ct": b64(ct)}


def decrypt(pw, doc):
    key = derive(pw, unb64(doc["salt"]), doc.get("iter", ITER))
    return json.loads(AESGCM(key).decrypt(unb64(doc["iv"]), unb64(doc["ct"]), None))


def main():
    email, pw, phrase = (os.environ.get(k, "") for k in ("GARMIN_EMAIL", "GARMIN_PASSWORD", "SYNC_PASSPHRASE"))
    if not phrase or not ((email and pw) or os.path.isdir(os.environ.get("GARMIN_TOKEN_DIR", ".garmin-tokens"))):
        sys.exit("Missing secrets: need SYNC_PASSPHRASE plus GARMIN_EMAIL and GARMIN_PASSWORD.")
    tokens = os.environ.get("GARMIN_TOKEN_DIR", ".garmin-tokens")
    api = Garmin(email or None, pw or None)
    api.login(tokens)

    days = int(os.environ.get("DAYS", "30"))
    end = date.today()
    raw = api.get_activities_by_date((end - timedelta(days=days)).isoformat(), end.isoformat())

    acts = []
    for a in raw:
        start = str(a.get("startTimeLocal") or "")[:19]
        if len(start) < 19:
            continue
        tkey = (a.get("activityType") or {}).get("typeKey") or "activity"
        acts.append({
            "id": start,
            "name": (a.get("activityName") or tkey.replace("_", " ").title()).strip()[:60],
            "kcal": int(round(float(a.get("calories") or 0))),
            "min": int(round(float(a.get("duration") or 0) / 60)),
        })
    acts.sort(key=lambda x: x["id"])

    if os.path.exists(OUT):
        try:
            if decrypt(phrase, json.load(open(OUT))).get("activities") == acts:
                print("No change.")
                return
        except Exception:
            pass
    doc = encrypt(phrase, {"updated": datetime.now(timezone.utc).isoformat(timespec="seconds"), "activities": acts})
    json.dump(doc, open(OUT, "w"))
    print(f"Wrote {len(acts)} activities.")


if __name__ == "__main__":
    main()
