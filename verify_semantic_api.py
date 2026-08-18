import json
import math
import urllib.request


ENDPOINT = "http://localhost:8000/api/pokemon/calculate_coord"

CASES = {
    "flame": "火山の火口で灼熱の炎を吐き、マグマの熱で体を温める。",
    "water": "深海を泳ぎ、水流を操って大波を起こす。",
    "electric": "体内に電気をため、強烈な放電で相手をしびれさせる。",
    "plant": "森で太陽の光を浴び、葉っぱから栄養を作って育つ。",
    "rock": "岩石のように硬い甲羅で攻撃を防ぐ。",
    "flight": "大空を翼で飛行し、力強く羽ばたく。",
    "poison": "猛毒の毒針と胞子で相手を弱らせる。",
    "strength": "鍛えた筋肉と怪力で大岩を砕き、敵を投げ飛ばす。",
    "profile": "休日はカフェでのんびり読書をして過ごすのが好きです。",
}

EXPECTED_TERMS = {
    "flame": {"炎", "燃える"},
    "water": {"水", "川", "泳ぐ"},
    "electric": {"電気", "放電"},
    "plant": {"光", "太陽"},
    "rock": {"殻", "鋼鉄"},
    "flight": {"飛ぶ", "翼"},
    "strength": {"力", "操る"},
}


def project(text):
    request = urllib.request.Request(
        ENDPOINT,
        data=json.dumps({"flavor_text_ja": text}, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=90) as response:
        return json.load(response)


def main():
    results = {}
    errors = []
    for name, text in CASES.items():
        result = project(text)
        keywords = result.get("cluster_keywords", "")
        compact = {
            "status": result.get("status"),
            "cluster_id": result.get("cluster_id"),
            "cluster_keywords": keywords,
            "x": result.get("x"),
            "y": result.get("y"),
        }
        results[name] = compact
        if result.get("status") != "ok" or not all(
            math.isfinite(float(result.get(axis, float("nan")))) for axis in ("x", "y")
        ):
            errors.append(f"{name}: invalid projection")
        expected = EXPECTED_TERMS.get(name)
        if expected and not any(term in keywords for term in expected):
            errors.append(f"{name}: unexpected cluster label {keywords!r}")

    representative_names = [name for name in CASES if name != "profile"]
    semantic_clusters = {results[name]["cluster_id"] for name in representative_names}
    if len(semantic_clusters) != len(representative_names):
        errors.append(
            f"representative themes collapsed to {len(semantic_clusters)} of "
            f"{len(representative_names)} distinct clusters"
        )

    print(json.dumps({"status": "ok" if not errors else "error", "results": results, "errors": errors}, ensure_ascii=False, indent=2))
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
