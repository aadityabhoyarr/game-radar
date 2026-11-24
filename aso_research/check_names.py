from google_play_scraper import search

names = [
    'Tidy Nook',
    'Cozy Crate',
    'Room Calm',
    'Sort Nest',
    'Pocket Tidy',
    'Haven Sort',
    'Cozy Pack',
    'Restful Room'
]

print("Checking 8 Name Ideas for Google Play Collisions:")
for n in names:
    try:
        res = search(n, n_hits=5, lang='en', country='us')
        exact = [r['title'] for r in res if n.lower() == r['title'].lower()]
        top_title = res[0]['title'] if res else 'None'
        print(f"Name: '{n}' -> Exact Collisions: {len(exact)} | Nearest Title: '{top_title}'")
    except Exception as e:
        print(f"Error checking {n}: {e}")
