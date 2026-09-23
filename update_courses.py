"""
Reads the ETH Library course list and writes courses/courses.json.
Run automatically by GitHub Actions (.github/workflows/update-courses.yml).
"""
import datetime as dt
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

LIST_URL = "https://library.ethz.ch/en/kurse-und-beratung/courses-and-workshops.html"
OUT = Path(__file__).resolve().parent.parent / "courses" / "courses.json"
DAYS_AHEAD = 60          # store this far ahead; the display page filters to 14 days / 5 courses
ONLINE = re.compile(r"\b(zoom|online|webex|teams)\b", re.I)
HEADERS = {"User-Agent": "ETH-Library-Signage/1.0 (course display for library screens)"}


def get(url):
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return BeautifulSoup(r.text, "html.parser")


def clean(text):
    return re.sub(r"\s+", " ", text or "").strip()


def parse_date(text):
    m = re.search(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", text or "")
    return dt.date(int(m.group(3)), int(m.group(2)), int(m.group(1))) if m else None


def find_course_table(soup):
    for table in soup.find_all("table"):
        heads = [clean(th.get_text()).lower() for th in table.find_all("th")]
        if any("date" in h or "datum" in h for h in heads) and table.find("a", href=re.compile(r"details\.")):
            return table, heads
    return None, []


def detail_fields(url):
    """Label -> value from the detail page's two-column table."""
    soup = get(url)
    fields = {}
    for tr in soup.find_all("tr"):
        cells = tr.find_all(["th", "td"], recursive=False)
        if len(cells) >= 2:
            fields[clean(cells[0].get_text()).lower()] = clean(cells[1].get_text(" "))
    return fields


def main():
    soup = get(LIST_URL)
    table, heads = find_course_table(soup)
    if table is None:
        sys.exit("Course table not found - page layout may have changed. Keeping old data.")

    def col(*names):
        for i, h in enumerate(heads):
            if any(n in h for n in names):
                return i
        return None

    i_title, i_date, i_dur = col("title", "titel"), col("date", "datum"), col("duration", "dauer")
    today = dt.date.today()
    courses = []

    for tr in table.find_all("tr"):
        tds = tr.find_all("td")
        if not tds:
            continue
        link = tr.find("a", href=re.compile(r"details\."))
        if not link:
            continue
        title = clean(link.get_text())
        date = parse_date(tds[i_date].get_text()) if i_date is not None and i_date < len(tds) else None
        if not date or date < today or date > today + dt.timedelta(days=DAYS_AHEAD):
            continue
        duration = clean(tds[i_dur].get_text()) if i_dur is not None and i_dur < len(tds) else ""
        url = urljoin(LIST_URL, link["href"])

        online, when = False, ""
        try:
            f = detail_fields(url)
            where = " ".join(v for k, v in f.items() if any(w in k for w in ("campus", "meeting place", "treffpunkt", "ort", "location")))
            online = bool(ONLINE.search(where) or ONLINE.search(title))
            appt = next((v for k, v in f.items() if "appointment" in k or "termin" in k), "")
            m = re.search(r"(\d{1,2}:\d{2})\s*-\s*(\d{1,2}:\d{2})", appt)
            when = f"{m.group(1)}–{m.group(2)}" if m else ""
            time.sleep(1)  # be polite to the library server
        except Exception as e:
            print(f"Warning: could not read details for {title}: {e}")

        courses.append({"date": date.isoformat(), "time": when, "title": title,
                        "duration": duration, "online": online, "url": url})

    courses.sort(key=lambda c: (c["date"], c["time"]))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"updated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                               "courses": courses}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {len(courses)} courses to {OUT}")


if __name__ == "__main__":
    main()
