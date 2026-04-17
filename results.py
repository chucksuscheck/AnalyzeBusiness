import json
from pathlib import Path

from flask import Blueprint, current_app, redirect, render_template_string, session, url_for

from ai_readiness import (
    AI_QUESTIONS,
    CATEGORY_RECOMMENDATIONS,
    ai_answers_for_display,
    calculate_ai_category_scores,
    determine_maturity,
    weakest_categories,
)
from business_diagnostic import (
    DIAG_QUESTIONS_FILE,
    DIAG_RESULTS_FILE,
    bar_chart_svg,
    build_diag_report,
    load_json,
    score_to_color,
)
from company_info import CONTEXT_QUESTIONS, escape_html


def get_context_answer(answers, qid, default='Not provided'):
    value = answers.get(qid)
    if value is None:
        return default
    if isinstance(value, list):
        return ', '.join(value) if value else default
    return str(value)


def build_company_report_html(context_answers):
    business_type = get_context_answer(context_answers, 'business_type')
    channels = get_context_answer(context_answers, 'channels')
    team_size = get_context_answer(context_answers, 'team_size')
    primary_pain = get_context_answer(context_answers, 'primary_pain')
    secondary_pain = get_context_answer(context_answers, 'secondary_pain')
    time_spent = get_context_answer(context_answers, 'time_spent')
    desired_outcome = get_context_answer(context_answers, 'desired_outcome')

    optional_items = []
    if 'ai_usage' in context_answers:
        optional_items.append(f"<li><strong>Current AI usage:</strong> {escape_html(get_context_answer(context_answers, 'ai_usage'))}</li>")
    if 'tech_comfort' in context_answers:
        optional_items.append(f"<li><strong>Change comfort:</strong> {escape_html(get_context_answer(context_answers, 'tech_comfort'))}</li>")
    if 'work_tracking' in context_answers:
        optional_items.append(f"<li><strong>Work tracking:</strong> {escape_html(get_context_answer(context_answers, 'work_tracking'))}</li>")
    if 'change_comfort' in context_answers:
        optional_items.append(f"<li><strong>Change comfort:</strong> {escape_html(get_context_answer(context_answers, 'change_comfort'))}</li>")

    return f"""
    <div class='card report-section company-section' style='background:#fff9db; border:1px solid #f4e7a1;'>
      <h2>Company Information</h2>
      <p>The company appears to be a <strong>{escape_html(business_type)}</strong> operation with a reported team size of <strong>{escape_html(team_size)}</strong>. Most customer interaction currently happens through <strong>{escape_html(channels)}</strong>, which helps frame the service, communication, and follow-through demands placed on the business.</p>
      <p>The stated operating pressure is led by <strong>{escape_html(primary_pain)}</strong>, with <strong>{escape_html(secondary_pain)}</strong> as a secondary concern. The owner or primary leader is spending the most time on <strong>{escape_html(time_spent)}</strong>, which suggests where management attention is currently being absorbed and where capacity may be constrained.</p>
      <p>In the next 30 days, the business most wants to improve <strong>{escape_html(desired_outcome)}</strong>. That stated near-term objective provides the practical lens for interpreting the diagnostic and readiness results that follow.</p>
      <h3>Reported Operating Profile</h3>
      <ul class='list-tight'>
        <li><strong>Business model:</strong> {escape_html(business_type)}</li>
        <li><strong>Primary interaction channels:</strong> {escape_html(channels)}</li>
        <li><strong>Team size:</strong> {escape_html(team_size)}</li>
        <li><strong>Primary challenge:</strong> {escape_html(primary_pain)}</li>
        <li><strong>Secondary challenge:</strong> {escape_html(secondary_pain)}</li>
        <li><strong>Leadership time concentration:</strong> {escape_html(time_spent)}</li>
        <li><strong>Desired 30-day outcome:</strong> {escape_html(desired_outcome)}</li>
        {''.join(optional_items)}
      </ul>
    </div>
    """

results_bp = Blueprint('results', __name__)


