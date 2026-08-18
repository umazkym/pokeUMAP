import itertools
import json
import math
import os
import pickle
import re
import sqlite3
import sys
import tempfile
from collections import Counter
from difflib import SequenceMatcher

import numpy as np
import scipy.sparse as sp
import umap
from sentence_transformers import SentenceTransformer
from sklearn.cluster import KMeans
from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import normalize
from sudachipy import dictionary, tokenizer

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

DB_PATH = "pokemon.db"
OUTPUT_JSON = "pokemon_map_data.json"
MODEL_PICKLE = "umap_model.pkl"
MODEL_NAME = "intfloat/multilingual-e5-small"
MODEL_VERSION = "semantic-map-v3"
LAYOUT_VERSION = "anchored-collision-v1"

DENSE_WEIGHT = 0.65
SPARSE_WEIGHT = 0.35
CHAR_WEIGHT = 0.25
DENSE_RAW_WEIGHT = 0.35
DENSE_CONCEPT_WEIGHT = 0.65
MAX_SEMANTIC_TEXTS = 6
MIN_POINT_DISTANCE = 28.0
MAP_MIN = 40.0
MAP_MAX = 960.0

GENERAL_STOP_WORDS = {
    "ポケモン", "自分", "相手", "場合", "存在", "確認", "記録", "時間", "瞬間",
    "以内", "以上", "以下", "全体", "部分", "周囲", "近く", "遠く", "世界", "一番",
    "発見", "場所", "仲間", "性格", "普段", "特徴", "様子", "状態", "理由", "原因",
    "方法", "変化", "効果", "攻撃", "安心", "大変", "自由", "危険", "注意", "関係",
    "種類", "情報", "調査", "研究", "現在", "当時", "以前", "最初", "最後", "中心",
    "能力", "行動", "生活", "誕生", "最高", "強力", "特殊", "普通", "可能", "必要",
    "姿", "体", "見る", "見える", "出す", "なる", "持つ", "使う", "大きい", "小さい",
    "強い", "弱い", "高い", "低い", "深い", "浅い", "重い", "軽い", "子供", "進化",
    "キロ", "メートル", "時速", "毎日", "いつも", "すべて", "前", "後", "上", "下",
    "中", "外", "間", "内", "もの", "こと", "よう", "ため", "ところ", "とき", "たち",
    "これ", "それ", "その", "この", "あの", "どの", "また", "そして", "という", "できる",
    "いる", "ある", "する", "れる", "られる", "なる", "やる", "いう", "くる", "いく",
    "見張る", "気持ち", "模様", "習性", "大昔", "巨大", "生息", "暮らす", "住む",
    "動く", "歩く", "立つ", "平気", "不思議", "地域", "アピール", "生命力", "パワー",
    "元気", "発散", "液体", "詳細", "説明", "居る", "有る", "為る", "成る", "出来る",
    "言う", "呼ぶ", "作る", "仕舞う", "覗き込む", "捲る", "取る", "付く", "入る", "出る",
    "分かる", "知る", "思う", "考える", "得意", "不得意", "好き", "嫌い", "臆病", "不気味",
    "活発", "盛ん", "丈夫", "大好物"
}

LABEL_ONLY_STOP_WORDS = {"物", "人", "人間", "時"}

ALLOWED_POS = {"名詞", "動詞", "形容詞"}
EXCLUDED_SUBPOS = {"代名詞", "数詞", "助数詞可能", "接尾辞", "形式名詞"}
_TOKENIZER = None
_SPLIT_MODE = tokenizer.Tokenizer.SplitMode.C


def get_tokenizer():
    global _TOKENIZER
    if _TOKENIZER is None:
        _TOKENIZER = dictionary.Dictionary().create()
    return _TOKENIZER


def normalize_text(text):
    return re.sub(r"\s+", " ", (text or "").replace("\n", " ").replace("\f", " ")).strip()


