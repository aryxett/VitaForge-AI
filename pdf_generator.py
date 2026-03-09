import io
from reportlab.lib.pagesizes import LETTER
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
from reportlab.lib.units import inch

def generate_resume_pdf(data):
    """Generate a PDF report from analysis results."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=LETTER, rightMargin=72, leftMargin=72, topMargin=72, bottomMargin=18)
    
    styles = getSampleStyleSheet()
    
    # Custom Styles
    title_style = ParagraphStyle(
        'MainTitle',
        parent=styles['Heading1'],
        fontSize=24,
        textColor=colors.HexColor('#7c4dff'),
        spaceAfter=12,
        alignment=1 # Center
    )
    
    section_style = ParagraphStyle(
        'SectionTitle',
        parent=styles['Heading2'],
        fontSize=16,
        textColor=colors.HexColor('#2c3e50'),
        spaceBefore=15,
        spaceAfter=8,
        borderPadding=(0, 0, 2, 0),
        borderWidth=0,
        borderColor=colors.HexColor('#7c4dff')
    )
    
    normal_style = styles['Normal']
    bullet_style = ParagraphStyle('Bullet', parent=styles['Normal'], leftIndent=20, bulletIndent=10, spaceAfter=5)
    
    content = []
    
    # --- 1. Header & Summary ---
    candidate_name = data.get('filename', 'Candidate').split('.')[0].replace('_', ' ').replace('-', ' ').title()
    content.append(Paragraph(f"Resume Analysis Report", title_style))
    content.append(Paragraph(f"<b>Candidate:</b> {candidate_name}", normal_style))
    content.append(Paragraph(f"<b>Target Role:</b> {data.get('role', 'N/A')}", normal_style))
    content.append(Spacer(1, 0.2 * inch))
    
    # Score Table
    score_data = [
        ['Resume Score', 'Job Match Score', 'Skill Gap Progress'],
        [f"{data.get('ats_score', {}).get('total', 0)}%", 
         f"{data.get('jd_match', {}).get('match_percentage', 0) if data.get('jd_match') else 'N/A'}%", 
         "Analyzed"]
    ]
    
    # Custom Skill Gap calculation logic (same as JS)
    found_len = len(data.get('found_skills', []))
    missing_len = len(data.get('missing_skills', []))
    total_len = found_len + missing_len
    if total_len > 0:
        score_data[1][2] = f"{round((found_len / total_len) * 100)}%"
    
    t = Table(score_data, colWidths=[2 * inch] * 3)
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f3f0ff')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.HexColor('#7c4dff')),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 12),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.whitesmoke),
        ('FONTSIZE', (0, 1), (-1, -1), 16),
        ('GRID', (0, 0), (-1, -1), 1, colors.white),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    content.append(t)
    content.append(Spacer(1, 0.2 * inch))
    
    # --- 2. Skills Analysis ---
    content.append(Paragraph("Skills Analysis", section_style))
    
    # Found Skills
    found = data.get('found_skills', [])
    content.append(Paragraph(f"<b>Detected Skills:</b>", normal_style))
    if found:
        content.append(Paragraph(", ".join(found[:30]), normal_style))
    else:
        content.append(Paragraph("No major skills detected.", normal_style))
    
    # Missing Skills
    missing = data.get('missing_skills', [])
    content.append(Spacer(1, 0.1 * inch))
    content.append(Paragraph(f"<b>Missing Skills (Recommended):</b>", normal_style))
    if missing:
        content.append(Paragraph(", ".join(missing[:30]), normal_style))
    else:
        content.append(Paragraph("No significant missing skills identified.", normal_style))

    # JD Keywords
    if data.get('jd_match'):
        content.append(Spacer(1, 0.1 * inch))
        keywords = data['jd_match'].get('missing_keywords', [])
        content.append(Paragraph(f"<b>Missing Job Description Keywords:</b>", normal_style))
        content.append(Paragraph(", ".join(keywords) if keywords else "None", normal_style))

    # --- 3. Strengths & Weaknesses ---
    content.append(Paragraph("Resume Strengths & Weaknesses", section_style))
    
    content.append(Paragraph("<b>Strengths:</b>", normal_style))
    for s in data.get('strengths', []):
        content.append(Paragraph(f"• {s['title']}: {s['detail']}", bullet_style))
    
    content.append(Spacer(1, 0.1 * inch))
    content.append(Paragraph("<b>Areas for Improvement:</b>", normal_style))
    for w in data.get('weaknesses', []):
        content.append(Paragraph(f"• {w['title']}: {w['detail']}", bullet_style))
        
    # --- 4. Skill Gap Roadmap ---
    roadmap = data.get('roadmap', {})
    if roadmap and roadmap.get('steps'):
        content.append(Paragraph("Skill Gap Roadmap", section_style))
        content.append(Paragraph(roadmap.get('title', 'Learning Path'), normal_style))
        for step in roadmap.get('steps', []):
            content.append(Spacer(1, 0.05 * inch))
            content.append(Paragraph(f"<b>- {step['title']}</b>", normal_style))
            content.append(Paragraph(step.get('detail', ''), bullet_style))
            if step.get('tech'):
                content.append(Paragraph(f"<i>Technologies: {', '.join(step['tech'])}</i>", bullet_style))

    # --- 5. AI Interview Preparation ---
    questions = data.get('interview_questions', {})
    if questions:
        content.append(Paragraph("AI Personalized Interview Prep", section_style))
        
        if questions.get('technical'):
            content.append(Paragraph("<b>Technical Questions:</b>", normal_style))
            for q in questions['technical'][:3]:
                content.append(Paragraph(f"• {q}", bullet_style))
        
        if questions.get('projects'):
            content.append(Spacer(1, 0.05 * inch))
            content.append(Paragraph("<b>Project-based Questions:</b>", normal_style))
            for q in questions['projects'][:2]:
                content.append(Paragraph(f"• {q}", bullet_style))
                
        if questions.get('behavioral'):
            content.append(Spacer(1, 0.05 * inch))
            content.append(Paragraph("<b>Behavioral Questions:</b>", normal_style))
            for q in questions['behavioral'][:2]:
                content.append(Paragraph(f"• {q}", bullet_style))

    # --- 6. Improvement Suggestions ---
    content.append(Paragraph("General Suggestions", section_style))
    for sug in data.get('suggestions', [])[:5]:
        content.append(Paragraph(f"• <b>{sug['title']}:</b> {sug['detail']}", bullet_style))

    doc.build(content)
    pdf_value = buffer.getvalue()
    buffer.close()
    return pdf_value
