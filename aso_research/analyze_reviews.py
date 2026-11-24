import json
from collections import Counter

with open('aso_research/competitor_negative_reviews.json', 'r', encoding='utf-8') as f:
    reviews = json.load(f)

print(f"Total reviews analyzed: {len(reviews)}")

# Group by app
by_app = {}
for r in reviews:
    by_app.setdefault(r['App_Title'], []).append(r)

for app_name, rlist in by_app.items():
    print(f"\n{app_name}: {len(rlist)} negative reviews")
    scores = Counter(r['Score'] for r in rlist)
    print(f"  Breakdown: 1-star={scores[1]}, 2-star={scores[2]}, 3-star={scores[3]}")

# Theme clustering
themes = {
    "Ad Aggression & Length": ["ad", "ads", "commercial", "commercials", "video", "pop up", "unskippable"],
    "Crashes & Freezes (ANRs)": ["crash", "crashed", "crashes", "freeze", "freezes", "black screen", "glitch", "bug", "stopped"],
    "Slot / Tray Bottlenecks": ["slot", "slots", "tray", "space", "full", "run out of space", "nowhere to put"],
    "Excessive Length & Fatigue": ["hours", "long", "forever", "tedious", "exhausting", "slow", "takes too long", "3 hours"],
    "Ambiguous Item Categorization": ["category", "box", "boxes", "where", "confusing", "doesn't fit", "wrong box", "label"],
    "Unfair RNG & Paywalls": ["pay", "money", "impossible", "forced", "unfair", "rigged", "buy", "cheat"],
    "Hardware Heat & Battery": ["hot", "heat", "battery", "drain", "warm", "overheating"]
}

theme_counts = {t: 0 for t in themes}
theme_examples = {t: [] for t in themes}

for r in reviews:
    text = r['Review_Text'].lower()
    for theme, words in themes.items():
        if any(w in text for w in words):
            theme_counts[theme] += 1
            if len(theme_examples[theme]) < 3:
                theme_examples[theme].append({
                    "app": r['App_Title'],
                    "score": r['Score'],
                    "text": r['Review_Text']
                })

print("\n" + "=" * 60)
print("CORE ISSUE CLUSTERS IN COMPETITOR 1-3 STAR REVIEWS")
print("=" * 60)
for theme, count in sorted(theme_counts.items(), key=lambda x: x[1], reverse=True):
    pct = (count / len(reviews)) * 100
    print(f"\n[Issue] {theme}: {count} reviews ({pct:.1f}%)")
    for ex in theme_examples[theme]:
        print(f"  - ({ex['app']} | {ex['score']}★): \"{ex['text'][:120]}...\"")
