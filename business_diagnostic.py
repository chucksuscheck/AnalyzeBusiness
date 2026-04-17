import json
from pathlib import Path
from statistics import mean
from typing import Any, Dict

from flask import Blueprint, current_app, redirect, render_template_string, request, session, url_for

from company_info import escape_html

business_diag_bp = Blueprint('diagnostic', __name__)

BASE_DIR = Path(__file__).resolve().parent
DIAG_QUESTIONS_FILE = BASE_DIR / 'adaptive_questions.json'
DIAG_RESULTS_FILE = BASE_DIR / 'businessresults.json'


def load_json(path: Path):
    if not path.exists():
        raise FileNotFoundError(f"Missing required file: {path.name}")
    with path.open('r', encoding='utf-8') as f:
        return json.load(f)


def score_to_color(score: float) -> str:
    if score < 1.5:
        return '#dc2626'
    if score < 2.5:
        return '#f59e0b'
    return '#16a34a'


def clamp_score(score: int) -> int:
    return max(0, min(3, int(score)))


def initialize_diag_session(questions_data):
    session['diag_framework_name'] = questions_data.get('framework_name', 'Business Assessment')
    session['diag_stage'] = 'initial'
    session['diag_current_category_index'] = 0
    session['diag_current_subcategory_index'] = 0
    session['diag_current_followup_index'] = 0
    session['diag_current_score'] = None
    session['diag_scores'] = {}
    session['diag_answers'] = []



def get_current_nodes(questions_data):
    c_idx = session.get('diag_current_category_index', 0)
    s_idx = session.get('diag_current_subcategory_index', 0)
    category = questions_data['categories'][c_idx]
    subcategory = category['subcategories'][s_idx]

    if session.get('diag_stage') == 'initial':
        question = subcategory['initial_question']
    else:
        current_score = str(session.get('diag_current_score', 0))
        followups = subcategory.get('follow_ups', {}).get(current_score, [])
        f_idx = session.get('diag_current_followup_index', 0)
        question = followups[f_idx]
    return category, subcategory, question



def save_subcategory_score(category_id, subcategory_id, score):
    scores = session.get('diag_scores', {})
    scores.setdefault(category_id, {})
    scores[category_id][subcategory_id] = clamp_score(score)
    session['diag_scores'] = scores



def advance_diag(questions_data):
    c_idx = session.get('diag_current_category_index', 0)
    s_idx = session.get('diag_current_subcategory_index', 0)
    category = questions_data['categories'][c_idx]
    subcategory = category['subcategories'][s_idx]

    if session.get('diag_stage') == 'initial':
        followups = subcategory.get('follow_ups', {}).get(str(session.get('diag_current_score', 0)), [])
        if followups:
            session['diag_stage'] = 'followup'
            session['diag_current_followup_index'] = 0
            return
        save_subcategory_score(category['id'], subcategory['id'], session.get('diag_current_score', 0))
    else:
        current_score = session.get('diag_current_score', 0)
        followups = subcategory.get('follow_ups', {}).get(str(current_score), [])
        next_fidx = session.get('diag_current_followup_index', 0) + 1
        if next_fidx < len(followups):
            session['diag_current_followup_index'] = next_fidx
            return
        save_subcategory_score(category['id'], subcategory['id'], current_score)

    if s_idx + 1 < len(category['subcategories']):
        session['diag_current_subcategory_index'] += 1
    else:
        if c_idx + 1 < len(questions_data['categories']):
            session['diag_current_category_index'] += 1
            session['diag_current_subcategory_index'] = 0
        else:
            session['diag_stage'] = 'complete'
            return

    session['diag_stage'] = 'initial'
    session['diag_current_followup_index'] = 0
    session['diag_current_score'] = None



def get_overall_state(avg_score, results_data):
    for state in results_data['overall_business_states']:
        if state['min_average'] <= avg_score <= state['max_average']:
            return state
    return results_data['overall_business_states'][-1]



