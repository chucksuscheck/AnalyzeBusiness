import json
import secrets
from pathlib import Path
from statistics import mean
from typing import Any, Dict, List

from flask import Flask, request, redirect, render_template_string, session, url_for

BASE_DIR = Path(__file__).resolve().parent
CONTEXT_FILE = BASE_DIR / "context.json"
AI_QUESTIONS_FILE = BASE_DIR / "questions.json"
DIAG_QUESTIONS_FILE = BASE_DIR / "adaptive_questions.json"
DIAG_RESULTS_FILE = BASE_DIR / "businessresults.json"

app = Flask(__name__)
app.secret_key = secrets.token_hex(16)


# ----------------------------
# Generic helpers
# ----------------------------
def load_json(path: Path):
    if not path.exists():
        raise FileNotFoundError(f"Missing required file: {path.name}")
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def escape_html(value: Any) -> str:
    text = str(value)
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def score_to_color(score: float) -> str:
    if score < 1.5:
        return "#dc2626"
    if score < 2.5:
        return "#f59e0b"
    return "#16a34a"


def clamp_score(score: int) -> int:
    return max(0, min(3, int(score)))


# ----------------------------
# Load and validate appBusines inputs
# ----------------------------
def load_context_questions(file_path: Path) -> List[Dict[str, Any]]:
    questions = load_json(file_path)
    if not isinstance(questions, list):
        raise ValueError("context.json must contain a JSON array.")

    required_fields = {"id", "type", "question", "options"}
    allowed_types = {"single_select", "multi_select"}
    for idx, q in enumerate(questions, start=1):
        missing = required_fields - set(q.keys())
        if missing:
            raise ValueError(f"Context question #{idx} is missing fields: {sorted(missing)}")
        if q["type"] not in allowed_types:
            raise ValueError(f"Context question #{idx} has invalid type: {q['type']}")
    return questions



def load_ai_questions(file_path: Path) -> List[Dict[str, Any]]:
    questions = load_json(file_path)
    if not isinstance(questions, list):
        raise ValueError("questions.json must contain a JSON array.")

    required_fields = {"id", "category", "text", "options"}
    for idx, q in enumerate(questions, start=1):
        missing = required_fields - set(q.keys())
        if missing:
            raise ValueError(f"AI question #{idx} is missing fields: {sorted(missing)}")
        if not isinstance(q["options"], list) or len(q["options"]) != 4:
            raise ValueError(f"AI question #{idx} must have exactly 4 options.")
    return questions


CONTEXT_QUESTIONS = load_context_questions(CONTEXT_FILE)
AI_QUESTIONS = load_ai_questions(AI_QUESTIONS_FILE)

MATURITY_LEVELS = [
    {
        "name": "Level 1: Unaware / At Risk",
        "min_score": 0,
        "max_score": 9,
        "narrative": (
            "AI is either not being used or is being used informally without structure. "
            "This creates both missed opportunities and unnecessary risk. Immediate focus "
            "should be on understanding where AI can provide value and establishing basic safeguards."
        ),
        "next_steps": [
            "Identify 2-3 safe, high-value use cases.",
            "Establish basic usage guidelines.",
            "Create awareness of common AI risks and limitations.",
        ],
    },
    {
        "name": "Level 2: Experimenting",
        "min_score": 10,
        "max_score": 18,
        "narrative": (
            "AI is being explored, but usage is fragmented and lacks consistency. "
            "Without structure, results will remain uneven and difficult to scale. "
            "The next step is to move from experimentation to repeatable processes."
        ),
        "next_steps": [
            "Standardize 1-2 workflows.",
            "Introduce basic governance.",
            "Begin tracking practical business outcomes.",
        ],
    },
    {
        "name": "Level 3: Operational",
        "min_score": 19,
        "max_score": 27,
        "narrative": (
            "AI is delivering value in specific areas of the business. "
            "The opportunity now is to expand and optimize these capabilities while "
            "strengthening governance and consistency."
        ),
        "next_steps": [
            "Expand successful use cases.",
            "Improve measurement and scaling.",
            "Strengthen governance and documentation.",
        ],
    },
    {
        "name": "Level 4: Strategic",
        "min_score": 28,
        "max_score": 36,
        "narrative": (
            "AI is being used as a strategic capability within the business. "
            "The focus should now shift toward optimization, innovation, and maintaining "
            "control as usage expands."
        ),
        "next_steps": [
            "Optimize mature workflows.",
            "Explore advanced use cases.",
            "Maintain governance discipline as adoption expands.",
        ],
    },
]

