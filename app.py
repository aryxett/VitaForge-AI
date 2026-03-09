"""
VitaForge AI — Optimization Backend
"""

import os
import io
import json
import tempfile
from dotenv import load_dotenv
from flask import Flask, request, jsonify, render_template, send_file, redirect, url_for
from flask_login import LoginManager, login_required, current_user
from werkzeug.utils import secure_filename

import pdfplumber
from docx import Document
from openai import OpenAI

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

# Initialize OpenAI Client
openai_client = None
if os.getenv('OPENAI_API_KEY'):
    openai_client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))

ALLOWED_EXTENSIONS = {'pdf', 'docx'}

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

        # Run analysis
        results = analyze_resume(text, job_role, job_description, custom_role)
        results['filename'] = filename

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
    
    user_msg = data['message'].lower()
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
    
    # Check if OpenAI is configured Let's use the API
    if openai_client:
        try:
            # Build a system prompt that gives the AI the personality and the exact context
            system_prompt = f"""You are an expert AI Career Mentor helping a candidate improve their resume and prepare for interviews.
            Always be encouraging, professional, and highly specific to the data provided. Use Markdown for bolding and lists.
            
            CANDIDATE CONTEXT:
            - Target Role: {role}
            - Current ATS Score: {total_score}/100
            - Key Strengths: {', '.join([s.get('title', '') for s in strengths[:3]])}
            - Weaknesses to Fix: {', '.join([w.get('title', '') for w in weaknesses[:3]])}
            - Missing Skills: {', '.join(missing_skills[:10])}
            - Known Skills: {', '.join(found_skills[:10])}
            
            When answering, directly reference their specific strengths, weaknesses, or missing skills if relevant to their question.
            Keep responses concise (3-4 short paragraphs max). End by offering to help with a related specific task (e.g., "Would you like me to write a bullet point for one of your projects?").
            """

            response = openai_client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_msg}
                ],
                temperature=0.7,
                max_tokens=400
            )
            
            ai_response = response.choices[0].message.content
            return jsonify({"response": ai_response})
            
        except Exception as e:
            # Fallback will trigger below if API fails
            pass
            
            
    # Fallback / Simulated Logic
    response = ""
    follow_up = ""

    # State machine or specific question matching logic
    if "improve" in user_msg or "how can i" in user_msg or "weakness" in user_msg:
        if weaknesses:
            response = f"Based on your current resume score of **{total_score}/100**, here are your priority areas for improvement:\n"
            for w in weaknesses[:3]:
                response += f"- **{w['title']}**: {w['detail']}\n"
            follow_up = "\n\nWould you like me to generate stronger resume bullet points for you?"
        else:
            response = f"Your resume is already very strong with a score of **{total_score}/100**! However, you can always improve by adding more quantifiable results to your experience."
            follow_up = "\n\nDo you want me to suggest specific metrics you could track for your projects?"
            
    elif "learn next" in user_msg or "what should i learn" in user_msg or "missing" in user_msg or "skill gap" in user_msg or "skills" in user_msg:
        if missing_skills:
            response = f"To become a top match for **{role}** roles, you should focus on these missing skills:\n**{', '.join(missing_skills[:5])}**.\n\n"
            if roadmap:
                response += f"According to your career roadmap, I suggest starting with:\n- **{roadmap[0]['title']}**: {roadmap[0]['detail']}"
            follow_up = "\n\nWould you like me to suggest specific projects to help you learn these skills?"
        else:
            response = f"You already have a fantastic skill match for **{role}**! Your strongest skills include **{', '.join(found_skills[:5])}**."
            follow_up = "\n\nWould you like me to generate some technical interview questions to test your knowledge?"
            
    elif "project" in user_msg or "add" in user_msg or "portfolio" in user_msg or "github" in user_msg:
        if missing_skills:
            response = f"A great way to strengthen your portfolio for **{role}** positions is to build projects utilizing your missing skills: **{', '.join(missing_skills[:3])}**.\n\n"
            if roadmap and len(roadmap) > 0 and 'projects' in roadmap[0] and roadmap[0]['projects']:
                response += f"For example, you could build: **{roadmap[0]['projects'][0]}**."
            else:
                response += "For example, you could build a full-stack application integrating these technologies and clearly document the architecture on GitHub."
            follow_up = "\n\nDo you want help writing the project descriptions for your resume?"
        else:
             response = f"Your project section should highlight your mastery of **{', '.join(found_skills[:3])}**. Make sure each GitHub repo has a detailed README outlining the problem solved and the technologies used."
             follow_up = "\n\nShould we review your current project bullet points to make them more impactful?"

    elif "ready for interview" in user_msg or "interview" in user_msg or "prepare" in user_msg:
        if total_score != 'N/A' and isinstance(total_score, (int, float)) and total_score >= 75:
            response = f"With an ATS score of **{total_score}/100**, your resume is in great shape to start landing interviews! You should start preparing for technical rounds."
            if interviews:
                response += f"\n\nHere is a practice question for a **{role}**: \n*{interviews[0]}*"
            follow_up = "\n\nWould you like more technical or behavioral practice questions?"
        else:
             response = f"Your resume score is currently **{total_score}/100**. I'd recommend improving your resume first to increase your chances of getting past the ATS."
             if weaknesses:
                 response += f"\nFocus on tackling: **{weaknesses[0]['title']}**."
             follow_up = "\n\nWould you like to focus on improving your resume first, or jump into interview prep?"

    elif "bullet" in user_msg or "description" in user_msg:
         response = "Strong bullet points follow the 'Action + Context + Result' format. Make sure to lead with strong verbs like 'Engineered' or 'Architected', and always include quantifiable metrics (e.g., 'reduced latency by 20%')."
         if context.get('bullet_rewrites') and len(context.get('bullet_rewrites')) > 0:
             response += f"\n\nHere is an example from your resume:\n**Instead of:** {context['bullet_rewrites'][0]['original']}\n**Say:** {context['bullet_rewrites'][0]['improved']}"
         follow_up = "\n\nShall I suggest more actionable verbs for your current role?"

    else:
        response = f"I'm your AI Career Mentor! I've analyzed your resume for the **{role}** profile and checked your current ATS score (**{total_score}/100**).\n\nYou can ask me things like:\n- How can I improve my resume?\n- Which skills am I missing?\n- What projects should I add?\n- Am I ready for interviews?"

    return jsonify({"response": response + follow_up})


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=8080)
