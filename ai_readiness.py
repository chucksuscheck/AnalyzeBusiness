import json
from pathlib import Path
from typing import Any, Dict, List

from flask import Blueprint, current_app, redirect, render_template_string, request, session, url_for

from company_info import escape_html

ai_bp = Blueprint('ai', __name__)

BASE_DIR = Path(__file__).resolve().parent
AI_QUESTIONS_FILE = BASE_DIR / 'questions.json'


def load_json(path: Path):
    if not path.exists():
        raise FileNotFoundError(f"Missing required file: {path.name}")
    with path.open('r', encoding='utf-8') as f:
        return json.load(f)


def load_ai_questions(file_path: Path) -> List[Dict[str, Any]]:
    questions = load_json(file_path)
    if not isinstance(questions, list):
        raise ValueError('questions.json must contain a JSON array.')

    required_fields = {'id', 'category', 'text', 'options'}
    for idx, q in enumerate(questions, start=1):
        missing = required_fields - set(q.keys())
        if missing:
            raise ValueError(f"AI question #{idx} is missing fields: {sorted(missing)}")
        if not isinstance(q['options'], list) or len(q['options']) != 4:
            raise ValueError(f"AI question #{idx} must have exactly 4 options.")
    return questions


AI_QUESTIONS = load_ai_questions(AI_QUESTIONS_FILE)

MATURITY_LEVELS = [
    {
        'name': 'Level 1: Unaware / At Risk',
        'min_score': 0,
        'max_score': 9,
        'narrative': (
            'AI is either not being used or is being used informally without structure. '
            'This creates both missed opportunities and unnecessary risk. Immediate focus '
            'should be on understanding where AI can provide value and establishing basic safeguards.'
        ),
        'next_steps': [
            'Identify 2-3 safe, high-value use cases.',
            'Establish basic usage guidelines.',
            'Create awareness of common AI risks and limitations.',
        ],
    },
    {
        'name': 'Level 2: Experimenting',
        'min_score': 10,
        'max_score': 18,
        'narrative': (
            'AI is being explored, but usage is fragmented and lacks consistency. '
            'Without structure, results will remain uneven and difficult to scale. '
            'The next step is to move from experimentation to repeatable processes.'
        ),
        'next_steps': [
            'Standardize 1-2 workflows.',
            'Introduce basic governance.',
            'Begin tracking practical business outcomes.',
        ],
    },
    {
        'name': 'Level 3: Operational',
        'min_score': 19,
        'max_score': 27,
        'narrative': (
            'AI is delivering value in specific areas of the business. '
            'The opportunity now is to expand and optimize these capabilities while '
            'strengthening governance and consistency.'
        ),
        'next_steps': [
            'Expand successful use cases.',
            'Improve measurement and scaling.',
            'Strengthen governance and documentation.',
        ],
    },
    {
        'name': 'Level 4: Strategic',
        'min_score': 28,
        'max_score': 36,
        'narrative': (
            'AI is being used as a strategic capability within the business. '
            'The focus should now shift toward optimization, innovation, and maintaining '
            'control as usage expands.'
        ),
        'next_steps': [
            'Optimize mature workflows.',
            'Explore advanced use cases.',
            'Maintain governance discipline as adoption expands.',
        ],
    },
]

CATEGORY_RECOMMENDATIONS = {
    'Awareness': [
        'Clarify where AI can create value in the business.',
        'Identify and rank the top use cases by impact and feasibility.',
        'Create simple criteria for evaluating AI tools.',
    ],
    'Usage': [
        'Move from isolated experimentation to shared practices.',
        'Define 1-2 repeatable AI-enabled workflows.',
        'Measure outcomes such as time saved, quality improved, or cost reduced.',
    ],
    'Risk & Governance': [
        'Create basic acceptable-use guidance for AI.',
        'Define how sensitive data may and may not be used with AI tools.',
        'Educate staff on hallucination, bias, privacy, and compliance risks.',
    ],
    'Process & Integration': [
        'Embed AI into actual workflows rather than one-off usage.',
        'Document prompts, tasks, and review steps for repeatability.',
        'Prioritize new AI opportunities using business value and risk.',
    ],
}


def normalize_ai_answers(raw_answers: Dict[Any, Any]) -> Dict[str, int]:
    normalized: Dict[str, int] = {}
    for key, value in (raw_answers or {}).items():
        normalized[str(key)] = int(value)
    return normalized


def determine_maturity(total_score: int) -> Dict[str, Any]:
    for level in MATURITY_LEVELS:
        if level['min_score'] <= total_score <= level['max_score']:
            return level
    return MATURITY_LEVELS[-1]


def calculate_ai_category_scores(responses: Dict[str, int]) -> Dict[str, int]:
    scores: Dict[str, int] = {}
    for q in AI_QUESTIONS:
        category = q['category']
        scores.setdefault(category, 0)
        scores[category] += responses.get(str(q['id']), 0)
    return scores


