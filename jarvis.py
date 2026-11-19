#!/usr/bin/env python3
"""Jarvis για Android (Termux). Ελαφρύ, χωρίς εξαρτήσεις πέρα από Python + termux-api.

Χρήση:
  python jarvis.py          -> ακούει φωνή
  python jarvis.py --text   -> γράφεις τις εντολές (για δοκιμή)
"""
import json
import os
import subprocess
import sys
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

# ---------- Εφαρμογές: όνομα (χωρίς τόνους) -> πακέτο ----------
APPS = {
    "youtube": "com.google.android.youtube",
    "γιουτουμπ": "com.google.android.youtube",
    "whatsapp": "com.whatsapp",
    "ουατσαπ": "com.whatsapp",
    "chrome": "com.android.chrome",
    "κρομ": "com.android.chrome",
    "spotify": "com.spotify.music",
    "σποτιφαι": "com.spotify.music",
    "χαρτες": "com.google.android.apps.maps",
    "maps": "com.google.android.apps.maps",
    "viber": "com.viber.voip",
    "βαιμπερ": "com.viber.voip",
    "instagram": "com.instagram.android",
    "ινσταγκραμ": "com.instagram.android",
    "facebook": "com.facebook.katana",
    "φειςμπουκ": "com.facebook.katana",
    "messenger": "com.facebook.orca",
    "gmail": "com.google.android.gm",
    "τικτοκ": "com.zhiliaoapp.musically",
    "tiktok": "com.zhiliaoapp.musically",
    "netflix": "com.netflix.mediaclient",
}

SEARCH_WORDS = ("ψαξε", "αναζητησε", "βρες", "βαλε", "search")
ON_WORDS = ("ανοιξε", "ανοιγμα", "ενεργοποιησε", "αναψε", "on")
OFF_WORDS = ("κλεισε", "απενεργοποιησε", "σβησε", "off")


