"""
Keyword Research and Competition Analysis for Cozy Room Sort Puzzle
Gathers live Google Play autocomplete, top search results, installs, ratings, and reviews.
"""
import csv
import json
import os
import time
from google_play_scraper import search, app
import gplay_scraper

# 50 Seed Keywords across required clusters:
# room sort, tidy up, organize, declutter, goods sort, sort puzzle, cozy puzzle,
# packing game, satisfying, ASMR, find items, hidden objects, plus long-tail & international
SEED_KEYWORDS = [
    # Core Primary & Direct Modifiers
    {"keyword": "room sort", "cluster": "room sort", "lang": "en"},
    {"keyword": "room sort puzzle", "cluster": "room sort", "lang": "en"},
    {"keyword": "room sort game", "cluster": "room sort", "lang": "en"},
    {"keyword": "tidy room", "cluster": "tidy up", "lang": "en"},
    {"keyword": "tidy room game", "cluster": "tidy up", "lang": "en"},
    {"keyword": "tidy up", "cluster": "tidy up", "lang": "en"},
    {"keyword": "tidy up 3d", "cluster": "tidy up", "lang": "en"},
    {"keyword": "tidy house", "cluster": "tidy up", "lang": "en"},
    {"keyword": "tidy house puzzle", "cluster": "tidy up", "lang": "en"},
    {"keyword": "clean and tidy", "cluster": "tidy up", "lang": "en"},
    
    # Organize / Declutter
    {"keyword": "organize room", "cluster": "organize", "lang": "en"},
    {"keyword": "organizing games", "cluster": "organize", "lang": "en"},
    {"keyword": "room organizer", "cluster": "organize", "lang": "en"},
    {"keyword": "organize it", "cluster": "organize", "lang": "en"},
    {"keyword": "closet organizer", "cluster": "organize", "lang": "en"},
    {"keyword": "declutter", "cluster": "declutter", "lang": "en"},
    {"keyword": "declutter room", "cluster": "declutter", "lang": "en"},
    {"keyword": "declutter game", "cluster": "declutter", "lang": "en"},
    {"keyword": "declutter house", "cluster": "declutter", "lang": "en"},
    
    # Goods Sort & Packing
    {"keyword": "goods sort", "cluster": "goods sort", "lang": "en"},
    {"keyword": "goods sorting", "cluster": "goods sort", "lang": "en"},
    {"keyword": "packing game", "cluster": "packing game", "lang": "en"},
    {"keyword": "box packing", "cluster": "packing game", "lang": "en"},
    {"keyword": "pack the room", "cluster": "packing game", "lang": "en"},
    {"keyword": "box sort", "cluster": "packing game", "lang": "en"},
    
    # Cozy & Sort Puzzle
    {"keyword": "cozy puzzle", "cluster": "cozy puzzle", "lang": "en"},
    {"keyword": "cozy games", "cluster": "cozy puzzle", "lang": "en"},
    {"keyword": "cozy sort", "cluster": "cozy puzzle", "lang": "en"},
    {"keyword": "cozy room", "cluster": "cozy puzzle", "lang": "en"},
    {"keyword": "sort puzzle", "cluster": "sort puzzle", "lang": "en"},
    {"keyword": "sort puzzle games", "cluster": "sort puzzle", "lang": "en"},
    {"keyword": "sorting games", "cluster": "sort puzzle", "lang": "en"},
    {"keyword": "item sort puzzle", "cluster": "sort puzzle", "lang": "en"},
    
    # Satisfying & ASMR
    {"keyword": "satisfying sort", "cluster": "satisfying", "lang": "en"},
    {"keyword": "satisfying cleaning", "cluster": "satisfying", "lang": "en"},
    {"keyword": "satisfying organizing", "cluster": "satisfying", "lang": "en"},
    {"keyword": "asmr sort", "cluster": "asmr", "lang": "en"},
    {"keyword": "asmr cleaning", "cluster": "asmr", "lang": "en"},
    {"keyword": "asmr room tidy", "cluster": "asmr", "lang": "en"},
    
    # Find Items & Hidden Objects
    {"keyword": "find items", "cluster": "find items", "lang": "en"},
    {"keyword": "find and sort", "cluster": "find items", "lang": "en"},
    {"keyword": "find objects puzzle", "cluster": "find items", "lang": "en"},
    {"keyword": "hidden objects room", "cluster": "hidden objects", "lang": "en"},
    {"keyword": "hidden items sort", "cluster": "hidden objects", "lang": "en"},
    
    # Non-English Variants (Japanese, Spanish, Portuguese-BR, German, French, Korean)
    {"keyword": "部屋の片付け", "cluster": "international_jp", "lang": "ja"},     # Room cleaning / tidy up (JA)
    {"keyword": "仕分けパズル", "cluster": "international_jp", "lang": "ja"},       # Sorting puzzle (JA)
    {"keyword": "ordenar habitacion", "cluster": "international_es", "lang": "es"}, # Tidy/organize room (ES)
    {"keyword": "juegos de organizar", "cluster": "international_es", "lang": "es"},# Organizing games (ES)
    {"keyword": "organizar quarto", "cluster": "international_pt", "lang": "pt"},   # Organize room (PT-BR)
    {"keyword": "arrumar a casa", "cluster": "international_pt", "lang": "pt"},     # Tidy up the house (PT-BR)
    {"keyword": "zimmer aufraumen", "cluster": "international_de", "lang": "de"},   # Clean/tidy room (DE)
    {"keyword": "sortierspiel", "cluster": "international_de", "lang": "de"},       # Sorting game (DE)
    {"keyword": "ranger la chambre", "cluster": "international_fr", "lang": "fr"},  # Tidy up the room (FR)
    {"keyword": "jeu de tri", "cluster": "international_fr", "lang": "fr"},         # Sorting game (FR)
    {"keyword": "방 정리", "cluster": "international_kr", "lang": "ko"},            # Room organizing (KR)
    {"keyword": "정리 퍼즐", "cluster": "international_kr", "lang": "ko"},           # Organizing puzzle (KR)
]

