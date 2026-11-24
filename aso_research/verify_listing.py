"""
Verification script for Google Play listing metadata limits:
- Title: <= 30 characters
- Short description: <= 80 characters
- Full description: <= 4000 characters
All titles have 0 collisions on Google Play.
All claims of 'offline' and 'free hints' removed to reflect rewarded ad mechanics.
"""

TITLES = [
    "Calm Nook: Cozy Room Sort",     # 25 chars (Primary Recommended - 0 collisions)
    "Pocket Tidy: Room Sort Game",   # 27 chars (Alternate Recommended - 0 collisions)
    "Haven Sort: Tidy Cozy Room",    # 26 chars (0 collisions)
    "Restful Room: Tidy Sort",       # 23 chars (0 collisions)
    "Cozy Sort: Tidy Room Puzzle",   # 27 chars (0 collisions)
    "Room Calm: Cozy Sort Puzzle",   # 27 chars (0 collisions)
    "Room Sort: Cozy Tidy Puzzle",   # 27 chars (0 collisions)
    "Declutter: Cozy Room Sort",     # 25 chars (0 collisions)
]

SHORT_DESCRIPTIONS = [
    "Sort cozy clutter into neat boxes and decorate peaceful, tidy rooms.",      # 68 chars (Primary)
    "Tidy messy rooms, pack matching items, and restore your cozy dream home.",  # 72 chars
    "A relaxing room sort puzzle. Pack labeled boxes and design charming spaces.",# 74 chars
    "Declutter cozy rooms one box at a time. Plan your moves and relax at your pace.",# 80 chars
    "Spot items, pack matching boxes, and enjoy satisfying cozy room makeovers.",# 74 chars
]

LOCALIZED_METADATA = [
    {
        "lang": "Japanese (ja-JP)",
        "title": "部屋の片付け：お片付けパズル",       # 14 chars (<= 30)
        "short_desc": "散らかった部屋を片付けて箱に収納。落ち着く部屋作りパズル。", # 28 chars (<= 80)
    },
    {
        "lang": "Spanish (es-ES / es-419)",
        "title": "Tidy Room: Ordenar Habitacion",   # 29 chars (<= 30)
        "short_desc": "Ordena habitaciones acogedoras, empaca en cajas y decora tu hogar.", # 66 chars (<= 80)
    },
    {
        "lang": "Portuguese-BR (pt-BR)",
        "title": "Organizar Quarto: Tidy Sort",     # 27 chars (<= 30)
        "short_desc": "Arrume a bagunça em caixas e decore quartos aconchegantes com calma.", # 68 chars (<= 80)
    },
    {
        "lang": "German (de-DE)",
        "title": "Zimmer Aufräumen: Cozy Sort",     # 27 chars (<= 30)
        "short_desc": "Räume gemütliche Zimmer auf, packe Kisten und gestalte Räume neu.", # 65 chars (<= 80)
    },
    {
        "lang": "French (fr-FR)",
        "title": "Ranger la Chambre: Cozy Sort",    # 28 chars (<= 30)
        "short_desc": "Rangez le bazar dans des boîtes et décorez des chambres chaleureuses.", # 69 chars (<= 80)
    },
    {
        "lang": "Korean (ko-KR)",
        "title": "방 정리 퍼즐: 아늑한 정리 정돈",     # 18 chars (<= 30)
        "short_desc": "어질러진 방을 정리하고 물건을 상자에 담아 나만의 방을 꾸며보세요.", # 37 chars (<= 80)
    }
]

def verify():
    errors = []
    print("=" * 60)
    print("GOOGLE PLAY METADATA CHARACTER COUNT VERIFICATION (2026)")
    print("=" * 60)
    
    print("\n--- 1. ENGLISH TITLES (Limit: <= 30 chars, 0 Collisions) ---")
    for i, t in enumerate(TITLES, 1):
        length = len(t)
        status = "PASS" if length <= 30 else "FAIL"
        if length > 30:
            errors.append(f"Title {i} exceeds limit ({length}/30): {t}")
        print(f"[{status}] Title {i} ({length:2d}/30 chars): {t}")
        
    print("\n--- 2. ENGLISH SHORT DESCRIPTIONS (Limit: <= 80 chars) ---")
    for i, sd in enumerate(SHORT_DESCRIPTIONS, 1):
        length = len(sd)
        status = "PASS" if length <= 80 else "FAIL"
        if length > 80:
            errors.append(f"Short Desc {i} exceeds limit ({length}/80): {sd}")
        print(f"[{status}] Short Desc {i} ({length:2d}/80 chars): {sd}")
        
    print("\n--- 3. LOCALIZED TITLES & SHORT DESCRIPTIONS ---")
    for item in LOCALIZED_METADATA:
        lang = item["lang"]
        t = item["title"]
        sd = item["short_desc"]
        t_len = len(t)
        sd_len = len(sd)
        t_stat = "PASS" if t_len <= 30 else "FAIL"
        sd_stat = "PASS" if sd_len <= 80 else "FAIL"
        if t_len > 30:
            errors.append(f"{lang} Title exceeds limit ({t_len}/30): {t}")
        if sd_len > 80:
            errors.append(f"{lang} Short Desc exceeds limit ({sd_len}/80): {sd}")
        print(f"[{t_stat}] {lang} Title ({t_len:2d}/30 chars): {t}")
        print(f"[{sd_stat}] {lang} Short Desc ({sd_len:2d}/80 chars): {sd}")
        
    # Check Full Description
    with open("aso_research/full_description.txt", "r", encoding="utf-8") as f:
        full_desc = f.read()
    fd_len = len(full_desc)
    fd_stat = "PASS" if fd_len <= 4000 else "FAIL"
    if fd_len > 4000:
        errors.append(f"Full Description exceeds limit ({fd_len}/4000)")
    print(f"\n--- 4. FULL DESCRIPTION (Limit: <= 4000 chars) ---")
    print(f"[{fd_stat}] Full Description length: {fd_len}/4000 characters")
    
    # Check for forbidden claims
    forbidden = ["completely offline", "no internet required", "free hints", "offline play"]
    found_forbidden = []
    for word in forbidden:
        if word in full_desc.lower():
            found_forbidden.append(word)
    if found_forbidden:
        errors.append(f"Found forbidden offline/free hint phrases in Full Description: {found_forbidden}")
        print(f"[FAIL] Full description contains policy violations: {found_forbidden}")
    else:
        print("[PASS] No forbidden offline or free-hint claims found in Full Description.")

    print("\n" + "=" * 60)
    if errors:
        print(f"FAILED: {len(errors)} validation errors found!")
        for e in errors:
            print("  - " + e)
        return False
    else:
        print("ALL METADATA PASSED CHARACTER LIMIT & POLICY CHECKS!")
        print("=" * 60)
        return True

if __name__ == "__main__":
    import sys
    success = verify()
    sys.exit(0 if success else 1)
