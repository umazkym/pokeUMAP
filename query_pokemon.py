import sqlite3
import sys

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

DB_PATH = 'pokemon.db'

def get_connection():
    return sqlite3.connect(DB_PATH)

def search_by_name_or_id(query):
    conn = get_connection()
    cursor = conn.cursor()

    if query.isdigit():
        cursor.execute('SELECT * FROM pokemons WHERE id = ?', (int(query),))
    else:
        cursor.execute('''
        SELECT * FROM pokemons 
        WHERE name_ja LIKE ? OR name_kana LIKE ? OR name_en LIKE ?
        ORDER BY id
        ''', (f'%{query}%', f'%{query}%', f'%{query}%'))

    rows = cursor.fetchall()
    conn.close()
    return rows

def get_flavor_texts(pokemon_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
    SELECT version_name, language, flavor_text
    FROM flavor_texts
    WHERE pokemon_id = ?
    ORDER BY id
    ''', (pokemon_id,))
    rows = cursor.fetchall()
    conn.close()
    return rows

def print_pokemon_detail(p):
    pid, name_ja, name_kana, name_en, genus_ja, gen, t1, t2, height, weight, hp, atk, df, sp_atk, sp_df, spd, total, is_leg, is_myth, flavor_rep, sprite, artwork = p

    print("=" * 60)
    print(f"No.{pid:04d}  {name_ja} ({name_kana})  [{name_en}]")
    print("=" * 60)
    print(f"・分類    : {genus_ja or '不明'} (第{gen}世代)")
    print(f"・タイプ  : {t1}" + (f" / {t2}" if t2 else ""))
    print(f"・高さ/重さ: {height} m / {weight} kg")
    print(f"・属性    : " + ("伝説のポケモン " if is_leg else "") + ("幻のポケモン " if is_myth else "通常"))
    print(f"・種族値  : H:{hp} A:{atk} B:{df} C:{sp_atk} D:{sp_df} S:{spd} (合計: {total})")
    print(f"・代表説明: {flavor_rep}")

    ft_list = get_flavor_texts(pid)
    if ft_list:
        print("\n--- バージョン別図鑑説明 (一部) ---")
        for ft in ft_list[:5]: # 最新5件表示
            print(f"  [{ft[0]:<12}] ({ft[1]}): {ft[2]}")
        if len(ft_list) > 5:
            print(f"  ... 他 {len(ft_list) - 5} 件のバージョン説明があります。")
    print()

def main():
    if len(sys.argv) < 2:
        print("使用法:")
        print("  python query_pokemon.py <検索キーワード/図鑑番号>")
        print("  例: python query_pokemon.py ピカチュウ")
        print("  例: python query_pokemon.py 25")
        sys.exit(0)

    query = sys.argv[1]
    results = search_by_name_or_id(query)

    if not results:
        print(f"'{query}' に一致するポケモンは見つかりませんでした。")
        return

    print(f"検索結果: {len(results)} 件")
    for p in results:
        print_pokemon_detail(p)

if __name__ == '__main__':
    main()
