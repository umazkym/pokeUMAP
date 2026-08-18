import sqlite3
import json
import time
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
import sys
import re

MAX_POKEMON_ID = 1025
MAX_WORKERS = 15
DB_PATH = 'pokemon.db'
JSON_PATH = 'pokemon_database.json'

def fetch_json(url, retries=3, delay=1.0):
    headers = {'User-Agent': 'PokeDB-Builder/1.0'}
    req = urllib.request.Request(url, headers=headers)
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.loads(resp.read().decode('utf-8'))
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
            if attempt == retries - 1:
                print(f"\n[ERROR] Failed to fetch {url} after {retries} attempts: {e}")
                return None
            time.sleep(delay * (attempt + 1))

def extract_generation_number(gen_data):
    if not gen_data or 'url' not in gen_data:
        return None
    # URL e.g. "https://pokeapi.co/api/v2/generation/1/"
    match = re.search(r'/generation/(\d+)/', gen_data['url'])
    return int(match.group(1)) if match else None

def clean_flavor_text(text):
    if not text:
        return ""
    # PokeAPI's flavor texts contain \n, \f, \u3000, etc.
    cleaned = text.replace('\n', ' ').replace('\f', ' ').replace('\r', ' ')
    cleaned = re.sub(r'\s+', ' ', cleaned)
    return cleaned.strip()

def fetch_single_pokemon(pokemon_id):
    pokemon_url = f"https://pokeapi.co/api/v2/pokemon/{pokemon_id}"
    species_url = f"https://pokeapi.co/api/v2/pokemon-species/{pokemon_id}"

    pokemon_data = fetch_json(pokemon_url)
    species_data = fetch_json(species_url)

    if not pokemon_data or not species_data:
        print(f"\n[WARN] Incomplete data for Pokemon ID: {pokemon_id}")
        return None

    # Name extraction
    name_ja = None
    name_kana = None
    name_en = pokemon_data.get('name', '')

    for n in species_data.get('names', []):
        lang = n['language']['name']
        if lang == 'ja':
            name_ja = n['name']
        elif lang == 'ja-Hrkt':
            name_kana = n['name']
        elif lang == 'en' and not name_en:
            name_en = n['name']

    if not name_ja:
        name_ja = name_kana if name_kana else name_en

    # Genus (Category/Classification)
    genus_ja = None
    for g in species_data.get('genera', []):
        if g['language']['name'] == 'ja':
            genus_ja = g['genus']
            break
        elif g['language']['name'] == 'ja-Hrkt' and not genus_ja:
            genus_ja = g['genus']

    # Generation
    gen_num = extract_generation_number(species_data.get('generation'))

    # Types
    types_list = sorted(pokemon_data.get('types', []), key=lambda x: x['slot'])
    type1 = types_list[0]['type']['name'] if len(types_list) > 0 else 'unknown'
    type2 = types_list[1]['type']['name'] if len(types_list) > 1 else None

    # Height (decimetres -> metres) & Weight (hectograms -> kg)
    height_m = pokemon_data.get('height', 0) / 10.0
    weight_kg = pokemon_data.get('weight', 0) / 10.0

    # Stats
    stats_dict = {}
    for s in pokemon_data.get('stats', []):
        stats_dict[s['stat']['name']] = s['base_stat']

    hp = stats_dict.get('hp', 0)
    attack = stats_dict.get('attack', 0)
    defense = stats_dict.get('defense', 0)
    sp_attack = stats_dict.get('special-attack', 0)
    sp_defense = stats_dict.get('special-defense', 0)
    speed = stats_dict.get('speed', 0)
    base_stats_total = hp + attack + defense + sp_attack + sp_defense + speed

    # Legendary / Mythical
    is_legendary = 1 if species_data.get('is_legendary') else 0
    is_mythical = 1 if species_data.get('is_mythical') else 0

    # Sprites
    sprites = pokemon_data.get('sprites', {})
    sprite_url = sprites.get('front_default')
    other_sprites = sprites.get('other', {})
    official_artwork = other_sprites.get('official-artwork', {}) if isinstance(other_sprites, dict) else {}
    artwork_url = official_artwork.get('front_default')

    # Flavor Text Entries (Japanese first, fallback to English)
    flavor_texts = []
    rep_flavor_text_ja = ""
    rep_flavor_text_en = ""

    for ft in species_data.get('flavor_text_entries', []):
        lang = ft['language']['name']
        if lang in ('ja', 'ja-Hrkt', 'en'):
            raw_text = ft['flavor_text']
            cleaned = clean_flavor_text(raw_text)
            version_name = ft['version']['name']
            flavor_texts.append({
                'version_name': version_name,
                'language': lang,
                'flavor_text': cleaned
            })
            if lang == 'ja' and not rep_flavor_text_ja:
                rep_flavor_text_ja = cleaned
            elif lang == 'ja-Hrkt' and not rep_flavor_text_ja:
                rep_flavor_text_ja = cleaned
            elif lang == 'en' and not rep_flavor_text_en:
                rep_flavor_text_en = cleaned

    # Fallback representative flavor text: Japanese first, then English
    rep_flavor_text = rep_flavor_text_ja if rep_flavor_text_ja else rep_flavor_text_en

    record = {
        'id': pokemon_id,
        'name_ja': name_ja,
        'name_kana': name_kana,
        'name_en': name_en,
        'genus_ja': genus_ja,
        'generation': gen_num,
        'type1': type1,
        'type2': type2,
        'height': height_m,
        'weight': weight_kg,
        'hp': hp,
        'attack': attack,
        'defense': defense,
        'special_attack': sp_attack,
        'special_defense': sp_defense,
        'speed': speed,
        'base_stats_total': base_stats_total,
        'is_legendary': is_legendary,
        'is_mythical': is_mythical,
        'flavor_text_ja': rep_flavor_text,
        'sprite_url': sprite_url,
        'artwork_url': artwork_url,
        'flavor_texts': flavor_texts
    }

    return record

