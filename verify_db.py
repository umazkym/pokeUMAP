import sqlite3
import sys

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

DB_PATH = 'pokemon.db'

def run_tests():
    print("=== Running DB Verification Tests ===")
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    errors = []

    # Test 1: Record count test
    cursor.execute('SELECT COUNT(*) FROM pokemons')
    count = cursor.fetchone()[0]
    print(f"[TEST 1] Total Pokemon count in DB: {count}")
    if count != 1025:
        errors.append(f"Expected 1025 pokemons, found {count}")

    # Test 2: Name NULL or Empty check
    cursor.execute('SELECT COUNT(*) FROM pokemons WHERE name_ja IS NULL OR name_ja = ""')
    empty_names = cursor.fetchone()[0]
    print(f"[TEST 2] Pokemons without Japanese name: {empty_names}")
    if empty_names > 0:
        errors.append(f"{empty_names} pokemons missing Japanese names")

    # Test 3: Flavor Text NULL or Empty check
    cursor.execute('SELECT COUNT(*) FROM pokemons WHERE flavor_text_ja IS NULL OR flavor_text_ja = ""')
    empty_flavor = cursor.fetchone()[0]
    print(f"[TEST 3] Pokemons without representative flavor text: {empty_flavor}")
    if empty_flavor > 0:
        errors.append(f"{empty_flavor} pokemons missing representative flavor text")

    # Test 4: Subtable flavor_texts check
    cursor.execute('SELECT COUNT(*) FROM flavor_texts')
    total_flavor_texts = cursor.fetchone()[0]
    print(f"[TEST 4] Total version flavor text entries: {total_flavor_texts}")
    if total_flavor_texts == 0:
        errors.append("flavor_texts subtable is empty!")

    # Test 5: Stat total calculation consistency check
    cursor.execute('''
    SELECT id, name_ja, base_stats_total, (hp + attack + defense + special_attack + special_defense + speed) as calc_total
    FROM pokemons
    WHERE base_stats_total != calc_total
    ''')
    stat_mismatches = cursor.fetchall()
    print(f"[TEST 5] Stat total mismatches: {len(stat_mismatches)}")
    if len(stat_mismatches) > 0:
        errors.append(f"Stat sum mismatch found in {len(stat_mismatches)} records")

    # Sample data output
    print("\n--- Sample Record (Pikachu - No.25) ---")
    cursor.execute('''
    SELECT id, name_ja, name_kana, name_en, genus_ja, type1, type2, base_stats_total, flavor_text_ja
    FROM pokemons WHERE id = 25
    ''')
    sample = cursor.fetchone()
    if sample:
        print(f"ID: {sample[0]}")
        print(f"名前 (和名): {sample[1]} ({sample[2]}) / {sample[3]}")
        print(f"分類: {sample[4]}")
        print(f"タイプ: {sample[5]}" + (f" / {sample[6]}" if sample[6] else ""))
        print(f"種族値合計: {sample[7]}")
        print(f"図鑑説明: {sample[8]}")

    conn.close()

    if errors:
        print("\n[FAIL] VERIFICATION FAILED with errors:")
        for err in errors:
            print(f"  - {err}")
        sys.exit(1)
    else:
        print("\n[PASS] ALL VERIFICATION TESTS PASSED SUCCESSFULLY!")

if __name__ == '__main__':
    run_tests()

