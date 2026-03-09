
from analyzer import analyze_resume
import json

dummy_text = """
JOHN DOE
Software Engineer
john.doe@example.com | 123-456-7890
linkedin.com/in/johndoe | github.com/johndoe

Summary
Passionate software engineer with 5 years of experience in Python and JavaScript.

Experience
Software Engineer at Tech Corp (Jan 2020 - Present)
• Developed scalable microservices using Python and Flask.
• Implemented frontend features using React and Redux.
• Increased system performance by 20% through code optimization.

Education
B.S. in Computer Science, University of Technology (2015-2019)

Skills
Python, JavaScript, React, Node.js, Docker, Kubernetes, SQL, AWS, Git
"""

results = analyze_resume(dummy_text, job_role="software_engineer")

# Check for required keys
required_keys = ["ats_score", "role", "identity", "sections", "section_strength", "formatting"]
missing = [k for k in required_keys if k not in results]

print(f"Missing keys: {missing}")
print("\n--- Identity ---")
print(json.dumps(results.get("identity"), indent=2))
print("\n--- Sections Found ---")
print(results.get("sections_found"))
print("\n--- Section Strength ---")
print(json.dumps(results.get("section_strength"), indent=2))
print("\n--- Formatting (First 2) ---")
print(json.dumps(results.get("formatting")[:2], indent=2))