CATEGORY_RECOMMENDATIONS = {
    "Awareness": [
        "Clarify where AI can create value in the business.",
        "Identify and rank the top use cases by impact and feasibility.",
        "Create simple criteria for evaluating AI tools.",
    ],
    "Usage": [
        "Move from isolated experimentation to shared practices.",
        "Define 1-2 repeatable AI-enabled workflows.",
        "Measure outcomes such as time saved, quality improved, or cost reduced.",
    ],
    "Risk & Governance": [
        "Create basic acceptable-use guidance for AI.",
        "Define how sensitive data may and may not be used with AI tools.",
        "Educate staff on hallucination, bias, privacy, and compliance risks.",
    ],
    "Process & Integration": [
        "Embed AI into actual workflows rather than one-off usage.",
        "Document prompts, tasks, and review steps for repeatability.",
        "Prioritize new AI opportunities using business value and risk.",
    ],
}


def determine_maturity(total_score: int) -> Dict[str, Any]:
    for level in MATURITY_LEVELS:
        if level["min_score"] <= total_score <= level["max_score"]:
            return level
    return MATURITY_LEVELS[-1]


# ----------------------------
# appBusines helpers
# ----------------------------
def parse_context_answers(form_data) -> Dict[str, Any]:
    answers: Dict[str, Any] = {}
    for q in CONTEXT_QUESTIONS:
        qid = q["id"]
        options = q["options"]
        if q["type"] == "multi_select":
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
        answer = saved_answers.get(q["id"])
        if answer is None:
            continue
        if isinstance(answer, list):
            answer_text = ", ".join(answer)
        else:
            answer_text = str(answer)
        summary.append(f"{q['question']}: {answer_text}")
    return summary



def parse_ai_answers(form_data) -> Dict[int, int]:
    answers: Dict[int, int] = {}
    for q in AI_QUESTIONS:
        raw = form_data.get(f"q{q['id']}")
        if raw is None:
            raise ValueError("Please answer every AI readiness question.")
        idx = int(raw)
        if idx < 0 or idx >= len(q["options"]):
            raise ValueError(f"Invalid answer for AI question {q['id']}")
        answers[q["id"]] = idx
    return answers



def calculate_ai_category_scores(responses: Dict[int, int]) -> Dict[str, int]:
    scores: Dict[str, int] = {}
    for q in AI_QUESTIONS:
        category = q["category"]
        scores.setdefault(category, 0)
        scores[category] += responses.get(q["id"], 0)
    return scores



def weakest_categories(category_scores: Dict[str, int]) -> List[Any]:
    return sorted(category_scores.items(), key=lambda item: item[1])



def ai_answers_for_display(responses: Dict[int, int]) -> List[Dict[str, str]]:
    items = []
    for q in AI_QUESTIONS:
        selected_idx = responses.get(q["id"])
        if selected_idx is None:
            continue
        items.append({
            "category": q["category"],
            "question": q["text"],
            "answer": q["options"][selected_idx],
        })
    return items


# ----------------------------
# DIAGBCBasic helpers
# ----------------------------
def initialize_diag_session(questions_data):
    session["diag_framework_name"] = questions_data.get("framework_name", "Business Assessment")
    session["diag_stage"] = "initial"
    session["diag_current_category_index"] = 0
    session["diag_current_subcategory_index"] = 0
    session["diag_current_followup_index"] = 0
    session["diag_current_score"] = None
    session["diag_scores"] = {}
    session["diag_answers"] = []



