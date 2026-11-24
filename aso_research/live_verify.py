import json
from google_play_scraper import app, search

COMPETITOR_IDS = [
    'com.gamefactory.roomsort',
    'com.CircleGames.TidyRoom',
    'puzzle.happy.tidy.room',
    'find.tidy.house.sort.puzzle.game'
]

print("=== 1. FETCHING LIVE COMPETITOR DATA FROM GOOGLE PLAY ===")
competitor_data = {}
for aid in COMPETITOR_IDS:
    try:
        data = app(aid, lang='en', country='us')
        competitor_data[aid] = {
            "title": data.get("title"),
            "developer": data.get("developer"),
            "installs": data.get("installs"),
            "realInstalls": data.get("realInstalls"),
            "score": data.get("score"),
            "ratings": data.get("ratings"),
            "reviews": data.get("reviews"),
            "released": data.get("released"),
            "updated": data.get("updated"),
            "genre": data.get("genre"),
            "genreId": data.get("genreId"),
            "summary": data.get("summary"),
            "description": data.get("description")[:300] if data.get("description") else None,
            "url": data.get("url")
        }
        print(f"\n[LIVE OK] {aid}:")
        print(f"  Title: {data.get('title')}")
        print(f"  Developer: {data.get('developer')}")
        print(f"  Installs: {data.get('installs')} (real: {data.get('realInstalls')})")
        print(f"  Score: {data.get('score')} ({data.get('ratings')} ratings, {data.get('reviews')} reviews)")
        print(f"  Released: {data.get('released')}")
        print(f"  Updated: {data.get('updated')}")
        print(f"  Summary: {data.get('summary')}")
    except Exception as e:
        print(f"[LIVE ERROR] {aid}: {e}")
        competitor_data[aid] = {"error": str(e)}

with open("aso_research/live_competitors.json", "w", encoding="utf-8") as f:
    json.dump(competitor_data, f, ensure_ascii=False, indent=2, default=str)

print("\n=== 2. FETCHING LIVE TOP 5 RESULTS FOR [room sort] ===")
try:
    rs_res = search('room sort', n_hits=10, lang='en', country='us')
    top5_room_sort = []
    for i, r in enumerate(rs_res[:5], 1):
        info = {
            "rank": i,
            "title": r.get("title"),
            "developer": r.get("developer"),
            "appId": r.get("appId"),
            "installs": r.get("installs"),
            "score": r.get("score")
        }
        top5_room_sort.append(info)
        print(f"{i}. {r.get('title')} | Dev: {r.get('developer')} | ID: {r.get('appId')} | Installs: {r.get('installs')} | Score: {r.get('score')}")
    with open("aso_research/room_sort_top5.json", "w", encoding="utf-8") as f:
        json.dump(top5_room_sort, f, ensure_ascii=False, indent=2)
except Exception as e:
    print(f"Error searching 'room sort': {e}")

print("\n=== 3. CHECKING PROPOSED TITLE CANDIDATES FOR COLLISIONS ===")
test_titles = [
    "Calm Nook: Cozy Room Sort",
    "Pocket Tidy: Room Sort Game",
    "Haven Sort: Tidy Cozy Room",
    "Restful Room: Tidy Sort",
    "Room Calm: Cozy Sort Puzzle",
    "Cozy Haven: Room Sort Puzzle",
    "Tidy Hearth: Cozy Room Sort",
    "Tidy Nook: Room Sort Puzzle" # Check the partial collision one
]

for t in test_titles:
    brand = t.split(":")[0].strip()
    try:
        s_res = search(brand, n_hits=10, lang='en', country='us')
        exact = [r['title'] for r in s_res if brand.lower() == r['title'].lower()]
        partial = [r['title'] for r in s_res if brand.lower() in r['title'].lower()]
        print(f"Brand: '{brand}' -> Exact: {len(exact)} | Partial: {len(partial)} | Closest: '{s_res[0]['title'] if s_res else 'None'}'")
        if partial:
            print(f"   Matches: {partial}")
    except Exception as e:
        print(f"Error checking '{brand}': {e}")