def is_meaningful_term(term):
    """Keep content words, including semantically important one-kanji concepts such as 炎 or 毒."""
    if not term or term in GENERAL_STOP_WORDS or term.isdigit():
        return False
    if len(term) < 2 and not re.fullmatch(r"[一-龯]", term):
        return False
    return bool(re.search(r"[一-龯ぁ-んァ-ヶーA-Za-z]", term))


def extract_content_terms(text):
    """Return display-safe content lemmas using a domain-independent Japanese parser."""
    terms = []
    for morpheme in get_tokenizer().tokenize(normalize_text(text), _SPLIT_MODE):
        pos = morpheme.part_of_speech()
        main_pos = pos[0]
        sub_pos = set(pos[1:4])
        if main_pos not in ALLOWED_POS or sub_pos.intersection(EXCLUDED_SUBPOS):
            continue
        term = morpheme.normalized_form().strip()
        term = re.sub(r"^[\W_]+|[\W_]+$", "", term, flags=re.UNICODE)
        if not is_meaningful_term(term):
            continue
        terms.append(term)
    return terms


def extract_label_terms(text):
    """Return concrete nouns/actions and compounds suitable for short map headings."""
    terms = []
    for morpheme in get_tokenizer().tokenize(normalize_text(text), _SPLIT_MODE):
        pos = morpheme.part_of_speech()
        if pos[0] not in {"名詞", "動詞"} or set(pos[1:4]).intersection(EXCLUDED_SUBPOS):
            continue
        term = morpheme.normalized_form().strip()
        term = re.sub(r"^[\W_]+|[\W_]+$", "", term, flags=re.UNICODE)
        if is_meaningful_term(term):
            terms.append(term)
    return terms


def make_label_candidates(terms):
    candidates = list(dict.fromkeys(terms))
    for left, right in zip(terms, terms[1:]):
        if left != right:
            candidates.append(f"{left} {right}")
    return list(dict.fromkeys(candidates))


def display_term(term):
    return term.replace(" ", "")


def build_sparse_features(texts, fit=True, artifacts=None):
    token_lists = [extract_content_terms(text) for text in texts]
    token_docs = [" ".join(terms) for terms in token_lists]
    raw_docs = [normalize_text(text) for text in texts]

    if fit:
        word_vectorizer = TfidfVectorizer(
            tokenizer=str.split,
            preprocessor=None,
            token_pattern=None,
            lowercase=False,
            ngram_range=(1, 2),
            min_df=2,
            max_df=0.85,
            sublinear_tf=True,
            max_features=4000,
        )
        char_vectorizer = TfidfVectorizer(
            analyzer="char",
            ngram_range=(2, 4),
            min_df=2,
            max_df=0.95,
            sublinear_tf=True,
            max_features=6000,
        )
        word_matrix = word_vectorizer.fit_transform(token_docs)
        char_matrix = char_vectorizer.fit_transform(raw_docs)
        combined_sparse = sp.hstack([word_matrix, char_matrix * CHAR_WEIGHT], format="csr")
        n_components = min(64, max(2, combined_sparse.shape[1] - 1))
        sparse_projector = TruncatedSVD(n_components=n_components, random_state=42)
        projected = sparse_projector.fit_transform(combined_sparse)
        artifacts = {
            "word_vectorizer": word_vectorizer,
            "char_vectorizer": char_vectorizer,
            "sparse_projector": sparse_projector,
        }
    else:
        word_matrix = artifacts["word_vectorizer"].transform(token_docs)
        char_matrix = artifacts["char_vectorizer"].transform(raw_docs)
        combined_sparse = sp.hstack([word_matrix, char_matrix * CHAR_WEIGHT], format="csr")
        projected = artifacts["sparse_projector"].transform(combined_sparse)

    zero_rows = int(np.sum(np.asarray(combined_sparse.getnnz(axis=1)) == 0))
    return normalize(projected), token_lists, zero_rows, artifacts


