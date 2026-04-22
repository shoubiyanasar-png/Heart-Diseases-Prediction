# ==============================
# CLEAN & CORRECT WORKING app.py
# ==============================

import os
import io
import base64
import sqlite3
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import joblib
from flask import Flask, render_template, request, redirect, url_for, flash, session, g
from werkzeug.security import generate_password_hash, check_password_hash
from twilio.rest import Client
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import smtplib
import re


import config   # your config.py

# ==========================================================
# PATH SETTINGS
# ==========================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DB_FOLDER = os.path.join(BASE_DIR, "data")
DB_PATH = os.path.join(DB_FOLDER, "heart_app.db")
MODEL_PATH = os.path.join(BASE_DIR, "model.pkl")

if not os.path.exists(DB_FOLDER):
    os.makedirs(DB_FOLDER)


# Flask init
app = Flask(__name__)
app.secret_key = config.FLASK_SECRET


# ==========================================================
# DATABASE FUNCTIONS
# ==========================================================
def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db

def close_db(e=None):
    db = g.pop('db', None)
    if db is not None:
        db.close()

app.teardown_appcontext(close_db)


@app.cli.command("init-db")
def init_db():
    """Creates the database tables."""
    conn = get_db()
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        age INTEGER,
        gender TEXT,
        email TEXT UNIQUE,
        mobile TEXT,
        password TEXT
    )''')
    print("Table 'users' check/creation command executed.")

    c.execute('''CREATE TABLE IF NOT EXISTS predictions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_email TEXT,
        patient_name TEXT,
        prob_no REAL,
        prob_yes REAL,
        result TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    print("Table 'predictions' check/creation command executed.")

    conn.commit()
    print("Database changes committed.")
    conn.close()
    print("Database connection closed.")

# ==========================================================
# MODEL LOAD
# ==========================================================
model = None
if os.path.exists(MODEL_PATH):
    model = joblib.load(MODEL_PATH)
    print("✔ Model Loaded")
else:
    print("❌ model.pkl NOT FOUND")


# ==========================================================
# EMAIL FUNCTION
# ==========================================================
def send_email(to_email, subject, body):
    try:
        msg = MIMEMultipart()
        msg['From'] = config.EMAIL_SENDER
        msg['To'] = to_email
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'plain'))

        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login(config.EMAIL_SENDER, config.EMAIL_APP_PASSWORD)
        server.send_message(msg)
        server.quit()
        return True

    except Exception as e:
        print("Email Error:", e)
        return False


# ==========================================================
# WHATSAPP ALERT
# ==========================================================
def send_whatsapp_alert(phone, text):
    try:
        client = Client(config.TWILIO_ACCOUNT_SID, config.TWILIO_AUTH_TOKEN)

        phone = phone.replace(" ", "").replace("+", "")
        to_whatsapp = f"whatsapp:+{phone}"

        msg = client.messages.create(
            from_=config.TWILIO_WHATSAPP_FROM,
            body=text,
            to=to_whatsapp
        )
        print("✔ WhatsApp Sent:", msg.sid)
        return True

    except Exception as e:
        print("WhatsApp Error:", e)
        return False


# ==========================================================
# CHART FUNCTION
# ==========================================================
def prob_chart(prob_no, prob_yes, result):
    plt.figure(figsize=(10, 3))

    labels = ["Low Risk", "High Risk"]
    values = [prob_no, prob_yes]

    colors = ['blue', 'red']

    plt.bar(labels, values, color=colors)
    plt.ylim(0, 101)

    for i, v in enumerate(values):
        plt.text(i, v + 0.02, f"{v:.2f}%", ha='center')

    buf = io.BytesIO()
    plt.savefig(buf, format='png')
    plt.close()
    buf.seek(0)

    return base64.b64encode(buf.read()).decode('utf-8')


# ==========================================================
# ROUTES
# ==========================================================
@app.route('/')
@app.route('/home')
def home():
    return render_template('home.html')


# LOGIN
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']

        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT * FROM users WHERE email=?", (email,))
        user = c.fetchone()

        if user and check_password_hash(user['password'], password):
            session['user'] = user['email']
            return redirect(url_for('predict'))

        flash("Invalid Login", "danger")

    return render_template('login.html')


# REGISTER
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form['name']
        age = request.form['age']
        gender = request.form['gender']
        email = request.form['email']
        mobile = request.form['mobile']
        pwd = generate_password_hash(request.form['password'])

        # MOBILE NUMBER VALIDATION
        if not re.fullmatch(r'[6-9]\d{9}', mobile):
            flash("Enter a valid 10–digit Indian mobile number", "danger")
            return redirect(url_for('register'))

        conn = get_db()
        c = conn.cursor()

        try:
            c.execute("INSERT INTO users(name, age, gender, email, mobile, password) VALUES(?,?,?,?,?,?)",
                      (name, age, gender, email, mobile, pwd))
            conn.commit()
            flash("Account created!", "success")
            return redirect(url_for('login'))

        except sqlite3.IntegrityError:
            flash("Email already exists!", "danger")
            return redirect(url_for('register'))

    return render_template('register.html')

