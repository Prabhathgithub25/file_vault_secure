from flask import Flask, render_template, request, redirect, url_for, flash, session, send_file
import os, time, json
from werkzeug.utils import secure_filename
from cryptography.fernet import Fernet

app = Flask(__name__)
app.secret_key = 'supersecretkey'


@app.after_request
def disable_cache(response):
    if "text/html" in response.headers.get("Content-Type", ""):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    return response


# ================= GLOBAL WEBSITE LOCK =================
LOCK_FILE = "site_lock.json"
SECRET_CODE = "SECURE123"

def load_lock():
    if os.path.exists(LOCK_FILE):
        with open(LOCK_FILE, "r") as f:
            return json.load(f)
    return {"locked": False}

def save_lock(data):
    with open(LOCK_FILE, "w") as f:
        json.dump(data, f, indent=4)

# ================= ATTACK LOG =================
LOG_FILE = "attack_logs.json"

def load_logs():
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, "r") as f:
            return json.load(f)
    return []

def save_logs(data):
    with open(LOG_FILE, "w") as f:
        json.dump(data, f, indent=4)

# ================= WRONG ATTEMPTS =================
ATTEMPTS_FILE = "attempts.json"

def load_attempts():
    if os.path.exists(ATTEMPTS_FILE):
        with open(ATTEMPTS_FILE, "r") as f:
            return json.load(f)
    return {}

def save_attempts(data):
    with open(ATTEMPTS_FILE, "w") as f:
        json.dump(data, f, indent=4)

# ================= LOGIN SYSTEM =================
USERS_FILE = "users.json"

def load_users():
    if os.path.exists(USERS_FILE):
        with open(USERS_FILE, "r") as f:
            return json.load(f)
    return {}

def save_users(users):
    with open(USERS_FILE, "w") as f:
        json.dump(users, f, indent=4)

@app.before_request
def force_full_lock():

    lock = load_lock().get("locked")

    # allow only unlock page + static files
    allowed_routes = ["unlock_site", "static"]

    if lock:
        if request.endpoint not in allowed_routes:
            return redirect(url_for("unlock_site"))


@app.route("/")
def index():
    return redirect(url_for("login"))

@app.route("/login", methods=["GET", "POST"])
def login():
    users = load_users()
    if request.method == "POST":
        u = request.form["username"]
        p = request.form["password"]

        if u not in users:
            flash("Account not found!", "error")
        elif users[u] == p:
            session["user"] = u
            flash("Login successful!", "success")
            return redirect(url_for("home"))
        else:
            flash("Wrong password!", "error")
    return render_template("login.html")

