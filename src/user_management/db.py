#!/usr/bin/env python3
"""
db.py — Interactive SQL shell for ecommerce.db (development utility only).
Usage:  python3 db.py
        python3 db.py "SELECT * FROM users;"
"""
import logging
import sqlite3
import sys
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "ecommerce.db")

# Configure a plain (non-JSON) handler for this CLI tool only.
# Service-layer code uses nfr/structured_logging.py instead.
_handler = logging.StreamHandler(sys.stdout)
_handler.setFormatter(logging.Formatter("%(message)s"))
logger = logging.getLogger(__name__)
logger.addHandler(_handler)
logger.setLevel(logging.INFO)
logger.propagate = False


def run(sql: str, con):
    try:
        cur = con.execute(sql)
        rows = cur.fetchall()
        if not rows:
            logger.info("(no rows)")
            return
        cols = [d[0] for d in cur.description]
        widths = [max(len(c), max((len(str(r[i])) for r in rows), default=0))
                  for i, c in enumerate(cols)]
        sep = "+-" + "-+-".join("-" * w for w in widths) + "-+"
        header = "| " + " | ".join(c.ljust(widths[i]) for i, c in enumerate(cols)) + " |"
        logger.info(sep)
        logger.info(header)
        logger.info(sep)
        for row in rows:
            logger.info("| " + " | ".join(str(v).ljust(widths[i]) for i, v in enumerate(row)) + " |")
        logger.info(sep)
        logger.info("  %d row(s)", len(rows))
    except Exception as exc:
        logger.error("ERROR: %s", exc)


def main():
    if not os.path.exists(DB_PATH):
        logger.error("Database not found: %s", DB_PATH)
        sys.exit(1)

    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row

    if len(sys.argv) > 1:
        run(" ".join(sys.argv[1:]), con)
        con.close()
        return

    logger.info("Connected to: %s", DB_PATH)
    logger.info("Type SQL and press Enter. Type 'exit' to quit.\n")
    buf = []
    while True:
        prompt = "sql> " if not buf else "  -> "
        try:
            line = input(prompt).strip()
        except (EOFError, KeyboardInterrupt):
            logger.info("\nBye.")
            break
        if line.lower() in ("exit", "quit", ".quit"):
            logger.info("Bye.")
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