def get_current_nodes(questions_data):
    c_idx = session.get("diag_current_category_index", 0)
    s_idx = session.get("diag_current_subcategory_index", 0)
    category = questions_data["categories"][c_idx]
    subcategory = category["subcategories"][s_idx]

    if session.get("diag_stage") == "initial":
        question = subcategory["initial_question"]
    else:
        current_score = str(session.get("diag_current_score", 0))
        followups = subcategory.get("follow_ups", {}).get(current_score, [])
        f_idx = session.get("diag_current_followup_index", 0)
        question = followups[f_idx]
    return category, subcategory, question



def save_subcategory_score(category_id, subcategory_id, score):
    scores = session.get("diag_scores", {})
    scores.setdefault(category_id, {})
    scores[category_id][subcategory_id] = clamp_score(score)
    session["diag_scores"] = scores



def advance_diag(questions_data):
    c_idx = session.get("diag_current_category_index", 0)
    s_idx = session.get("diag_current_subcategory_index", 0)
    category = questions_data["categories"][c_idx]
    subcategory = category["subcategories"][s_idx]

    if session.get("diag_stage") == "initial":
        followups = subcategory.get("follow_ups", {}).get(str(session.get("diag_current_score", 0)), [])
        if followups:
            session["diag_stage"] = "followup"
            session["diag_current_followup_index"] = 0
            return
        save_subcategory_score(category["id"], subcategory["id"], session.get("diag_current_score", 0))
    else:
        current_score = session.get("diag_current_score", 0)
        followups = subcategory.get("follow_ups", {}).get(str(current_score), [])
        next_fidx = session.get("diag_current_followup_index", 0) + 1
        if next_fidx < len(followups):
            session["diag_current_followup_index"] = next_fidx
            return
        save_subcategory_score(category["id"], subcategory["id"], current_score)

    if s_idx + 1 < len(category["subcategories"]):
        session["diag_current_subcategory_index"] += 1
    else:
        if c_idx + 1 < len(questions_data["categories"]):
            session["diag_current_category_index"] += 1
            session["diag_current_subcategory_index"] = 0
        else:
            session["diag_stage"] = "complete"
            return

    session["diag_stage"] = "initial"
    session["diag_current_followup_index"] = 0
    session["diag_current_score"] = None



def get_overall_state(avg_score, results_data):
    for state in results_data["overall_business_states"]:
        if state["min_average"] <= avg_score <= state["max_average"]:
            return state
    return results_data["overall_business_states"][-1]



def build_subcategory_report(category, subcategory, score, results_data):
    category_result = results_data["categories"][category["id"]]
    sub_result = category_result["subcategories"][subcategory["id"]]
    rating = sub_result["ratings"][str(score)]
    scale = results_data["rating_scale"][str(score)]
    return {
        "category_id": category["id"],
        "category_label": category["label"],
        "subcategory_id": subcategory["id"],
        "subcategory_label": subcategory["label"],
        "subcategory_description": sub_result.get("description", ""),
        "score": score,
        "rating_label": scale["label"],
        "rating_summary": scale["summary"],
        "what_is_happening": rating["what_is_happening"],
        "why_it_happens": rating["why_it_happens"],
        "what_it_is_costing": rating["what_it_is_costing"],
        "what_is_preventing_maturity": rating["what_is_preventing_maturity"],
    }