def build_subcategory_report(category, subcategory, score, results_data):
    category_result = results_data['categories'][category['id']]
    sub_result = category_result['subcategories'][subcategory['id']]
    rating = sub_result['ratings'][str(score)]
    scale = results_data['rating_scale'][str(score)]
    return {
        'category_id': category['id'],
        'category_label': category['label'],
        'subcategory_id': subcategory['id'],
        'subcategory_label': subcategory['label'],
        'subcategory_description': sub_result.get('description', ''),
        'score': score,
        'rating_label': scale['label'],
        'rating_summary': scale['summary'],
        'what_is_happening': rating['what_is_happening'],
        'why_it_happens': rating['why_it_happens'],
        'what_it_is_costing': rating['what_it_is_costing'],
        'what_is_preventing_maturity': rating['what_is_preventing_maturity'],
    }



def build_diag_report(questions_data, results_data):
    saved_scores = session.get('diag_scores', {})
    category_sections = []
    category_overview = []
    all_sub_reports = []

    for category in questions_data['categories']:
        sub_reports = []
        sub_scores = []
        for subcategory in category['subcategories']:
            raw_score = saved_scores.get(category['id'], {}).get(subcategory['id'], 0)
            score = clamp_score(raw_score)
            sub_scores.append(score)
            sub_report = build_subcategory_report(category, subcategory, score, results_data)
            sub_reports.append(sub_report)
            all_sub_reports.append(sub_report)

        category_average = round(mean(sub_scores), 2) if sub_scores else 0.0
        category_sections.append({
            'id': category['id'],
            'label': category['label'],
            'description': results_data['categories'][category['id']].get('description', ''),
            'average': category_average,
            'color': score_to_color(category_average),
            'subcategories': sub_reports,
        })
        category_overview.append({
            'id': category['id'],
            'label': category['label'],
            'score': category_average,
            'color': score_to_color(category_average),
        })

    overall_average = round(mean([item['score'] for item in category_overview]), 2) if category_overview else 0.0
    overall_state = get_overall_state(overall_average, results_data)
    min_score = min((item['score'] for item in all_sub_reports), default=0)
    lowest = [item for item in all_sub_reports if item['score'] == min_score][:3]

    return {
        'overall_average': overall_average,
        'overall_state': overall_state,
        'category_overview': category_overview,
        'category_sections': category_sections,
        'lowest': lowest,
    }



def diag_progress_percent(questions_data):
    total = sum(len(c['subcategories']) for c in questions_data['categories'])
    answered = sum(len(v) for v in session.get('diag_scores', {}).values())
    current = answered + (0 if session.get('diag_stage') == 'complete' else 1)
    return int((current / total) * 100) if total else 0



def bar_chart_svg(items, title='', max_value=3.0, height_per_bar=56, width=940):
    if not items:
        return ''

    left_pad = 230
    right_pad = 60
    top_pad = 44 if title else 18
    bottom_pad = 20
    bar_height = 26
    chart_width = width - left_pad - right_pad
    total_height = top_pad + bottom_pad + len(items) * height_per_bar

    parts = [f"<svg viewBox='0 0 {width} {total_height}' class='chart-svg' role='img' aria-label='{escape_html(title or 'bar chart')}'>"]

    if title:
        parts.append(f"<text x='0' y='22' font-size='20' font-weight='700' fill='#111827'>{escape_html(title)}</text>")

    for tick in range(4):
        x = left_pad + (chart_width * tick / 3)
        parts.append(f"<line x1='{x:.1f}' y1='{top_pad - 8}' x2='{x:.1f}' y2='{total_height - bottom_pad + 2}' stroke='#e5e7eb' stroke-width='1' />")
        parts.append(f"<text x='{x:.1f}' y='{total_height - 2}' text-anchor='middle' font-size='11' fill='#6b7280'>{tick}</text>")

    for idx, item in enumerate(items):
        y = top_pad + idx * height_per_bar
        label_y = y + 18
        bar_y = y + 24
        value = max(0.0, min(max_value, float(item['score'])))
        fill_width = chart_width * (value / max_value)
        label = escape_html(item['label'])
        color = item.get('color') or score_to_color(value)

        parts.append(f"<text x='0' y='{label_y}' font-size='14' fill='#111827'>{label}</text>")
        parts.append(f"<rect x='{left_pad}' y='{bar_y}' width='{chart_width}' height='{bar_height}' rx='8' fill='#e5e7eb' />")
        parts.append(f"<rect x='{left_pad}' y='{bar_y}' width='{fill_width:.1f}' height='{bar_height}' rx='8' fill='{color}' />")
        parts.append(f"<text x='{left_pad + chart_width + 12}' y='{bar_y + 18}' font-size='13' fill='#374151'>{value:.2f}</text>")

    parts.append('</svg>')
    return ''.join(parts)


