import os
import io
import csv
import json
import re
import random
import smtplib
import pymysql
import uuid
import logging
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from openai import OpenAI
from dotenv import load_dotenv

# Configure Logging (Prints full errors to your terminal, hides them from users)
logging.basicConfig(level=logging.ERROR, format='%(asctime)s - %(levelname)s - %(message)s')

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'fallback_dev_secret_key')

# --- CONFIGURATION ---
SENDER_EMAIL = os.environ.get('SENDER_EMAIL')
SENDER_PASSWORD = os.environ.get('SENDER_PASSWORD')
GROQ_API_KEY = os.environ.get('GROQ_API_KEY')
# --------------------

UPLOAD_FOLDER = 'uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

def get_db_connection():
    return pymysql.connect(
        host=os.environ.get('DB_HOST', 'localhost'),
        user=os.environ.get('DB_USER', 'root'),
        password=os.environ.get('DB_PASSWORD', ''),
        database=os.environ.get('DB_NAME', 'quiz'),
        cursorclass=pymysql.cursors.DictCursor,
        charset='utf8'
    )

def send_otp_email(email, name, otp):
    try:
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(SENDER_EMAIL, SENDER_PASSWORD)
        subject = "Your Quiz Portal Verification Code"
        body = f"Hello {name},\n\nYour verification code is: {otp}"
        message = f"Subject: {subject}\n\n{body}"
        server.sendmail(SENDER_EMAIL, email, message)
        server.quit()
        return True
    except Exception as e:
        logging.error(f"Failed to send OTP email to {email}: {e}")
        return False

# ---------------- CUSTOM ERROR HANDLERS ----------------

@app.errorhandler(404)
def not_found_error(error):
    return render_template('error.html', error_code=404, message="The page you are looking for does not exist."), 404

@app.errorhandler(500)
def internal_error(error):
    logging.error(f"Internal Server Error: {error}", exc_info=True)
    return render_template('error.html', error_code=500, message="An internal server error occurred. Please try again later."), 500

@app.errorhandler(Exception)
def unhandled_exception(error):
    logging.error(f"Unhandled Exception: {error}", exc_info=True)
    return render_template('error.html', error_code=500, message="An unexpected error occurred. Our team has been notified."), 500

# ---------------- HOME & AUTH ----------------

@app.route('/')
def home():
    if 'user_id' in session:
        return render_template('index.html', logged_in=True, username=session['username'], is_admin=session.get('is_admin'))
    return render_template('index.html', logged_in=False)

@app.route('/check_username', methods=['POST'])
def check_username():
    data = request.get_json()
    username = data.get('username', '').strip()
    if not username: return jsonify({"exists": False})
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM users WHERE username = %s", (username,))
        user = cursor.fetchone()
        conn.close()
        return jsonify({"exists": bool(user)})
    except Exception as e:
        logging.error(f"DB Error in check_username: {e}")
        return jsonify({"error": "Service unavailable"}), 500

