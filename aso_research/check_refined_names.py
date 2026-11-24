from google_play_scraper import search

candidates = [
    'Calm Nook',
    'Haven Sort',
    'Pocket Tidy',
    'Tidy Hearth',
    'Sort & Settle',
    'Cozy Clutter',
    'Room Calm',
    'Restful Room'
]

print("Checking Refined Candidates for Exact Play Store Collisions:")
for n in candidates:
    res = search(n, n_hits=5, lang='en', country='us')
    exact = [r['title'] for r in res if n.lower() == r['title'].lower()]
    top_title = res[0]['title'] if res else 'None'
    print(f"Name: '{n}' -> Collisions: {len(exact)} | Closest: '{top_title}'")
