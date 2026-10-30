#!/usr/bin/env python3
"""
Earnings calendar for a watchlist.

Setup:    pip install yfinance rich
Run:      python earnings_calendar.py            # terminal calendar (auto-refreshes stale data)
          python earnings_calendar.py --refresh  # force re-fetch everything
          python earnings_calendar.py --html     # also write + open earnings_calendar.html
          python earnings_calendar.py --months 4 # show 4 months of calendar grids

Auto-update: dates are cached in earnings_cache.json and re-fetched when they are
older than TTL_HOURS, or when a cached date has already passed. Schedule the script
(cron / Task Scheduler) with --html to keep the HTML page fresh, e.g.
    0 */6 * * *  python /path/to/earnings_calendar.py --html --quiet
"""
import argparse
import calendar
import datetime as dt
import json
import webbrowser
from pathlib import Path

import yfinance as yf
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

WATCHLIST = [
    "NOW", "ASML", "META", "MSFT", "TSM", "AVGO", "GOOGL", "AMZN", "CRDO", "UBER",
    "ISRG", "TMO", "MA", "MSCI", "SPGI", "V", "INTC", "ABT", "NFLX", "MU", "CL", "MCD", "MNST",
]
HERE = Path(__file__).resolve().parent
CACHE_FILE = HERE / "earnings_cache.json"
HTML_FILE = HERE / "earnings_calendar.html"
TTL_HOURS = 12

console = Console()


# ----------------------------------------------------------------- fetching
def _to_date(x):
    if isinstance(x, dt.datetime):
        return x.date()
    if isinstance(x, dt.date):
        return x
    try:  # pandas Timestamp
        return x.date()
    except Exception:
        return None


def fetch_next_earnings(symbol: str):
    """Return {'date': iso, 'end': iso|None} for the next earnings date, or None."""
    today = dt.date.today()
    t = yf.Ticker(symbol)
    found = []
    from_calendar = []

    # 1) Ticker.calendar -> {'Earnings Date': [d1, d2?], ...}
    try:
        cal = t.calendar
        if isinstance(cal, dict):
            found = [_to_date(d) for d in (cal.get("Earnings Date") or [])]
            from_calendar = sorted(d for d in found if d)
    except Exception:
        pass

    # 2) Fallback: earnings history/schedule table
    if not [d for d in found if d and d >= today]:
        try:
            df = t.get_earnings_dates(limit=12)
            if df is not None:
                found = [_to_date(ts) for ts in df.index]
        except Exception:
            pass

    future = sorted(set(d for d in found if d and d >= today))
    if not future:
        return None
    # Ticker.calendar returns two dates when Yahoo only has an estimated window.
    end = None
    if from_calendar and len(from_calendar) == 2 and from_calendar[0] != from_calendar[1]:
        end = from_calendar[1].isoformat()
    return {"date": future[0].isoformat(), "end": end}


def load_cache():
    try:
        return json.loads(CACHE_FILE.read_text())
    except Exception:
        return {}


def needs_refresh(entry, force):
    if force or not entry:
        return True
    try:
        age = dt.datetime.now() - dt.datetime.fromisoformat(entry["fetched_at"])
        if age > dt.timedelta(hours=TTL_HOURS):
            return True
        d = entry.get("date")
        return bool(d) and dt.date.fromisoformat(d) < dt.date.today()
    except Exception:
        return True


def get_data(force=False, quiet=False):
    cache = load_cache()
    stale = [s for s in WATCHLIST if needs_refresh(cache.get(s), force)]
    if stale and not quiet:
        console.print(f"[dim]Updating {len(stale)} ticker(s)...[/dim]")
    for s in stale:
        try:
            res = fetch_next_earnings(s)
        except Exception as e:
            res = None
            if not quiet:
                console.print(f"[yellow]{s}: fetch failed ({e})[/yellow]")
        old = cache.get(s, {})
        if res is None and old.get("date") and dt.date.fromisoformat(old["date"]) >= dt.date.today():
            res = {"date": old["date"], "end": old.get("end")}  # keep last good value
        cache[s] = {
            "date": res["date"] if res else None,
            "end": res["end"] if res else None,
            "fetched_at": dt.datetime.now().isoformat(timespec="seconds"),
        }
    if stale:
        CACHE_FILE.write_text(json.dumps(cache, indent=2))
    return {s: cache.get(s, {}) for s in WATCHLIST}


# ------------------------------------------------------------------ display
def by_date(data):
    out = {}
    for sym, e in data.items():
        if e.get("date"):
            out.setdefault(dt.date.fromisoformat(e["date"]), []).append(sym)
    return out


