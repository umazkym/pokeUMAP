import sqlite3
import csv
import sys

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

DB_PATH = 'pokemon.db'

def export_pokemon_csv(output_file='pokemon_sample_100.csv', limit=100):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    query = '''
    SELECT id, name_ja, name_kana, name_en, genus_ja, generation, 
           type1, type2, height, weight, hp, attack, defense, 
           special_attack, special_defense, speed, base_stats_total, 
           is_legendary, is_mythical, flavor_text_ja, sprite_url, artwork_url
    FROM pokemons
    ORDER BY id
    '''
    if limit:
        query += f" LIMIT {limit}"

    cursor.execute(query)
    rows = cursor.fetchall()
    headers = [column[0] for column in cursor.description]
    conn.close()

    # Write as UTF-8 with BOM (utf-8-sig) for seamless Excel compatibility
    with open(output_file, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerows(rows)

    print(f"Successfully exported {len(rows)} records to '{output_file}'.")

if __name__ == '__main__':
    # Export 100 sample rows
    export_pokemon_csv('pokemon_sample_100.csv', limit=1025)
