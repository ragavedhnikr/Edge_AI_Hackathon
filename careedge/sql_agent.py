"""Question -> SQL -> rows, using the chat model (Qwen2.5-7B) with the schema and worked examples
in the prompt (no training). Every query is validated and run read-only."""
import re
from dataclasses import dataclass, field
from datetime import date

import models
import patient_db

SQL_PROMPT = """You write SQLite queries for a care home's patient database.

Schema:
{schema}

Residents: {residents}
Today's date is {today}. Use date('now') for today.

Rules:
- Reply with ONE SQLite SELECT statement and nothing else.
- Match residents by name with LIKE, e.g. r.name LIKE '%Lakshmi%'.
- Current medications have status = 'active'.
- medications.times is text such as '08:00, 20:00'; find a time with LIKE '%22:00%'.
- Always include the resident's name in the output columns.
- If the question cannot be answered from these tables, reply with: SELECT 'not in database' AS note

Examples:
Q: What medications is Lakshmi taking?
SELECT r.name, m.drug, m.dose, m.times, m.purpose FROM medications m JOIN residents r ON r.id = m.resident_id WHERE r.name LIKE '%Lakshmi%' AND m.status = 'active';

Q: Which residents get medication at 22:00?
SELECT r.name, r.room, m.drug, m.dose FROM medications m JOIN residents r ON r.id = m.resident_id WHERE m.status = 'active' AND m.times LIKE '%22:00%' ORDER BY r.room;

Q: What was Joseph's average blood pressure over the last 7 days?
SELECT r.name, ROUND(AVG(v.systolic)) AS avg_systolic, ROUND(AVG(v.diastolic)) AS avg_diastolic, COUNT(*) AS readings FROM vitals v JOIN residents r ON r.id = v.resident_id WHERE r.name LIKE '%Joseph%' AND v.date >= date('now', '-7 days');

Q: When is Maria's next appointment?
SELECT r.name, a.date, a.time, a.type, a.provider, a.location FROM appointments a JOIN residents r ON r.id = a.resident_id WHERE r.name LIKE '%Maria%' AND a.date >= date('now') ORDER BY a.date, a.time LIMIT 1;

Q: Is Robert allergic to anything?
SELECT r.name, a.allergen, a.reaction, a.severity, a.avoid, a.emergency_medication FROM residents r LEFT JOIN allergies a ON a.resident_id = r.id WHERE r.name LIKE '%Robert%';
"""

FORBIDDEN = re.compile(r"\b(insert|update|delete|drop|alter|create|attach|detach|pragma|replace"
                       r"|vacuum|reindex|analyze|transaction|commit)\b", re.I)


@dataclass
class SqlResult:
    question: str
    sql: str = ""
    columns: list = field(default_factory=list)
    rows: list = field(default_factory=list)
    error: str = ""
    attempts: int = 0
    gen_ms: float = 0.0
    exec_ms: float = 0.0

    @property
    def ok(self):
        return not self.error


def schema_text():
    return patient_db.SCHEMA.strip()


def extract_sql(text):
    text = models.strip_thinking(text)
    block = re.search(r"```(?:sql)?\s*(.*?)```", text, re.S | re.I)
    if block:
        text = block.group(1)
    m = re.search(r"\b(select|with)\b.*", text, re.S | re.I)
    sql = (m.group(0) if m else text).strip()
    return sql.split(";")[0].strip()  # one statement only


def validate(sql):
    if not re.match(r"^\s*(select|with)\b", sql, re.I):
        raise patient_db.QueryError("only SELECT queries are allowed")
    if FORBIDDEN.search(sql):
        raise patient_db.QueryError("query contains a forbidden keyword")


def query(question, resident_hint=None):
    """Generate, validate and run SQL. One retry with the error message."""
    names = ", ".join(f"{r['name']} (room {r['room']})" for r in patient_db.residents())
    system = SQL_PROMPT.format(schema=schema_text(), residents=names,
                               today=date.today().isoformat())
    user = question
    if resident_hint:
        user += f"\n(The caregiver has {resident_hint['name']} selected.)"
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    result = SqlResult(question=question)

    for attempt in (1, 2):
        result.attempts = attempt
        reply = models.chat(messages, max_tokens=300, temperature=0)
        result.gen_ms += reply.ms
        result.sql = extract_sql(reply.text)
        try:
            validate(result.sql)
            result.columns, result.rows, result.exec_ms = patient_db.run_readonly(result.sql)
            result.error = ""
            return result
        except patient_db.QueryError as exc:
            result.error = str(exc)
            messages += [{"role": "assistant", "content": reply.text},
                         {"role": "user", "content": f"That query failed: {exc}. "
                                                     "Reply with one corrected SELECT only."}]
    return result


def rows_as_text(result, limit=50):
    """Compact table text for the answer prompt."""
    if not result.ok:
        return f"(database query failed: {result.error})"
    if not result.rows:
        return "(the query returned no rows)"
    lines = [" | ".join(result.columns)]
    lines += [" | ".join("" if v is None else str(v) for v in row) for row in result.rows[:limit]]
    if len(result.rows) > limit:
        lines.append(f"... {len(result.rows) - limit} more rows")
    return "\n".join(lines)