@results_bp.route('/results')
def results_page():
    if session.get('diag_stage') != 'complete':
        return redirect(url_for('diagnostic.diag_question'))
    if 'ai_answers' not in session:
        return redirect(url_for('ai.ai_assessment'))

    diag_questions = load_json(DIAG_QUESTIONS_FILE)
    diag_results = load_json(DIAG_RESULTS_FILE)
    diag_data = build_diag_report(diag_questions, diag_results)

    context_answers = session.get('context_answers', {})
    ai_answers = session.get('ai_answers', {})

    ai_total_score = sum(ai_answers.values())
    ai_max_score = len(AI_QUESTIONS) * 3
    ai_maturity = determine_maturity(ai_total_score)
    ai_category_scores = calculate_ai_category_scores(ai_answers)
    ai_category_maxes = {}
    for q in AI_QUESTIONS:
        ai_category_maxes[q['category']] = ai_category_maxes.get(q['category'], 0) + 3
    weakest = weakest_categories(ai_category_scores)

    company_report_html = build_company_report_html(context_answers)

    ai_chart_items = [
        {
            'label': cat,
            'score': round(score / 3, 2) if False else round(score / max(1, len([q for q in AI_QUESTIONS if q['category'] == cat])) , 2),
            'color': score_to_color(round(score / max(1, len([q for q in AI_QUESTIONS if q['category'] == cat])) , 2)),
        }
        for cat, score in ai_category_scores.items()
    ]
    ai_overview_chart = bar_chart_svg(ai_chart_items, title='AI Readiness Category Scores')

    preface_html = f"""
    <div class='card report-section intro-section' style='background:#fafafa;'>
      <h1>Assessment Results</h1>
      <p class='muted'>Company information is summarized first, followed by the AI readiness summary, the business diagnostic summary, and the detailed diagnostic findings.</p>
    </div>

    {company_report_html}
    """

    ai_summary_html = f"""
    <div class='card report-section ai-section' style='background:#edf9ee; border:1px solid #cfead3;'>
      <h2>AI Readiness Summary</h2>
      <p><strong>Total Score:</strong> {ai_total_score} / {ai_max_score}</p>
      <p><strong>Maturity:</strong> {escape_html(ai_maturity['name'])}</p>
      <p>{escape_html(ai_maturity['narrative'])}</p>
      <h3>Category Scores</h3>
      <ul class='list-tight'>
        {''.join(f"<li><strong>{escape_html(cat)}</strong>: {score} / {ai_category_maxes.get(cat, 0)}</li>" for cat, score in ai_category_scores.items())}
      </ul>
      <div class='legend'>
        <span class='low'>Needs attention</span>
        <span class='mid'>Developing</span>
        <span class='high'>Stronger</span>
      </div>
      {ai_overview_chart}
      <h3>Top Areas to Improve</h3>
      {''.join(f"<p><strong>{escape_html(cat)}</strong> ({score} / {ai_category_maxes.get(cat, 0)})</p><ul class='list-tight'>" + ''.join(f"<li>{escape_html(rec)}</li>" for rec in CATEGORY_RECOMMENDATIONS.get(cat, [])) + '</ul>' for cat, score in weakest[:2])}
      <h3>Recommended Next Steps</h3>
      <ul class='list-tight'>{''.join(f"<li>{escape_html(step)}</li>" for step in ai_maturity['next_steps'])}</ul>
    </div>
    """

    overview_chart = bar_chart_svg(diag_data['category_overview'], title='Category Scores')

    category_sections_html = []
    detail_shades = [
        ('#eef6ff', '#dbeafe'),
        ('#e7f0ff', '#cfe0ff'),
        ('#deebff', '#bfd7ff'),
        ('#d6e7ff', '#aecfff'),
        ('#cfe1ff', '#9fc4fb'),
        ('#c8dcff', '#93bcf5'),
    ]
    for idx, section in enumerate(diag_data['category_sections']):
        bg_color, border_color = detail_shades[min(idx, len(detail_shades)-1)]
        sub_items = [
            {'label': sub['subcategory_label'], 'score': sub['score'], 'color': score_to_color(sub['score'])}
            for sub in section['subcategories']
        ]
        sub_chart = bar_chart_svg(sub_items, title=f"{section['label']} Subcategory Scores")

        sub_blocks = []
        for sub in section['subcategories']:
            sub_blocks.append(f"""
            <div class='sub-block' style='background:rgba(255,255,255,0.45); border:1px solid rgba(255,255,255,0.55);'>
              <h3>{escape_html(sub['subcategory_label'])}</h3>
              <p><span class='pill'>Score {sub['score']} · {escape_html(sub['rating_label'])}</span></p>
              <p class='muted'>{escape_html(sub['subcategory_description'])}</p>
              <p><strong>What is happening:</strong> {escape_html(sub['what_is_happening'])}</p>
              <p><strong>Why it happens:</strong> {escape_html(sub['why_it_happens'])}</p>
              <p><strong>What it is costing:</strong> {escape_html(sub['what_it_is_costing'])}</p>
              <p><strong>What is preventing maturity:</strong> {escape_html(sub['what_is_preventing_maturity'])}</p>
            </div>
            """)

        category_sections_html.append(f"""
        <div class='card section report-section diagnostic-detail-section' style='background:{bg_color}; border:1px solid {border_color};'>
          <h2>{escape_html(section['label'])}</h2>
          <p class='muted'>{escape_html(section['description'])}</p>
          <p><span class='pill'>Category average {section['average']:.2f}</span></p>
          {sub_chart}
          {''.join(sub_blocks)}
        </div>
        """)

    direction_html = ''.join(
        f"<li>{escape_html(item)}</li>" for item in diag_data['overall_state'].get('direction', [])
    )
    lowest_html = ''.join(
        f"<li><strong>{escape_html(item['category_label'])} — {escape_html(item['subcategory_label'])}</strong>: score {item['score']}</li>"
        for item in diag_data['lowest']
    )

    body = f"""
    {preface_html}

    {ai_summary_html}

    <div class='card report-section diagnostic-summary-section' style='background:#f3f8ff; border:1px solid #d6e6ff;'>
      <h2>Business Diagnostic Summary</h2>
      <div class='stat-grid'>
        <div class='stat'><div class='muted'>Overall average</div><div class='score'>{diag_data['overall_average']:.2f}</div></div>
        <div class='stat'><div class='muted'>Business state</div><div class='score' style='font-size:1.35rem'>{escape_html(diag_data['overall_state']['name'])}</div></div>
      </div>
      <p style='margin-top:18px;'>{escape_html(diag_data['overall_state']['narrative'])}</p>
      <h3>Recommended Direction</h3>
      <ul class='list-tight'>{direction_html}</ul>
      <h3>Priority Needs</h3>
      <ul class='list-tight'>{lowest_html}</ul>
      <div class='legend'>
        <span class='low'>Needs attention</span>
        <span class='mid'>Developing</span>
        <span class='high'>Stronger</span>
      </div>
      {overview_chart}
    </div>

    {''.join(category_sections_html)}
    """
    return render_template_string(current_app.config['PAGE_TEMPLATE'], title='Assessment Results', body=body)