def build_hybrid_features(texts, model, fit_sparse=True, sparse_artifacts=None):
    sparse_features, token_lists, zero_rows, sparse_artifacts = build_sparse_features(
        texts, fit=fit_sparse, artifacts=sparse_artifacts
    )
    raw_dense = model.encode(
        [f"passage: {normalize_text(text)}" for text in texts],
        show_progress_bar=len(texts) > 20,
        normalize_embeddings=True,
    )
    concept_docs = [" ".join(terms) or normalize_text(text) for terms, text in zip(token_lists, texts)]
    concept_dense = model.encode(
        [f"passage: {document}" for document in concept_docs],
        show_progress_bar=len(texts) > 20,
        normalize_embeddings=True,
    )
    dense = normalize(
        raw_dense * DENSE_RAW_WEIGHT + concept_dense * DENSE_CONCEPT_WEIGHT
    )
    hybrid = np.hstack([dense * DENSE_WEIGHT, sparse_features * SPARSE_WEIGHT])
    hybrid = normalize(hybrid)
    return hybrid, token_lists, zero_rows, sparse_artifacts


def _near_duplicate(left, right):
    a = display_term(left).lower()
    b = display_term(right).lower()
    if a in b or b in a:
        return True
    reading_a = "".join(
        morpheme.reading_form() for morpheme in get_tokenizer().tokenize(a, _SPLIT_MODE)
    )
    reading_b = "".join(
        morpheme.reading_form() for morpheme in get_tokenizer().tokenize(b, _SPLIT_MODE)
    )
    if reading_a and reading_a == reading_b:
        return True
    return SequenceMatcher(None, a, b).ratio() >= 0.82


def _positive_npmi(left, right, document_sets, global_df):
    total = len(document_sets)
    both = sum(left in doc and right in doc for doc in document_sets)
    if both == 0:
        return 0.0
    px = global_df[left] / total
    py = global_df[right] / total
    pxy = both / total
    value = math.log(pxy / (px * py)) / -math.log(pxy)
    # Rare one-off co-occurrences otherwise receive an unrealistically perfect NPMI.
    confidence = min(1.0, both / 3.0)
    return float(max(0.0, min(1.0, value)) * confidence)


