from flask import Flask, render_template, request, redirect, url_for, flash, session, send_file
import os, time, json
from werkzeug.utils import secure_filename
from cryptography.fernet import Fernet

app = Flask(__name__)
app.secret_key = 'supersecretkey'

# ---------------- LOGIN SYSTEM ----------------

USERS_FILE = "users.json"

def load_users():
    if os.path.exists(USERS_FILE):
        with open(USERS_FILE, "r") as f:
            return json.load(f)
    return {}

def save_users(users):
    with open(USERS_FILE, "w") as f:
        json.dump(users, f, indent=4)

@app.route("/")
def index():
    return redirect(url_for("login"))

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        users = load_users()

        if username not in users:
            flash("❌ Account not found!", "error")
            return render_template("login.html")
        elif users[username] == password:
            session["user"] = username
            flash("✅ Login successful!", "success")
            return redirect(url_for("vault_home"))
        else:
            flash("❌ Wrong username or password!", "error")
            return render_template("login.html")

    return render_template("login.html")

@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        users = load_users()

        if username in users:
            flash("❌ User already exists!", "error")
            return render_template("signup.html")

        users[username] = password
        save_users(users)

        flash("✅ Account created successfully! Please log in.", "success")
        return redirect(url_for("login"))

    return render_template("signup.html")

@app.route("/home")
def home():
    if "user" in session:
        return render_template("home.html", user=session["user"])
    return redirect(url_for("login"))

@app.route("/logout")
def logout():
    session.pop("user", None)
    flash("✅ You have been logged out.", "info")
    return redirect(url_for("login"))

# ---------------- FILE ENCRYPTION SYSTEM ----------------

BASE_UPLOAD_FOLDER = 'locked_files'
BASE_TEMP_FOLDER = 'temp_uploads'
BASE_DECRYPTED_FOLDER = 'decrypted_files'

os.makedirs(BASE_UPLOAD_FOLDER, exist_ok=True)
os.makedirs(BASE_TEMP_FOLDER, exist_ok=True)
os.makedirs(BASE_DECRYPTED_FOLDER, exist_ok=True)

KEY_FILE = 'secret.key'

def load_or_create_key():
    if os.path.exists(KEY_FILE):
        with open(KEY_FILE, 'rb') as f:
            return f.read()
    else:
        new_key = Fernet.generate_key()
        with open(KEY_FILE, 'wb') as f:
            f.write(new_key)
        return new_key

key = load_or_create_key()
cipher = Fernet(key)

def encrypt_data(data):
    return cipher.encrypt(data.encode()).decode()

def decrypt_data(data):
    return cipher.decrypt(data.encode()).decode()

def generate_otp():
    return str(int(time.time()) % 1000000).zfill(6)

# -------- Per-user folders --------

def get_user_locked_folder():
    folder = os.path.join(BASE_UPLOAD_FOLDER, session["user"])
    os.makedirs(folder, exist_ok=True)
    return folder

def get_user_decrypted_folder():
    folder = os.path.join(BASE_DECRYPTED_FOLDER, session["user"])
    os.makedirs(folder, exist_ok=True)
    return folder

# -------- ROUTES -----------

@app.route('/vault_home')
def vault_home():
    if "user" not in session:
        return redirect(url_for("login"))
    otp_value = generate_otp()
    session['current_otp'] = otp_value
    return render_template('home.html')

@app.route('/upload_temp', methods=['POST'])
def upload_temp():
    file = request.files.get('file')
    if file:
        filename = secure_filename(file.filename)
        temp_path = os.path.join(BASE_TEMP_FOLDER, filename)
        file.save(temp_path)
        session['temp_file'] = temp_path
        flash("✅ File uploaded temporarily. Lock it now.", "success")
    else:
        flash("❌ No file selected.", "error")
    return redirect(url_for('vault_home'))

