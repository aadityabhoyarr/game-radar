"""
Fetch all 1 to 3 star reviews for the 4 competitor games on Google Play,
save them to CSV, and output aggregate statistics and issue clusters.
"""
import csv
import json
import os
import time
from google_play_scraper import reviews, Sort

COMPETITORS = [
    {"app_id": "com.gamefactory.roomsort", "name": "Amochiroom Puzzle: Room Sort"},
    {"app_id": "com.CircleGames.TidyRoom", "name": "Tidy Room!"},
    {"app_id": "puzzle.happy.tidy.room", "name": "Happy Tidy Room"},
    {"app_id": "find.tidy.house.sort.puzzle.game", "name": "Tidy House: Find Objects"}
]

def fetch_low_star_reviews():
    all_reviews = []
    
    print("=" * 60)
    print("FETCHING 1, 2, AND 3-STAR REVIEWS FROM GOOGLE PLAY")
    print("=" * 60)
    
    for comp in COMPETITORS:
        aid = comp["app_id"]
        name = comp["name"]
        print(f"\nProcessing: {name} ({aid})...")
        
        comp_reviews_count = 0
        for star in [1, 2, 3]:
            try:
                # Fetch up to 200 reviews per score tier
                rvs, _ = reviews(
                    aid,
                    lang='en',
                    country='us',
                    sort=Sort.NEWEST,
                    count=200,
                    filter_score_with=star
                )
                print(f"  Fetched {len(rvs)} reviews with {star} star(s).")
                for r in rvs:
                    all_reviews.append({
                        "App_ID": aid,
                        "App_Title": name,
                        "Review_ID": r.get("reviewId", ""),
                        "User_Name": r.get("userName", ""),
                        "Score": r.get("score", star),
                        "Date": str(r.get("at", "")),
                        "Review_Text": (r.get("content") or "").replace("\n", " ").strip(),
                        "Thumbs_Up_Count": r.get("thumbsUpCount", 0),
                        "Developer_Reply": (r.get("replyContent") or "").replace("\n", " ").strip() if r.get("replyContent") else "None"
                    })
                comp_reviews_count += len(rvs)
                time.sleep(0.5)
            except Exception as e:
                print(f"  Error fetching {star}-star reviews for {aid}: {e}")
                
        print(f"  Total 1-3 star reviews collected for {name}: {comp_reviews_count}")

    # Write to CSV
    csv_path = "aso_research/competitor_negative_reviews.csv"
    fieldnames = [
        "App_ID", "App_Title", "Review_ID", "User_Name", "Score",
        "Date", "Review_Text", "Thumbs_Up_Count", "Developer_Reply"
    ]
    
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in all_reviews:
            writer.writerow(r)
            
    print("\n" + "=" * 60)
    print(f"SUCCESS: Saved {len(all_reviews)} negative/critical reviews to:")
    print(f"  {csv_path}")
    print("=" * 60)
    
    # Save a JSON summary for deeper analysis
    with open("aso_research/competitor_negative_reviews.json", "w", encoding="utf-8") as f:
        json.dump(all_reviews, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    fetch_low_star_reviews()