def build_diag_report(questions_data, results_data):
    saved_scores = session.get("diag_scores", {})
    category_sections = []
    category_overview = []
    all_sub_reports = []

    for category in questions_data["categories"]:
        sub_reports = []
        sub_scores = []
        for subcategory in category["subcategories"]:
            raw_score = saved_scores.get(category["id"], {}).get(subcategory["id"], 0)
            score = clamp_score(raw_score)
            sub_scores.append(score)
            sub_report = build_subcategory_report(category, subcategory, score, results_data)
            sub_reports.append(sub_report)
            all_sub_reports.append(sub_report)

        category_average = round(mean(sub_scores), 2) if sub_scores else 0.0
        category_sections.append({
            "id": category["id"],
            "label": category["label"],
            "description": results_data["categories"][category["id"]].get("description", ""),
            "average": category_average,
            "color": score_to_color(category_average),
            "subcategories": sub_reports,
        })
        category_overview.append({
            "id": category["id"],
            "label": category["label"],
            "score": category_average,
            "color": score_to_color(category_average),
        })

    overall_average = round(mean([item["score"] for item in category_overview]), 2) if category_overview else 0.0
    overall_state = get_overall_state(overall_average, results_data)
    min_score = min((item["score"] for item in all_sub_reports), default=0)
    lowest = [item for item in all_sub_reports if item["score"] == min_score][:3]

    return {
        "overall_average": overall_average,
        "overall_state": overall_state,
        "category_overview": category_overview,
        "category_sections": category_sections,
        "lowest": lowest,
    }



def diag_progress_percent(questions_data):
    total = sum(len(c["subcategories"]) for c in questions_data["categories"])
    answered = sum(len(v) for v in session.get("diag_scores", {}).values())
    current = answered + (0 if session.get("diag_stage") == "complete" else 1)
    return int((current / total) * 100) if total else 0



def bar_chart_svg(items, title="", max_value=3.0, height_per_bar=56, width=940):
    if not items:
        return ""

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
        value = max(0.0, min(max_value, float(item["score"])))
        fill_width = chart_width * (value / max_value)
        label = escape_html(item["label"])
        color = item.get("color") or score_to_color(value)

        parts.append(f"<text x='0' y='{label_y}' font-size='14' fill='#111827'>{label}</text>")
        parts.append(f"<rect x='{left_pad}' y='{bar_y}' width='{chart_width}' height='{bar_height}' rx='8' fill='#e5e7eb' />")
        parts.append(f"<rect x='{left_pad}' y='{bar_y}' width='{fill_width:.1f}' height='{bar_height}' rx='8' fill='{color}' />")
        parts.append(f"<text x='{left_pad + chart_width + 12}' y='{bar_y + 18}' font-size='13' fill='#374151'>{value:.2f}</text>")

    parts.append("</svg>")
    return "".join(parts)


# ----------------------------
# Templates
# ----------------------------
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


# ----------------------------
# Routes
# ----------------------------
@app.route("/")
def index():
    try:
        load_json(CONTEXT_FILE)
        load_json(AI_QUESTIONS_FILE)
        diag_questions = load_json(DIAG_QUESTIONS_FILE)
        load_json(DIAG_RESULTS_FILE)
    except FileNotFoundError as e:
        body = f"<div class='card'><h1>Setup needed</h1><p>{escape_html(e)}</p></div>"
        return render_template_string(PAGE_TEMPLATE, title="Setup needed", body=body), 500

    session.clear()
    initialize_diag_session(diag_questions)

    body = """
    <div class='card'>
      <h1>Combined Business Assessment</h1>
      <p class='muted'>This app first captures the business and AI readiness questions from appBusines.py, then continues into the DIAGBCBasic business diagnostic.</p>
      <p>The final results page begins with the appBusines answers and then preserves the DIAGBCBasic display underneath.</p>
      <a class='btn' href='{}'>Start assessment</a>
    </div>
    """.format(url_for("context_page"))
    return render_template_string(PAGE_TEMPLATE, title="Combined Assessment", body=body)