@app.route('/lock', methods=['POST'])
def lock():
    password = request.form['password']
    lat = request.form['latitude']
    lon = request.form['longitude']
    otp = session.get('current_otp')
    if not otp:
        flash("❌ OTP not available. Please generate OTP first.", "error")
        return redirect(url_for('vault_home'))

    temp_file = session.get('temp_file')
    if not temp_file or not os.path.exists(temp_file):
        flash("❌ No uploaded file to lock.", "error")
        return redirect(url_for('vault_home'))

    with open(temp_file, 'rb') as f:
        file_data = f.read()

    content_to_encrypt = file_data.decode(errors='ignore') + password + lat + lon + otp
    encrypted_data = encrypt_data(content_to_encrypt)

    locked_filename = os.path.basename(temp_file) + '.locked'
    locked_path = os.path.join(get_user_locked_folder(), locked_filename)
    with open(locked_path, 'w') as f:
        f.write(encrypted_data)

    os.remove(temp_file)
    session.pop('temp_file', None)

    flash(f"🔒 File locked and saved using OTP: {otp}", "success")
    return redirect(url_for('open_locked'))

@app.route("/latlon")
def latlon_vault():
    if not session.get("access_granted"):
        return redirect(url_for("ip_gate"))
    secret = "Welcome to the Latitude & Longitude Vault!"
    encrypted = encrypt_data(secret)
    decrypted = decrypt_data(encrypted)
    return render_template("latlon.html", secret=decrypted)

@app.route('/open_locked')
def open_locked():
    files = [f for f in os.listdir(get_user_locked_folder()) if f.endswith('.locked')]
    return render_template('open_locked.html', files=files)

@app.route('/decrypt_file', methods=['POST'])
def decrypt_file():
    filename = request.form['filename']
    password = request.form['password']
    lat = request.form['latitude']
    lon = request.form['longitude']
    otp = session.get('current_otp')
    if not otp:
        flash("❌ Current OTP missing. Please generate a new OTP before unlocking.", "error")
        return redirect(url_for('open_locked'))

    try:
        file_path = os.path.join(get_user_locked_folder(), filename)
        with open(file_path, 'r') as f:
            encrypted = f.read()

        decrypted = decrypt_data(encrypted)
        expected = password + lat + lon + otp

        if expected in decrypted:
            original_data = decrypted.replace(expected, '').encode('utf-8')
            original_filename = filename.replace('.locked', '')
            decrypted_path = os.path.join(get_user_decrypted_folder(), original_filename)

            with open(decrypted_path, 'wb') as f:
                f.write(original_data)

            flash(f"✅ File decrypted and saved: {original_filename}", "success")
            return redirect(url_for('downloadfiles'))
        else:
            flash("❌ Invalid credentials or OTP. File decryption failed.", "error")
            return redirect(url_for('open_locked'))

    except Exception as e:
        print(f"[ERROR] Decryption: {e}")
        flash("❌ Error decrypting the file.", "error")
        return redirect(url_for('open_locked'))

@app.route('/downloadfiles')
def downloadfiles():
    user_decrypted_folder = get_user_decrypted_folder()
    files = os.listdir(user_decrypted_folder)
    return render_template('downloadfiles.html', files=files)

@app.route('/downloadfiles/<filename>')
def download_decrypted(filename):
    path = os.path.join(get_user_decrypted_folder(), filename)
    if os.path.exists(path):
        return send_file(path, as_attachment=True)
    flash("❌ File not found.", "error")
    return redirect(url_for('downloadfiles'))

@app.route("/ip", methods=["GET", "POST"])
def ip_gate():
    client_ip = request.remote_addr
    if request.method == "POST":
        ip_input = request.form.get("ip_address")
        if ip_input == client_ip:
            session["access_granted"] = True
            flash("✅ Access Granted!", "success")
            return redirect(url_for("latlon_vault"))
        else:
            flash("❌ Access Denied", "error")
    return render_template("ip_gate.html", client_ip=client_ip)

if __name__ == "__main__":
    app.run(debug=True)