def norm(s: str) -> str:
    """Πεζά, χωρίς τόνους, ς -> σ."""
    s = unicodedata.normalize("NFD", s.lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.replace("ς", "σ").strip()


def run(cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=30).stdout
    except Exception as e:  # noqa
        return ""


def say(text):
    print("Jarvis:", text)
    run(["termux-tts-speak", "-l", "el", text[:700]])


def listen():
    out = run(["termux-speech-to-text"]).strip()
    return out


def open_url(url):
    run(["am", "start", "-a", "android.intent.action.VIEW", "-d", url])


def open_app(pkg):
    """Ανοίγει εφαρμογή. Δοκιμάζει πρώτα intent, μετά monkey."""
    try:
        r = subprocess.run(
            ["am", "start", "-a", "android.intent.action.MAIN",
             "-c", "android.intent.category.LAUNCHER", "-p", pkg],
            capture_output=True, text=True, timeout=20)
        out = (r.stdout + r.stderr).lower()
        if "error" not in out and "unable" not in out and "exception" not in out:
            return
    except Exception:
        pass
    run(["monkey", "-p", pkg, "-c", "android.intent.category.LAUNCHER", "1"])


def after_keyword(words, text):
    """Επιστρέφει ό,τι ακολουθεί την πρώτη λέξη-κλειδί αναζήτησης."""
    parts = text.split()
    for i, w in enumerate(parts):
        if w in words:
            return " ".join(parts[i + 1:]).strip()
    return ""


def strip_noise(q):
    for junk in ("στο youtube", "στο γιουτουμπ", "στο google", "στο γκουγκλ",
                 "youtube", "γιουτουμπ", "και"):
        q = q.replace(junk, " ")
    return " ".join(q.split())


# ---------- Gemini (καταλαβαίνει φυσική γλώσσα + απαντά σε ερωτήσεις) ----------
KEY_FILE = os.path.expanduser("~/.jarvis_key")
MODEL = os.environ.get("GEMINI_MODEL", "gemini-flash-latest")
HISTORY = []

SYSTEM = """Είσαι ο Τζάρβις, φωνητικός βοηθός στο κινητό Android. Απαντάς πάντα στα Ελληνικά, σύντομα και καθαρά, γιατί το κείμενο διαβάζεται φωναχτά. Σε ερωτήσεις γνώσης ή μαθημάτων (μαθηματικά, φυσική, ιστορία, κ.λπ.) εξήγησε σωστά και απλά. Επίστρεψε ΜΟΝΟ JSON σε μία από αυτές τις μορφές:
{"type":"answer","text":"..."}
{"type":"command","action":"open_app","arg":"όνομα εφαρμογής ή package"}
{"type":"command","action":"youtube_search","arg":"όρος αναζήτησης"}
{"type":"command","action":"google_search","arg":"όρος αναζήτησης"}
{"type":"command","action":"torch","arg":"on ή off"}
{"type":"command","action":"wifi","arg":"on ή off"}
{"type":"command","action":"settings","arg":""}
{"type":"command","action":"camera","arg":""}
Αν ο χρήστης ζητά κάτι που δεν μπορείς να κάνεις (π.χ. να πατήσεις like μέσα σε άλλη εφαρμογή), πες το ευγενικά ως answer."""


def get_key():
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if key:
        return key
    if os.path.exists(KEY_FILE):
        with open(KEY_FILE) as f:
            return f.read().strip()
    print("Βάλε το κλειδί Gemini API (αποθηκεύεται μόνο στο κινητό σου):")
    key = input("Κλειδί> ").strip()
    if key:
        with open(KEY_FILE, "w") as f:
            f.write(key)
        os.chmod(KEY_FILE, 0o600)
    return key


def ask_gemini(text):
    key = get_key()
    if not key:
        return None
    HISTORY.append({"role": "user", "parts": [{"text": text}]})
    recent = HISTORY[-8:]
    while recent and recent[0]["role"] != "user":
        recent = recent[1:]
    body = {
        "system_instruction": {"parts": [{"text": SYSTEM}]},
        "contents": recent,
        "generationConfig": {"responseMimeType": "application/json"},
    }
    url = ("https://generativelanguage.googleapis.com/v1beta/models/"
           + MODEL + ":generateContent")
    req = urllib.request.Request(
        url, data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "x-goog-api-key": key})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.load(r)
        raw = data["candidates"][0]["content"]["parts"][0]["text"]
    except urllib.error.HTTPError as e:
        HISTORY.pop()
        if e.code == 429:
            return {"type": "answer", "text": "Έφτασες το όριο του Gemini. Δοκίμασε σε λίγο."}
        return {"type": "answer", "text": "Πρόβλημα με το κλειδί ή το μοντέλο Gemini. "
                "Για να βάλεις νέο κλειδί, σβήσε το αρχείο: rm ~/.jarvis_key"}
    except Exception:
        HISTORY.pop()
        return {"type": "answer", "text": "Δεν έχω σύνδεση στο internet."}
    HISTORY.append({"role": "model", "parts": [{"text": raw}]})
    try:
        return json.loads(raw)
    except Exception:
        return {"type": "answer", "text": raw}


def execute(res: dict):
    if res.get("type") != "command":
        say(str(res.get("text", "")).strip() or "Δεν έχω απάντηση.")
        return
    action = res.get("action", "")
    arg = str(res.get("arg", "")).strip()
    if action == "open_app":
        a = norm(arg)
        pkg = next((p for n, p in APPS.items() if n in a or a in n), None)
        if pkg is None and "." in arg:
            pkg = arg
        if pkg:
            say(f"Ανοίγω {arg}")
            open_app(pkg)
        else:
            say(f"Δεν ξέρω την εφαρμογή {arg}.")
    elif action == "youtube_search":
        say(f"Ψάχνω στο YouTube: {arg}")
        open_url("https://www.youtube.com/results?search_query=" + urllib.parse.quote(arg))
    elif action == "google_search":
        say(f"Ψάχνω: {arg}")
        open_url("https://www.google.com/search?q=" + urllib.parse.quote(arg))
    elif action == "torch":
        on = arg.lower() != "off"
        run(["termux-torch", "on" if on else "off"])
        say("Άναψα τον φακό" if on else "Έσβησα τον φακό")
    elif action == "wifi":
        on = arg.lower() != "off"
        run(["termux-wifi-enable", "true" if on else "false"])
        say("Ενεργοποίησα το Wi-Fi" if on else "Απενεργοποίησα το Wi-Fi")
    elif action == "settings":
        say("Ανοίγω τις ρυθμίσεις")
        run(["am", "start", "-a", "android.settings.SETTINGS"])
    elif action == "camera":
        say("Ανοίγω την κάμερα")
        run(["am", "start", "-a", "android.media.action.STILL_IMAGE_CAMERA"])
    else:
        say("Δεν μπορώ να το κάνω αυτό ακόμα.")