def create_db_tables(conn):
    cursor = conn.cursor()
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS pokemons (
        id INTEGER PRIMARY KEY,
        name_ja TEXT NOT NULL,
        name_kana TEXT,
        name_en TEXT NOT NULL,
        genus_ja TEXT,
        generation INTEGER,
        type1 TEXT NOT NULL,
        type2 TEXT,
        height REAL,
        weight REAL,
        hp INTEGER NOT NULL,
        attack INTEGER NOT NULL,
        defense INTEGER NOT NULL,
        special_attack INTEGER NOT NULL,
        special_defense INTEGER NOT NULL,
        speed INTEGER NOT NULL,
        base_stats_total INTEGER NOT NULL,
        is_legendary INTEGER NOT NULL,
        is_mythical INTEGER NOT NULL,
        flavor_text_ja TEXT,
        sprite_url TEXT,
        artwork_url TEXT
    )
    ''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS flavor_texts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        pokemon_id INTEGER NOT NULL,
        version_name TEXT NOT NULL,
        language TEXT NOT NULL,
        flavor_text TEXT NOT NULL,
        FOREIGN KEY (pokemon_id) REFERENCES pokemons(id)
    )
    ''')

    cursor.execute('CREATE INDEX IF NOT EXISTS idx_pokemons_name_ja ON pokemons(name_ja)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_flavor_texts_pokemon_id ON flavor_texts(pokemon_id)')
    conn.commit()

def save_to_sqlite(records, db_path):
    conn = sqlite3.connect(db_path)
    create_db_tables(conn)
    cursor = conn.cursor()

    # Clear existing data if any
    cursor.execute('DELETE FROM flavor_texts')
    cursor.execute('DELETE FROM pokemons')

    for r in records:
        cursor.execute('''
        INSERT INTO pokemons (
            id, name_ja, name_kana, name_en, genus_ja, generation,
            type1, type2, height, weight, hp, attack, defense,
            special_attack, special_defense, speed, base_stats_total,
            is_legendary, is_mythical, flavor_text_ja, sprite_url, artwork_url
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            r['id'], r['name_ja'], r['name_kana'], r['name_en'], r['genus_ja'], r['generation'],
            r['type1'], r['type2'], r['height'], r['weight'], r['hp'], r['attack'], r['defense'],
            r['special_attack'], r['special_defense'], r['speed'], r['base_stats_total'],
            r['is_legendary'], r['is_mythical'], r['flavor_text_ja'], r['sprite_url'], r['artwork_url']
        ))

        for ft in r['flavor_texts']:
            cursor.execute('''
            INSERT INTO flavor_texts (pokemon_id, version_name, language, flavor_text)
            VALUES (?, ?, ?, ?)
            ''', (r['id'], ft['version_name'], ft['language'], ft['flavor_text']))

    conn.commit()
    conn.close()

def main():
    print(f"=== Starting PokeAPI Data Extraction (1 to {MAX_POKEMON_ID}) ===")
    start_time = time.time()

    records = []
    completed_count = 0

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_id = {executor.submit(fetch_single_pokemon, pid): pid for pid in range(1, MAX_POKEMON_ID + 1)}
        
        for future in as_completed(future_to_id):
            pid = future_to_id[future]
            try:
                data = future.result()
                if data:
                    records.append(data)
                completed_count += 1
                percent = (completed_count / MAX_POKEMON_ID) * 100
                sys.stdout.write(f"\rProgress: {completed_count}/{MAX_POKEMON_ID} ({percent:.1f}%)")
                sys.stdout.flush()
            except Exception as exc:
                print(f"\n[ERROR] Pokemon ID {pid} generated an exception: {exc}")

    print(f"\nFetched {len(records)} records successfully.")

    # Sort records by ID
    records.sort(key=lambda x: x['id'])

    # Save to SQLite DB
    print(f"Saving to SQLite database ({DB_PATH})...")
    save_to_sqlite(records, DB_PATH)

    # Save to JSON
    print(f"Saving to JSON file ({JSON_PATH})...")
    with open(JSON_PATH, 'w', encoding='utf-8') as f:
        json.dump(records, f, ensure_ascii=False, indent=2)

    elapsed = time.time() - start_time
    print(f"=== Done! Total time elapsed: {elapsed:.2f} seconds ===")

if __name__ == '__main__':
    main()