@business_diag_bp.route('/diag', methods=['GET', 'POST'])
def diag_question():
    if 'context_answers' not in session:
        return redirect(url_for('company.context_page'))

    questions_data = load_json(DIAG_QUESTIONS_FILE)
    if session.get('diag_stage') == 'complete':
        return redirect(url_for('ai.ai_assessment'))

    category, subcategory, current_question = get_current_nodes(questions_data)

    if request.method == 'POST':
        selected = request.form.get('selected_option')
        if selected is None:
            return redirect(url_for('diagnostic.diag_question'))

        option_idx = int(selected)
        option = current_question['options'][option_idx]
        answers = session.get('diag_answers', [])
        answers.append({
            'question_id': current_question.get('id'),
            'question_text': current_question.get('text'),
            'selected_text': option.get('text'),
            'category_id': category['id'],
            'subcategory_id': subcategory['id'],
        })
        session['diag_answers'] = answers

        if session.get('diag_stage') == 'initial':
            session['diag_current_score'] = clamp_score(option.get('score', 0))
        else:
            current = session.get('diag_current_score', 0)
            adjustment = int(option.get('score_adjustment', 0))
            session['diag_current_score'] = clamp_score(current + adjustment)

        advance_diag(questions_data)

        if session.get('diag_stage') == 'complete':
            return redirect(url_for('ai.ai_assessment'))
        return redirect(url_for('diagnostic.diag_question'))

    options_html = []
    for idx, option in enumerate(current_question['options']):
        options_html.append(
            f"<button class='option' type='submit' name='selected_option' value='{idx}'>{escape_html(option['text'])}</button>"
        )

    progress = diag_progress_percent(questions_data)
    total_subcategories = sum(len(c['subcategories']) for c in questions_data['categories'])
    answered = sum(len(v) for v in session.get('diag_scores', {}).values())
    body = f"""
    <div style='background:#eff6ff; border:1px solid #bfdbfe; border-radius:20px; padding:22px;'>
      <div class='card' style='margin-bottom:18px; border:1px solid #bfdbfe; box-shadow:0 10px 24px rgba(29, 78, 216, 0.08);'>
        <h1>{escape_html(session.get('diag_framework_name', 'Business Assessment'))}</h1>
        <p class='muted'>Progress through the assessment one question at a time.</p>
        <div class='progress'><div style='width:{progress}%; background:#2563eb;'></div></div>
        <p class='muted' style='margin-top:10px;'>Area {answered + 1} of {total_subcategories}</p>
      </div>

      <div class='card' style='border:1px solid #bfdbfe; box-shadow:0 10px 24px rgba(29, 78, 216, 0.08);'>
        <h2>{escape_html(current_question['text'])}</h2>
        <form method='post' class='option-wrap'>
          {''.join(options_html)}
        </form>
      </div>
    </div>
    """
    return render_template_string(current_app.config['PAGE_TEMPLATE'], title='Business Diagnostic', body=body)