@app.route("/context", methods=["GET", "POST"])
def context_page():
    error = ""
    if request.method == "POST":
        try:
            answers = parse_context_answers(request.form)
            session["context_answers"] = answers
            return redirect(url_for("ai_assessment"))
        except ValueError as exc:
            error = str(exc)

    saved_answers = session.get("context_answers", {})
    blocks = []
    for idx, q in enumerate(CONTEXT_QUESTIONS, start=1):
        options = []
        if q["type"] == "multi_select":
            selected_values = set(saved_answers.get(q["id"], []))
            for option in q["options"]:
                checked = "checked" if option in selected_values else ""
                options.append(
                    f"<div class='context-option'><label><input type='checkbox' name='{escape_html(q['id'])}' value='{escape_html(option)}' {checked}> {escape_html(option)}</label></div>"
                )
        else:
            selected_value = saved_answers.get(q["id"])
            for option in q["options"]:
                checked = "checked" if selected_value == option else ""
                options.append(
                    f"<div class='context-option'><label><input type='radio' name='{escape_html(q['id'])}' value='{escape_html(option)}' required {checked}> {escape_html(option)}</label></div>"
                )

        blocks.append(
            f"<div class='card field-card'><h3>{idx}. {escape_html(q['question'])}</h3>{''.join(options)}</div>"
        )

    body = f"""
    <div class='card'>
      <h1>Business Context</h1>
      <p class='muted'>Answer these business questions first. After that, you will continue to the AI readiness evaluation.</p>
      {'<div class="error">' + escape_html(error) + '</div>' if error else ''}
      <form method='post'>
        {''.join(blocks)}
        <button type='submit'>Continue to AI Evaluation</button>
      </form>
    </div>
    """
    return render_template_string(PAGE_TEMPLATE, title="Business Context", body=body)


@app.route("/ai", methods=["GET", "POST"])
def ai_assessment():
    if "context_answers" not in session:
        return redirect(url_for("context_page"))

    error = ""
    if request.method == "POST":
        try:
            ai_answers = parse_ai_answers(request.form)
            session["ai_answers"] = ai_answers
            return redirect(url_for("diag_question"))
        except ValueError as exc:
            error = str(exc)

    saved_answers = session.get("ai_answers", {})
    context_summary = build_context_summary(session.get("context_answers", {}))
    blocks = []
    for q in AI_QUESTIONS:
        options = []
        for idx, option in enumerate(q["options"]):
            checked = "checked" if str(saved_answers.get(q["id"], "")) == str(idx) else ""
            options.append(
                f"<div class='context-option'><label><input type='radio' name='q{q['id']}' value='{idx}' required {checked}> {escape_html(option)}</label></div>"
            )
        blocks.append(
            f"<div class='card field-card'><div class='muted'><strong>{escape_html(q['category'])}</strong></div><h3>Question {q['id']}</h3><p>{escape_html(q['text'])}</p>{''.join(options)}</div>"
        )

    context_list = "".join(f"<li>{escape_html(item)}</li>" for item in context_summary)
    body = f"""
    <div class='card'>
      <h1>AI Readiness Assessment</h1>
      <p class='muted'>This 12-question assessment helps identify your organization's current AI maturity.</p>
      <div class='sub-block'>
        <strong>Business context captured</strong>
        <ul class='list-tight'>{context_list}</ul>
      </div>
      {'<div class="error">' + escape_html(error) + '</div>' if error else ''}
      <form method='post'>
        {''.join(blocks)}
        <button type='submit'>Continue to DIAGBCBasic</button>
      </form>
    </div>
    """
    return render_template_string(PAGE_TEMPLATE, title="AI Readiness Assessment", body=body)


