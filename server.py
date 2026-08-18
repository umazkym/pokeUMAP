import http.server
import socketserver
import json
import urllib.parse
import os
import sys
import pickle

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

PORT = 8000
WEB_DIR = os.path.join(os.path.dirname(__file__), 'web')
JSON_FILE = os.path.join(os.path.dirname(__file__), 'pokemon_map_data.json')
MODEL_PICKLE = os.path.join(os.path.dirname(__file__), 'umap_model.pkl')

# Global lazy loaded transformer model & umap reducer
sentence_model = None
umap_data = None

def load_embedding_models():
    global sentence_model, umap_data
    if umap_data is None and os.path.exists(MODEL_PICKLE):
        print("[SERVER] Loading UMAP reducer pickle...")
        with open(MODEL_PICKLE, 'rb') as f:
            umap_data = pickle.load(f)

        if os.path.exists(JSON_FILE):
            with open(JSON_FILE, 'r', encoding='utf-8') as f:
                map_payload = json.load(f)
            json_version = map_payload.get('meta', {}).get('model_version') if isinstance(map_payload, dict) else None
            model_version = umap_data.get('model_version')
            if json_version and model_version and json_version != model_version:
                raise RuntimeError(
                    f"Map/model version mismatch: JSON={json_version}, model={model_version}"
                )

    if sentence_model is None:
        model_name = (umap_data or {}).get('model_name', 'intfloat/multilingual-e5-small')
        print(f"[SERVER] Loading SentenceTransformer model ({model_name})...")
        from sentence_transformers import SentenceTransformer
        sentence_model = SentenceTransformer(model_name)

class PokeMapRequestHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=WEB_DIR, **kwargs)

    def do_GET(self):
        parsed_path = urllib.parse.urlparse(self.path)
        if parsed_path.path == '/api/pokemon':
            self.handle_get_pokemon()
        else:
            # Fallback to serving static files from web/
            super().do_GET()

    def do_POST(self):
        parsed_path = urllib.parse.urlparse(self.path)
        content_length = int(self.headers.get('Content-Length', 0))
        post_data = self.rfile.read(content_length)

        if parsed_path.path == '/api/pokemon/save':
            self.handle_save_pokemon(post_data)
        elif parsed_path.path == '/api/pokemon/calculate_coord':
            self.handle_calculate_coord(post_data)
        elif parsed_path.path == '/api/pokemon/reset':
            self.handle_reset_pokemon()
        else:
            self.send_error(404, "Endpoint Not Found")

    def handle_get_pokemon(self):
        if not os.path.exists(JSON_FILE):
            self.send_response(404)
            self.end_headers()
            return

        with open(JSON_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)

        self.send_response(200)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode('utf-8'))

    def handle_save_pokemon(self, post_bytes):
        try:
            payload = json.loads(post_bytes.decode('utf-8'))
            with open(JSON_FILE, 'w', encoding='utf-8') as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)

            web_json = os.path.join(WEB_DIR, 'pokemon_map_data.json')
            with open(web_json, 'w', encoding='utf-8') as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)

            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.end_headers()
            self.wfile.write(json.dumps({'status': 'ok', 'message': 'Data saved successfully'}).encode('utf-8'))
        except Exception as e:
            self.send_response(500)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.end_headers()
            self.wfile.write(json.dumps({'status': 'error', 'message': str(e)}).encode('utf-8'))

    def handle_calculate_coord(self, post_bytes):
        try:
            payload = json.loads(post_bytes.decode('utf-8'))
            input_text = (
                payload.get('flavor_text_ja') or 
                payload.get('flavor_text') or 
                payload.get('description') or 
                payload.get('text') or 
                ''
            ).strip()

            if not input_text:
                input_text = "詳細な説明はありません。"

            load_embedding_models()
            if not umap_data:
                raise RuntimeError("Semantic projection model is not available")

            import build_umap_coords
            features, _, _, _ = build_umap_coords.build_hybrid_features(
                [input_text],
                sentence_model,
                fit_sparse=False,
                sparse_artifacts=umap_data['sparse_artifacts'],
            )
            raw_coords = umap_data['reducer'].transform(features)
            anchor_x, anchor_y = build_umap_coords.scale_projected_coordinate(
                float(raw_coords[0, 0]),
                float(raw_coords[0, 1]),
                umap_data['scale_bounds'],
            )

            training_features = umap_data.get('training_features')
            training_cluster_ids = umap_data.get('training_cluster_ids')
            if training_features is not None and training_cluster_ids is not None:
                import numpy as np
                similarities = np.asarray(features @ training_features.T)[0]
                neighbor_count = min(9, len(similarities))
                neighbor_indices = np.argpartition(similarities, -neighbor_count)[-neighbor_count:]
                cluster_scores = {}
                for neighbor_index in neighbor_indices:
                    neighbor_cluster = int(training_cluster_ids[neighbor_index])
                    weight = max(0.0, float(similarities[neighbor_index])) ** 3
                    cluster_scores[neighbor_cluster] = cluster_scores.get(neighbor_cluster, 0.0) + weight
                vote_total = sum(cluster_scores.values()) or 1.0
                vote_probabilities = np.array([
                    cluster_scores.get(cluster_index, 0.0) / vote_total
                    for cluster_index in range(len(umap_data['clusters']))
                ])
                label_embeddings = umap_data.get('cluster_label_embeddings')
                if label_embeddings is not None:
                    query_embedding = sentence_model.encode(
                        [f"query: {input_text}"], normalize_embeddings=True,
                        show_progress_bar=False,
                    )[0]
                    label_similarities = np.asarray(label_embeddings @ query_embedding)
                    label_logits = np.exp((label_similarities - label_similarities.max()) * 8.0)
                    label_probabilities = label_logits / label_logits.sum()
                    input_terms = set(build_umap_coords.extract_content_terms(input_text))
                    input_compact = build_umap_coords.normalize_text(input_text).replace(' ', '')
                    lexical_scores = np.array([
                        sum(
                            1.0
                            for term in item.get('top_words', [])
                            if term in input_terms or term.replace(' ', '') in input_compact
                        )
                        for item in umap_data['clusters']
                    ])
                    if lexical_scores.sum() > 0:
                        lexical_probabilities = lexical_scores / lexical_scores.sum()
                        combined_probabilities = (
                            0.60 * lexical_probabilities
                            + 0.30 * label_probabilities
                            + 0.10 * vote_probabilities
                        )
                    else:
                        combined_probabilities = 0.90 * label_probabilities + 0.10 * vote_probabilities
                    cluster_id = int(np.argmax(combined_probabilities))
                else:
                    cluster_id = max(cluster_scores, key=cluster_scores.get)
            else:
                old_cluster_id = int(umap_data['clusterer'].predict(features)[0])
                cluster_id = int(umap_data['cluster_id_map'][old_cluster_id])
            cluster = next(
                item for item in umap_data['clusters'] if int(item['id']) == cluster_id
            )

            occupied = []
            if os.path.exists(JSON_FILE):
                with open(JSON_FILE, 'r', encoding='utf-8') as f:
                    current_payload = json.load(f)
                current_pokemons = (
                    current_payload.get('pokemons', [])
                    if isinstance(current_payload, dict)
                    else current_payload
                )
                occupied = [
                    (float(item['x']), float(item['y']))
                    for item in current_pokemons
                    if 'x' in item and 'y' in item
                ]
            calc_x, calc_y = build_umap_coords.find_nearest_free_position(
                anchor_x,
                anchor_y,
                occupied,
                minimum_distance=float(umap_data.get('minimum_point_distance', 28.0)),
            )

            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.end_headers()
            self.wfile.write(json.dumps({
                'status': 'ok',
                'x': calc_x,
                'y': calc_y,
                'anchor_x': round(anchor_x, 2),
                'anchor_y': round(anchor_y, 2),
                'cluster_id': cluster_id,
                'cluster_keywords': cluster['keywords'],
            }, ensure_ascii=False).encode('utf-8'))
        except Exception as e:
            print(f"[SERVER ERROR] calculate_coord error: {e}")
            self.send_response(500)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.end_headers()
            self.wfile.write(json.dumps({'status': 'error', 'message': str(e)}).encode('utf-8'))

    def handle_reset_pokemon(self):
        global umap_data
        try:
            import build_umap_coords
            build_umap_coords.build_map_data()
            umap_data = None
            load_embedding_models()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.end_headers()
            self.wfile.write(json.dumps({'status': 'ok', 'message': 'Map data reset to default'}).encode('utf-8'))
        except Exception as e:
            self.send_response(500)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.end_headers()
            self.wfile.write(json.dumps({'status': 'error', 'message': str(e)}).encode('utf-8'))

class ReusableTCPServer(socketserver.TCPServer):
    allow_reuse_address = True

def run_server():
    os.makedirs(WEB_DIR, exist_ok=True)
    with ReusableTCPServer(("", PORT), PokeMapRequestHandler) as httpd:
        print(f"=== PokeMap Server Running at http://localhost:{PORT} ===")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nServer shutting down.")

if __name__ == '__main__':
    run_server()
