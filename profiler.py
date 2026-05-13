import os
import json
import sqlite3
import psycopg2
import click
from datetime import datetime
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box
from dotenv import load_dotenv

load_dotenv()
console = Console()
HISTORY_DB = "history.db"


# ── History (SQLite) ─────────────────────────────────────────────────────────
def init_history():
    """Create the history table if it doesn't exist yet."""
    conn = sqlite3.connect(HISTORY_DB)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS history (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            query       TEXT    NOT NULL,
            exec_time   REAL,
            plan_time   REAL,
            rows        INTEGER,
            warnings    INTEGER,
            ran_at      TEXT    NOT NULL
        )
    """)
    conn.commit()
    conn.close()


def save_to_history(query, exec_time, plan_time, rows, warnings):
    conn = sqlite3.connect(HISTORY_DB)
    conn.execute(
        "INSERT INTO history (query, exec_time, plan_time, rows, warnings, ran_at) VALUES (?,?,?,?,?,?)",
        (query, exec_time, plan_time, rows, warnings, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    )
    conn.commit()
    conn.close()


def show_history():
    conn = sqlite3.connect(HISTORY_DB)
    rows = conn.execute(
        "SELECT id, ran_at, exec_time, warnings, query FROM history ORDER BY id DESC LIMIT 20"
    ).fetchall()
    conn.close()

    if not rows:
        console.print("[yellow]No history yet. Run a query first![/yellow]")
        return

    table = Table(box=box.ROUNDED, show_header=True, header_style="bold cyan")
    table.add_column("#",         style="dim",    width=4)
    table.add_column("Ran at",    style="cyan",   width=20)
    table.add_column("Time (ms)", style="green",  width=10)
    table.add_column("Warnings",  style="yellow", width=10)
    table.add_column("Query",     style="white",  no_wrap=False)

    for row in rows:
        id_, ran_at, exec_time, warnings, query = row
        warn_str = str(warnings) if warnings == 0 else f"[yellow]{warnings}[/yellow]"
        display_query = query if len(query) <= 60 else query[:57] + "..."
        table.add_row(str(id_), ran_at, f"{exec_time:.2f}", warn_str, display_query)

    console.print(Panel(table, title="[bold]Query History (last 20)[/bold]", border_style="cyan"))


# ── Connect to PostgreSQL ────────────────────────────────────────────────────
def get_connection():
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        console.print("[red]❌ No DATABASE_URL found in .env file.[/red]")
        raise SystemExit(1)
    try:
        return psycopg2.connect(db_url)
    except Exception as e:
        console.print(f"[red]❌ Could not connect to database: {e}[/red]")
        raise SystemExit(1)


# ── Run EXPLAIN ANALYZE ──────────────────────────────────────────────────────
def run_explain(query: str):
    conn = get_connection()
    conn.autocommit = True
    cur = conn.cursor()
    try:
        cur.execute(f"EXPLAIN (ANALYZE, FORMAT JSON) {query}")
        plan = cur.fetchone()[0][0]
        return plan
    except Exception as e:
        console.print(f"[red]❌ Query error: {e}[/red]")
        raise SystemExit(1)
    finally:
        cur.close()
        conn.close()


# ── Walk the plan tree ───────────────────────────────────────────────────────
def collect_nodes(node, nodes=None):
    if nodes is None:
        nodes = []
    nodes.append(node)
    for child in node.get("Plans", []):
        collect_nodes(child, nodes)
    return nodes


# ── Analyze and return suggestions ──────────────────────────────────────────
def analyze_plan(plan):
    suggestions = []
    nodes = collect_nodes(plan["Plan"])

    for node in nodes:
        node_type   = node.get("Node Type", "")
        actual_rows = node.get("Actual Rows", 0)
        plan_rows   = node.get("Plan Rows", 1)
        relation    = node.get("Relation Name", "")
        actual_time = node.get("Actual Total Time", 0)

        if node_type == "Seq Scan" and relation:
            suggestions.append({
                "level": "warning",
                "title": f"Sequential scan on '{relation}' ({actual_rows:,} rows read)",
                "detail": (
                    f"PostgreSQL is reading every single row in '{relation}' to find your results. "
                    f"This is like reading an entire book to find one word.\n"
                    f"  → Add an index on the column you're filtering by:\n"
                    f"     CREATE INDEX ON {relation}(<your_filter_column>);"
                ),
            })

        if plan_rows > 0:
            ratio = actual_rows / plan_rows
            if ratio > 10 or ratio < 0.1:
                suggestions.append({
                    "level": "warning",
                    "title": f"Row estimate was way off on '{relation or node_type}'",
                    "detail": (
                        f"PostgreSQL guessed {plan_rows:,} rows but got {actual_rows:,}. "
                        f"Its internal statistics are outdated.\n"
                        f"  → Fix it by running:  ANALYZE {relation};"
                        if relation else
                        f"PostgreSQL guessed {plan_rows:,} rows but got {actual_rows:,}. "
                        f"Run ANALYZE on the relevant table."
                    ),
                })

        if actual_time > 100:
            suggestions.append({
                "level": "warning",
                "title": f"Slow operation: '{node_type}' took {actual_time:.1f}ms",
                "detail": (
                    f"This step alone took {actual_time:.1f}ms. "
                    f"If this is a scan, an index will help. "
                    f"If it's a sort, consider whether you need all those rows."
                ),
            })

        if node_type == "Hash" and actual_rows > 50_000:
            suggestions.append({
                "level": "info",
                "title": f"Large hash join ({actual_rows:,} rows hashed)",
                "detail": (
                    "A large hash join is using a lot of memory. "
                    "Make sure work_mem is set high enough:\n"
                    "  → SET work_mem = '64MB';  -- run before your query"
                ),
            })

    if not suggestions:
        suggestions.append({
            "level": "good",
            "title": "Looks good!",
            "detail": "No obvious performance issues detected in this query.",
        })

    return suggestions


# ── Pretty-print results ─────────────────────────────────────────────────────
def print_results(plan, suggestions):
    exec_time  = plan.get("Execution Time", 0)
    plan_time  = plan.get("Planning Time", 0)
    total_rows = plan["Plan"].get("Actual Rows", "?")

    table = Table(box=box.ROUNDED, show_header=False, padding=(0, 1))
    table.add_column("Key",   style="bold cyan",  no_wrap=True)
    table.add_column("Value", style="bold white")
    table.add_row("Execution time", f"{exec_time:.2f} ms")
    table.add_row("Planning time",  f"{plan_time:.2f} ms")
    table.add_row("Rows returned",  f"{total_rows:,}" if isinstance(total_rows, int) else str(total_rows))
    console.print(Panel(table, title="[bold]SQL Query Profiler[/bold]", border_style="cyan"))

    console.print()
    for s in suggestions:
        if s["level"] == "good":
            icon, title_style, detail_style = "✅", "bold green", "green"
        elif s["level"] == "warning":
            icon, title_style, detail_style = "⚠️ ", "bold yellow", "yellow"
        else:
            icon, title_style, detail_style = "ℹ️ ", "bold blue", "blue"

        console.print(f"{icon} [{title_style}]{s['title']}[/{title_style}]")
        console.print(f"   [{detail_style}]{s['detail']}[/{detail_style}]")
        console.print()

    return exec_time, plan_time, total_rows


# ── CLI ──────────────────────────────────────────────────────────────────────
@click.command()
@click.option("--query", "-q", default=None, help="The SQL query you want to analyze.")
@click.option("--history", "-h", is_flag=True, default=False, help="Show past queries.")
def main(query, history):
    """SQL Query Performance Profiler — find out why your queries are slow."""
    init_history()

    if history:
        show_history()
        return

    if not query:
        query = click.prompt("Enter your SQL query")

    console.print("\n[cyan]Running analysis...[/cyan]\n")
    plan        = run_explain(query)
    suggestions = analyze_plan(plan)
    exec_time, plan_time, total_rows = print_results(plan, suggestions)

    warning_count = sum(1 for s in suggestions if s["level"] == "warning")
    save_to_history(
        query     = query,
        exec_time = exec_time,
        plan_time = plan_time,
        rows      = total_rows if isinstance(total_rows, int) else 0,
        warnings  = warning_count,
    )
    console.print("[dim]✓ Saved to history. Run with --history to review past queries.[/dim]\n")


if __name__ == "__main__":
    main()