def weakest_categories(category_scores: Dict[str, int]) -> List[Any]:
    return sorted(category_scores.items(), key=lambda item: item[1])


def ai_answers_for_display(responses: Dict[str, int]) -> List[Dict[str, str]]:
    items = []
    for q in AI_QUESTIONS:
        selected_idx = responses.get(str(q['id']))
        if selected_idx is None:
            continue
        items.append({
            'category': q['category'],
            'question': q['text'],
            'answer': q['options'][selected_idx],
        })
    return items


@ai_bp.route('/ai', methods=['GET', 'POST'])
def ai_assessment():
    if 'context_answers' not in session:
        return redirect(url_for('company.context_page'))

    answers = normalize_ai_answers(session.get('ai_answers', {}))
    session['ai_answers'] = answers

    current_index = int(session.get('ai_index', 0))
    total_questions = len(AI_QUESTIONS)

    if request.method == 'POST':
        selected = request.form.get('answer')
        if selected is not None:
            question = AI_QUESTIONS[current_index]
            answers[str(question['id'])] = int(selected)
            session['ai_answers'] = answers
            current_index += 1
            session['ai_index'] = current_index
            if current_index >= total_questions:
                session.pop('ai_index', None)
                return redirect(url_for('results.results_page'))
            return redirect(url_for('ai.ai_assessment'))

    if current_index >= total_questions:
        session.pop('ai_index', None)
        return redirect(url_for('results.results_page'))

    question = AI_QUESTIONS[current_index]
    progress_pct = int((current_index / total_questions) * 100)

    option_blocks = []
    for idx, option in enumerate(question['options']):
        option_blocks.append(
            f"""
            <button type='submit' name='answer' value='{idx}' class='option'>
              {escape_html(option)}
            </button>
            """
        )

    body = f"""
    <style>
      .phase-card {{
        background: #eef8f0;
        border: 1px solid #cfe7d5;
        border-radius: 18px;
        box-shadow: 0 12px 30px rgba(0,0,0,.06);
        padding: 28px;
      }}
      .phase-label {{
        color: #1e6b3e;
        font-size: 0.95rem;
        font-weight: 700;
        letter-spacing: .02em;
        margin-bottom: 8px;
      }}
      .phase-title {{
        margin: 0 0 12px;
        color: #174d2f;
      }}
      .phase-subtitle {{
        color: #355d45;
        margin-bottom: 18px;
      }}
      .progress-wrap {{
        background: #d8eadc;
        border-radius: 999px;
        height: 12px;
        overflow: hidden;
        margin: 14px 0 10px;
      }}
      .progress-bar {{
        background: #5a9a6e;
        height: 100%;
        width: {progress_pct}%;
      }}
      .progress-text {{
        color: #355d45;
        font-size: .95rem;
        margin-bottom: 24px;
      }}
      .question-card {{
        background: #f7fcf8;
        border: 1px solid #d6eadb;
        border-radius: 16px;
        padding: 22px;
      }}
      .question-meta {{
        color: #2b6b46;
        font-weight: 700;
        font-size: .92rem;
        margin-bottom: 8px;
      }}
      .question-text {{
        font-size: 1.25rem;
        line-height: 1.5;
        color: #153a25;
        margin-bottom: 18px;
      }}
      .option-list {{
        display: grid;
        gap: 12px;
      }}
      .option {{
        display: block;
        width: 100%;
        text-align: left;
        padding: 16px 18px;
        border: 1px solid #bddac5;
        border-radius: 14px;
        background: #ffffff;
        color: #153a25;
        font-size: 1rem;
        cursor: pointer;
        transition: transform .05s ease, background .15s ease, border-color .15s ease, box-shadow .15s ease;
      }}
      .option:hover {{
        background: #edf7f0;
        border-color: #97c4a4;
        box-shadow: 0 8px 18px rgba(64, 120, 82, .10);
      }}
      .option:active {{
        transform: translateY(1px);
      }}
    </style>

    <div class='phase-card'>
      <div class='phase-label'>AI Readiness Assessment</div>
      <h1 class='phase-title'>AI readiness</h1>
      <div class='phase-subtitle'>Answer each question based on current practice. Choose the option that best reflects how the business operates today.</div>

      <div class='progress-wrap'><div class='progress-bar'></div></div>
      <div class='progress-text'>Question {current_index + 1} of {total_questions}</div>

      <div class='question-card'>
        <div class='question-meta'>{escape_html(question['category'])}</div>
        <div class='question-text'>{escape_html(question['text'])}</div>
        <form method='post'>
          <div class='option-list'>
            {''.join(option_blocks)}
          </div>
        </form>
      </div>
    </div>
    """
    return render_template_string(current_app.config['PAGE_TEMPLATE'], title='AI Readiness Assessment', body=body)
