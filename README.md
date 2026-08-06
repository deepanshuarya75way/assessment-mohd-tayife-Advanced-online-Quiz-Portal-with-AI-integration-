🎯 Advanced Online Quiz Portal
An enterprise-grade EdTech application designed to solve real-world problems in online assessments. Built with Python (Flask), MySQL, and AI integration, this portal moves beyond standard quiz systems by implementing adaptive learning, cryptographic authentication, and robust anti-cheating mechanisms.

🌟 Key Real-World Features
1. Adaptive Difficulty Engine
Dynamic Pathing: The quiz starts at "Medium" difficulty. If the student answers correctly, the next question is pulled from the "Hard" pool. If wrong, it drops to "Easy".
Dynamic Question Pools: SQL ORDER BY RAND() ensures no two students get the exact same set of questions, preventing exam leaks.
2. Enterprise Authentication & Access Control
3-Tier Role System: Super Admin (1), Teacher (2), and Student (0) are strictly separated. Cross-portal login is blocked.
Magic Link Invites: Teachers cannot self-register. The Admin generates a cryptographically secure, time-bound (24-hour) UUID token emailed to the teacher.
Student Roster Whitelist: Students must register using their exact College Registration Number, Name, and Email—matched strictly against a pre-uploaded database roster.
Email OTP Verification: Students must verify their email via a 6-digit One-Time Password before their account is activated.
3. AI Question Generation
Groq Llama-3.1 Integration: Teachers input a topic (e.g., "OOP") and select difficulty. Python sends a strict system prompt to the Groq API, which returns structured JSON.
Category Cross-Checking: The backend validates the prompt against the selected category to prevent generating Python questions for a Java quiz.
4. Anti-Cheat & Proctoring System
Tab-Switch Detection: Uses the JavaScript visibilitychange API. If a student switches tabs more than twice, the quiz is force-submitted automatically.
Integrity Badges: The public leaderboard displays a red "⚠️ Cheated" badge next to students who triggered the anti-cheat system.
5. Resilient Quiz Engine
Client-Side Caching (Auto-Save): Uses localStorage to save answers instantly. If a student's Wi-Fi drops or browser crashes, they can resume exactly where they left off.
Negative Marking: Configurable per-category (e.g., -0.25 per wrong answer) to prevent blind guessing.
🛠 Tech Stack
Component	Technology
Backend	Python, Flask, Gunicorn (WSGI)
Database	MySQL (Local: WAMP, Cloud: Aiven)
Frontend	HTML5, CSS3 (Glassmorphism UI), JavaScript
AI/LLM	OpenAI SDK, Groq API (Llama-3.1-8b-instant)
Security	Werkzeug (Password Hashing), UUID (Magic Links), python-dotenv
Deployment	Render.com, GitHub
🔒 Security Implementations
No Hardcoded Secrets: All API keys, passwords, and database URIs are loaded via environment variables (.env).
Secure File Uploads:
MAX_CONTENT_LENGTH set to 16MB to prevent DoS attacks.
Strict MIME-type and extension validation (.csv, .txt only).
Files are parsed in-memory (io.StringIO) and never saved to disk, eliminating the risk of malicious code execution.
secure_filename used to sanitize all uploaded file names.
Error Handling: Global try/except blocks and custom 404/500 error handlers ensure users never see raw stack traces or database schema errors.
SQL Injection Prevention: 100% use of parameterized queries (%s) via PyMySQL.
📂 Database Schema
The application requires the following MySQL tables:

users: (id, name, email, username, password, is_admin)
categories: (id, category_name, negative_mark)
questions: (id, category, question, option1, option2, option3, option4, answer, difficulty)
results: (id, username, category, score, cheated)
invites: (id, email, token, expires_at) - For teacher magic links
enrolled_students: (roll_no, student_name, email, is_used) - For student whitelist
🚀 Local Setup Instructions
Prerequisites
Python 3.10+
MySQL Server (e.g., WAMP/XAMPP)
VS Code
1. Clone & Setup Environment
git clone https://github.com/your-username/quiz-portal.gitcd quiz-portalpython -m venv venvvenv\Scripts\activate  # On Windowspip install -r requirements.txt
2. Configure Environment Variables
Create a .env file in the root directory:

SECRET_KEY=your_super_secret_random_string
SENDER_EMAIL=your_email@gmail.com
SENDER_PASSWORD=your_16_char_gmail_app_password
GROQ_API_KEY=your_groq_api_key
DB_HOST=localhost
DB_USER=root
DB_PASSWORD=
DB_NAME=quiz

3. Database Initialization
Run your MySQL server and execute the SQL commands to create the database and tables (users, categories, questions, results, invites, enrolled_students).

Manually insert your Super Admin account into the users table with is_admin = 1 (ensure the password is hashed using Werkzeug).

4. Run the Application
python app.py

python app.py
Visit http://127.0.0.1:5000 in your browser.

🌐 Deployment Guide (Render.com + Aiven)
Database: Create a free MySQL database on Aiven.io. Import your local SQL schema.
GitHub: Push your code to a GitHub repository (ensure .env is in .gitignore!).
Render: Create a new Web Service on Render.com and connect your GitHub repo.
Environment Variables: Add all your .env variables into the Render dashboard (use Aiven's cloud DB credentials).
Start Command: Set Render's start command to gunicorn app:app.
Developed by Mohd Tayife | Internship Project at Netcamp Pvt Limited