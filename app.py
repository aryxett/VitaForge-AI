"""
VitaForge AI — Optimization Backend
"""

import os
import io
import json
import hashlib
import tempfile
from dotenv import load_dotenv
from flask import Flask, request, jsonify, render_template, send_file, redirect, url_for
from flask_login import LoginManager, login_required, current_user
from werkzeug.utils import secure_filename

import pdfplumber
from docx import Document
import google.generativeai as genai

from models import db, User
from analyzer import analyze_resume, get_available_roles
from pdf_generator import generate_resume_pdf
from auth import auth, init_oauth

# ─── Load Environment Variables ───────────────────────────────────────────────
load_dotenv()

# ─── App Setup ────────────────────────────────────────────────────────────────
app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-fallback-secret-key')
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024  # 10MB max
app.config['UPLOAD_FOLDER'] = tempfile.mkdtemp()
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'sqlite:///users.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Initialize Gemini Client
gemini_configured = False
gemini_api_key = os.getenv('GEMINI_API_KEY')
print(f"DEBUG: GEMINI_API_KEY present: {bool(gemini_api_key)}")
if gemini_api_key:
    try:
        genai.configure(api_key=gemini_api_key)
        gemini_configured = True
        print("DEBUG: Gemini SDK configured successfully.")
    except Exception as e:
        print(f"DEBUG: Gemini SDK configuration FAILED: {e}")
        pass
ALLOWED_EXTENSIONS = {'pdf', 'docx'}

# ─── SHA256 Result Cache ──────────────────────────────────────────────────────
_result_cache = {}

