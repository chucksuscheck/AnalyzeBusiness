import secrets
from pathlib import Path

from flask import Flask, redirect, render_template_string, session, url_for

from business_diagnostic import DIAG_QUESTIONS_FILE, DIAG_RESULTS_FILE, business_diag_bp, initialize_diag_session, load_json as load_diag_json
from ai_readiness import AI_QUESTIONS_FILE, ai_bp, load_json as load_ai_json
from company_info import CONTEXT_FILE, company_bp, escape_html, load_json as load_company_json
from results import results_bp

BASE_DIR = Path(__file__).resolve().parent

PAGE_TEMPLATE = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{{ title }}</title>
  <style>
    body { font-family: Arial, sans-serif; margin: 0; background: #f3f6fb; color: #111827; }
    .wrap { max-width: 1080px; margin: 0 auto; padding: 28px 18px 60px; }
    .card { background: #fff; border-radius: 16px; padding: 24px; box-shadow: 0 10px 28px rgba(15,23,42,.08); margin-bottom: 20px; }
    h1, h2, h3, h4 { margin-top: 0; }
    h1 { font-size: 2rem; }
    h2 { font-size: 1.5rem; margin-bottom: 10px; }
    h3 { font-size: 1.1rem; margin-bottom: 8px; }
    .muted { color: #6b7280; }
    .btn, button { background: #1d4ed8; color: #fff; border: none; border-radius: 10px; padding: 12px 18px; text-decoration: none; cursor: pointer; font-size: 15px; display: inline-block; }
    .btn:hover, button:hover { background: #1e40af; }
    .btn.secondary { background: #475569; }
    .btn.secondary:hover { background: #334155; }
    .option { display: block; margin: 12px 0; padding: 14px 16px; border: 1px solid #d1d5db; border-radius: 12px; background: #fff; color: #111827; cursor: pointer; text-align: left; width: 100%; }
    .option:hover { background: #f8fafc; border-color: #93c5fd; }
    .option-wrap { margin-top: 18px; }
    .progress { width: 100%; height: 12px; background: #e5e7eb; border-radius: 999px; overflow: hidden; }
    .progress > div { height: 100%; background: #2563eb; }
    .stat-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 14px; margin-top: 18px; }
    .stat { background: #f8fafc; border: 1px solid #e5e7eb; border-radius: 14px; padding: 16px; }
    .score { font-size: 2rem; font-weight: 700; }
    .legend { display: flex; gap: 20px; flex-wrap: wrap; margin-top: 10px; color: #475569; font-size: 14px; }
    .legend span::before { content: ''; display: inline-block; width: 12px; height: 12px; border-radius: 3px; margin-right: 8px; vertical-align: -1px; }
    .legend .low::before { background: #dc2626; }
    .legend .mid::before { background: #f59e0b; }
    .legend .high::before { background: #16a34a; }
    .section { border-top: 1px solid #e5e7eb; margin-top: 24px; padding-top: 24px; }
    .sub-block { border: 1px solid #e5e7eb; border-radius: 14px; padding: 18px; margin-top: 16px; background: #fff; }
    .pill { display: inline-block; padding: 6px 10px; border-radius: 999px; background: #eff6ff; color: #1d4ed8; font-size: 13px; font-weight: 600; }
    .chart-svg { width: 100%; height: auto; display: block; }
    .list-tight { margin: 8px 0 0 0; padding-left: 20px; }
    .list-tight li { margin-bottom: 8px; }
    p { line-height: 1.55; }
    .field-card { margin-top: 16px; }
    .field-card h3 { margin-bottom: 12px; }
    .context-option { margin: 8px 0; }
    .error { color: #b00020; font-weight: 700; margin-bottom: 16px; }
  </style>
</head>
<body>
  <div class="wrap">{{ body|safe }}</div>
</body>
</html>
"""

app = Flask(__name__)
app.secret_key = secrets.token_hex(16)
app.config['PAGE_TEMPLATE'] = PAGE_TEMPLATE

app.register_blueprint(company_bp)
app.register_blueprint(ai_bp)
app.register_blueprint(business_diag_bp)
app.register_blueprint(results_bp)


@app.route('/')
def index():
    try:
        load_company_json(CONTEXT_FILE)
        load_ai_json(AI_QUESTIONS_FILE)
        diag_questions = load_diag_json(DIAG_QUESTIONS_FILE)
        load_diag_json(DIAG_RESULTS_FILE)
    except FileNotFoundError as exc:
        body = f"<div class='card'><h1>Setup needed</h1><p>{escape_html(exc)}</p></div>"
        return render_template_string(PAGE_TEMPLATE, title='Setup needed', body=body), 500

    session.clear()
    initialize_diag_session(diag_questions)

    body = f"""
    <div class='card'>
      <h1>Combined Business Assessment</h1>
      <p class='muted'>This modular version uses separate Python files for company information, AI readiness, the adaptive business diagnostic, and final results.</p>
      <p>The flow is: company information first, business diagnostic second, AI readiness third, and results last.</p>
      <a class='btn' href='{url_for('company.context_page')}'>Start assessment</a>
    </div>
    """
    return render_template_string(PAGE_TEMPLATE, title='Combined Assessment', body=body)


if __name__ == '__main__':
    app.run(debug=True)