def print_list(data):
    today = dt.date.today()
    rows = sorted(
        ((dt.date.fromisoformat(e["date"]), s, e) for s, e in data.items() if e.get("date")),
    )
    table = Table(title=f"Upcoming earnings (as of {today:%a %d %b %Y})", header_style="bold cyan")
    table.add_column("Date")
    table.add_column("Day")
    table.add_column("In", justify="right")
    table.add_column("Ticker", style="bold")
    table.add_column("Status")
    for d, s, e in rows:
        n = (d - today).days
        style = "bold red" if n <= 7 else "yellow" if n <= 14 else ""
        status = f"est. window to {e['end']}" if e.get("end") else "confirmed/likely"
        table.add_row(f"{d:%d %b %Y}", f"{d:%a}", "today" if n == 0 else f"{n}d", s, status, style=style)
    console.print(table)
    missing = [s for s, e in data.items() if not e.get("date")]
    if missing:
        console.print(f"[dim]No date found for: {', '.join(missing)}[/dim]")


def month_panel(year, month, events):
    today = dt.date.today()
    grid = Table(show_lines=True, expand=True, padding=(0, 1))
    for name in ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]:
        grid.add_column(name, justify="left", ratio=1, header_style="bold")
    for week in calendar.Calendar(0).monthdayscalendar(year, month):
        cells = []
        for day in week:
            if day == 0:
                cells.append("")
                continue
            d = dt.date(year, month, day)
            t = Text(str(day), style="bold black on yellow" if d == today else "dim")
            for sym in events.get(d, []):
                t.append("\n" + sym, style="bold green")
            cells.append(t)
        grid.add_row(*cells)
    return Panel(grid, title=f"[bold]{calendar.month_name[month]} {year}[/bold]", border_style="cyan")


def print_calendar(data, months):
    events = by_date(data)
    today = dt.date.today()
    y, m = today.year, today.month
    for _ in range(months):
        console.print(month_panel(y, m, events))
        m += 1
        if m > 12:
            y, m = y + 1, 1


def write_html(data, months):
    events = by_date(data)
    today = dt.date.today()
    y, m = today.year, today.month
    blocks = []
    for _ in range(months):
        cells = "".join(f"<div class='h'>{n}</div>" for n in ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"])
        for week in calendar.Calendar(0).monthdayscalendar(y, m):
            for day in week:
                if day == 0:
                    cells += "<div class='c empty'></div>"
                    continue
                d = dt.date(y, m, day)
                chips = "".join(f"<span class='chip'>{s}</span>" for s in events.get(d, []))
                cls = "c today" if d == today else "c"
                cells += f"<div class='{cls}'><b>{day}</b>{chips}</div>"
        blocks.append(f"<section><h2>{calendar.month_name[m]} {y}</h2><div class='g'>{cells}</div></section>")
        m += 1
        if m > 12:
            y, m = y + 1, 1
    html = f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Earnings Calendar</title><style>
:root{{--bg:#fff;--fg:#1a1a1a;--card:#f5f6f8;--line:#dcdfe4;--acc:#0a7d4f}}
@media(prefers-color-scheme:dark){{:root{{--bg:#111418;--fg:#e8e8e8;--card:#1a1e24;--line:#2c323a;--acc:#3ddc97}}}}
body{{background:var(--bg);color:var(--fg);font-family:system-ui,sans-serif;max-width:1000px;margin:0 auto;padding:16px}}
.g{{display:grid;grid-template-columns:repeat(7,1fr);gap:4px}}
.h{{text-align:center;font-size:12px;opacity:.6;padding:4px}}
.c{{background:var(--card);border:1px solid var(--line);border-radius:6px;min-height:72px;padding:4px;font-size:12px}}
.c.empty{{background:transparent;border:none}}
.c.today{{outline:2px solid var(--acc)}}
.chip{{display:block;margin-top:2px;background:var(--acc);color:var(--bg);border-radius:4px;padding:1px 4px;font-weight:600}}
small{{opacity:.6}}
</style></head><body><h1>Earnings Calendar</h1>
<small>Updated {dt.datetime.now():%Y-%m-%d %H:%M}</small>{''.join(blocks)}</body></html>"""
    HTML_FILE.write_text(html, encoding="utf-8")
    return HTML_FILE


# --------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description="Watchlist earnings calendar")
    ap.add_argument("--refresh", action="store_true", help="force re-fetch all tickers")
    ap.add_argument("--html", action="store_true", help="write and open an HTML calendar")
    ap.add_argument("--months", type=int, default=3, help="months to display (default 3)")
    ap.add_argument("--quiet", action="store_true", help="no terminal output (for scheduled runs)")
    args = ap.parse_args()

    data = get_data(force=args.refresh, quiet=args.quiet)
    if not args.quiet:
        print_list(data)
        print_calendar(data, args.months)
    if args.html:
        path = write_html(data, args.months)
        if not args.quiet:
            console.print(f"[green]Wrote {path}[/green]")
            webbrowser.open(path.as_uri())


if __name__ == "__main__":
    main()