# ─── Initialize Extensions ───────────────────────────────────────────────────
db.init_app(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'auth.login'
login_manager.login_message = 'Please log in to access this page.'
login_manager.login_message_category = 'error'

# Register auth blueprint
app.register_blueprint(auth)

# Initialize Google OAuth
init_oauth(app)

# Create database tables
with app.app_context():
    db.create_all()


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


# ─── Helpers ──────────────────────────────────────────────────────────────────

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def extract_text_from_pdf(filepath):
    """Extract text from PDF using pdfplumber."""
    text = ""
    with pdfplumber.open(filepath) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                text += page_text + "\n"
    full_text = text.strip()
    # Clean PDF artifacts like (cid:127)
    import re
    full_text = re.sub(r'\(cid:\d+\)', '', full_text)
    return full_text.strip()


def extract_text_from_docx(filepath):
    """Extract text from DOCX using python-docx."""
    doc = Document(filepath)
    text = "\n".join([para.text for para in doc.paragraphs if para.text.strip()])
    return text.strip()


# ─── Routes ───────────────────────────────────────────────────────────────────

@app.route('/')
@login_required
def index():
    roles = get_available_roles()
    return render_template('index.html', roles=roles)


@app.route('/dashboard')
@login_required
def dashboard():
    return render_template('dashboard.html')


@app.route('/api/roles', methods=['GET'])
@login_required
def api_roles():
    return jsonify(get_available_roles())


@app.route('/api/upload', methods=['POST'])
@login_required
def upload_resume():
    # Validate file
    if 'resume' not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    file = request.files['resume']
    if file.filename == '':
        return jsonify({"error": "No file selected"}), 400

    if not allowed_file(file.filename):
        return jsonify({"error": "Invalid file type. Only PDF and DOCX are supported."}), 400

    # Get parameters
    job_role = request.form.get('job_role', 'software_engineer')
    job_description = request.form.get('job_description', '')
    custom_role = request.form.get('custom_role', '')

    # Save and extract text
    filename = secure_filename(file.filename)
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(filepath)

    try:
        ext = filename.rsplit('.', 1)[1].lower()
        if ext == 'pdf':
            text = extract_text_from_pdf(filepath)
        elif ext == 'docx':
            text = extract_text_from_docx(filepath)
        else:
            return jsonify({"error": "Unsupported file format"}), 400

        if not text or len(text.strip()) < 50:
            return jsonify({"error": "Could not extract enough text from the file. Ensure it's not a scanned/image-based PDF."}), 400

        # SHA256 cache: same resume + same role = identical results
        cache_key = hashlib.sha256((text + job_role + custom_role).encode('utf-8')).hexdigest()
        if cache_key in _result_cache:
            cached = _result_cache[cache_key].copy()
            cached['filename'] = filename
            cached['cached'] = True
            return jsonify(cached)

        # Run analysis
        results = analyze_resume(text, job_role, job_description, custom_role)
        results['filename'] = filename

        # Store in cache
        _result_cache[cache_key] = results.copy()

        return jsonify(results)

    except Exception as e:
        return jsonify({"error": f"Error processing file: {str(e)}"}), 500

    finally:
        # Clean up uploaded file
        if os.path.exists(filepath):
            os.remove(filepath)


@app.route('/api/download-pdf', methods=['POST'])
@login_required
def download_pdf():
    """Endpoint to generate and download analysis PDF."""
    try:
        data = request.json
        if not data:
            return jsonify({"error": "No data provided"}), 400
        
        pdf_bytes = generate_resume_pdf(data)
        
        filename = data.get('filename', 'analysis_report.pdf')
        if not filename.endswith('.pdf'):
            filename = f"{filename.split('.')[0]}_report.pdf"
        else:
            filename = filename.replace('.pdf', '_report.pdf')

        return send_file(
            io.BytesIO(pdf_bytes),
            mimetype='application/pdf',
            as_attachment=True,
            download_name=filename
        )
    except Exception as e:
        return jsonify({"error": f"Failed to generate PDF: {str(e)}"}), 500


@app.route('/api/chat', methods=['POST'])
@login_required
def chat():
    data = request.json
    if not data or 'message' not in data:
        return jsonify({"error": "No message provided"}), 400
    
    user_msg = data['message']
    print(f"DEBUG: Incoming /api/chat message: {user_msg}")
    context = data.get('context', {})
    
    # Extract context data for smarter responses
    role = context.get('role', 'your target role')
    ats = context.get('ats_score', {})
    total_score = ats.get('total', 'N/A')
    missing_skills = context.get('missing_skills', [])
    found_skills = context.get('found_skills', [])
    weaknesses = context.get('weaknesses', [])
    strengths = context.get('strengths', [])
    roadmap = context.get('roadmap', {}).get('steps', [])
    interviews = context.get('interview_questions', {}).get('technical', [])
    jd_match = context.get('jd_match', {})
    
    # Check if Gemini is configured
    if gemini_configured:
        try:
            print(f"DEBUG: Gemini calling with prompt: {user_msg}")
            # Build a powerful system prompt for Bunny
            system_prompt = f"""You are Bunny 🐰, an intelligent, friendly, and highly capable AI Resume Companion.
            
            YOUR PERSONALITY:
            - Friendly, supportive, and conversational.
            - Feel like a real AI mentor, not a rigid bot.
            - Use emojis thoughtfully but not excessively.
            - Keep responses concise (2-3 paragraphs max) unless generating specific resume content.
            
            YOUR CAPABILITIES:
            - Understand conversation context and memory.
            - Handle short intents naturally. If the user says "yes", "sure", or "please", execute the action you previously suggested.
            - If the user says "no" or "not now", acknowledge gracefully (e.g., "No problem! Let me know if you want to look at something else.")
            - Proactively offer specific help based on their resume data.
            - Do NOT repeat the exact same response or phrasing if the user asks a similar question.
            
            CANDIDATE'S RESUME CONTEXT:
            - Target Role: {role}
            - ATS Score: {total_score}/100
            - Key Strengths: {', '.join([s.get('title', '') for s in strengths[:3]])}
            - Weaknesses to Fix: {', '.join([w.get('title', '') for w in weaknesses[:3]])}
            - Missing Skills: {', '.join(missing_skills[:10]) if missing_skills else 'None detected!'}
            - Known Skills: {', '.join(found_skills[:15])}
            
            INSTRUCTIONS FOR RESPONDING:
            1. Integrate the candidate's actual resume data into your advice to make it deeply personalized.
            2. If they ask to improve their resume, generate specific strong bullet points or suggest exactly where to add missing skills.
            3. Always offer a clear next step or suggestion at the end of your response to keep the conversation dynamic.
            """

            model = genai.GenerativeModel(
                model_name="gemini-1.5-flash",
                system_instruction=system_prompt,
                generation_config=genai.GenerationConfig(
                    temperature=0.4,
                    top_p=0.9,
                    max_output_tokens=500,
                )
            )

            # history from frontend already includes the current user message as the last item
            history = data.get('history', [])
            print(f"DEBUG: History length: {len(history)}")
            
            gemini_history = []
            for msg in history[-10:]:
                if msg.get('content'):
                    role_map = {'user': 'user', 'assistant': 'model'}
                    g_role = role_map.get(msg.get('role'))
                    if g_role:
                        gemini_history.append({"role": g_role, "parts": [msg['content']]})

            latest_user_message = user_msg
            if gemini_history and gemini_history[-1]['role'] == 'user':
                latest_user_message = gemini_history[-1]['parts'][0]
                gemini_history = gemini_history[:-1]

            print(f"DEBUG: gemini_history size: {len(gemini_history)}")
            print(f"DEBUG: latest_user_message: {latest_user_message}")

            chat_session = model.start_chat(history=gemini_history)
            print("DEBUG: Sending message to Gemini...")
            response = chat_session.send_message(latest_user_message)
            
            ai_response = response.text
            print(f"DEBUG: Gemini successfully responded: {ai_response[:100]}...")
            return jsonify({"response": ai_response})
            
        except Exception as e:
            error_str = str(e)
            print(f"DEBUG ERROR in /api/chat: {error_str}")
            if "quota" in error_str.lower():
                return jsonify({
                    "response": f"I'd love to chat more, but it looks like my AI API quota has been reached! 🐰\n\nI can still see your ATS score is **{total_score}**. Once the quota is updated, I'll be able to give you full AI advice again!"
                })
            return jsonify({"error": f"AI service temporarily unavailable. ({error_str})"}), 503
            
    # Fallback if Gemini is not configured
    return jsonify({
        "response": f"I'm currently running in offline mode because my AI API key isn't configured. 🐰\n\nI can still tell you that your ATS score is **{total_score}** and you are targeting a **{role}** role. Connect my API to unlock full conversation capabilities!"
    })


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=8080)
