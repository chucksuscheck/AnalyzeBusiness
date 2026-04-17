import json
from pathlib import Path
from typing import Any, Dict, List

from flask import Blueprint, current_app, redirect, render_template_string, request, session, url_for

company_bp = Blueprint('company', __name__)

BASE_DIR = Path(__file__).resolve().parent
CONTEXT_FILE = BASE_DIR / 'context.json'


def load_json(path: Path):
    if not path.exists():
        raise FileNotFoundError(f"Missing required file: {path.name}")
    with path.open('r', encoding='utf-8') as f:
        return json.load(f)


def escape_html(value: Any) -> str:
    text = str(value)
    return (
        text.replace('&', '&amp;')
        .replace('<', '&lt;')
        .replace('>', '&gt;')
        .replace('"', '&quot;')
        .replace("'", '&#39;')
    )


def load_context_questions(file_path: Path) -> List[Dict[str, Any]]:
    questions = load_json(file_path)
    if not isinstance(questions, list):
        raise ValueError('context.json must contain a JSON array.')

    required_fields = {'id', 'type', 'question', 'options'}
    allowed_types = {'single_select', 'multi_select'}
    for idx, q in enumerate(questions, start=1):
        missing = required_fields - set(q.keys())
        if missing:
            raise ValueError(f"Context question #{idx} is missing fields: {sorted(missing)}")
        if q['type'] not in allowed_types:
            raise ValueError(f"Context question #{idx} has invalid type: {q['type']}")
    return questions


CONTEXT_QUESTIONS = load_context_questions(CONTEXT_FILE)


def parse_context_answers(form_data) -> Dict[str, Any]:
    answers: Dict[str, Any] = {}
    for q in CONTEXT_QUESTIONS:
        qid = q['id']
        options = q['options']
        if q['type'] == 'multi_select':
            values = form_data.getlist(qid)
            if not values:
                raise ValueError(f"Missing answer for context question '{qid}'")
            for value in values:
                if value not in options:
                    raise ValueError(f"Invalid selection for context question '{qid}'")
            answers[qid] = values
        else:
            value = form_data.get(qid)
            if not value:
                raise ValueError(f"Missing answer for context question '{qid}'")
            if value not in options:
                raise ValueError(f"Invalid answer for context question '{qid}'")
            answers[qid] = value
    return answers



def build_context_summary(saved_answers: Dict[str, Any]) -> List[str]:
    summary = []
    for q in CONTEXT_QUESTIONS:
        answer = saved_answers.get(q['id'])
        if answer is None:
            continue
        answer_text = ', '.join(answer) if isinstance(answer, list) else str(answer)
        summary.append(f"{q['question']}: {answer_text}")
    return summary


@company_bp.route('/context', methods=['GET', 'POST'])
def context_page():
    error = ''
    if request.method == 'POST':
        try:
            answers = parse_context_answers(request.form)
            session['context_answers'] = answers
            return redirect(url_for('diagnostic.diag_question'))
        except ValueError as exc:
            error = str(exc)

    saved_answers = session.get('context_answers', {})
    blocks = []
    for idx, q in enumerate(CONTEXT_QUESTIONS, start=1):
        options = []
        if q['type'] == 'multi_select':
            selected_values = set(saved_answers.get(q['id'], []))
            for option in q['options']:
                checked = 'checked' if option in selected_values else ''
                options.append(
                    f"<div class='context-option'><label><input type='checkbox' name='{escape_html(q['id'])}' value='{escape_html(option)}' {checked}> {escape_html(option)}</label></div>"
                )
        else:
            selected_value = saved_answers.get(q['id'])
            for option in q['options']:
                checked = 'checked' if selected_value == option else ''
                options.append(
                    f"<div class='context-option'><label><input type='radio' name='{escape_html(q['id'])}' value='{escape_html(option)}' required {checked}> {escape_html(option)}</label></div>"
                )

        blocks.append(
            f"<div class='card field-card' style='border:1px solid #fde68a; box-shadow:0 8px 20px rgba(146, 64, 14, 0.08);'><h3>{idx}. {escape_html(q['question'])}</h3>{''.join(options)}</div>"
        )

    body = f"""
    <div style='background:#fff9db; border:1px solid #fef08a; border-radius:20px; padding:22px;'>
      <div class='card' style='margin-bottom:18px; border:1px solid #fef3c7; box-shadow:0 10px 24px rgba(146, 64, 14, 0.08);'>
        <h1>Business Context</h1>
        <p class='muted'>Answer these business questions first. After that, you will continue to the business diagnostic, followed by the AI readiness evaluation.</p>
        {'<div class="error">' + escape_html(error) + '</div>' if error else ''}
      </div>
      <form method='post'>
        {''.join(blocks)}
        <button type='submit'>Continue to Business Diagnostic</button>
      </form>
    </div>
    """
    return render_template_string(current_app.config['PAGE_TEMPLATE'], title='Business Context', body=body)