def main():
    print(f"Starting analysis for {len(SEED_KEYWORDS)} keywords...")
    scraper = gplay_scraper.GPlayScraper()
    
    results = []
    
    for item in SEED_KEYWORDS:
        kw = item["keyword"]
        lang = item["lang"]
        country = "us" if lang == "en" else ("jp" if lang == "ja" else ("br" if lang == "pt" else ("de" if lang == "de" else ("fr" if lang == "fr" else ("kr" if lang == "ko" else "es")))))
        
        # 1. Autocomplete suggestions
        autocompletes = []
        try:
            sugs = scraper.suggest_analyze(term=kw, country=country)
            autocompletes = sugs if isinstance(sugs, list) else []
        except Exception:
            autocompletes = []
            
        # 2. Search top 10
        top_apps = []
        try:
            search_res = search(kw, n_hits=10, lang=lang, country=country)
            for r in search_res:
                top_apps.append({
                    "title": r.get("title", ""),
                    "developer": r.get("developer", ""),
                    "installs": r.get("installs", "0+"),
                    "score": r.get("score", 0.0),
                    "app_id": r.get("appId", "")
                })
        except Exception as e:
            print(f"Search failed for {kw}: {e}")
            
        # Evaluate Openness
        # Check if top 5 are dominated by mega games (>5M installs or mega publishers)
        dominated_count = 0
        total_top5 = min(len(top_apps), 5)
        for a in top_apps[:total_top5]:
            inst = a["installs"]
            # Convert install string to rough number
            clean_inst = inst.replace(",", "").replace("+", "").strip()
            num_inst = 0
            if clean_inst.isdigit():
                num_inst = int(clean_inst)
            elif "M" in inst:
                num_inst = int(float(inst.replace("M+", "").replace("M", "").strip()) * 1000000)
            elif "K" in inst:
                num_inst = int(float(inst.replace("K+", "").replace("K", "").strip()) * 1000)
                
            if num_inst >= 5000000:
                dominated_count += 1
                
        openness = "dominated" if dominated_count >= 3 else ("open" if dominated_count <= 1 else "moderate")
        
        results.append({
            "keyword": kw,
            "cluster": item["cluster"],
            "lang": lang,
            "autocompletes": autocompletes[:5],
            "openness": openness,
            "top_apps_count": len(top_apps),
            "top3_apps": [f"{a['title']} ({a['installs']})" for a in top_apps[:3]]
        })
        time.sleep(0.5)
        print(f"Processed: {kw} -> Openness: {openness}, Autocompletes: {len(autocompletes)}")
        
    with open("aso_research/search_competition_raw.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print("Raw competition research saved successfully.")

if __name__ == "__main__":
    main()
