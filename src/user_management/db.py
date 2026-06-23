#!/usr/bin/env python3
"""
db.py — Interactive SQL shell for ecommerce.db
Usage:  python3 db.py
        python3 db.py "SELECT * FROM users;"
"""
import sqlite3, sys, os

DB_PATH = os.path.join(os.path.dirname(__file__), "ecommerce.db")

def run(sql: str, con):
    try:
        cur = con.execute(sql)
        rows = cur.fetchall()
        if not rows:
            print("(no rows)")
            return
        cols = [d[0] for d in cur.description]
        # column widths
        widths = [max(len(c), max((len(str(r[i])) for r in rows), default=0))
                  for i, c in enumerate(cols)]
        sep = "+-" + "-+-".join("-" * w for w in widths) + "-+"
        header = "| " + " | ".join(c.ljust(widths[i]) for i, c in enumerate(cols)) + " |"
        print(sep)
        print(header)
        print(sep)
        for row in rows:
            print("| " + " | ".join(str(v).ljust(widths[i]) for i, v in enumerate(row)) + " |")
        print(sep)
        print(f"  {len(rows)} row(s)\n")
    except Exception as e:
        print(f"ERROR: {e}\n")

def main():
    if not os.path.exists(DB_PATH):
        print(f"Database not found: {DB_PATH}")
        sys.exit(1)

    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row

    # Single query mode: python3 db.py "SELECT ..."
    if len(sys.argv) > 1:
        run(" ".join(sys.argv[1:]), con)
        con.close()
        return

    # Interactive mode
    print(f"Connected to: {DB_PATH}")
    print("Type SQL and press Enter. Type 'exit' to quit.\n")
    buf = []
    while True:
        prompt = "sql> " if not buf else "  -> "
        try:
            line = input(prompt).strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye.")
            break
        if line.lower() in ("exit", "quit", ".quit"):
            print("Bye.")
            break
        if not line:
            continue
        buf.append(line)
        full = " ".join(buf)
        if full.rstrip().endswith(";"):
            run(full, con)
            buf = []

    con.close()

if __name__ == "__main__":
    main()
