---
name: sentiment-analysis
description: >-
  Perform sentiment analysis on text columns in DuckDB tables, especially news
  and articles. Use when the user asks for sentiment, tone, opinion mining,
  emotional analysis, or journalistic framing of text data.
---

# Sentiment Analysis

## Agent persona

Act as an **expert journalist**: identify tone, bias signals, emotional framing, and narrative stance — not just positive/negative scores.

## SQL execution — always prefer MCP (duckdb_mcp)

The `duckdb_mcp` extension exposes tools (`query`, `describe`, `list_tables`, `export`)
to the AI agent. **Always prefer MCP** for SQL queries — no terminal commands.

### MCP tools available

| Tool | Purpose |
|------|---------|
| `query` | Run SELECT queries (read-only) |
| `describe` | Show table schema |
| `export` | Export query results (json/csv/markdown) |

### Fallback: `db.py run-sql`

Use only for DDL (`CREATE TABLE`, `INSERT`) or when MCP cannot handle the task:

```bash
kill $(lsof -t data/duckdb/datasyn.duckdb 2>/dev/null) 2>/dev/null
uv run python scripts/python/db.py run-sql "SQL..."
```

This connects directly to `data/duckdb/datasyn.duckdb` — not through MCP.

---

## Workflow

1. Identify text column(s) — via MCP `describe` and `query` to profile
2. Choose approach (A: TextBlob Python · B: SQL keyword heuristics)
3. Create sentiment results table — via `db.py run-sql` (DDL)
4. Summarize findings with journalistic language — write to `reports/`

---

## Approach A: TextBlob (Python — fallback, requires direct DB connection)

Only when SQL keyword heuristics are insufficient. Uses `db.connect()` — **not MCP**:

```python
from textblob import TextBlob
import sys
from pathlib import Path
sys.path.insert(0, str(Path("scripts/python").resolve()))
import db
import pandas as pd

con = db.connect()  # direct connection — fallback for Python NLP
df = con.sql("SELECT id, body FROM articles").df()

def analyze(text):
    if not text:
        return None, 0.0, 0.0
    blob = TextBlob(str(text))
    polarity = blob.sentiment.polarity
    subjectivity = blob.sentiment.subjectivity
    if polarity > 0.1:
        label = "positive"
    elif polarity < -0.1:
        label = "negative"
    else:
        label = "neutral"
    return label, polarity, subjectivity

df[["sentiment", "polarity", "subjectivity"]] = df["body"].apply(
    lambda t: pd.Series(analyze(t))
)
con.register("sentiment_df", df)
con.sql("CREATE OR REPLACE TABLE articles_sentiment AS SELECT * FROM sentiment_df")
con.close()
```

---

## Approach B: SQL + keyword heuristics (prefer MCP)

For quick news tone scanning. **Profile data via MCP `query` first**, then create table:

### Step 1: Profile text via MCP

Use MCP `query` to explore the text data:

```sql
SELECT id, SUBSTRING(body, 1, 200) AS preview FROM articles LIMIT 5;
SELECT COUNT(*) FROM articles WHERE body IS NULL OR TRIM(body) = '';
```

### Step 2: Create sentiment table via `db.py run-sql`

```bash
kill $(lsof -t data/duckdb/datasyn.duckdb) 2>/dev/null
uv run python scripts/python/db.py run-sql "
CREATE OR REPLACE TABLE articles_sentiment AS
SELECT *,
  CASE
    WHEN regexp_matches(lower(body), '(crisis|scandal|attack|fail|loss|fraud|collapse)') THEN 'negative'
    WHEN regexp_matches(lower(body), '(success|growth|win|breakthrough|hope|launch|record)') THEN 'positive'
    ELSE 'neutral'
  END AS tone_heuristic
FROM articles;
"
```

### Step 3: Analyze results via MCP

```sql
SELECT tone_heuristic, COUNT(*) AS n,
       ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER(), 1) AS pct
FROM articles_sentiment GROUP BY 1 ORDER BY 2 DESC;

SELECT * FROM articles_sentiment WHERE tone_heuristic = 'negative' LIMIT 5;
```

---

## Journalistic summary template

```markdown
# Sentiment & Tone Analysis

## Overall tone distribution
[positive / neutral / negative counts and %]

## Dominant narratives
- [Theme 1]: predominantly [tone], example headline
- [Theme 2]: ...

## Framing signals
- Emotional language, certainty, attribution patterns

## Caveats
- Method limitations, language bias, sample size
```

---

## Validation (via MCP)

```sql
SELECT tone_heuristic, COUNT(*) AS n FROM articles_sentiment GROUP BY 1 ORDER BY 2 DESC;
SELECT * FROM articles_sentiment LIMIT 10;
```