# PREDICT
@app.route('/predict', methods=['GET', 'POST'])
def predict():
    if 'user' not in session:
        return redirect(url_for('login'))

    if request.method == 'POST':
            try:
                # Get user info from DB
                conn = get_db()
                c = conn.cursor()
                c.execute("SELECT * FROM users WHERE email=?", (session['user'],))
                user = c.fetchone()
                if not user:
                    flash("User not found.", "danger")
                    return redirect(url_for('login'))
                
                patient_name = user['name']
                mobile = user['mobile']
    
                # Load scaler
                scaler = joblib.load("scaler.pkl")
    
                # Get form input
                data = [
                    float(request.form['age']),
                    float(request.form['sex']),
                    float(request.form['cp']),
                    float(request.form['trestbps']),
                    float(request.form['chol']),
                    float(request.form['fbs']),
                    float(request.form['restecg']),
                    float(request.form['thalach']),
                    float(request.form['exang']),
                    float(request.form['oldpeak']),
                    float(request.form['slope']),
                    float(request.form['ca']),
                    float(request.form['thal'])
                ]
    
                # Convert to 2D list
                final_input = scaler.transform([data])
    
                # Predict
                prediction_probabilities = model.predict_proba(final_input)
                output = model.predict(final_input)[0]
    
                # Corrected logic: model's 0 is High Risk, 1 is Low Risk
                result = "High Risk" if output == 0 else "Low Risk"
                
                prob_yes = round(prediction_probabilities[0][0] * 100, 2)  # Probability of High Risk (class 0)
                prob_no = round(prediction_probabilities[0][1] * 100, 2)   # Probability of Low Risk (class 1)
    
                # Chart
                chart = prob_chart(prob_no, prob_yes, result)
                # ALERT MSG
                message = f"Heart Risk Report for {patient_name}: {result}. Probability = {prob_yes:.2f}%"
    
                send_email(config.HOSPITAL_EMAIL, "Heart Disease Alert", message)
    
                if result == "High Risk":
                    send_whatsapp_alert(mobile, message)
                    send_whatsapp_alert(config.HOSPITAL_MOBILE, message)
                
                # Store prediction in DB
                conn = get_db()
                c = conn.cursor()
                c.execute("INSERT INTO predictions(user_email, patient_name, prob_no, prob_yes, result) VALUES(?,?,?,?,?)",
                          (session['user'], patient_name, prob_no, prob_yes, result))
                conn.commit()
    
                return render_template(
                    "result.html",
                    patient_name=patient_name,
                    prob_yes=prob_yes,
                    prob_no=prob_no,
                    result=result,
                    chart=chart,
                    high=prob_yes,
                    low=prob_no
                )
            except Exception as e:
                flash(f"An error occurred: {e}", "danger")
                return redirect(url_for('predict'))
    return render_template('predict.html')

# ---------- Advice route (Doctor Advice Page) ----------
@app.route('/advice')
def advice():
    # require login
    if 'user' not in session:
        return redirect(url_for('login'))

    # fetch last prediction for this logged-in user
    conn = get_db()
    c = conn.cursor()
    c.execute("""
        SELECT patient_name, prob_no, prob_yes, result, created_at
        FROM predictions
        WHERE user_email = ?
        ORDER BY created_at DESC
        LIMIT 1
    """, (session['user'],))
    last = c.fetchone()

    if not last:
        flash("No prediction found. Please run a prediction first.", "warning")
        return redirect(url_for('predict'))

    # ===========================
    # LOW RISK - SHOW 3 IMAGES
    # ===========================
    if last['result'] == "Low Risk":
        banner_color = "success"

        tips = [
            "Maintain a healthy balanced diet.",
            "Continue 30 minutes walking daily.",
            "Drink enough water and avoid stress."
        ]

        foods = [
            "Fruits, vegetables, whole grains",
            "Low-oil foods, high-fibre meals",
            "Plenty of water"                                                 
        ]

        activities = [
            "Daily walking / light jogging",
            "Meditation / breathing exercises",
            "Regular hydration"
        ]

        # Your available images
        images = {
            "diet": url_for('static', filename='images/low_diet.jpg'),
            "walk": url_for('static', filename='images/stress_free.jpg'),
            "healthy_heart": url_for('static', filename='images/water.jpg')
        }

    # ===========================
    # HIGH RISK - SHOW DIFFERENT IMAGES
    # ===========================
    else:
        banner_color = "danger"

        tips = [
            "Consult your doctor immediately.",
            "Avoid heavy physical activity.",
            "Reduce salt, oil, and sugar intake.",
            "Monitor BP and symptoms regularly."
        ]

        foods = [
            "Low sodium diet",
            "Avoid oily and fried food",
            "More vegetables and light meals"
        ]

        activities = [
            "Light walking only if doctor allows",
            "No heavy workouts",
            "Daily stress management"
        ]

        # Your existing high-risk images
        images = {
            "diet": url_for('static', filename='images/diet_plate.png'),
            "walk": url_for('static', filename='images/walk.png'),
            "healthy_heart": url_for('static', filename='images/healthy_heart.png')
        }

    return render_template(
        'advice.html',
        patient_name=last['patient_name'],
        result=last['result'],
        prob_yes=last['prob_yes'],
        prob_no=last['prob_no'],
        created_at=last['created_at'],
        advice_title="Doctor Health Recommendation",
        tips=tips,
        foods=foods,
        activities=activities,
        banner_color=banner_color,
        images=images
    )

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# ==========================================================
# SERVER START
# ==========================================================
if __name__ == '__main__':
    app.run(debug=True)  