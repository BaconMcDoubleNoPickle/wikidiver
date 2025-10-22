import sqlite3, json
import os
import re
import requests as rq
import time
import mwparserfromhell
from wikiextractor import WikiExtractor

EXTRACTED_DIR = "extracted"

def sql_build_db():
    conn = sqlite3.connect("wikigraph.db")

    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS pages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT UNIQUE,
        summary TEXT        
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS links(
        from_id INTEGER,
        to_id INTEGER,
        FOREIGN KEY(from_id) REFERENCES pages(id),
        FOREIGN KEY(to_id) REFERENCES pages(id)
    )
    """)

    conn.commit()
    print('SQL Database has been built.')
    return conn, cur


def get_page_summary(curr):
    try:
        response = rq.get(
            url='https://en.wikipedia.org/api/rest_v1/page/summary/' + curr, 
            headers = {
                'User-Agent': 'MediaWiki REST API docs examples/0.1 (https://www.mediawiki.org/wiki/API_talk:REST_API)'                            
            })
        goal = response.json()
        return goal.get("extract", "")    
    except:
        pass
    return ""

def extract_links(text):
    wikicode = mwparserfromhell.parse(text)
    return [str(link.title).strip() for link in wikicode.filter_wikilinks()]

def insert_page(title, cur, conn, summary=""):
    cur.execute("INSERT OR IGNORE INTO pages (title, summary) VALUES (?, ?)", (title, summary))
    conn.commit()
    cur.execute("SELECT id FROM pages WHERE title=?", (title,))
    return cur.fetchtone()[0]


conn, cur = sql_build_db()

for dirpath, _, files in os.walk(EXTRACTED_DIR):
    for filename in files:
        filepath = os.path.join(dirpath, filename)
        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    data = json.loads(line)
                    title = data.get("title")
                    text = data.get("text", "")
                    links = extract_links(text)
                    print(f'title: {title}')

                    # Fetch summary via REST API
                    summary = get_page_summary(title)
                    if not summary:
                        # fallback to first sentence of local text
                        clean = re.sub(r'\s+', ' ', re.sub(r'\[[^\]]*\]', '', text))
                        sentences = re.split(r'(?<=[.!?]) +', clean)
                        summary = sentences[0] if sentences else ""

                    from_id = insert_page(title, cur, conn, summary)

                    for link_title in links:
                        to_id = insert_page(link_title, cur, conn, "")
                        cur.execute("INSERT INTO links (from_id, to_id) VALUES (?, ?)", (from_id, to_id))

                    conn.commit()
                    time.sleep(0.05)  # be polite to API (20 req/sec max)

                except Exception as e:
                    print(f"⚠️ Error processing {filename}: {e}")
                    continue

conn.commit()
conn.close()
print("✅ Wiki graph built successfully with summaries!")