def handle(raw: str) -> bool:
    """Εκτελεί την εντολή. Επιστρέφει False για έξοδο."""
    t = norm(raw)
    if not t:
        return True
    if any(w in t for w in ("εξοδος", "σταματα", "τελος", "γεια σου jarvis", "quit")):
        say("Εντάξει, τα λέμε.")
        return False

    # --- YouTube αναζήτηση ---
    if "youtube" in t or "γιουτουμπ" in t:
        q = strip_noise(after_keyword(SEARCH_WORDS, t))
        if q:
            say(f"Ψάχνω στο YouTube: {q}")
            open_url("https://www.youtube.com/results?search_query=" + urllib.parse.quote(q))
        else:
            say("Ανοίγω το YouTube")
            open_app(APPS["youtube"])
        return True

    # --- Φακός ---
    if "φακο" in t:
        if any(w in t for w in OFF_WORDS):
            run(["termux-torch", "off"]); say("Έσβησα τον φακό")
        else:
            run(["termux-torch", "on"]); say("Άναψα τον φακό")
        return True

    # --- Wi-Fi ---
    if "wifi" in t or "ουαιφαι" in t or "wi-fi" in t:
        on = not any(w in t for w in OFF_WORDS)
        run(["termux-wifi-enable", "true" if on else "false"])
        say("Ενεργοποίησα το Wi-Fi" if on else "Απενεργοποίησα το Wi-Fi")
        return True

    # --- Κάμερα / Ρυθμίσεις ---
    if "καμερα" in t:
        say("Ανοίγω την κάμερα")
        run(["am", "start", "-a", "android.media.action.STILL_IMAGE_CAMERA"])
        return True
    if "ρυθμισεις" in t:
        say("Ανοίγω τις ρυθμίσεις")
        run(["am", "start", "-a", "android.settings.SETTINGS"])
        return True

    # --- Άνοιγμα εφαρμογής ---
    if any(w in t for w in ("ανοιξε", "ανοιγμα", "ξεκινα")):
        for name, pkg in APPS.items():
            if name in t:
                say(f"Ανοίγω {name}")
                open_app(pkg)
                return True

    # --- Αναζήτηση Google, μόνο όταν το ζητάς ρητά ---
    if "google" in t or "γκουγκλ" in t:
        q = strip_noise(after_keyword(SEARCH_WORDS, t))
        if q:
            say(f"Ψάχνω: {q}")
            open_url("https://www.google.com/search?q=" + urllib.parse.quote(q))
            return True

    # --- Όλα τα άλλα: τα καταλαβαίνει και απαντά ο Gemini ---
    res = ask_gemini(raw)
    if res is None:
        say("Χρειάζομαι κλειδί Gemini για να σε καταλάβω.")
        return True
    execute(res)
    return True


def main():
    text_mode = "--text" in sys.argv
    say("Έτοιμος.")
    while True:
        if text_mode:
            raw = input("Εντολή> ")
        else:
            raw = listen()
            if raw:
                print("Άκουσα:", raw)
        if not handle(raw):
            break


if __name__ == "__main__":
    main()
