import json
import math
import sys


MAP_FILE = "pokemon_map_data.json"
MIN_DISTANCE = 28.0
REGRESSION_EXPECTATIONS = {
    "リザードン": {"炎", "燃える"},
    "カメックス": {"水", "川"},
    "トランセル": {"殻", "鋼鉄"},
    "コクーン": {"殻", "鋼鉄"},
    "オニスズメ": {"飛ぶ", "翼"},
}


def verify_map_quality():
    with open(MAP_FILE, "r", encoding="utf-8") as handle:
        payload = json.load(handle)

    meta = payload.get("meta", {})
    metrics = meta.get("quality_metrics", {})
    clusters = payload.get("clusters", [])
    pokemons = payload.get("pokemons", [])

    errors = []
    if meta.get("classification_basis") != "japanese_flavor_texts_only":
        errors.append("classification_basis must be japanese_flavor_texts_only")
    if len(pokemons) != 500:
        errors.append(f"expected 500 Pokemon, found {len(pokemons)}")
    if not 7 <= len(clusters) <= 9:
        errors.append(f"expected 7-9 clusters, found {len(clusters)}")
    if metrics.get("sparse_zero_count") != 0:
        errors.append(f"sparse_zero_count is {metrics.get('sparse_zero_count')}")
    type_purity = metrics.get("primary_type_purity_weighted")
    if not isinstance(type_purity, (int, float)) or not 0.0 <= type_purity <= 1.0:
        errors.append("primary_type_purity_weighted is missing or invalid")
    if len(metrics.get("primary_type_purity_by_cluster", [])) != len(clusters):
        errors.append("primary_type_purity_by_cluster does not match cluster count")

    cluster_ids = {cluster.get("id") for cluster in clusters}
    calculated_counts = {cluster_id: 0 for cluster_id in cluster_ids}
    points = []
    for pokemon in pokemons:
        x = pokemon.get("x")
        y = pokemon.get("y")
        cluster_id = pokemon.get("cluster_id")
        if not isinstance(x, (int, float)) or not math.isfinite(x):
            errors.append(f"invalid x for Pokemon {pokemon.get('id')}")
        if not isinstance(y, (int, float)) or not math.isfinite(y):
            errors.append(f"invalid y for Pokemon {pokemon.get('id')}")
        if cluster_id not in cluster_ids:
            errors.append(f"invalid cluster_id for Pokemon {pokemon.get('id')}: {cluster_id}")
        else:
            calculated_counts[cluster_id] += 1
        points.append((float(x), float(y), pokemon.get("id")))

    for cluster in clusters:
        words = cluster.get("top_words", [])
        if len(words) not in (2, 3):
            errors.append(f"cluster {cluster.get('id')} has {len(words)} label words")
        if cluster.get("keywords") != " / ".join(words):
            errors.append(f"cluster {cluster.get('id')} keyword serialization mismatch")
        count = calculated_counts.get(cluster.get("id"), 0)
        if count != cluster.get("count"):
            errors.append(f"cluster {cluster.get('id')} count mismatch: {count} != {cluster.get('count')}")
        if count < 15 or count > 125:
            errors.append(f"cluster {cluster.get('id')} violates size bounds: {count}")

    cluster_words = {
        cluster.get("id"): set(cluster.get("top_words", [])) for cluster in clusters
    }
    pokemon_by_name = {pokemon.get("name_ja"): pokemon for pokemon in pokemons}
    regression_results = {}
    for name, expected_words in REGRESSION_EXPECTATIONS.items():
        pokemon = pokemon_by_name.get(name)
        actual_words = cluster_words.get(pokemon.get("cluster_id"), set()) if pokemon else set()
        passed = bool(actual_words.intersection(expected_words))
        regression_results[name] = {
            "cluster_id": pokemon.get("cluster_id") if pokemon else None,
            "keywords": " / ".join(sorted(actual_words)),
            "passed": passed,
        }
        if not passed:
            errors.append(
                f"semantic regression failed for {name}: {sorted(actual_words)}"
            )

    minimum_seen = float("inf")
    collision_pairs = []
    for index, left in enumerate(points):
        for right in points[index + 1:]:
            distance = math.hypot(left[0] - right[0], left[1] - right[1])
            minimum_seen = min(minimum_seen, distance)
            if distance < MIN_DISTANCE - 0.02:
                collision_pairs.append((left[2], right[2], distance))
    if collision_pairs:
        errors.append(f"found {len(collision_pairs)} node collisions; first={collision_pairs[0]}")

    print(json.dumps({
        "status": "ok" if not errors else "error",
        "pokemon_count": len(pokemons),
        "cluster_count": len(clusters),
        "cluster_sizes": [cluster.get("count") for cluster in clusters],
        "sparse_zero_count": metrics.get("sparse_zero_count"),
        "minimum_point_distance": round(minimum_seen, 4),
        "labels": [cluster.get("keywords") for cluster in clusters],
        "semantic_regressions": regression_results,
        "errors": errors,
    }, ensure_ascii=False, indent=2))
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    verify_map_quality()
