# SQL Query Profiler

A command-line tool that analyzes PostgreSQL query performance and gives plain-English suggestions to fix slow queries.

Instead of reading raw `EXPLAIN ANALYZE` output (which is hard to understand), this tool parses it for you and tells you exactly what's wrong and how to fix it.

## Demo

**Before adding an index:**
```
╭─────────────────────────────────╮
│       SQL Query Profiler        │
│  Execution time │ 10.93 ms      │
│  Planning time  │ 0.45 ms       │
│  Rows returned  │ 1             │
╰─────────────────────────────────╯

⚠️  Sequential scan on 'orders' (100,000 rows read)
   PostgreSQL is reading every single row in 'orders' to find your results.
   This is like reading an entire book to find one word.
   → Add an index on the column you're filtering by:
     CREATE INDEX ON orders(user_id);
```

**After adding the index:**
```
╭─────────────────────────────────╮
│       SQL Query Profiler        │
│  Execution time │ 0.61 ms       │
│  Planning time  │ 12.81 ms      │
│  Rows returned  │ 1             │
╰─────────────────────────────────╯

✅ Looks good!
   No obvious performance issues detected in this query.
```

**18x speedup from one line of SQL.**

## Features

- Detects sequential scans on large tables and suggests indexes
- Flags when PostgreSQL's row estimates are way off (stale statistics)
- Identifies slow individual operations within a query
- Saves every query you run to a local history so you can compare over time
- Clean, color-coded terminal output

## Tech Stack

- **Python** — core logic and CLI
- **PostgreSQL** — database being analyzed
- **psycopg2** — PostgreSQL connection
- **Click** — CLI interface
- **Rich** — terminal formatting
- **SQLite** — local query history storage

## Setup

**1. Clone the repo**
```bash
git clone https://github.com/your-username/sql-profiler.git
cd sql-profiler
```

**2. Create a virtual environment**
```bash
python3 -m venv venv
source venv/bin/activate
```

**3. Install dependencies**
```bash
pip install psycopg2-binary click rich python-dotenv
```

**4. Add your database connection**
```bash
cp .env.example .env
```
Then open `.env` and update the connection string:
```
DATABASE_URL=postgresql://localhost/your_database_name
```

## Usage

**Analyze a query:**
```bash
python profiler.py -q "SELECT * FROM orders WHERE user_id = 5"
```

**Or run without a flag and get prompted:**
```bash
python profiler.py
```

**View past queries:**
```bash
python profiler.py --history
```

## What I Learned

- How PostgreSQL's query planner works under the hood
- How to read and parse `EXPLAIN ANALYZE` output
- The difference between sequential scans and index scans, and when each is used
- How database indexes speed up queries and when to add them
- How stale table statistics cause bad query plans
- Building CLI tools with Click and Rich in Python
- Storing persistent data with SQLite

## Future Ideas

- Auto-detect the filter column and suggest the exact index to create
- Support for MySQL and SQLite in addition to PostgreSQL
- Export history to CSV for deeper analysis
- Web UI frontend
