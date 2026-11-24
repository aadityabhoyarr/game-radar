"""
Re-build keywords.csv with:
1. Re-scored 'room sort' openness (2/5) reflecting actual top 5 Play results (10M+, 1M+, 1M+).
2. Strict descending sorting by Total_Score.
3. Removed unverified ad spend claims.
"""
import csv
import json

def generate_csv():
    with open("aso_research/search_competition_raw.json", "r", encoding="utf-8") as f:
        raw_data = json.load(f)
        
    scoring_rules = {
        # Core Room Sort (Re-scored openness to 2/5 based on actual top 5 Play results)
        "room sort": {
            "demand": 5, "openness": 2, "relevance": 5, "fit": 5, "verdict": "TARGET",
            "reason": "Top query in subgenre, but top 5 has 10M+ and two 1M+ games; heavily contested at head, target via long-tail."
        },
        "room sort puzzle": {
            "demand": 4, "openness": 3, "relevance": 5, "fit": 4, "verdict": "TARGET",
            "reason": "High intent search query; strong secondary title/subtitle target."
        },
        "room sort game": {
            "demand": 4, "openness": 3, "relevance": 5, "fit": 4, "verdict": "TEST",
            "reason": "Solid autocomplete volume; useful modifier in description."
        },
        
        # Tidy Up / Tidy Room
        "tidy room": {
            "demand": 4, "openness": 4, "relevance": 5, "fit": 5, "verdict": "TARGET",
            "reason": "High conversion cozy intent; top indie apps under 100K; excellent 10-char title fit."
        },
        "tidy room game": {
            "demand": 3, "openness": 4, "relevance": 5, "fit": 4, "verdict": "TEST",
            "reason": "Solid long-tail modifier, perfect for description body and tags."
        },
        "tidy up": {
            "demand": 4, "openness": 3, "relevance": 4, "fit": 5, "verdict": "TEST",
            "reason": "Broad evergreen search term; mixed competition with 3D hypercasual cleaning games."
        },
        "tidy up 3d": {
            "demand": 3, "openness": 2, "relevance": 2, "fit": 5, "verdict": "SKIP",
            "reason": "Our game is 2D isometric/hand-drawn cozy, not 3D hypercasual cleaning."
        },
        "tidy house": {
            "demand": 3, "openness": 4, "relevance": 4, "fit": 5, "verdict": "TEST",
            "reason": "Good secondary keyword; competes partly with chore/calendar utility apps."
        },
        "tidy house puzzle": {
            "demand": 2, "openness": 4, "relevance": 4, "fit": 4, "verdict": "TEST",
            "reason": "Niche low-competition long tail; easy to rank in description copy."
        },
        "clean and tidy": {
            "demand": 3, "openness": 3, "relevance": 4, "fit": 4, "verdict": "TEST",
            "reason": "Natural lifestyle query; good for promo captions and secondary sentences."
        },
        
        # Organize & Declutter
        "organize room": {
            "demand": 4, "openness": 4, "relevance": 5, "fit": 4, "verdict": "TARGET",
            "reason": "High organic search intent; matches themed rooms (kitchen, cafe, bedroom); open competition."
        },
        "organizing games": {
            "demand": 5, "openness": 3, "relevance": 4, "fit": 4, "verdict": "TARGET",
            "reason": "Massive evergreen query across Play Store and YouTube; driven by 'A Little to the Left' trend."
        },
        "room organizer": {
            "demand": 3, "openness": 3, "relevance": 4, "fit": 4, "verdict": "TEST",
            "reason": "Search split between interior design tools and casual sorting games."
        },
        "organize it": {
            "demand": 3, "openness": 2, "relevance": 3, "fit": 5, "verdict": "SKIP",
            "reason": "Dominated by old hypercasual titles (Organize It 3D); vague intent."
        },
        "closet organizer": {
            "demand": 3, "openness": 2, "relevance": 2, "fit": 4, "verdict": "SKIP",
            "reason": "Dominated by fashion wardrobe apps and 2022 closet restock games."
        },
        "declutter": {
            "demand": 3, "openness": 5, "relevance": 5, "fit": 5, "verdict": "TARGET",
            "reason": "Blue ocean for games; zero dominant game competitors; high therapeutic appeal."
        },
        "declutter room": {
            "demand": 3, "openness": 5, "relevance": 5, "fit": 4, "verdict": "TARGET",
            "reason": "Exact fit for room-by-room tidying progression; very low competition."
        },
        "declutter game": {
            "demand": 2, "openness": 4, "relevance": 5, "fit": 4, "verdict": "TEST",
            "reason": "Emerging long tail; great conversion candidate for cozy players."
        },
        "declutter house": {
            "demand": 2, "openness": 4, "relevance": 4, "fit": 4, "verdict": "TEST",
            "reason": "Good for full description feature bullets."
        },
        
        # Goods Sort & Packing
        "goods sort": {
            "demand": 5, "openness": 1, "relevance": 3, "fit": 5, "verdict": "SKIP",
            "reason": "Completely dominated by Falcon, Guru, Veraxen; saturated red ocean for indies."
        },
        "goods sorting": {
            "demand": 4, "openness": 1, "relevance": 3, "fit": 4, "verdict": "SKIP",
            "reason": "Red ocean supermarket shelf sorting category; wrong art/gameplay expectation."
        },
        "packing game": {
            "demand": 4, "openness": 4, "relevance": 5, "fit": 5, "verdict": "TARGET",
            "reason": "Core box-packing mechanic matches exact player action; manageable indie competition."
        },
        "box packing": {
            "demand": 3, "openness": 4, "relevance": 5, "fit": 5, "verdict": "TEST",
            "reason": "Direct mechanic description; useful in screenshot captions and description."
        },
        "pack the room": {
            "demand": 2, "openness": 5, "relevance": 5, "fit": 4, "verdict": "TEST",
            "reason": "Catchy potential title modifier; completely uncrowded."
        },
        "box sort": {
            "demand": 3, "openness": 4, "relevance": 4, "fit": 5, "verdict": "TEST",
            "reason": "Compact 8-character keyword with good autocomplete volume."
        },
        
        # Cozy & Sort Puzzle
        "cozy puzzle": {
            "demand": 4, "openness": 5, "relevance": 5, "fit": 5, "verdict": "TARGET",
            "reason": "Rapidly surging aesthetic category on Play Store; perfect audience alignment for soft colors & calm pacing."
        },
        "cozy games": {
            "demand": 5, "openness": 2, "relevance": 4, "fit": 5, "verdict": "TEST",
            "reason": "Very broad umbrella keyword; useful in description metadata, but tough to rank as single term."
        },
        "cozy sort": {
            "demand": 3, "openness": 5, "relevance": 5, "fit": 5, "verdict": "TARGET",
            "reason": "Unique fusion term; zero dominant incumbents; prime candidate for title naming."
        },
        "cozy room": {
            "demand": 3, "openness": 4, "relevance": 4, "fit": 5, "verdict": "TEST",
            "reason": "Aesthetic lifestyle query; strong synergy with decor feature."
        },
        "sort puzzle": {
            "demand": 5, "openness": 1, "relevance": 4, "fit": 5, "verdict": "SKIP",
            "reason": "Heavily saturated red ocean (Water Sort, Ball Sort with 100M+ downloads); zero organic visibility."
        },
        "sort puzzle games": {
            "demand": 4, "openness": 1, "relevance": 4, "fit": 3, "verdict": "SKIP",
            "reason": "Completely crowded out by legacy giants."
        },
        "sorting games": {
            "demand": 5, "openness": 2, "relevance": 4, "fit": 4, "verdict": "TEST",
            "reason": "High volume category keyword; include naturally in description copy."
        },
        "item sort puzzle": {
            "demand": 2, "openness": 5, "relevance": 5, "fit": 4, "verdict": "TEST",
            "reason": "Exact mechanic descriptor with zero mega-game competition."
        },
        
        # Satisfying & ASMR
        "satisfying sort": {
            "demand": 4, "openness": 3, "relevance": 5, "fit": 4, "verdict": "TEST",
            "reason": "Strong sensory hook; good in short description and promo video."
        },
        "satisfying cleaning": {
            "demand": 3, "openness": 3, "relevance": 4, "fit": 3, "verdict": "TEST",
            "reason": "Good for store listing conversion, but leans slightly towards power-washer games."
        },
        "satisfying organizing": {
            "demand": 3, "openness": 3, "relevance": 5, "fit": 2, "verdict": "TEST",
            "reason": "High relevance, but at 21 characters it is hard to pair in a 30-char title."
        },
        "asmr sort": {
            "demand": 4, "openness": 2, "relevance": 4, "fit": 5, "verdict": "TEST",
            "reason": "High viral search volume; several ASMR titles dominate the head term."
        },
        "asmr cleaning": {
            "demand": 4, "openness": 2, "relevance": 3, "fit": 4, "verdict": "SKIP",
            "reason": "Dominated by rug cleaning, deep clean 3D, and face makeover ASMR apps."
        },
        "asmr room tidy": {
            "demand": 2, "openness": 5, "relevance": 5, "fit": 4, "verdict": "TEST",
            "reason": "Highly specific intent; ideal for long-tail ASO in description text."
        },
        
        # Find Items & Hidden Objects
        "find items": {
            "demand": 4, "openness": 2, "relevance": 4, "fit": 5, "verdict": "TEST",
            "reason": "High traffic; dominated by scavenger hunt games (Find Out, Scavenger Hunt)."
        },
        "find and sort": {
            "demand": 3, "openness": 4, "relevance": 5, "fit": 4, "verdict": "TARGET",
            "reason": "Accurately conveys the two-step gameplay loop (spot in room, pack into box)."
        },
        "find objects puzzle": {
            "demand": 3, "openness": 2, "relevance": 4, "fit": 3, "verdict": "SKIP",
            "reason": "Crowded traditional hidden object crime/mystery genre."
        },
        "hidden objects room": {
            "demand": 3, "openness": 2, "relevance": 3, "fit": 3, "verdict": "SKIP",
            "reason": "Dominated by escape room and detective hidden object games."
        },
        "hidden items sort": {
            "demand": 2, "openness": 4, "relevance": 4, "fit": 4, "verdict": "TEST",
            "reason": "Accurate long tail for description bullet points."
        },
        
        # International Variants
        "部屋の片付け": {
            "demand": 4, "openness": 5, "relevance": 5, "fit": 5, "verdict": "TARGET",
            "reason": "Japanese 'Room Tidying'; huge organic audience for cozy organization in JP."
        },
        "仕分けパズル": {
            "demand": 4, "openness": 3, "relevance": 5, "fit": 5, "verdict": "TEST",
            "reason": "Japanese 'Sorting Puzzle'; widely recognized subgenre tag."
        },
        "ordenar habitacion": {
            "demand": 3, "openness": 5, "relevance": 5, "fit": 4, "verdict": "TARGET",
            "reason": "Spanish 'Tidy/Organize Room'; open indie competition across LATAM and Spain."
        },
        "juegos de organizar": {
            "demand": 4, "openness": 4, "relevance": 5, "fit": 3, "verdict": "TARGET",
            "reason": "Spanish 'Organizing Games'; high search volume on mobile storefronts."
        },
        "organizar quarto": {
            "demand": 3, "openness": 5, "relevance": 5, "fit": 4, "verdict": "TARGET",
            "reason": "Portuguese-BR 'Organize Bedroom'; zero entrenched mega-games; fast-ranking."
        },
        "arrumar a casa": {
            "demand": 4, "openness": 4, "relevance": 4, "fit": 4, "verdict": "TEST",
            "reason": "Portuguese-BR 'Tidy the House'; common colloquial phrase for household tidying."
        },
        "zimmer aufraumen": {
            "demand": 3, "openness": 5, "relevance": 5, "fit": 4, "verdict": "TARGET",
            "reason": "German 'Clean/Tidy Room'; open field with high eCPM potential in DE."
        },
        "sortierspiel": {
            "demand": 3, "openness": 4, "relevance": 4, "fit": 5, "verdict": "TEST",
            "reason": "German 'Sorting Game'; clean single-word keyword fitting easily into titles."
        },
        "ranger la chambre": {
            "demand": 3, "openness": 5, "relevance": 5, "fit": 4, "verdict": "TARGET",
            "reason": "French 'Tidy the Room'; very low publisher competition in France & Canada."
        },
        "jeu de tri": {
            "demand": 3, "openness": 4, "relevance": 4, "fit": 5, "verdict": "TEST",
            "reason": "French 'Sorting Game'; standard category keyword."
        },
        "방 정리": {
            "demand": 4, "openness": 5, "relevance": 5, "fit": 5, "verdict": "TARGET",
            "reason": "Korean 'Room Tidying'; strong viral aesthetic trend among Korean mobile puzzle gamers."
        },
        "정리 퍼즐": {
            "demand": 4, "openness": 4, "relevance": 5, "fit": 5, "verdict": "TARGET",
            "reason": "Korean 'Organizing Puzzle'; direct match for Korean storefront title & tags."
        }
    }

    processed_rows = []
    
    for item in raw_data:
        kw = item["keyword"]
        rule = scoring_rules.get(kw, {
            "demand": 3, "openness": 3, "relevance": 3, "fit": 3,
            "verdict": "TEST", "reason": "Generic keyword candidate."
        })
        
        d_sc = rule["demand"]
        o_sc = rule["openness"]
        r_sc = rule["relevance"]
        f_sc = rule["fit"]
        total = d_sc + o_sc + r_sc + f_sc
        
        sug_str = " | ".join(item.get("autocompletes", [])[:4])
        if not sug_str:
            sug_str = "None recorded"
            
        processed_rows.append({
            "Keyword": kw,
            "Cluster": item["cluster"],
            "Language": item["lang"],
            "Autocomplete_Suggestions": sug_str,
            "Competition_Openness": "Dominated" if o_sc <= 2 else ("Open" if o_sc >= 4 else "Moderate"),
            "Demand_Trend (1-5)": d_sc,
            "Openness_Score (1-5)": o_sc,
            "Relevance_Score (1-5)": r_sc,
            "Title_Fit_Score (1-5)": f_sc,
            "Total_Score (out of 20)": total,
            "Verdict": rule["verdict"],
            "Verdict_Reason": rule["reason"]
        })
        
    # Sort strictly descending by Total_Score (out of 20), secondary sort by Demand
    processed_rows.sort(key=lambda r: (r["Total_Score (out of 20)"], r["Demand_Trend (1-5)"]), reverse=True)
    
    fieldnames = [
        "Keyword", "Cluster", "Language", "Autocomplete_Suggestions",
        "Competition_Openness", "Demand_Trend (1-5)", "Openness_Score (1-5)",
        "Relevance_Score (1-5)", "Title_Fit_Score (1-5)", "Total_Score (out of 20)",
        "Verdict", "Verdict_Reason"
    ]
    
    with open("aso_research/keywords.csv", "w", encoding="utf-8", newline="") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        for row in processed_rows:
            writer.writerow(row)
            
    print(f"Successfully wrote {len(processed_rows)} sorted keywords to aso_research/keywords.csv")
    print("\nTop 10 Sorted Keywords by Score:")
    for i, r in enumerate(processed_rows[:10], 1):
        print(f"{i}. {r['Keyword']} | Total: {r['Total_Score (out of 20)']} (D:{r['Demand_Trend (1-5)']}, O:{r['Openness_Score (1-5)']}, R:{r['Relevance_Score (1-5)']}, F:{r['Title_Fit_Score (1-5)']}) | Verdict: {r['Verdict']}")

if __name__ == "__main__":
    generate_csv()