@app.route("/diag", methods=["GET", "POST"])
def diag_question():
    if "ai_answers" not in session:
        return redirect(url_for("ai_assessment"))

    questions_data = load_json(DIAG_QUESTIONS_FILE)
    if session.get("diag_stage") == "complete":
        return redirect(url_for("report"))

    category, subcategory, current_question = get_current_nodes(questions_data)

    if request.method == "POST":
        selected = request.form.get("selected_option")
        if selected is None:
            return redirect(url_for("diag_question"))

        option_idx = int(selected)
        option = current_question["options"][option_idx]
        answers = session.get("diag_answers", [])
        answers.append({
            "question_id": current_question.get("id"),
            "question_text": current_question.get("text"),
            "selected_text": option.get("text"),
            "category_id": category["id"],
            "subcategory_id": subcategory["id"],
        })
        session["diag_answers"] = answers

        if session.get("diag_stage") == "initial":
            session["diag_current_score"] = clamp_score(option.get("score", 0))
        else:
            current = session.get("diag_current_score", 0)
            adjustment = int(option.get("score_adjustment", 0))
            session["diag_current_score"] = clamp_score(current + adjustment)

        advance_diag(questions_data)

        if session.get("diag_stage") == "complete":
            return redirect(url_for("report"))
        return redirect(url_for("diag_question"))

    options_html = []
    for idx, option in enumerate(current_question["options"]):
        options_html.append(
            f"<button class='option' type='submit' name='selected_option' value='{idx}'>{escape_html(option['text'])}</button>"
        )

    progress = diag_progress_percent(questions_data)
    total_subcategories = sum(len(c["subcategories"]) for c in questions_data["categories"])
    answered = sum(len(v) for v in session.get("diag_scores", {}).values())
    body = f"""
    <div class='card'>
      <h1>{escape_html(session.get('diag_framework_name', 'Business Assessment'))}</h1>
      <p class='muted'>Progress through the assessment one question at a time.</p>
      <div class='progress'><div style='width:{progress}%'></div></div>
      <p class='muted' style='margin-top:10px;'>Area {answered + 1} of {total_subcategories}</p>
    </div>

    <div class='card'>
      <h2>{escape_html(current_question['text'])}</h2>
      <form method='post' class='option-wrap'>
        {''.join(options_html)}
      </form>
    </div>
    """
    return render_template_string(PAGE_TEMPLATE, title="Business Diagnostic", body=body)