def rank_cluster_keywords(labels, cluster_id, token_lists, model, embedding_cache):
    member_indices = np.where(labels == cluster_id)[0]
    cluster_size = len(member_indices)
    minimum_support = max(2, math.ceil(cluster_size * 0.04))
    per_doc_candidates = [set(make_label_candidates(tokens)) for tokens in token_lists]
    global_df = Counter(term for terms in per_doc_candidates for term in terms)
    cluster_df = Counter(term for i in member_indices for term in per_doc_candidates[i])

    relevance = {}
    for term, support in cluster_df.items():
        if (
            support < minimum_support
            or display_term(term) in GENERAL_STOP_WORDS
            or display_term(term) in LABEL_ONLY_STOP_WORDS
        ):
            continue
        specificity = math.log((len(token_lists) + 1) / (global_df[term] + 1))
        support_rate = support / cluster_size
        relevance[term] = support_rate * specificity
    if len(relevance) < 2:
        return None

    ranked = sorted(relevance, key=relevance.get, reverse=True)[:20]
    max_relevance = max(relevance[term] for term in ranked) or 1.0
    normalized_relevance = {term: relevance[term] / max_relevance for term in ranked}

    missing = [term for term in ranked if term not in embedding_cache]
    if missing:
        vectors = model.encode(
            [f"query: {display_term(term)}" for term in missing],
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        embedding_cache.update(zip(missing, vectors))

    def pair_metrics(left, right):
        semantic = float(max(0.0, np.dot(embedding_cache[left], embedding_cache[right])))
        cooccurrence = _positive_npmi(left, right, per_doc_candidates, global_df)
        return semantic, cooccurrence

    best_pair = None
    for terms in itertools.combinations(ranked, 2):
        if _near_duplicate(*terms):
            continue
        semantic, cooccurrence = pair_metrics(*terms)
        if semantic < 0.28 and cooccurrence == 0.0:
            continue
        rel = sum(normalized_relevance[t] for t in terms) / 2
        score = 0.45 * rel + 0.35 * semantic + 0.20 * cooccurrence
        if best_pair is None or score > best_pair[0]:
            best_pair = (score, terms, semantic, cooccurrence)
    if best_pair is None:
        return None

    selected = best_pair
    for terms in itertools.combinations(ranked, 3):
        if any(_near_duplicate(a, b) for a, b in itertools.combinations(terms, 2)):
            continue
        pairs = [pair_metrics(a, b) for a, b in itertools.combinations(terms, 2)]
        mean_semantic = float(np.mean([pair[0] for pair in pairs]))
        mean_npmi = float(np.mean([pair[1] for pair in pairs]))
        if min(pair[0] for pair in pairs) < 0.32 and mean_npmi == 0.0:
            continue
        rel = sum(normalized_relevance[t] for t in terms) / 3
        score = 0.45 * rel + 0.35 * mean_semantic + 0.20 * mean_npmi
        if score >= selected[0] + 0.015:
            selected = (score, terms, mean_semantic, mean_npmi)

    score, terms, semantic, cooccurrence = selected
    coherence = 0.65 * semantic + 0.35 * cooccurrence
    return {
        "top_words": [display_term(term) for term in terms],
        "keywords": " / ".join(display_term(term) for term in terms),
        "coherence_score": round(float(coherence), 4),
        "selection_score": round(float(score), 4),
        "minimum_support": minimum_support,
    }


def select_cluster_model(features, token_lists, model):
    candidates = []
    embedding_cache = {}
    for cluster_count in (7, 8, 9):
        clusterer = KMeans(n_clusters=cluster_count, n_init=20, random_state=42)
        labels = clusterer.fit_predict(features)
        counts = np.bincount(labels, minlength=cluster_count)
        if int(counts.min()) < 15 or int(counts.max()) > 125:
            print(f"k={cluster_count}: rejected by size bounds {counts.tolist()}")
            continue

        keyword_meta = []
        valid = True
        for cluster_id in range(cluster_count):
            meta = rank_cluster_keywords(labels, cluster_id, token_lists, model, embedding_cache)
            if meta is None:
                print(f"k={cluster_count}: cluster {cluster_id} has no coherent label pair")
                valid = False
                break
            keyword_meta.append(meta)
        if not valid:
            print(f"k={cluster_count}: rejected because a coherent label pair was unavailable")
            continue

        silhouette = float(silhouette_score(features, labels, metric="cosine"))
        normalized_silhouette = (silhouette + 1.0) / 2.0
        probabilities = counts / counts.sum()
        entropy = float(-np.sum(probabilities * np.log(probabilities)) / math.log(cluster_count))
        label_coherence = float(np.mean([meta["coherence_score"] for meta in keyword_meta]))
        total_score = 0.50 * normalized_silhouette + 0.35 * label_coherence + 0.15 * entropy
        candidates.append({
            "cluster_count": cluster_count, "clusterer": clusterer, "labels": labels,
            "counts": counts, "keyword_meta": keyword_meta, "silhouette": silhouette,
            "size_entropy": entropy, "label_coherence": label_coherence,
            "selection_score": total_score,
        })
        print(
            f"k={cluster_count}: score={total_score:.4f}, silhouette={silhouette:.4f}, "
            f"coherence={label_coherence:.4f}, entropy={entropy:.4f}, sizes={counts.tolist()}, "
            f"labels={[meta['keywords'] for meta in keyword_meta]}"
        )
    if not candidates:
        raise RuntimeError("No k in {7, 8, 9} passed cluster size and keyword coherence gates")

    candidates.sort(key=lambda item: (-item["selection_score"], item["cluster_count"]))
    best = candidates[0]
    for candidate in candidates[1:]:
        if best["selection_score"] - candidate["selection_score"] <= 0.01:
            if candidate["cluster_count"] < best["cluster_count"]:
                best = candidate
    print(f"Selected k={best['cluster_count']} with score={best['selection_score']:.4f}")
    return best


def robust_scale_coordinates(coords_raw):
    low_x, high_x = np.quantile(coords_raw[:, 0], [0.02, 0.98])
    low_y, high_y = np.quantile(coords_raw[:, 1], [0.02, 0.98])

    def scale_axis(values, low, high):
        span = high - low if high > low else 1.0
        return np.clip(MAP_MIN + ((values - low) / span) * (MAP_MAX - MAP_MIN), MAP_MIN, MAP_MAX)

    scaled = np.column_stack([
        scale_axis(coords_raw[:, 0], low_x, high_x),
        scale_axis(coords_raw[:, 1], low_y, high_y),
    ])
    return scaled, {
        "low_x": float(low_x), "high_x": float(high_x),
        "low_y": float(low_y), "high_y": float(high_y),
    }


def scale_projected_coordinate(raw_x, raw_y, bounds):
    def scale(value, low, high):
        span = high - low if high > low else 1.0
        return float(np.clip(MAP_MIN + ((value - low) / span) * (MAP_MAX - MAP_MIN), MAP_MIN, MAP_MAX))
    return (
        scale(raw_x, bounds["low_x"], bounds["high_x"]),
        scale(raw_y, bounds["low_y"], bounds["high_y"]),
    )


def _count_collisions(points, minimum_distance=MIN_POINT_DISTANCE):
    count = 0
    min_seen = float("inf")
    for i in range(len(points)):
        for j in range(i + 1, len(points)):
            distance = float(np.linalg.norm(points[i] - points[j]))
            min_seen = min(min_seen, distance)
            if distance < minimum_distance - 1e-6:
                count += 1
    return count, min_seen


def relax_collisions(anchors, minimum_distance=MIN_POINT_DISTANCE, max_iterations=500):
    points = np.array(anchors, dtype=float, copy=True)
    for _ in range(max_iterations):
        movement = (anchors - points) * 0.012
        collisions = 0
        grid = {}
        for index, point in enumerate(points):
            cell = (int(point[0] // minimum_distance), int(point[1] // minimum_distance))
            grid.setdefault(cell, []).append(index)
        for cell, indices in grid.items():
            nearby = []
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    nearby.extend(grid.get((cell[0] + dx, cell[1] + dy), []))
            for left in indices:
                for right in nearby:
                    if right <= left:
                        continue
                    delta = points[left] - points[right]
                    distance = float(np.linalg.norm(delta))
                    if distance >= minimum_distance:
                        continue
                    collisions += 1
                    if distance < 1e-8:
                        angle = ((left + 1) * 137.508 + (right + 1) * 17.0) * math.pi / 180.0
                        direction = np.array([math.cos(angle), math.sin(angle)])
                    else:
                        direction = delta / distance
                    push = (minimum_distance - distance) * 0.52
                    movement[left] += direction * push
                    movement[right] -= direction * push
        points += movement
        points = np.clip(points, MAP_MIN, MAP_MAX)
        if collisions == 0:
            break

    placed = []
    resolved = np.empty_like(points)
    for index, preferred in enumerate(points):
        candidate = preferred.copy()
        if any(np.linalg.norm(candidate - prior) < minimum_distance for prior in placed):
            found = False
            for ring in range(1, 80):
                radius = ring * (minimum_distance * 0.55)
                steps = max(16, ring * 12)
                start = ((index + 1) * 0.61803398875) % 1.0
                for step in range(steps):
                    angle = 2 * math.pi * (start + step / steps)
                    trial = preferred + np.array([math.cos(angle), math.sin(angle)]) * radius
                    if np.any(trial < MAP_MIN) or np.any(trial > MAP_MAX):
                        continue
                    if all(np.linalg.norm(trial - prior) >= minimum_distance for prior in placed):
                        candidate = trial
                        found = True
                        break
                if found:
                    break
            if not found:
                raise RuntimeError(f"Unable to resolve point collision for index {index}")
        resolved[index] = candidate
        placed.append(candidate.copy())

    collision_count, min_distance = _count_collisions(resolved, minimum_distance)
    if collision_count:
        raise RuntimeError(f"Collision relaxation left {collision_count} unresolved pairs")
    return resolved, float(min_distance)


def find_nearest_free_position(anchor_x, anchor_y, occupied, minimum_distance=MIN_POINT_DISTANCE):
    occupied_points = [np.array(point, dtype=float) for point in occupied]
    preferred = np.array([
        float(np.clip(anchor_x, MAP_MIN, MAP_MAX)),
        float(np.clip(anchor_y, MAP_MIN, MAP_MAX)),
    ])
    if all(np.linalg.norm(preferred - point) >= minimum_distance for point in occupied_points):
        return round(float(preferred[0]), 2), round(float(preferred[1]), 2)
    for ring in range(1, 80):
        radius = ring * (minimum_distance * 0.55)
        steps = max(16, ring * 12)
        for step in range(steps):
            angle = 2 * math.pi * step / steps
            trial = preferred + np.array([math.cos(angle), math.sin(angle)]) * radius
            if np.any(trial < MAP_MIN) or np.any(trial > MAP_MAX):
                continue
            if all(np.linalg.norm(trial - point) >= minimum_distance for point in occupied_points):
                return round(float(trial[0]), 2), round(float(trial[1]), 2)
    raise RuntimeError("No collision-free coordinate is available")


def _atomic_write_json_and_pickle(payload, model_data):
    output_dir = os.path.abspath(os.path.dirname(OUTPUT_JSON) or ".")
    json_temp = None
    pickle_temp = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=output_dir, suffix=".json.tmp") as handle:
            json_temp = handle.name
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        with tempfile.NamedTemporaryFile("wb", delete=False, dir=output_dir, suffix=".pkl.tmp") as handle:
            pickle_temp = handle.name
            pickle.dump(model_data, handle)
        os.replace(pickle_temp, MODEL_PICKLE)
        pickle_temp = None
        os.replace(json_temp, OUTPUT_JSON)
        json_temp = None

        # Synchronize with web/ static directory
        web_json_path = os.path.join(output_dir, "web", "pokemon_map_data.json")
        if os.path.exists(os.path.dirname(web_json_path)):
            with open(web_json_path, "w", encoding="utf-8") as wf:
                json.dump(payload, wf, ensure_ascii=False, indent=2)
    finally:
        for path in (json_temp, pickle_temp):
            if path and os.path.exists(path):
                os.unlink(path)


def build_map_data():
    print(f"Loading SentenceTransformer model ({MODEL_NAME})...")
    model = SentenceTransformer(MODEL_NAME)
    print("Fetching Pokemon 1 to 500 from SQLite database...")
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute("""
            SELECT id, name_ja, name_kana, name_en, genus_ja, flavor_text_ja, type1, type2,
                   height, weight, hp, attack, defense, special_attack, special_defense, speed,
                   base_stats_total, is_legendary, is_mythical, sprite_url, artwork_url
            FROM pokemons WHERE id BETWEEN 1 AND 500 ORDER BY id
        """).fetchall()
        flavor_rows = conn.execute("""
            SELECT pokemon_id, flavor_text
            FROM flavor_texts
            WHERE pokemon_id BETWEEN 1 AND 500 AND language = 'ja'
            ORDER BY pokemon_id, id
        """).fetchall()

    flavor_variants = {}
    for pokemon_id, flavor_text in flavor_rows:
        normalized = normalize_text(flavor_text)
        variants = flavor_variants.setdefault(pokemon_id, [])
        if normalized and normalized not in variants:
            variants.append(normalized)

    pokemon_records = []
    texts = []
    for row in rows:
        (pid, name_ja, name_kana, name_en, genus_ja, flavor_text_ja, type1, type2,
         height, weight, hp, attack, defense, sp_attack, sp_defense, speed,
         bst, is_leg, is_myth, sprite_url, artwork_url) = row
        flavor = flavor_text_ja or "詳細な説明はありません。"
        semantic_variants = [normalize_text(flavor)]
        for variant in flavor_variants.get(pid, []):
            if len(semantic_variants) >= MAX_SEMANTIC_TEXTS:
                break
            if variant not in semantic_variants:
                semantic_variants.append(variant)
        semantic_text = " ".join(semantic_variants)
        texts.append(semantic_text)
        pokemon_records.append({
            "id": pid, "name_ja": name_ja, "name_kana": name_kana or "", "name_en": name_en,
            "genus_ja": genus_ja or "不明", "flavor_text_ja": flavor,
            "type1": type1, "type2": type2 or "", "height": height, "weight": weight,
            "hp": hp, "attack": attack, "defense": defense,
            "special_attack": sp_attack, "special_defense": sp_defense, "speed": speed,
            "base_stats_total": bst, "is_legendary": bool(is_leg), "is_mythical": bool(is_myth),
            "sprite_url": sprite_url or "", "artwork_url": artwork_url or "", "is_custom": False,
            "semantic_text_count": len(semantic_variants),
        })

    print("Building dense and sparse semantic features...")
    features, _, sparse_zero_count, sparse_artifacts = build_hybrid_features(texts, model)
    if sparse_zero_count:
        raise RuntimeError(f"Sparse feature quality gate failed: {sparse_zero_count} zero rows")

    label_token_lists = [extract_label_terms(text) for text in texts]

    print("Selecting a macro-cluster count from k=7,8,9...")
    selected = select_cluster_model(features, label_token_lists, model)
    original_labels = selected["labels"]
    print("Projecting hybrid features with UMAP...")
    reducer = umap.UMAP(
        n_neighbors=20, min_dist=0.18, spread=2.0, n_components=2,
        metric="cosine", random_state=42,
    )
    coords_raw = reducer.fit_transform(features)
    anchors, scale_bounds = robust_scale_coordinates(coords_raw)
    coords, min_point_distance = relax_collisions(anchors)

    old_centers = {
        old_id: np.mean(coords[original_labels == old_id], axis=0)
        for old_id in range(selected["cluster_count"])
    }
    ordered_old_ids = sorted(old_centers, key=lambda old_id: (old_centers[old_id][1], old_centers[old_id][0]))
    cluster_id_map = {old_id: new_id for new_id, old_id in enumerate(ordered_old_ids)}
    labels = np.array([cluster_id_map[int(label)] for label in original_labels], dtype=int)

    palette = ["#f59e0b", "#10b981", "#06b6d4", "#ef4444", "#a855f7", "#3b82f6", "#ec4899", "#84cc16", "#14b8a6"]
    clusters_meta = []
    for old_id in ordered_old_ids:
        cluster_id = cluster_id_map[old_id]
        members = np.where(original_labels == old_id)[0]
        center = np.mean(coords[members], axis=0)
        keyword_meta = selected["keyword_meta"][old_id]
        clusters_meta.append({
            "id": cluster_id, "cx": round(float(center[0]), 2), "cy": round(float(center[1]), 2),
            "count": int(len(members)), "keywords": keyword_meta["keywords"],
            "top_words": keyword_meta["top_words"], "coherence_score": keyword_meta["coherence_score"],
            "minimum_support": keyword_meta["minimum_support"], "color": palette[cluster_id % len(palette)],
        })

    for index, pokemon in enumerate(pokemon_records):
        pokemon["x"] = round(float(coords[index, 0]), 2)
        pokemon["y"] = round(float(coords[index, 1]), 2)
        pokemon["cluster_id"] = int(labels[index])

    counts = [cluster["count"] for cluster in clusters_meta]
    type_purity_diagnostics = []
    majority_total = 0
    for cluster in clusters_meta:
        member_types = [
            pokemon["type1"] for pokemon in pokemon_records
            if pokemon["cluster_id"] == cluster["id"] and pokemon.get("type1")
        ]
        type_counts = Counter(member_types)
        dominant_type, dominant_count = type_counts.most_common(1)[0] if type_counts else (None, 0)
        majority_total += dominant_count
        type_purity_diagnostics.append({
            "cluster_id": cluster["id"],
            "dominant_primary_type": dominant_type,
            "purity": round(dominant_count / len(member_types), 4) if member_types else 0.0,
        })
    cluster_label_embeddings = model.encode(
        [f"passage: {cluster['keywords']}" for cluster in clusters_meta],
        normalize_embeddings=True,
        show_progress_bar=False,
    ).astype(np.float32)
    quality_metrics = {
        "sparse_zero_count": sparse_zero_count, "cluster_count": selected["cluster_count"],
        "cluster_sizes": counts, "min_cluster_size": min(counts), "max_cluster_size": max(counts),
        "silhouette_cosine": round(selected["silhouette"], 6),
        "mean_label_coherence": round(selected["label_coherence"], 6),
        "size_entropy": round(selected["size_entropy"], 6),
        "model_selection_score": round(selected["selection_score"], 6),
        "minimum_point_distance": round(min_point_distance, 4),
        "primary_type_purity_weighted": round(majority_total / len(pokemon_records), 4),
        "primary_type_purity_by_cluster": type_purity_diagnostics,
    }
    payload = {
        "meta": {
            "model_version": MODEL_VERSION, "layout_version": LAYOUT_VERSION,
            "classification_basis": "japanese_flavor_texts_only", "dense_weight": DENSE_WEIGHT,
            "sparse_weight": SPARSE_WEIGHT, "dense_raw_weight": DENSE_RAW_WEIGHT,
            "dense_concept_weight": DENSE_CONCEPT_WEIGHT, "quality_metrics": quality_metrics,
        },
        "clusters": clusters_meta, "pokemons": pokemon_records,
    }
    model_data = {
        "model_version": MODEL_VERSION, "layout_version": LAYOUT_VERSION, "model_name": MODEL_NAME,
        "reducer": reducer, "clusterer": selected["clusterer"], "cluster_id_map": cluster_id_map,
        "scale_bounds": scale_bounds, "clusters": clusters_meta, "sparse_artifacts": sparse_artifacts,
        "dense_weight": DENSE_WEIGHT, "sparse_weight": SPARSE_WEIGHT,
        "dense_raw_weight": DENSE_RAW_WEIGHT, "dense_concept_weight": DENSE_CONCEPT_WEIGHT,
        "minimum_point_distance": MIN_POINT_DISTANCE,
        "training_features": features.astype(np.float32),
        "training_cluster_ids": labels.astype(np.int16),
        "cluster_label_embeddings": cluster_label_embeddings,
    }

    print("Writing validated JSON and model artifacts atomically...")
    _atomic_write_json_and_pickle(payload, model_data)
    for cluster in clusters_meta:
        samples = [p["name_ja"] for p in pokemon_records if p["cluster_id"] == cluster["id"]][:6]
        print(
            f"Cluster {cluster['id']}: n={cluster['count']:3d} [{cluster['keywords']}] "
            f"coherence={cluster['coherence_score']:.3f} samples={', '.join(samples)}"
        )
    print(json.dumps(quality_metrics, ensure_ascii=False, indent=2))
    return payload


if __name__ == "__main__":
    build_map_data()