# --- ADMIN LOGIN (is_admin = 1) ---
@app.route('/admin_login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users WHERE username = %s", (username,))
            user = cursor.fetchone()
            conn.close()
            
            if user and check_password_hash(user['password'], password) and int(user['is_admin']) == 1:
                session['user_id'] = user['id']
                session['username'] = user['username']
                session['is_admin'] = 1
                return redirect(url_for('admin_portal'))
            else:
                return render_template('admin_login.html', error="Invalid Admin credentials.")
        except Exception as e:
            logging.error(f"Admin login error: {e}")
            return render_template('admin_login.html', error="Service temporarily unavailable. Please try again.")
            
    return render_template('admin_login.html')

# --- TEACHER & STUDENT LOGIN ---
@app.route('/login', methods=['GET', 'POST'])
def login():
    intended_role = int(request.args.get('role', 0))
    
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        intended_role = int(request.form.get('intended_role', 0))
        
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users WHERE username = %s", (username,))
            user = cursor.fetchone()
            conn.close()
        except Exception as e:
            logging.error(f"Login DB error: {e}")
            return render_template('login.html', error="Service temporarily unavailable.", intended_role=intended_role)
        
        if user and check_password_hash(user['password'], password):
            user_role = int(user['is_admin'])
            
            if user_role == 1:
                return render_template('login.html', error="Admins must use the Admin Portal.", intended_role=intended_role)
            
            if user_role != intended_role:
                role_name = "Teacher" if intended_role == 2 else "Student"
                return render_template('login.html', error=f"Access Denied: This account is not a {role_name}.", intended_role=intended_role)
            
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['is_admin'] = user_role
            
            if user_role == 2:
                return redirect(url_for('teacher_portal'))
            else:
                return redirect(url_for('home'))
        else:
            return render_template('login.html', error="Invalid username or password!", intended_role=intended_role)
            
    return render_template('login.html', intended_role=intended_role)

# --- STUDENT REGISTRATION ---
@app.route('/register/student', methods=['GET', 'POST'])
def register_student():
    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email']
        username = request.form['username']
        password = request.form['password']
        roll_no = request.form.get('roll_no', '').upper()
        hashed_password = generate_password_hash(password)
        
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM enrolled_students WHERE roll_no = %s", (roll_no,))
            enrolled = cursor.fetchone()
            
            if not enrolled:
                conn.close()
                return render_template('register.html', error="Access Denied: Registration Number not in college roster.")
                
            if enrolled['is_used'] == 1:
                conn.close()
                return render_template('register.html', error="This Registration Number is already used.")
            
            if enrolled['student_name'].strip().lower() != name.strip().lower():
                conn.close()
                return render_template('register.html', error="Authentication Failed: The Name does not match the official roster.")
                
            if enrolled['email'].strip().lower() != email.strip().lower():
                conn.close()
                return render_template('register.html', error="Authentication Failed: The Email does not match the official roster.")
            
            cursor.execute("SELECT * FROM users WHERE username = %s OR email = %s", (username, email))
            if cursor.fetchone():
                conn.close()
                return render_template('register.html', error="Username or Email already exists in the portal. Please login.")
            
            otp = str(random.randint(100000, 999999))
            session['temp_user_data'] = {
                'name': name, 'email': email, 'username': username, 
                'password': hashed_password, 'otp': otp, 'is_admin': 0, 'roll_no': roll_no
            }
            conn.close()
            
            if send_otp_email(email, name, otp):
                return redirect(url_for('verify_otp'))
            else:
                return render_template('register.html', error="Could not send OTP email. Check email address.")
        except Exception as e:
            logging.error(f"Student registration error: {e}")
            return render_template('register.html', error="An error occurred during registration. Please try again.")
            
    return render_template('register.html')

# --- TEACHER REGISTRATION (Via Magic Link) ---
@app.route('/register/teacher', methods=['GET', 'POST'])
def register_teacher():
    if request.method == 'POST':
        name = request.form['name']
        username = request.form['username']
        password = request.form['password']
        hashed_password = generate_password_hash(password)
        token = request.form.get('token')
        email = request.form.get('email')
        
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM invites WHERE token = %s AND email = %s AND expires_at > NOW()", (token, email))
            invite = cursor.fetchone()
            
            if not invite:
                conn.close()
                return render_template('register.html', error="Invalid or expired invite link.")
                
            cursor.execute("SELECT id FROM users WHERE username = %s", (username,))
            if cursor.fetchone():
                conn.close()
                return render_template('register.html', error="Username already taken.")
                
            cursor.execute("INSERT INTO users (name, email, username, password, is_admin) VALUES (%s, %s, %s, %s, 2)", (name, email, username, hashed_password))
            cursor.execute("DELETE FROM invites WHERE token = %s", (token,))
            conn.commit()
            conn.close()
            
            return redirect(url_for('login', role='2'))
        except Exception as e:
            logging.error(f"Teacher registration error: {e}")
            return render_template('register.html', error="An error occurred during registration. Please try again.")
        
    token = request.args.get('token')
    if not token:
        return render_template('register.html', error="You need a valid invite link from the Admin to register as a teacher.")
        
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT email FROM invites WHERE token = %s AND expires_at > NOW()", (token,))
        invite = cursor.fetchone()
        conn.close()
    except Exception as e:
        logging.error(f"Token validation error: {e}")
        return render_template('register.html', error="Service temporarily unavailable.")
    
    if not invite:
        return render_template('register.html', error="This invite link is invalid or has expired.")
        
    return render_template('register.html', token=token, email=invite['email'])

@app.route('/verify_otp', methods=['GET', 'POST'])
def verify_otp():
    if 'temp_user_data' not in session:
        return redirect(url_for('home'))
        
    if request.method == 'POST':
        entered_otp = request.form['otp']
        temp_data = session['temp_user_data']
        
        if entered_otp == temp_data['otp']:
            try:
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute("INSERT INTO users (name, email, username, password, is_admin) VALUES (%s, %s, %s, %s, %s)", 
                               (temp_data['name'], temp_data['email'], temp_data['username'], temp_data['password'], temp_data['is_admin']))
                if temp_data['is_admin'] == 0 and 'roll_no' in temp_data:
                    cursor.execute("UPDATE enrolled_students SET is_used = 1 WHERE roll_no = %s", (temp_data['roll_no'],))
                conn.commit()
                conn.close()
            except Exception as e:
                logging.error(f"OTP Verify DB Error: {e}")
                return render_template('verify_otp.html', error="Database error. Please contact support.")
                
            session.pop('temp_user_data', None)
            return redirect(url_for('login', role='0'))
        else:
            return render_template('verify_otp.html', error="Invalid OTP. Please try again.")
            
    return render_template('verify_otp.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('home'))

# ---------------- STUDENT AREA ----------------

@app.route('/profile')
def profile():
    if 'user_id' not in session or session.get('is_admin') != 0:
        return redirect(url_for('login', role='0'))
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE id = %s", (session['user_id'],))
        user_details = cursor.fetchone()
        cursor.execute("SELECT category, score, cheated FROM results WHERE username = %s ORDER BY id DESC", (session['username'],))
        history = cursor.fetchall()
        conn.close()
        return render_template('profile.html', user=user_details, history=history)
    except Exception as e:
        logging.error(f"Profile error: {e}")
        return render_template('error.html', error_code=500, message="Could not load profile data."), 500

@app.route('/quiz_select')
def quiz_select():
    if 'user_id' not in session or session.get('is_admin') != 0:
        return redirect(url_for('login', role='0'))
    return render_template('quiz_select.html', username=session['username'])

@app.route('/take_quiz/<category>')
def take_quiz(category):
    if 'user_id' not in session or session.get('is_admin') != 0:
        return redirect(url_for('login', role='0'))
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM questions WHERE category = %s ORDER BY RAND() LIMIT 10", (category,))
        questions = cursor.fetchall()
        conn.close()
        questions_json = json.dumps(questions)
        return render_template('take_quiz.html', category=category, questions=questions_json, username=session['username'])
    except Exception as e:
        logging.error(f"Take quiz error: {e}")
        return render_template('error.html', error_code=500, message="Could not load quiz questions."), 500

@app.route('/submit_quiz', methods=['POST'])
def submit_quiz():
    if 'user_id' not in session or session.get('is_admin') != 0:
        return redirect(url_for('login', role='0'))
        
    category = request.form['category']
    answers = json.loads(request.form['answers'])
    tab_switches = int(request.form['tab_switches'])
    username = session['username']
    is_cheated = 1 if tab_switches > 2 else 0
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT negative_mark FROM categories WHERE category_name = %s", (category,))
        cat_data = cursor.fetchone()
        neg_mark = cat_data['negative_mark'] if cat_data else 0
        
        score = 0.0
        correct_count = 0
        wrong_count = 0
        
        for q_id, user_ans in answers.items():
            cursor.execute("SELECT answer FROM questions WHERE id = %s", (q_id,))
            q_data = cursor.fetchone()
            if q_data:
                if user_ans == q_data['answer']:
                    score += 1.0
                    correct_count += 1
                else:
                    score -= float(neg_mark)
                    wrong_count += 1
                    
        raw_score = round(score, 2)
        final_score = max(0, raw_score)
            
        cursor.execute("SELECT score, cheated FROM results WHERE username = %s AND category = %s", (username, category))
        existing = cursor.fetchone()
        
        if existing:
            new_cheat_count = (existing['cheated'] or 0) + is_cheated
            if is_cheated == 1:
                if final_score > existing['score']:
                    cursor.execute("UPDATE results SET score = %s, cheated = %s WHERE username = %s AND category = %s", (final_score, new_cheat_count, username, category))
                else:
                    cursor.execute("UPDATE results SET cheated = %s WHERE username = %s AND category = %s", (new_cheat_count, username, category))
            elif final_score > existing['score']:
                cursor.execute("UPDATE results SET score = %s WHERE username = %s AND category = %s", (final_score, username, category))
        else:
            cursor.execute("INSERT INTO results (username, category, score, cheated) VALUES (%s, %s, %s, %s)", (username, category, final_score, is_cheated))
            
        conn.commit()
        conn.close()
        
        return render_template('result.html', final_score=final_score, raw_score=raw_score, correct=correct_count, wrong=wrong_count, category=category, neg_mark=float(neg_mark), cheated=(tab_switches > 2), username=username)
    except Exception as e:
        logging.error(f"Submit quiz error: {e}")
        return render_template('error.html', error_code=500, message="Could not submit quiz. Please contact support."), 500

# ---------------- LEADERBOARD ----------------

@app.route('/all_leaderboards')
def all_leaderboards():
    if 'user_id' not in session:
        return redirect(url_for('login', role='0'))
    return render_template('all_leaderboards.html', username=session['username'])

@app.route('/leaderboard/<category>')
def leaderboard(category):
    if 'user_id' not in session:
        return redirect(url_for('login', role='0'))
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT username, score, cheated FROM results WHERE category = %s ORDER BY score DESC LIMIT 10", (category,))
        results = cursor.fetchall()
        conn.close()
        return render_template('leaderboard.html', category=category, results=results, username=session['username'])
    except Exception as e:
        logging.error(f"Leaderboard error: {e}")
        return render_template('error.html', error_code=500, message="Could not load leaderboard."), 500

# ---------------- ADMIN PORTAL ----------------

@app.route('/admin_portal')
def admin_portal():
    if 'user_id' not in session or session.get('is_admin') != 1:
        return redirect(url_for('admin_login'))
        
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) as count FROM users WHERE is_admin = 2")
        teachers_count = cursor.fetchone()['count']
        cursor.execute("SELECT COUNT(*) as count FROM users WHERE is_admin = 0")
        students_count = cursor.fetchone()['count']
        cursor.execute("SELECT COUNT(*) as count FROM questions")
        questions_count = cursor.fetchone()['count']
        cursor.execute("SELECT * FROM categories ORDER BY category_name ASC")
        categories = cursor.fetchall()
        conn.close()
        return render_template('admin_portal.html', username=session['username'], teachers_count=teachers_count, students_count=students_count, questions_count=questions_count, categories=categories)
    except Exception as e:
        logging.error(f"Admin portal error: {e}")
        return render_template('error.html', error_code=500, message="Could not load admin dashboard."), 500

@app.route('/admin_add_category', methods=['POST'])
def admin_add_category():
    if 'user_id' not in session or session.get('is_admin') != 1:
        return redirect(url_for('admin_login'))
    try:
        category_name = request.form.get('category_name', '').strip()
        negative_mark = request.form.get('negative_mark', 0.0)
        if not category_name:
            flash("Error: Category name is required.")
            return redirect(url_for('admin_portal'))
        try:
            neg_mark_float = float(negative_mark)
        except ValueError:
            neg_mark_float = 0.0
            
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM categories WHERE category_name = %s", (category_name,))
        if cursor.fetchone():
            flash(f"Error: Category '{category_name}' already exists.")
        else:
            cursor.execute("INSERT INTO categories (category_name, negative_mark) VALUES (%s, %s)", (category_name, neg_mark_float))
            conn.commit()
            flash(f"Success! Category '{category_name}' added.")
        conn.close()
    except Exception as e:
        logging.error(f"Add category error: {e}")
        flash("An error occurred while adding the category.")
    return redirect(url_for('admin_portal'))

@app.route('/admin_add_student', methods=['POST'])
def admin_add_student():
    if 'user_id' not in session or session.get('is_admin') != 1:
        return redirect(url_for('admin_login'))
    try:
        roll_no = request.form.get('roll_no', '').upper()
        student_name = request.form.get('student_name', '')
        email = request.form.get('email', '')
        if not roll_no or not student_name or not email:
            flash("Error: Roll Number, Name, and Email are all required.")
            return redirect(url_for('admin_portal'))
            
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT roll_no FROM enrolled_students WHERE roll_no = %s", (roll_no,))
        if cursor.fetchone():
            flash(f"Error: Roll No {roll_no} is already in the roster.")
        else:
            cursor.execute("INSERT INTO enrolled_students (roll_no, student_name, email, is_used) VALUES (%s, %s, %s, 0)", (roll_no, student_name, email))
            conn.commit()
            flash(f"Success! {student_name} ({roll_no}) added to the roster.")
        conn.close()
    except Exception as e:
        logging.error(f"Add student error: {e}")
        flash("An error occurred while adding the student.")
    return redirect(url_for('admin_portal'))

@app.route('/upload_roster', methods=['POST'])
def upload_roster():
    if 'user_id' not in session or session.get('is_admin') != 1:
        return redirect(url_for('admin_login'))
    if 'roster_file' not in request.files:
        flash("No file selected.")
        return redirect(url_for('admin_portal'))
    file = request.files['roster_file']
    if file.filename == '':
        flash("No file selected.")
        return redirect(url_for('admin_portal'))
    try:
        stream = io.StringIO(file.stream.read().decode("UTF8"), newline=None)
        csv_input = csv.reader(stream)
        conn = get_db_connection()
        cursor = conn.cursor()
        inserted_count = 0
        for row in csv_input:
            if len(row) >= 3 and row[0].strip():
                roll_no = row[0].strip().upper()
                name = row[1].strip()
                email = row[2].strip().lower()
                cursor.execute("INSERT IGNORE INTO enrolled_students (roll_no, student_name, email, is_used) VALUES (%s, %s, %s, 0)", (roll_no, name, email))
                inserted_count += 1
        conn.commit()
        conn.close()
        flash(f"Success! {inserted_count} student records have been whitelisted.")
    except Exception as e:
        logging.error(f"Roster upload error: {e}")
        flash("An error occurred while reading the file. Ensure it is a valid CSV.")
    return redirect(url_for('admin_portal'))

@app.route('/admin_generate_invite', methods=['POST'])
def admin_generate_invite():
    if 'user_id' not in session or session.get('is_admin') != 1:
        return redirect(url_for('admin_login'))
    try:
        email = request.form['email']
        token = str(uuid.uuid4())
        expires_at = datetime.now() + timedelta(hours=24)
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO invites (email, token, expires_at) VALUES (%s, %s, %s)", (email, token, expires_at))
        conn.commit()
        conn.close()
        
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(SENDER_EMAIL, SENDER_PASSWORD)
        subject = "Invitation to Register as a Teacher - Online Quiz Portal"
        link = f"http://127.0.0.1:5000/register/teacher?token={token}"
        body = f"You have been invited to register as a Teacher.\n\nClick the link below to complete your registration. This link will expire in 24 hours.\n\n{link}"
        message = f"Subject: {subject}\n\n{body}"
        server.sendmail(SENDER_EMAIL, email, message)
        server.quit()
        flash(f"Success! Magic invite link sent to {email}.")
    except Exception as e:
        logging.error(f"Invite generation error: {e}")
        flash("Failed to send invite email. Check your SMTP settings or email address.")
    return redirect(url_for('admin_portal'))

# ---------------- TEACHER PORTAL ----------------

@app.route('/teacher_portal')
def teacher_portal():
    if 'user_id' not in session or session.get('is_admin') != 2:
        return redirect(url_for('login', role='2'))
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM categories")
        categories = cursor.fetchall()
        cursor.execute("SELECT * FROM questions ORDER BY id DESC LIMIT 10")
        questions = cursor.fetchall()
        conn.close()
        return render_template('teacher_portal.html', categories=categories, questions=questions, username=session['username'])
    except Exception as e:
        logging.error(f"Teacher portal error: {e}")
        return render_template('error.html', error_code=500, message="Could not load teacher portal."), 500

@app.route('/add_question', methods=['POST'])
def add_question():
    if 'user_id' not in session or session.get('is_admin') != 2:
        return redirect(url_for('login', role='2'))
    try:
        category = request.form['category']
        question = request.form['question']
        option1 = request.form['option1']
        option2 = request.form['option2']
        option3 = request.form['option3']
        option4 = request.form['option4']
        answer = request.form['answer']
        difficulty = request.form.get('difficulty', 'Medium')
        
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM questions WHERE category = %s AND question = %s", (category, question))
        if cursor.fetchone():
            conn.close()
            flash("Error: This question already exists.")
            return redirect(url_for('teacher_portal'))
        cursor.execute("INSERT INTO questions (category, question, option1, option2, option3, option4, answer, difficulty) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)", (category, question, option1, option2, option3, option4, answer, difficulty))
        conn.commit()
        conn.close()
    except Exception as e:
        logging.error(f"Add question error: {e}")
        flash("An error occurred while adding the question.")
    return redirect(url_for('teacher_portal'))

@app.route('/upload_quiz_file', methods=['POST'])
def upload_quiz_file():
    if 'user_id' not in session or session.get('is_admin') != 2:
        return redirect(url_for('login', role='2'))
    if 'quiz_file' not in request.files:
        flash("No file selected.")
        return redirect(url_for('teacher_portal'))
    file = request.files['quiz_file']
    category = request.form['file_category']
    if file.filename == '':
        flash("No file selected.")
        return redirect(url_for('teacher_portal'))
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        inserted_count = 0
        skipped_count = 0
        duplicate_count = 0
        filename = file.filename.lower()
        
        if filename.endswith('.csv'):
            stream = io.StringIO(file.stream.read().decode("UTF8"), newline=None)
            csv_input = csv.reader(stream)
            is_header = True
            for row in csv_input:
                if not row or len(row) == 0: continue
                if is_header: is_header = False; continue
                if len(row) == 7:
                    file_cat, q, o1, o2, o3, o4, ans = row[0], row[1], row[2], row[3], row[4], row[5], row[6]
                elif len(row) == 6:
                    file_cat = category
                    q, o1, o2, o3, o4, ans = row
                else:
                    skipped_count += 1; continue
                if file_cat.strip().lower() != category.strip().lower():
                    flash(f"Error: File contains '{file_cat}' questions, but you selected '{category}'.")
                    conn.close(); return redirect(url_for('teacher_portal'))
                cursor.execute("SELECT id FROM questions WHERE category = %s AND question = %s", (category, q.strip()))
                if cursor.fetchone():
                    duplicate_count += 1
                    continue
                cursor.execute("INSERT INTO questions (category, question, option1, option2, option3, option4, answer, difficulty) VALUES (%s, %s, %s, %s, %s, %s, %s, 'Medium')", (category, q.strip(), o1.strip(), o2.strip(), o3.strip(), o4.strip(), ans.strip()))
                inserted_count += 1
        elif filename.endswith('.txt'):
            content = file.stream.read().decode("UTF8")
            cat_match = re.search(r'Category:\s*([A-Za-z0-9\s\+\#]+)', content)
            if cat_match:
                file_cat = re.sub(r'\d+$', '', cat_match.group(1).strip())
                if file_cat.lower() != category.lower():
                    flash(f"Error: File contains '{file_cat}' questions, but you selected '{category}'.")
                    conn.close(); return redirect(url_for('teacher_portal'))
            content = re.sub(r'\s+', ' ', content.replace('\n', ' ').replace('\r', ' '))
            pattern = r'(?:\d+\.\s*)?Question:\s*(.*?)\s*A\.\s*(.*?)\s*B\.\s*(.*?)\s*C\.\s*(.*?)\s*D\.\s*(.*?)\s*Answer:\s*([A-D])'
            matches = re.findall(pattern, content)
            for match in matches:
                q, o1, o2, o3, o4 = match[0].strip(), match[1].strip(), match[2].strip(), match[3].strip(), match[4].strip()
                ans = {'A': o1, 'B': o2, 'C': o3, 'D': o4}.get(match[5].strip().upper(), '')
                if q and ans:
                    cursor.execute("SELECT id FROM questions WHERE category = %s AND question = %s", (category, q))
                    if cursor.fetchone():
                        duplicate_count += 1
                        continue
                    cursor.execute("INSERT INTO questions (category, question, option1, option2, option3, option4, answer, difficulty) VALUES (%s, %s, %s, %s, %s, %s, %s, 'Medium')", (category, q, o1, o2, o3, o4, ans))
                    inserted_count += 1
                else: skipped_count += 1
        else:
            flash("Error: Please upload a .csv or .txt file.")
            return redirect(url_for('teacher_portal'))
            
        conn.commit(); conn.close()
        if inserted_count > 0: flash(f"Success! Added {inserted_count} questions. (Skipped {skipped_count} invalid, Ignored {duplicate_count} duplicates).")
        else: flash(f"Error: 0 questions were added. Skipped {skipped_count} invalid, Ignored {duplicate_count} duplicates.")
    except Exception as e:
        logging.error(f"Quiz file upload error: {e}")
        flash("An error occurred while processing the file.")
    return redirect(url_for('teacher_portal'))

@app.route('/generate_ai_quiz', methods=['POST'])
def generate_ai_quiz():
    if 'user_id' not in session or session.get('is_admin') != 2:
        return redirect(url_for('login', role='2'))
    try:
        topic = request.form['ai_topic']
        category = request.form['ai_category']
        num_questions = request.form.get('num_questions', 5)
        difficulty = request.form.get('difficulty', 'Mixed')

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT category_name FROM categories")
        all_categories = [row['category_name'].lower() for row in cursor.fetchall()]
        for cat in all_categories:
            if cat in topic.lower() and cat != category.lower():
                flash(f"Error: You selected '{category}', but your prompt mentions '{cat.title()}'.")
                conn.close()
                return redirect(url_for('teacher_portal'))

        client = OpenAI(api_key=GROQ_API_KEY, base_url="https://api.groq.com/openai/v1")
        response = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[
                {"role": "system", "content": "You are an expert professor. Output ONLY valid JSON. The JSON must be an object with a key 'questions' containing a list of objects. Keys: 'question', 'option1', 'option2', 'option3', 'option4', 'answer'. The 'answer' must EXACTLY match one of the options."},
                {"role": "user", "content": f"Generate {num_questions} multiple choice questions about '{topic}' specifically applied to {category}. Difficulty: {difficulty}. Questions MUST be strictly related to {category}."}
            ],
            response_format={ "type": "json_object" }
        )

        ai_content = response.choices[0].message.content
        parsed_data = json.loads(ai_content)
        questions_list = next(iter(parsed_data.values())) if isinstance(parsed_data, dict) else parsed_data

        inserted_count = 0
        duplicate_count = 0
        for q in questions_list:
            cursor.execute("SELECT id FROM questions WHERE category = %s AND question = %s", (category, q['question']))
            if cursor.fetchone():
                duplicate_count += 1
                continue
            cursor.execute("INSERT INTO questions (category, question, option1, option2, option3, option4, answer, difficulty) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)", (category, q['question'], q['option1'], q['option2'], q['option3'], q['option4'], q['answer'], difficulty))
            inserted_count += 1
            
        conn.commit()
        conn.close()
        
        if duplicate_count > 0:
            flash(f"Success! Added {inserted_count} new questions. Ignored {duplicate_count} duplicates.")
        return redirect(url_for('teacher_portal'))
    except Exception as e:
        logging.error(f"AI Generation Error: {e}", exc_info=True)
        flash("An error occurred while generating questions with AI. Please try again.")
        return redirect(url_for('teacher_portal'))

if __name__ == '__main__':
    app.run(debug=True)