@app.route("/report")
def report():
    if session.get("diag_stage") != "complete":
        return redirect(url_for("diag_question"))

    diag_questions = load_json(DIAG_QUESTIONS_FILE)
    diag_results = load_json(DIAG_RESULTS_FILE)
    diag_data = build_diag_report(diag_questions, diag_results)

    context_answers = session.get("context_answers", {})
    ai_answers = session.get("ai_answers", {})

    context_list_items = []
    for q in CONTEXT_QUESTIONS:
        answer = context_answers.get(q["id"])
        if answer is None:
            continue
        answer_text = ", ".join(answer) if isinstance(answer, list) else str(answer)
        context_list_items.append(f"<li><strong>{escape_html(q['question'])}</strong>: {escape_html(answer_text)}</li>")

    ai_display = ai_answers_for_display(ai_answers)
    ai_list_items = [
        f"<li><strong>{escape_html(item['category'])}</strong> — {escape_html(item['question'])}: {escape_html(item['answer'])}</li>"
        for item in ai_display
    ]

    ai_total_score = sum(ai_answers.values())
    ai_max_score = len(AI_QUESTIONS) * 3
    ai_maturity = determine_maturity(ai_total_score)
    ai_category_scores = calculate_ai_category_scores(ai_answers)
    ai_category_maxes = {}
    for q in AI_QUESTIONS:
        ai_category_maxes[q['category']] = ai_category_maxes.get(q['category'], 0) + 3
    weakest = weakest_categories(ai_category_scores)

    preface_html = f"""
    <div class='card'>
      <h1>appBusines Answers</h1>
      <p class='muted'>These answers were captured before the DIAGBCBasic diagnostic.</p>
    </div>

    <div class='card'>
      <h2>Business Context Answers</h2>
      <ul class='list-tight'>{''.join(context_list_items)}</ul>
    </div>

    <div class='card'>
      <h2>AI Readiness Answers</h2>
      <ul class='list-tight'>{''.join(ai_list_items)}</ul>
    </div>

    <div class='card'>
      <h2>AI Readiness Summary</h2>
      <p><strong>Total Score:</strong> {ai_total_score} / {ai_max_score}</p>
      <p><strong>Maturity:</strong> {escape_html(ai_maturity['name'])}</p>
      <p>{escape_html(ai_maturity['narrative'])}</p>
      <h3>Category Scores</h3>
      <ul class='list-tight'>
        {''.join(f"<li><strong>{escape_html(cat)}</strong>: {score} / {ai_category_maxes.get(cat, 0)}</li>" for cat, score in ai_category_scores.items())}
      </ul>
      <h3>Top Areas to Improve</h3>
      {''.join(f"<p><strong>{escape_html(cat)}</strong> ({score} / {ai_category_maxes.get(cat, 0)})</p><ul class='list-tight'>" + ''.join(f"<li>{escape_html(rec)}</li>" for rec in CATEGORY_RECOMMENDATIONS.get(cat, [])) + "</ul>" for cat, score in weakest[:2])}
      <h3>Recommended Next Steps</h3>
      <ul class='list-tight'>{''.join(f"<li>{escape_html(step)}</li>" for step in ai_maturity['next_steps'])}</ul>
    </div>
    """

    # Preserve DIAGBCBasic report layout underneath.
    overview_chart = bar_chart_svg(diag_data["category_overview"], title="Category Scores")

    category_sections_html = []
    for section in diag_data["category_sections"]:
        sub_items = [
            {"label": sub["subcategory_label"], "score": sub["score"], "color": score_to_color(sub["score"])}
            for sub in section["subcategories"]
        ]
        sub_chart = bar_chart_svg(sub_items, title=f"{section['label']} Subcategory Scores")

        sub_blocks = []
        for sub in section["subcategories"]:
            sub_blocks.append(f"""
            <div class='sub-block'>
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
        <div class='card section'>
          <h2>{escape_html(section['label'])}</h2>
          <p class='muted'>{escape_html(section['description'])}</p>
          <p><span class='pill'>Category average {section['average']:.2f}</span></p>
          {sub_chart}
          {''.join(sub_blocks)}
        </div>
        """)

    direction_html = "".join(
        f"<li>{escape_html(item)}</li>" for item in diag_data["overall_state"].get("direction", [])
    )
    lowest_html = "".join(
        f"<li><strong>{escape_html(item['category_label'])} — {escape_html(item['subcategory_label'])}</strong>: score {item['score']}</li>"
        for item in diag_data["lowest"]
    )

    diag_body = f"""
    <div class='card'>
      <h1>Assessment Results</h1>
      <div class='stat-grid'>
        <div class='stat'>
          <div class='muted'>Overall average</div>
          <div class='score'>{diag_data['overall_average']:.2f}</div>
        </div>
        <div class='stat'>
          <div class='muted'>Business state</div>
          <div class='score' style='font-size:1.5rem'>{escape_html(diag_data['overall_state']['name'])}</div>
        </div>
      </div>
      <p style='margin-top:18px;'>{escape_html(diag_data['overall_state']['narrative'])}</p>
      <h3>Recommended direction</h3>
      <ul class='list-tight'>{direction_html}</ul>
      <h3 style='margin-top:22px;'>Highest-priority needs</h3>
      <ul class='list-tight'>{lowest_html}</ul>
      <div class='legend'>
        <span class='low'>Needs attention</span>
        <span class='mid'>Developing</span>
        <span class='high'>Stronger</span>
      </div>
    </div>

    <div class='card'>
      {overview_chart}
    </div>

    {''.join(category_sections_html)}

    <div class='card'>
      <a class='btn' href='{url_for('index')}'>Start over</a>
    </div>
    """

    body = preface_html + diag_body
    return render_template_string(PAGE_TEMPLATE, title="Assessment Results", body=body)


if __name__ == "__main__":
    app.run(debug=True)
