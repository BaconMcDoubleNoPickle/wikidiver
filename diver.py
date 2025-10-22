import requests as rq
from urllib.parse import urlparse
import re
from sentence_transformers import SentenceTransformer, util
import heapq
import json
import pathlib as path
from concurrent.futures import ThreadPoolExecutor, as_completed
import sqlite3


class Diver:
    def __init__(self, model=None):
        # Initialize model
        self.model = model or SentenceTransformer('all-MiniLM-L6-v2')

        # State tracking
        self.best = ''
        self.highest_score = 0
        self.start = ''
        self.current = ''
        self.dest = ''
        self.jumps = 0
        self.path_taken = []
        self.all_paths = {}

        # Initialize start/destination and embeddings
        self.init()

    def init(self):
        """Set up start and destination pages"""
        self.start, self.dest = self.get_random_page()
        self.current = self.start

        print('INIT', self.start)
        goal = self.get_page_summary(self.start)
        self.goal_embedding = self.get_goal_embedding(goal)
        print('Embedded')


    def same_domain(self):
        try:    
            url1 = urlparse(self.start)
            url2 = urlparse(self.dest)
        
            return url1.netloc == url2.netloc
        except AttributeError:
            return False
        
    def get_goal_embedding(self, goal):
        return self.model.encode(goal, normalize_embeddings=True)

    def check_model(self):
        #need to define what models we can work with
        a='a'

    def a_star_helper(self, open_set, visited, max_depth, max_threads=5):
        
        f_score, current, path = heapq.heappop(open_set)
        self.current = current
        print(current, f_score)
        # Goal check
        if self.check_correct(current, self.dest):
            self.path_taken = path
            print(f"🏁 Found destination in {self.jumps} jumps!")
            self.save_memory()
            return 1

        # Skip visited or overly long paths
        if current in visited or len(path) > max_depth:
            return
        visited.add(current)

        # Fetch links
        try:
            links = self.get_page_links(current)
        except Exception as e:
            print(f"Failed to fetch links for {current}: {e}")
            links = []

        if not links:
            return

        # Multithreaded sifting
        ranked_links = []

        def sift_link_subset(subset):
            return self.sift(subset)

        # Split links into roughly equal chunks for threads
        summaries = [self.get_page_summary(m) for m in links if m != '']
        chunk_size = max(1, len(summaries) // max_threads)
        chunks = [links[i:i + chunk_size] for i in range(0, len(links), chunk_size)]

        with ThreadPoolExecutor(max_workers=max_threads) as executor:
            futures = [executor.submit(sift_link_subset, chunk) for chunk in chunks]
            for future in as_completed(futures):
                result = future.result()
                if result:
                    ranked_links.extend(result)

        # Push all ranked links to open_set

        for link, score in ranked_links:
            if link in path:
                continue
            g = len(path)
            h = (1 - float(score))
            f = g / max_depth + h 
            if score > self.highest_score:
                self.highest_score = score
                self.best = link
            heapq.heappush(open_set, (f, link, path + [link]))
                

        #print(f"Exploring {current} | f_score={f_score} | links added={len(ranked_links)}")

    def a_star_search(self, max_depth=5):
        open_set = []
        heapq.heappush(open_set, (0, self.start, [self.start]))
        visited = set()
        while open_set:
            if(self.a_star_helper(open_set, visited, max_depth) == 1):
                return None
            

        print("❌ Goal not found within depth limit.")
        self.save_memory()
        return None

    def get_page_summary(self, curr):
        response = rq.get(
            url='https://en.wikipedia.org/api/rest_v1/page/summary/' + curr, 
            headers = {
                'User-Agent': 'MediaWiki REST API docs examples/0.1 (https://www.mediawiki.org/wiki/API_talk:REST_API)'                            
            })
        goal = response.json()
        return goal.get("extract", "")

    def get_page_links(self, topic: str):
        url = f'https://en.wikipedia.org/w/index.php?title={topic}&action=raw'
        headers = {
                "User-Agent": "WikiRacerBot/1.0 (https://yourwebsite.example/; contact@example.com)"
        }
        response = rq.get(url=url, headers=headers)
        pattern = r'\[\[(?!File:|Category:|.*\.jpg|.*thumb)(.*?)\]\]'
        matches = re.findall(pattern, response.text)
        links = [m.split('|')[0].replace('#', ' ') if isinstance(m, str) else str(m) for m in matches]   
        return links
    
    def fetch_links_thread(self, page, results, index):
        try:
            results[index] = self.get_page_links(page)
        except Exception as e:
            results[index] = []


    def get_random_page(self):
        S = rq.Session()

        URL = "https://en.wikipedia.org/w/api.php"

        PARAMS = {
            "action": "query",
            "format": "json",
            "list": "random",
            "rnnamespace": 0,  # 0 = main/article namespace
            "rnlimit": "2"
        }
        HEADERS = {
                "User-Agent": "WikiRacerBot/1.0 (https://yourwebsite.example/; contact@example.com)"
        }

        R = S.get(url=URL, params=PARAMS, headers=HEADERS)
        DATA = R.json()

        return DATA['query']['random'][0]['title'], DATA['query']['random'][1]['title']

    def sift(self, links=[]):
        if not links:
            return []  
        link_embeddings = self.model.encode(links, normalize_embeddings=True)
        similarities = util.cos_sim(self.goal_embedding, link_embeddings)[0]
        ranked = sorted(zip(links, similarities), key=lambda x: x[1], reverse=True)    
        #ranked = sorted(zip(links, similarities), reverse=True)    
        to_return = []
        for i, a in enumerate(ranked):
            if a[1] >= 0.8 or i <= 3:
                to_return.append(a)

        return to_return
    
    def check_correct(self, curr, dest):
        return curr.lower().replace('_', ' ') == dest.lower().replace('_', ' ')
    
    def increment(self):
        self.jumps += 1

    def save_memory(self, filename="memory.json"):
        mem_path = path.Path(filename)
        with mem_path.open('w', encoding='utf-8') as f:
            json.dump(self.all_paths, f, ensure_ascii=False, indent=2)
        

    '''
    /////////////
    /////////////
    DB IMPLEMENTATION
    /////////////
    /////////////
    '''

    def get_wikipedia_page_info(self, id, title):
        #gets data from wikipedia page db dump
        conn = sqlite3.connect('wikigraph.db')
        cur = conn.cursor()

        cur.execute('SELECT id, summary FROM pages WHERE title=?', (title,))
        conn.commit()
        conn.close()

    def get_links(self, title):
        conn = sqlite3.connect('wikigraph.db')
        cur = conn.cursor()

        cur.execute("""
        SELECT p2.title
        FROM links
        JOIN pages AS p1 ON p1.id = links.from_id
        JOIN pages AS p2 ON p2.id = links.to_id
        WHERE p1.title = ?
        """, (title,))
        return [r[0] for r in cur.fetchall()]