@app.route("/signup", methods=["GET", "POST"])
def signup():
    users = load_users()
    if request.method == "POST":
        u = request.form["username"]
        p = request.form["password"]

        if u in users:
            flash("User exists!", "error")
        else:
            users[u] = p
            save_users(users)
            flash("Signup successful!", "success")
            return redirect(url_for("login"))
    return render_template("signup.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# ================= ENCRYPTION =================
BASE_UPLOAD_FOLDER = 'locked_files'
BASE_TEMP_FOLDER = 'temp_uploads'
BASE_DECRYPTED_FOLDER = 'decrypted_files'

os.makedirs(BASE_UPLOAD_FOLDER, exist_ok=True)
os.makedirs(BASE_TEMP_FOLDER, exist_ok=True)
os.makedirs(BASE_DECRYPTED_FOLDER, exist_ok=True)

KEY_FILE = 'secret.key'

def load_or_create_key():
    if os.path.exists(KEY_FILE):
        return open(KEY_FILE, 'rb').read()
    key = Fernet.generate_key()
    open(KEY_FILE, 'wb').write(key)
    return key

cipher = Fernet(load_or_create_key())

def generate_otp():
    return str(int(time.time()) % 1000000).zfill(6)

def encrypt_data(data: str) -> str:
    return cipher.encrypt(data.encode()).decode()

def decrypt_data(data: str) -> str:
    return cipher.decrypt(data.encode()).decode()

def get_user_locked_folder():
    f = os.path.join(BASE_UPLOAD_FOLDER, session["user"])
    os.makedirs(f, exist_ok=True)
    return f

def get_user_decrypted_folder():
    f = os.path.join(BASE_DECRYPTED_FOLDER, session["user"])
    os.makedirs(f, exist_ok=True)
    return f

# ================= ROUTES =================

@app.route("/home")
def home():
    if "user" not in session:
        return redirect(url_for("login"))
    session["current_otp"] = generate_otp()
    return render_template("home.html")

@app.route("/upload_temp", methods=["POST"])
def upload_temp():
    file = request.files.get("file")
    if file:
        path = os.path.join(BASE_TEMP_FOLDER, secure_filename(file.filename))
        file.save(path)
        session["temp_file"] = path
        flash("File uploaded. Lock now.", "success")
    return redirect(url_for("home"))

@app.route("/lock", methods=["POST"])
def lock():
    temp = session.get("temp_file")
    if not temp or not os.path.exists(temp):
        flash("No file uploaded.", "error")
        return redirect(url_for("home"))

    password = request.form["password"].strip()
    lat = request.form["latitude"][:2]
    lon = request.form["longitude"][:2]
    otp = session.get("current_otp")

    data = open(temp, "rb").read()
    meta = f"{password}|{lat}|{lon}|{otp}".encode()
    encrypted = cipher.encrypt(meta + b"::SEP::" + data)

    out = os.path.join(get_user_locked_folder(), os.path.basename(temp) + ".locked")
    open(out, "wb").write(encrypted)
    os.remove(temp)

    flash("File locked successfully.", "success")
    return redirect(url_for("open_locked"))

@app.route("/open_locked")
def open_locked():
    files = [f for f in os.listdir(get_user_locked_folder()) if f.endswith(".locked")]
    return render_template("open_locked.html", files=files)

@app.route('/decrypt_file', methods=['POST'])
def decrypt_file():
    filename = request.form['filename']
    password = request.form['password'].strip()
    lat = request.form['latitude'].strip()
    lon = request.form['longitude'].strip()

    try:
        file_path = os.path.join(get_user_locked_folder(), filename)
        if not os.path.exists(file_path):
            flash("File not found.", "error")
            return redirect(url_for('open_locked'))

        with open(file_path, 'rb') as f:
            encrypted_data = f.read()

        decrypted_data = cipher.decrypt(encrypted_data)
        metadata, file_binary = decrypted_data.split(b"::SEP::", 1)
        stored_password, stored_lat, stored_lon, stored_otp = metadata.decode().split("|")

        if password == stored_password and lat[:2] == stored_lat and lon[:2] == stored_lon:

            attempts = load_attempts()
            file_key = f"{session['user']}::{filename}"
            attempts[file_key] = 0
            save_attempts(attempts)

            session["current_otp"] = generate_otp()

            original_filename = filename.replace('.locked', '')
            decrypted_path = os.path.join(get_user_decrypted_folder(), original_filename)

            with open(decrypted_path, 'wb') as f:
                f.write(file_binary)

            flash(f"File decrypted successfully: {original_filename}", "success")
            return redirect(url_for('downloadfiles'))

        else:
            attempts = load_attempts()
            file_key = f"{session['user']}::{filename}"
            wrong_count = attempts.get(file_key, 0) + 1
            attempts[file_key] = wrong_count
            save_attempts(attempts)

            if wrong_count >= 5:
                logs = load_logs()
                logs.append({
                    "user": session.get("user"),
                    "file": filename,
                    "time": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "lat": lat,
                    "lon": lon,
                    "ip": request.remote_addr
                })
                save_logs(logs)

                save_lock({"locked": True})
                flash("SECURITY LOCKDOWN ACTIVATED", "error")
                return redirect(url_for('unlock_site'))

            flash(f"Invalid credentials. Attempts left: {5-wrong_count}", "error")
            return redirect(url_for('open_locked'))

    except Exception as e:
        print("[DECRYPT ERROR]", e)
        flash("Error decrypting file.", "error")
        return redirect(url_for('open_locked'))

@app.route("/downloadfiles")
def downloadfiles():
    files = os.listdir(get_user_decrypted_folder())
    return render_template("downloadfiles.html", files=files)

@app.route("/downloadfiles/<filename>")
def download_decrypted(filename):
    path = os.path.join(get_user_decrypted_folder(), filename)
    return send_file(path, as_attachment=True)

@app.route("/unlock_site", methods=["GET", "POST"])
def unlock_site():
    if request.method == "POST":
        if request.form.get("code") == SECRET_CODE:
            save_lock({"locked": False})
            flash("Website unlocked.", "success")
            return redirect(url_for("home"))
        else:
            flash("Wrong secret code.", "error")
    return render_template("unlock.html")

@app.route("/ip", methods=["GET", "POST"])
def ip_gate():
    client_ip = request.remote_addr
    if request.method == "POST":
        ip_input = request.form.get("ip_address")
        if ip_input == client_ip:
            session["access_granted"] = True
            flash("Access Granted!", "success")
            return redirect(url_for("latlon_vault"))
        else:
            flash("Access Denied", "error")
    return render_template("ip_gate.html", client_ip=client_ip)

@app.route("/latlon")
def latlon_vault():
    if not session.get("access_granted"):
        return redirect(url_for("ip_gate"))
    secret = "Welcome to the Latitude & Longitude Vault!"
    encrypted = encrypt_data(secret)
    decrypted = decrypt_data(encrypted)
    return render_template("latlon.html", secret=decrypted)

@app.route("/aboutus")
def aboutus():
    return render_template("aboutus.html")

# ================= RUN =================
if __name__ == "__main__":
    app.run(debug=True)
