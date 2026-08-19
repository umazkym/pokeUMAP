// PokeDB Similarity Map Interactive Engine (Robust Topic Model & Pure Keywords)
(function() {
    'use strict';

    // State Variables
    let pokemons = [];
    let mapClusters = [];
    let mapMeta = {};
    let imageCache = {};
    let selectedPokemon = null;
    let hoveredPokemon = null;
    let isDraggingNode = false;
    let draggedPokemon = null;
    let activeTypeFilter = null;
    let searchQuery = '';
    let pendingAiClusterId = null;
    let pendingAiClusterKeywords = '';
    let viewMode = readViewModeFromUrl();

    // Canvas Transform State
    let scale = 1.0;
    let translateX = 0;
    let translateY = 0;
    let isPanning = false;
    let startPanX = 0;
    let startPanY = 0;

    // Drag & Click Tracking Variables
    let dragStartScreenX = 0;
    let dragStartScreenY = 0;
    let dragOffsetX = 0;
    let dragOffsetY = 0;
    let hasDraggedNode = false;

    // Render Scheduling State
    let renderRequested = false;

    // DOM Elements
    const canvas = document.getElementById('mapCanvas');
    const ctx = canvas.getContext('2d');
    const sidebar = document.getElementById('sidebar');
    const searchInput = document.getElementById('searchInput');
    const typeFiltersContainer = document.getElementById('typeFilters');
    const coordIndicator = document.getElementById('coordIndicator');
    const viewTabs = [...document.querySelectorAll('[data-view-mode]')];

    // Type Color Palette
    const TYPE_COLORS = {
        grass: '#22c55e', fire: '#ef4444', water: '#3b82f6', electric: '#eab308',
        normal: '#94a3b8', ice: '#06b6d4', fighting: '#dc2626', poison: '#a855f7',
        ground: '#d97706', flying: '#38bdf8', psychic: '#ec4899', bug: '#84cc16',
        rock: '#b45309', ghost: '#6b21a8', dragon: '#7c3aed', steel: '#64748b',
        fairy: '#f472b6', dark: '#334155'
    };

    // Display-only projection: preserve semantic source coordinates while making
    // topic structure easier to read at a glance.
    const LAYOUT_CONTRAST = Object.freeze({
        clusterSeparation: 1.45,
        clusterCohesion: 0.70,
        viewportPadding: 58
    });
    let layoutCenter = { x: 500, y: 500 };
    let clusterLayout = new Map();

    // Universal Stop Words for Domain-Agnostic Concept Tagging
    const GENERAL_STOP_WORDS = new Set([
        'ポケモン', '自分', '相手', '場合', '存在', '確認', '記録', '時間', '瞬間',
        '以内', '以上', '以下', '全体', '部分', '周囲', '近く', '遠く', '世界', '一番',
        '発見', '場所', '仲間', '性格', '普段', '特徴', '様子', '状態', '理由', '原因',
        '方法', '変化', '効果', '攻撃', '安心', '大変', '自由', '危険', '注意', '関係',
        '種類', '情報', '調査', '研究', '現在', '当時', '以前', '最初', '最後', '中心',
        '能力', '行動', '生活', '誕生', '最高', '強力', '特殊', '普通', '可能', '必要',
        '姿', '体', '見る', '見える', '出す', 'なる', '持つ', '使う', '大きい', '小さい',
        '強い', '弱い', '高い', '低い', '深い', '浅い', '重い', '軽い', '子供', '進化',
        'キロ', 'メートル', '時速', '毎日', 'いつも', 'すべて', '前', '後', '上', '下',
        '中', '外', '間', '内', '的', '化', '性', '風', '平気', '不思議', '地域',
        'アピール', '生命力', 'パワー', '元気', '発散', '液体', 'こと', 'よう', 'いる'
    ]);

    // Initialize Application
    async function init() {
        updateViewTabs();
        resizeCanvas();
        window.addEventListener('resize', () => {
            resizeCanvas();
            requestRender();
        });

        setupEventListeners();
        renderTypeFilters();
        await loadMapData();
        resetView();
    }

    // Resize Canvas
    function resizeCanvas() {
        const rect = canvas.getBoundingClientRect();
        canvas.width = Math.floor(rect.width);
        canvas.height = Math.floor(rect.height);
    }

    // Helper: Mouse Pos relative to Canvas
    function getCanvasMousePos(e) {
        const rect = canvas.getBoundingClientRect();
        return {
            x: e.clientX - rect.left,
            y: e.clientY - rect.top
        };
    }

    // Schedule Frame Render
    function requestRender() {
        if (!renderRequested) {
            renderRequested = true;
            requestAnimationFrame(drawFrame);
        }
    }

    // Load Map & Cluster JSON (Static JSON with API fallback)
    async function loadMapData() {
        try {
            let resp = await fetch('./pokemon_map_data.json');
            if (!resp.ok) {
                resp = await fetch('/api/pokemon');
            }
            if (!resp.ok) throw new Error('Failed to load pokemon data');
            let data = await resp.json();
            
            // Check local storage for client-side modifications if on static hosting
            const localSaved = localStorage.getItem('pokedb_custom_map_data');
            if (localSaved) {
                try {
                    const parsedLocal = JSON.parse(localSaved);
                    if (parsedLocal && parsedLocal.pokemons && parsedLocal.clusters) {
                        data = parsedLocal;
                    }
                } catch (e) {}
            }

            if (data && data.clusters && data.pokemons) {
                mapClusters = data.clusters;
                pokemons = data.pokemons;
                mapMeta = data.meta || {};
            } else if (Array.isArray(data)) {
                pokemons = data;
                mapClusters = [];
                mapMeta = {};
            }

            // One-time compatibility migration for data generated before cluster_id existed.
            pokemons.forEach(p => {
                if (!Number.isInteger(p.cluster_id)) {
                    const legacyCluster = getClosestCluster(p.x, p.y);
                    p.cluster_id = legacyCluster ? legacyCluster.id : null;
                }
            });

            refreshLayoutProjection();

            preloadImages();
            showToast(`Loaded ${pokemons.length} elements with ${mapClusters.length} verified topic clusters.`);
            requestRender();
        } catch (err) {
            console.error('Error loading map data:', err);
            showToast('Error loading map data', 'error');
        }
    }

    // Preload sprite images
    function preloadImages() {
        pokemons.forEach(p => {
            if (p.sprite_url && !imageCache[p.sprite_url]) {
                const img = new Image();
                img.crossOrigin = 'anonymous';
                img.onload = () => requestRender();
                img.src = p.sprite_url;
                imageCache[p.sprite_url] = img;
            }
        });
    }

    // Type Filter Buttons
    function renderTypeFilters() {
        typeFiltersContainer.innerHTML = '';
        const types = Object.keys(TYPE_COLORS);
        
        const allBtn = document.createElement('div');
        allBtn.className = 'type-filter-chip active';
        allBtn.textContent = 'ALL';
        allBtn.style.backgroundColor = '#334155';
        allBtn.onclick = () => filterByType(null, allBtn);
        typeFiltersContainer.appendChild(allBtn);

        types.forEach(t => {
            const chip = document.createElement('div');
            chip.className = 'type-filter-chip';
            chip.textContent = t.toUpperCase();
            chip.style.backgroundColor = TYPE_COLORS[t];
            chip.onclick = () => filterByType(t, chip);
            typeFiltersContainer.appendChild(chip);
        });
    }

    function filterByType(type, chipElement) {
        document.querySelectorAll('.type-filter-chip').forEach(c => c.classList.remove('active'));
        chipElement.classList.add('active');
        activeTypeFilter = type;
        requestRender();
    }

    // Coordinate Conversion Helpers (World <-> Canvas Screen)
    function worldToScreen(wx, wy) {
        return {
            x: (wx * scale) + translateX,
            y: (wy * scale) + translateY
        };
    }

    function screenToWorld(sx, sy) {
        return {
            x: (sx - translateX) / scale,
            y: (sy - translateY) / scale
        };
    }

    function readViewModeFromUrl() {
        return new URLSearchParams(window.location.search).get('view') === 'after' ? 'after' : 'before';
    }

    function isEnhancedView() {
        return viewMode === 'after';
    }

    function updateViewTabs() {
        viewTabs.forEach(tab => {
            const active = tab.dataset.viewMode === viewMode;
            tab.classList.toggle('active', active);
            tab.setAttribute('aria-selected', String(active));
        });
        document.body.dataset.viewMode = viewMode;
    }

    function setViewMode(nextMode, updateHistory = true) {
        const normalizedMode = nextMode === 'after' ? 'after' : 'before';
        viewMode = normalizedMode;
        updateViewTabs();

        if (updateHistory) {
            const url = new URL(window.location.href);
            url.searchParams.set('view', normalizedMode);
            window.history.pushState({ viewMode: normalizedMode }, '', url);
        }

        resetView();
        requestRender();
    }

    function colorWithAlpha(color, alpha) {
        const match = /^#([0-9a-f]{6})$/i.exec(color || '');
        if (!match) return `rgba(56, 189, 248, ${alpha})`;
        const value = parseInt(match[1], 16);
        return `rgba(${(value >> 16) & 255}, ${(value >> 8) & 255}, ${value & 255}, ${alpha})`;
    }

    function refreshLayoutProjection() {
        const totalWeight = mapClusters.reduce((sum, cluster) => sum + Math.max(1, cluster.count || 1), 0);
        if (totalWeight) {
            layoutCenter = {
                x: mapClusters.reduce((sum, cluster) => sum + cluster.cx * Math.max(1, cluster.count || 1), 0) / totalWeight,
                y: mapClusters.reduce((sum, cluster) => sum + cluster.cy * Math.max(1, cluster.count || 1), 0) / totalWeight
            };
        }

        const projections = mapClusters.map(cluster => {
            const displayCenter = {
                x: layoutCenter.x + (cluster.cx - layoutCenter.x) * LAYOUT_CONTRAST.clusterSeparation,
                y: layoutCenter.y + (cluster.cy - layoutCenter.y) * LAYOUT_CONTRAST.clusterSeparation
            };
            const memberDistances = pokemons
                .filter(pokemon => pokemon.cluster_id === cluster.id)
                .map(pokemon => Math.hypot(pokemon.x - cluster.cx, pokemon.y - cluster.cy) * LAYOUT_CONTRAST.clusterCohesion)
                .sort((left, right) => left - right);
            const percentileIndex = Math.min(
                Math.max(0, memberDistances.length - 1),
                Math.floor(memberDistances.length * 0.88)
            );
            const fieldRadius = Math.max(72, Math.min(235, (memberDistances[percentileIndex] || 80) + 28));
            return {
                cluster,
                displayCenter,
                desiredCenter: { ...displayCenter },
                fieldRadius
            };
        });

        // Resolve overlapping macro fields while gently retaining the UMAP topology.
        for (let iteration = 0; iteration < 80; iteration++) {
            const movement = projections.map(projection => ({
                x: (projection.desiredCenter.x - projection.displayCenter.x) * 0.025,
                y: (projection.desiredCenter.y - projection.displayCenter.y) * 0.025
            }));
            for (let leftIndex = 0; leftIndex < projections.length; leftIndex++) {
                for (let rightIndex = leftIndex + 1; rightIndex < projections.length; rightIndex++) {
                    const left = projections[leftIndex];
                    const right = projections[rightIndex];
                    let dx = left.displayCenter.x - right.displayCenter.x;
                    let dy = left.displayCenter.y - right.displayCenter.y;
                    let distance = Math.hypot(dx, dy);
                    const minimumDistance = (left.fieldRadius + right.fieldRadius) * 0.74;
                    if (distance >= minimumDistance) continue;
                    if (distance < 0.001) {
                        const angle = (left.cluster.id * 137.508 + right.cluster.id * 47) * Math.PI / 180;
                        dx = Math.cos(angle);
                        dy = Math.sin(angle);
                        distance = 1;
                    }
                    const push = (minimumDistance - distance) * 0.16;
                    const pushX = dx / distance * push;
                    const pushY = dy / distance * push;
                    movement[leftIndex].x += pushX;
                    movement[leftIndex].y += pushY;
                    movement[rightIndex].x -= pushX;
                    movement[rightIndex].y -= pushY;
                }
            }
            projections.forEach((projection, index) => {
                projection.displayCenter.x += movement[index].x;
                projection.displayCenter.y += movement[index].y;
            });
        }

        clusterLayout = new Map(projections.map(projection => [projection.cluster.id, projection]));
    }

    function getPokemonDisplayPosition(pokemon) {
        if (!isEnhancedView()) return { x: pokemon.x, y: pokemon.y };
        const projection = clusterLayout.get(pokemon.cluster_id);
        if (!projection) return { x: pokemon.x, y: pokemon.y };
        return {
            x: projection.displayCenter.x + (pokemon.x - projection.cluster.cx) * LAYOUT_CONTRAST.clusterCohesion,
            y: projection.displayCenter.y + (pokemon.y - projection.cluster.cy) * LAYOUT_CONTRAST.clusterCohesion
        };
    }

    function pokemonToScreen(pokemon) {
        const display = getPokemonDisplayPosition(pokemon);
        return worldToScreen(display.x, display.y);
    }

    function displayToPokemonCoordinate(displayX, displayY, pokemon) {
        if (!isEnhancedView()) return { x: displayX, y: displayY };
        const projection = clusterLayout.get(pokemon.cluster_id);
        if (!projection) return { x: displayX, y: displayY };
        return {
            x: projection.cluster.cx + (displayX - projection.displayCenter.x) / LAYOUT_CONTRAST.clusterCohesion,
            y: projection.cluster.cy + (displayY - projection.displayCenter.y) / LAYOUT_CONTRAST.clusterCohesion
        };
    }

    function getDisplayBounds() {
        if (!pokemons.length) return { minX: 0, minY: 0, maxX: 1000, maxY: 1000 };
        const positions = pokemons.map(getPokemonDisplayPosition);
        return positions.reduce((bounds, position) => ({
            minX: Math.min(bounds.minX, position.x),
            minY: Math.min(bounds.minY, position.y),
            maxX: Math.max(bounds.maxX, position.x),
            maxY: Math.max(bounds.maxY, position.y)
        }), {
            minX: Infinity, minY: Infinity, maxX: -Infinity, maxY: -Infinity
        });
    }

    // Reset View
    function resetView() {
        const containerW = canvas.width;
        const containerH = canvas.height;
        if (!isEnhancedView()) {
            scale = Math.min(containerW / 1150, containerH / 1150);
            translateX = (containerW - 1000 * scale) / 2;
            translateY = (containerH - 1000 * scale) / 2;
            requestRender();
            return;
        }

        const bounds = getDisplayBounds();
        const spanX = Math.max(1, bounds.maxX - bounds.minX);
        const spanY = Math.max(1, bounds.maxY - bounds.minY);
        const availableW = Math.max(1, containerW - LAYOUT_CONTRAST.viewportPadding * 2);
        const availableH = Math.max(1, containerH - LAYOUT_CONTRAST.viewportPadding * 2);

        scale = Math.min(1.25, availableW / spanX, availableH / spanY);
        translateX = containerW / 2 - ((bounds.minX + bounds.maxX) / 2) * scale;
        translateY = containerH / 2 - ((bounds.minY + bounds.maxY) / 2) * scale;
        requestRender();
    }

    // Focus Camera on a Specific Node
    function focusOnPokemon(p) {
        const containerW = canvas.width;
        const containerH = canvas.height;

        const display = getPokemonDisplayPosition(p);
        scale = 1.6;
        translateX = (containerW / 2) - (display.x * scale);
        translateY = (containerH / 2) - (display.y * scale);
        selectedPokemon = p;
        openSidebar(p);
        requestRender();
    }

    // Helper: Find Closest Keyword Cluster
    function getClosestCluster(x, y) {
        if (!mapClusters || !mapClusters.length) return null;
        let closest = mapClusters[0];
        let minDist = Infinity;
        mapClusters.forEach(c => {
            const d = Math.hypot(c.cx - x, c.cy - y);
            if (d < minDist) {
                minDist = d;
                closest = c;
            }
        });
        return closest;
    }

    function getClusterForPokemon(pokemon) {
        if (pokemon && Number.isInteger(pokemon.cluster_id)) {
            const exact = mapClusters.find(cluster => cluster.id === pokemon.cluster_id);
            if (exact) return exact;
        }
        return getClosestCluster(pokemon.x, pokemon.y);
    }

    // Helper: Tokenize Japanese text into pure concrete concepts (Kanji/Katakana)
    function extractCandidateConcepts(text) {
        if (!text) return [];
        const kanji = text.match(/[\u4E00-\u9FFF]{2,6}/g) || [];
        const katakana = text.match(/[\u30A0-\u30FF]{2,8}/g) || [];
        const hiragana = (text.match(/[\u3040-\u309F]{2,4}/g) || []).filter(w => 
            ['しっぽ', 'つめ', 'キバ', 'つぼみ', 'はね', 'ひれ', 'どく', 'ほのお', 'いかり'].includes(w)
        );

        const particleRegex = /(の|を|が|に|は|で|と|へ|も|から|より|まで|して|する|された|される|ている|てある|になる|になると|である|たら|なら|ば|ね|よ|わ|ぞ|て|た|だ|ない|ます|ませ|まし|ず|ぬ)$/;

        const cleaned = [];
        [...kanji, ...katakana, ...hiragana].forEach(t => {
            const w = t.replace(particleRegex, '').replace(/^\d+|\d+$/g, '').trim();
            if (w.length >= 2 && !GENERAL_STOP_WORDS.has(w)) {
                cleaned.push(w);
            }
        });
        return Array.from(new Set(cleaned));
    }

    // Extract Pure Keywords for Selected Element
    function extractSimilarityAnalysis(target) {
        const targetText = target.flavor_text_ja || '';
        const targetConcepts = extractCandidateConcepts(targetText);
        const closestCluster = getClusterForPokemon(target);

        // The build pipeline has already coherence-validated these terms with Sudachi.
        // Prefer them to re-tokenizing Japanese text with a browser-side regex.
        let displayTopics = closestCluster && closestCluster.top_words
            ? closestCluster.top_words.slice(0, 3)
            : targetConcepts.slice(0, 3);
        if (displayTopics.length === 0) {
            displayTopics = ['特徴概念'];
        }

        const clusterKeywords = closestCluster ? closestCluster.keywords : '未分類';
        let reasonSummary = '';
        if (targetConcepts.length > 0) {
            const termsStr = targetConcepts.slice(0, 3).map(w => `「${w}」`).join('・');
            reasonSummary = `【領域キーワード: ${clusterKeywords}】に位置。テキスト中の主要な概念（${termsStr}）に基づいてこの領域に配置されています。`;
        } else {
            reasonSummary = `【領域キーワード: ${clusterKeywords}】に位置。全体の文章構造とトピック類似性に基づいて配置されています。`;
        }

        return {
            cluster: closestCluster,
            clusterKeywords,
            topics: displayTopics,
            reasonSummary
        };
    }

    function rectanglesOverlap(a, b, padding = 0) {
        return !(
            a.right + padding <= b.left ||
            a.left >= b.right + padding ||
            a.bottom + padding <= b.top ||
            a.top >= b.bottom + padding
        );
    }

    function getNodeSize() {
        return isEnhancedView()
            ? Math.max(12, Math.min(40, 21 * scale))
            : Math.max(14, Math.min(40, 24 * scale));
    }

    // Place every macro label in screen space, avoiding both sprites and earlier labels.
    function drawAreaLabels(baseSize) {
        if (!mapClusters || !mapClusters.length) return;

        const enhanced = isEnhancedView();
        ctx.save();
        const scaleFactor = Math.min(1.2, Math.max(0.75, scale));
        const nodePadding = 3;
        const nodeRects = pokemons.map(p => {
            const pos = pokemonToScreen(p);
            return {
                left: pos.x - baseSize / 2 - nodePadding,
                right: pos.x + baseSize / 2 + nodePadding,
                top: pos.y - baseSize / 2 - nodePadding,
                bottom: pos.y + baseSize / 2 + nodePadding
            };
        }).filter(rect => rect.right >= 0 && rect.left <= canvas.width && rect.bottom >= 0 && rect.top <= canvas.height);
        const placements = [];

        const areas = [...mapClusters].sort((a, b) => b.count - a.count || a.id - b.id);
        areas.forEach(area => {
            const projection = clusterLayout.get(area.id);
            const displayCenter = enhanced && projection
                ? projection.displayCenter
                : { x: area.cx, y: area.cy };
            const anchor = worldToScreen(displayCenter.x, displayCenter.y);
            if (enhanced && (
                anchor.x < -40 || anchor.x > canvas.width + 40 ||
                anchor.y < -40 || anchor.y > canvas.height + 40
            )) return;
            const text = area.keywords;
            const fontSize = Math.round(11 * scaleFactor);
            ctx.font = `${enhanced ? 700 : 600} ${fontSize}px "Noto Sans JP", sans-serif`;
            const textMetrics = ctx.measureText(text);
            const boxPaddingX = 14 * scaleFactor;
            const boxPaddingY = 6 * scaleFactor;
            const boxW = textMetrics.width + boxPaddingX * 2;
            const boxH = fontSize + boxPaddingY * 2;
            const cornerR = 6;

            const makeRect = (cx, cy) => ({
                left: cx - boxW / 2,
                right: cx + boxW / 2,
                top: cy - boxH / 2,
                bottom: cy + boxH / 2,
                cx,
                cy
            });
            const fits = rect => (
                rect.left >= 8 && rect.right <= canvas.width - 8 &&
                rect.top >= 8 && rect.bottom <= canvas.height - 8 &&
                !placements.some(item => rectanglesOverlap(rect, item.rect, 6)) &&
                !nodeRects.some(nodeRect => rectanglesOverlap(rect, nodeRect, 1))
            );

            const fieldRadius = (projection ? projection.fieldRadius : 100) * scale;
            const labelTarget = {
                x: anchor.x,
                y: enhanced
                    ? anchor.y - Math.min(128, Math.max(44, fieldRadius * 0.72))
                    : anchor.y
            };
            const center = {
                x: Math.max(8 + boxW / 2, Math.min(canvas.width - 8 - boxW / 2, labelTarget.x)),
                y: Math.max(8 + boxH / 2, Math.min(canvas.height - 8 - boxH / 2, labelTarget.y))
            };
            const candidateCenters = [{ x: center.x, y: center.y }];
            for (let ring = 1; ring <= 10; ring++) {
                const radius = ring * 24;
                const steps = Math.max(12, ring * 8);
                for (let step = 0; step < steps; step++) {
                    const angle = -Math.PI / 2 + (Math.PI * 2 * step / steps);
                    candidateCenters.push({
                        x: center.x + Math.cos(angle) * radius,
                        y: center.y + Math.sin(angle) * radius
                    });
                }
            }

            let rect = null;
            for (const candidate of candidateCenters) {
                const trial = makeRect(candidate.x, candidate.y);
                if (fits(trial)) {
                    rect = trial;
                    break;
                }
            }

            // Guaranteed callout fallback: scan edge rails, then the full viewport grid.
            if (!rect) {
                const railXs = [canvas.width - boxW / 2 - 12, boxW / 2 + 12];
                for (const railX of railXs) {
                    for (let y = 12 + boxH / 2; y <= canvas.height - 12 - boxH / 2; y += boxH + 8) {
                        const trial = makeRect(railX, y);
                        if (fits(trial)) {
                            rect = trial;
                            break;
                        }
                    }
                    if (rect) break;
                }
            }
            if (!rect) {
                outer: for (let y = 12 + boxH / 2; y <= canvas.height - 12 - boxH / 2; y += 12) {
                    for (let x = 12 + boxW / 2; x <= canvas.width - 12 - boxW / 2; x += 12) {
                        const trial = makeRect(x, y);
                        if (fits(trial)) {
                            rect = trial;
                            break outer;
                        }
                    }
                }
            }
            if (!rect) return;

            const displaced = Math.hypot(rect.cx - anchor.x, rect.cy - anchor.y) > 10;
            if (displaced) {
                ctx.beginPath();
                ctx.moveTo(
                    Math.max(0, Math.min(canvas.width, anchor.x)),
                    Math.max(0, Math.min(canvas.height, anchor.y))
                );
                ctx.lineTo(rect.cx, rect.cy);
                ctx.strokeStyle = area.color || '#38bdf8';
                ctx.globalAlpha = enhanced ? 0.55 : 0.38;
                ctx.lineWidth = enhanced ? 1.25 : 1;
                ctx.stroke();
                ctx.globalAlpha = 1;
            }

            if (enhanced) {
                ctx.shadowColor = colorWithAlpha(area.color || '#38bdf8', 0.45);
                ctx.shadowBlur = 10;
            }
            ctx.beginPath();
            ctx.roundRect(rect.left, rect.top, boxW, boxH, cornerR);
            ctx.fillStyle = enhanced ? 'rgba(8, 15, 29, 0.96)' : 'rgba(15, 23, 42, 0.94)';
            ctx.fill();
            ctx.shadowBlur = 0;
            ctx.lineWidth = enhanced ? 1.4 : 1;
            ctx.strokeStyle = area.color || '#38bdf8';
            ctx.globalAlpha = enhanced ? 0.92 : 0.72;
            ctx.stroke();
            ctx.globalAlpha = 1.0;
            ctx.textAlign = 'center';
            ctx.textBaseline = 'middle';
            ctx.fillStyle = '#f8fafc';
            ctx.fillText(text, rect.cx, rect.cy + 0.5);

            placements.push({ area, rect, anchor, displaced });
        });

        window.__mapDebug = window.__mapDebug || {};
        window.__mapDebug.labelPlacements = placements.map(item => ({
            clusterId: item.area.id,
            keywords: item.area.keywords,
            rect: item.rect,
            displaced: item.displaced
        }));
        canvas.dataset.mapDebug = JSON.stringify({
            scale,
            nodeSize: baseSize,
            clusterCount: mapClusters.length,
            modelVersion: mapMeta.model_version || null,
            labelPlacements: window.__mapDebug.labelPlacements,
            nodeRects
        });
        ctx.restore();
    }

    function drawClusterFields() {
        if (!isEnhancedView() || !mapClusters.length) return;

        const fieldDebug = [];
        ctx.save();
        [...mapClusters]
            .sort((left, right) => right.count - left.count || left.id - right.id)
            .forEach(area => {
                const projection = clusterLayout.get(area.id);
                if (!projection) return;
                const center = worldToScreen(projection.displayCenter.x, projection.displayCenter.y);
                const radius = projection.fieldRadius * scale;
                if (
                    center.x + radius < 0 || center.x - radius > canvas.width ||
                    center.y + radius < 0 || center.y - radius > canvas.height
                ) return;

                const color = area.color || '#38bdf8';
                const gradient = ctx.createRadialGradient(
                    center.x, center.y, Math.max(3, radius * 0.08),
                    center.x, center.y, Math.max(4, radius)
                );
                gradient.addColorStop(0, colorWithAlpha(color, 0.17));
                gradient.addColorStop(0.58, colorWithAlpha(color, 0.07));
                gradient.addColorStop(1, colorWithAlpha(color, 0));
                ctx.fillStyle = gradient;
                ctx.beginPath();
                ctx.arc(center.x, center.y, radius, 0, Math.PI * 2);
                ctx.fill();

                ctx.setLineDash([5, 8]);
                ctx.lineWidth = 1;
                ctx.strokeStyle = colorWithAlpha(color, 0.28);
                ctx.stroke();
                ctx.setLineDash([]);
                fieldDebug.push({ clusterId: area.id, center, radius });
            });
        ctx.restore();

        window.__mapDebug = window.__mapDebug || {};
        window.__mapDebug.clusterFields = fieldDebug;
    }

    function getNearestSemanticNeighbors(target, limit = 4) {
        return pokemons
            .filter(candidate => candidate.id !== target.id)
            .map(candidate => ({
                pokemon: candidate,
                distance: Math.hypot(candidate.x - target.x, candidate.y - target.y)
            }))
            .sort((left, right) => left.distance - right.distance || left.pokemon.id - right.pokemon.id)
            .slice(0, limit);
    }

    function drawSimilarityLinks() {
        if (!isEnhancedView() || !selectedPokemon) return;

        const start = pokemonToScreen(selectedPokemon);
        const neighbors = getNearestSemanticNeighbors(selectedPokemon);
        const cluster = getClusterForPokemon(selectedPokemon);
        const color = cluster && cluster.color ? cluster.color : '#38bdf8';

        ctx.save();
        neighbors.forEach((item, index) => {
            const end = pokemonToScreen(item.pokemon);
            const gradient = ctx.createLinearGradient(start.x, start.y, end.x, end.y);
            gradient.addColorStop(0, colorWithAlpha(color, 0.9));
            gradient.addColorStop(1, colorWithAlpha(color, 0.18));
            ctx.beginPath();
            ctx.moveTo(start.x, start.y);
            ctx.lineTo(end.x, end.y);
            ctx.strokeStyle = gradient;
            ctx.lineWidth = Math.max(1, 2.4 - index * 0.3);
            ctx.shadowColor = colorWithAlpha(color, 0.65);
            ctx.shadowBlur = 7;
            ctx.stroke();

            ctx.shadowBlur = 0;
            ctx.beginPath();
            ctx.arc(end.x, end.y, 3.2, 0, Math.PI * 2);
            ctx.fillStyle = colorWithAlpha(color, 0.8 - index * 0.1);
            ctx.fill();
        });
        ctx.restore();

        window.__mapDebug = window.__mapDebug || {};
        window.__mapDebug.similarityNeighborIds = neighbors.map(item => item.pokemon.id);
    }

    // Core Drawing Frame Routine
    function drawFrame() {
        renderRequested = false;

        ctx.clearRect(0, 0, canvas.width, canvas.height);
        ctx.imageSmoothingEnabled = false;

        // 1. Background Grid
        drawGrid();

        const enhanced = isEnhancedView();
        if (enhanced) {
            // 2. Soft topic fields expose the macro structure without hiding nodes.
            drawClusterFields();

            // 3. Draw the selected element's nearest semantic relationships.
            drawSimilarityLinks();
        } else {
            window.__mapDebug = window.__mapDebug || {};
            window.__mapDebug.clusterFields = [];
            window.__mapDebug.similarityNeighborIds = [];
        }

        // 4. Draw nodes at a compact overview size. Labels are placed afterwards.
        const baseSize = getNodeSize();

        pokemons.forEach(p => {
            const pos = pokemonToScreen(p);

            // Filter Opacity Check
            let opacity = 1.0;
            if (activeTypeFilter) {
                if (p.type1 !== activeTypeFilter && p.type2 !== activeTypeFilter) {
                    opacity = 0.12;
                }
            }

            if (searchQuery) {
                const match = p.name_ja.includes(searchQuery) ||
                              (p.name_kana && p.name_kana.includes(searchQuery)) ||
                              p.name_en.toLowerCase().includes(searchQuery.toLowerCase()) ||
                              String(p.id) === searchQuery;
                if (!match) opacity = 0.08;
            }

            ctx.globalAlpha = opacity;

            const isSelected = selectedPokemon && selectedPokemon.id === p.id;
            const isHovered = hoveredPokemon && hoveredPokemon.id === p.id;
            const cluster = getClusterForPokemon(p);
            const clusterColor = cluster && cluster.color ? cluster.color : '#64748b';

            if (enhanced) {
                // A dark plate and cluster-colored edge keep every sprite legible.
                ctx.beginPath();
                ctx.arc(pos.x, pos.y, (baseSize / 2) + 1.25, 0, Math.PI * 2);
                ctx.fillStyle = 'rgba(3, 7, 18, 0.88)';
                ctx.fill();
                ctx.lineWidth = isSelected ? 2.5 : (isHovered ? 1.8 : 0.85);
                ctx.strokeStyle = isSelected ? '#f8fafc' : clusterColor;
                ctx.shadowColor = colorWithAlpha(clusterColor, isSelected ? 0.85 : 0.42);
                ctx.shadowBlur = isSelected ? 10 : 3;
                ctx.stroke();
                ctx.shadowBlur = 0;
            } else if (isSelected || isHovered) {
                // Preserve the original plot's selection treatment.
                ctx.beginPath();
                ctx.arc(pos.x, pos.y, (baseSize / 2) + 3, 0, Math.PI * 2);
                ctx.lineWidth = isSelected ? 3 : 2;
                ctx.strokeStyle = isSelected ? '#3b82f6' : '#06b6d4';
                ctx.stroke();
            }

            // Draw Sprite Image or Fallback Dot
            const img = imageCache[p.sprite_url];
            if (img && img.complete && img.naturalWidth !== 0) {
                ctx.drawImage(img, Math.round(pos.x - baseSize / 2), Math.round(pos.y - baseSize / 2), baseSize, baseSize);
            } else {
                ctx.beginPath();
                ctx.arc(pos.x, pos.y, baseSize / 4, 0, Math.PI * 2);
                ctx.fillStyle = TYPE_COLORS[p.type1] || '#94a3b8';
                ctx.fill();
            }

            // Custom added indicator
            if (p.is_custom) {
                ctx.beginPath();
                ctx.arc(pos.x + baseSize / 3, pos.y - baseSize / 3, 5, 0, Math.PI * 2);
                ctx.fillStyle = '#ef4444';
                ctx.fill();
            }

            // Draw Text Label ONLY when selected or hovered
            if (isSelected || isHovered) {
                if (enhanced) {
                    ctx.beginPath();
                    ctx.arc(pos.x, pos.y, (baseSize / 2) + 4, 0, Math.PI * 2);
                    ctx.lineWidth = isSelected ? 2.4 : 1.6;
                    ctx.strokeStyle = isSelected ? clusterColor : '#67e8f9';
                    ctx.stroke();
                }

                ctx.font = '700 12px "Noto Sans JP", sans-serif';
                ctx.textAlign = 'center';
                ctx.textBaseline = 'alphabetic';
                ctx.fillStyle = isSelected ? '#60a5fa' : '#38bdf8';
                ctx.shadowColor = '#000';
                ctx.shadowBlur = 4;
                ctx.fillText(p.name_ja, pos.x, pos.y + baseSize / 2 + 13);
                ctx.shadowBlur = 0;
            }

            ctx.globalAlpha = 1.0;
        });

        // 5. Coherence-validated topic labels stay above nodes and never cover them.
        drawAreaLabels(baseSize);

        window.__mapDebug = window.__mapDebug || {};
        window.__mapDebug.scale = scale;
        window.__mapDebug.nodeSize = baseSize;
        window.__mapDebug.clusterCount = mapClusters.length;
        window.__mapDebug.modelVersion = mapMeta.model_version || null;
        window.__mapDebug.viewMode = viewMode;
        window.__mapDebug.layoutContrast = {
            clusterSeparation: LAYOUT_CONTRAST.clusterSeparation,
            clusterCohesion: LAYOUT_CONTRAST.clusterCohesion,
            layoutCenter,
            displayBounds: getDisplayBounds(),
            clusterCenters: [...clusterLayout.values()].map(projection => ({
                clusterId: projection.cluster.id,
                source: { x: projection.cluster.cx, y: projection.cluster.cy },
                display: projection.displayCenter,
                fieldRadius: projection.fieldRadius
            }))
        };

        // Update HUD indicator
        coordIndicator.textContent = enhanced
            ? `Zoom: ${Math.round(scale * 100)}% | ${pokemons.length}匹 | 近いほど類似`
            : `Zoom: ${Math.round(scale * 100)}% | Pkms: ${pokemons.length}`;
    }

    // Draw Grid Lines
    function drawGrid() {
        const step = 100 * scale;
        const startX = translateX % step;
        const startY = translateY % step;

        ctx.strokeStyle = 'rgba(255, 255, 255, 0.04)';
        ctx.lineWidth = 1;

        for (let x = startX; x < canvas.width; x += step) {
            ctx.beginPath();
            ctx.moveTo(x, 0);
            ctx.lineTo(x, canvas.height);
            ctx.stroke();
        }

        for (let y = startY; y < canvas.height; y += step) {
            ctx.beginPath();
            ctx.moveTo(0, y);
            ctx.lineTo(canvas.width, y);
            ctx.stroke();
        }
    }

    // Hit Test
    function getPokemonAt(sx, sy) {
        const baseSize = getNodeSize();
        const threshold = baseSize / 2 + 4;

        for (let i = pokemons.length - 1; i >= 0; i--) {
            const p = pokemons[i];
            const pos = pokemonToScreen(p);
            const dist = Math.hypot(pos.x - sx, pos.y - sy);
            if (dist <= threshold) {
                return p;
            }
        }
        return null;
    }

    // Setup Interaction Listeners
    function setupEventListeners() {
        viewTabs.forEach(tab => {
            tab.addEventListener('click', event => {
                if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
                event.preventDefault();
                setViewMode(tab.dataset.viewMode, true);
            });
        });
        window.addEventListener('popstate', () => {
            setViewMode(readViewModeFromUrl(), false);
        });

        // Wheel Zoom
        canvas.addEventListener('wheel', (e) => {
            e.preventDefault();
            const mouse = getCanvasMousePos(e);
            const zoomFactor = e.deltaY < 0 ? 1.15 : 0.87;
            const newScale = Math.max(0.1, Math.min(8.0, scale * zoomFactor));

            translateX = mouse.x - (mouse.x - translateX) * (newScale / scale);
            translateY = mouse.y - (mouse.y - translateY) * (newScale / scale);
            scale = newScale;

            requestRender();
        }, { passive: false });

        // Mouse Down
        canvas.addEventListener('mousedown', (e) => {
            if (e.button !== 0) return;
            const mousePos = getCanvasMousePos(e);

            dragStartScreenX = mousePos.x;
            dragStartScreenY = mousePos.y;
            hasDraggedNode = false;

            const hitPokemon = getPokemonAt(mousePos.x, mousePos.y);
            if (hitPokemon) {
                draggedPokemon = hitPokemon;
                isDraggingNode = true;
                
                const worldPos = screenToWorld(mousePos.x, mousePos.y);
                const displayPos = getPokemonDisplayPosition(hitPokemon);
                dragOffsetX = displayPos.x - worldPos.x;
                dragOffsetY = displayPos.y - worldPos.y;
                
                canvas.style.cursor = 'grabbing';
            } else {
                isPanning = true;
                startPanX = e.clientX - translateX;
                startPanY = e.clientY - translateY;
                canvas.classList.add('grabbing');
            }
            requestRender();
        });

        // Mouse Move
        canvas.addEventListener('mousemove', (e) => {
            const mousePos = getCanvasMousePos(e);

            if (isDraggingNode && draggedPokemon) {
                const moveDist = Math.hypot(mousePos.x - dragStartScreenX, mousePos.y - dragStartScreenY);
                if (moveDist > 3) {
                    hasDraggedNode = true;
                    const worldPos = screenToWorld(mousePos.x, mousePos.y);
                    const semanticPos = displayToPokemonCoordinate(
                        worldPos.x + dragOffsetX,
                        worldPos.y + dragOffsetY,
                        draggedPokemon
                    );
                    draggedPokemon.x = Math.max(0, Math.min(1000, Math.round(semanticPos.x * 100) / 100));
                    draggedPokemon.y = Math.max(0, Math.min(1000, Math.round(semanticPos.y * 100) / 100));

                    if (selectedPokemon && selectedPokemon.id === draggedPokemon.id) {
                        document.getElementById('coordXInput').value = draggedPokemon.x;
                        document.getElementById('coordYInput').value = draggedPokemon.y;
                    }
                    requestRender();
                }
            } else if (isPanning) {
                translateX = e.clientX - startPanX;
                translateY = e.clientY - startPanY;
                requestRender();
            } else {
                const hit = getPokemonAt(mousePos.x, mousePos.y);
                if (hit !== hoveredPokemon) {
                    hoveredPokemon = hit;
                    canvas.style.cursor = hit ? 'pointer' : 'grab';
                    requestRender();
                }
            }
        });

        // Mouse Up
        window.addEventListener('mouseup', () => {
            if (isDraggingNode && draggedPokemon) {
                if (!hasDraggedNode) {
                    selectedPokemon = draggedPokemon;
                    openSidebar(draggedPokemon);
                } else {
                    showToast(`No.${draggedPokemon.id} ${draggedPokemon.name_ja} の位置を変更しました`);
                }
                requestRender();
            }
            
            isPanning = false;
            isDraggingNode = false;
            draggedPokemon = null;
            hasDraggedNode = false;
            canvas.classList.remove('grabbing');
        });

        // Search Input Listener
        searchInput.addEventListener('input', (e) => {
            searchQuery = e.target.value.trim();
            if (searchQuery) {
                const found = pokemons.find(p => p.name_ja.includes(searchQuery) || String(p.id) === searchQuery);
                if (found) {
                    focusOnPokemon(found);
                }
            }
            requestRender();
        });

        // Navigation HUD Buttons
        document.getElementById('zoomInBtn').onclick = () => {
            const centerX = canvas.width / 2;
            const centerY = canvas.height / 2;
            const newScale = Math.min(8.0, scale * 1.25);
            translateX = centerX - (centerX - translateX) * (newScale / scale);
            translateY = centerY - (centerY - translateY) * (newScale / scale);
            scale = newScale;
            requestRender();
        };

        document.getElementById('zoomOutBtn').onclick = () => {
            const centerX = canvas.width / 2;
            const centerY = canvas.height / 2;
            const newScale = Math.max(0.1, scale * 0.8);
            translateX = centerX - (centerX - translateX) * (newScale / scale);
            translateY = centerY - (centerY - translateY) * (newScale / scale);
            scale = newScale;
            requestRender();
        };

        document.getElementById('resetViewBtn').onclick = resetView;

        // Sidebar & Modal Buttons
        document.getElementById('closeSidebarBtn').onclick = closeSidebar;
        document.getElementById('applyCoordBtn').onclick = applyManualCoords;

        document.getElementById('addPokemonBtn').onclick = openAddModal;
        document.getElementById('closeModalBtn').onclick = closeAddModal;
        document.getElementById('cancelAddBtn').onclick = closeAddModal;
        document.getElementById('calcAiCoordBtn').onclick = calculateAiCoordinates;
        document.getElementById('confirmAddBtn').onclick = addNewPokemon;

        document.getElementById('saveBtn').onclick = saveMapData;
        document.getElementById('resetBtn').onclick = resetMapData;
    }

    // Sidebar Detail Panel (Pure Keywords & Context)
    function openSidebar(p) {
        document.getElementById('sidebarId').textContent = `No.${p.id}`;
        document.getElementById('sidebarName').textContent = p.name_ja;
        document.getElementById('sidebarKana').textContent = p.name_kana || p.name_en;
        document.getElementById('sidebarGenus').textContent = p.genus_ja || '分類未登録';
        document.getElementById('sidebarFlavorText').textContent = p.flavor_text_ja || '図鑑説明文はありません。';
        document.getElementById('sidebarArtwork').src = p.artwork_url || p.sprite_url;

        // Types
        const typesContainer = document.getElementById('sidebarTypes');
        typesContainer.innerHTML = `
            <span class="type-badge" style="background:${TYPE_COLORS[p.type1] || '#334155'}">${p.type1}</span>
            ${p.type2 ? `<span class="type-badge" style="background:${TYPE_COLORS[p.type2] || '#334155'}">${p.type2}</span>` : ''}
        `;

        // Render Pure Keyword & Context Analysis
        const analysis = extractSimilarityAnalysis(p);

        // Keywords Tags (Extracted from this text)
        const keywordsContainer = document.getElementById('sidebarKeywords');
        keywordsContainer.innerHTML = analysis.topics.map(t => `
            <span class="keyword-tag">🏷️ ${t}</span>
        `).join('');

        // Reason summary
        document.getElementById('sidebarAiReason').textContent = `💡 ${analysis.reasonSummary}`;

        // Manual Coords
        document.getElementById('coordXInput').value = p.x;
        document.getElementById('coordYInput').value = p.y;

        // Stats
        document.getElementById('sidebarBst').textContent = p.base_stats_total || 'N/A';
        const statsContainer = document.getElementById('sidebarStats');
        statsContainer.innerHTML = `
            <div class="stat-item"><div class="stat-name">HP</div><div class="stat-val">${p.hp || '-'}</div></div>
            <div class="stat-item"><div class="stat-name">攻撃</div><div class="stat-val">${p.attack || '-'}</div></div>
            <div class="stat-item"><div class="stat-name">防御</div><div class="stat-val">${p.defense || '-'}</div></div>
            <div class="stat-item"><div class="stat-name">特攻</div><div class="stat-val">${p.special_attack || '-'}</div></div>
            <div class="stat-item"><div class="stat-name">特防</div><div class="stat-val">${p.special_defense || '-'}</div></div>
            <div class="stat-item"><div class="stat-name">素早さ</div><div class="stat-val">${p.speed || '-'}</div></div>
        `;

        sidebar.classList.remove('hidden');
        requestRender();
    }

    function closeSidebar() {
        sidebar.classList.add('hidden');
        selectedPokemon = null;
        requestRender();
    }

    function applyManualCoords() {
        if (!selectedPokemon) return;
        const newX = parseFloat(document.getElementById('coordXInput').value);
        const newY = parseFloat(document.getElementById('coordYInput').value);

        if (!isNaN(newX) && !isNaN(newY)) {
            selectedPokemon.x = newX;
            selectedPokemon.y = newY;
            showToast(`No.${selectedPokemon.id} ${selectedPokemon.name_ja} の座標を更新しました`);
            requestRender();
        }
    }

    function findNearestFreeWorldPosition(anchorX, anchorY, minimumDistance = 28) {
        const isFree = (x, y) => pokemons.every(p => Math.hypot(p.x - x, p.y - y) >= minimumDistance);
        const preferredX = Math.max(40, Math.min(960, anchorX));
        const preferredY = Math.max(40, Math.min(960, anchorY));
        if (isFree(preferredX, preferredY)) return { x: preferredX, y: preferredY };
        for (let ring = 1; ring < 80; ring++) {
            const radius = ring * minimumDistance * 0.55;
            const steps = Math.max(16, ring * 12);
            for (let step = 0; step < steps; step++) {
                const angle = Math.PI * 2 * step / steps;
                const x = preferredX + Math.cos(angle) * radius;
                const y = preferredY + Math.sin(angle) * radius;
                if (x < 40 || x > 960 || y < 40 || y > 960) continue;
                if (isFree(x, y)) return { x, y };
            }
        }
        return { x: preferredX, y: preferredY };
    }

    // Modal: Add New Pokemon
    function openAddModal() {
        document.getElementById('addModal').classList.remove('hidden');
        document.getElementById('addAiReasonBox').classList.add('hidden');
        pendingAiClusterId = null;
        pendingAiClusterKeywords = '';
    }

    function closeAddModal() {
        document.getElementById('addModal').classList.add('hidden');
        document.getElementById('addAiReasonBox').classList.add('hidden');
    }

    async function calculateAiCoordinates() {
        const genusJa = document.getElementById('addGenusJa').value.trim();
        const flavorJa = document.getElementById('addFlavorTextJa').value.trim();
        const type1 = document.getElementById('addType1').value;
        const type2 = document.getElementById('addType2').value;

        if (!flavorJa) {
            showToast('図鑑説明文 / 自己紹介文を入力してください', 'error');
            return;
        }

        const calcBtn = document.getElementById('calcAiCoordBtn');
        calcBtn.textContent = '⏳ AI解析中...';
        calcBtn.disabled = true;

        try {
            let res = null;
            try {
                const resp = await fetch('/api/pokemon/calculate_coord', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ flavor_text_ja: flavorJa, genus_ja: genusJa, type1: type1, type2: type2 })
                });
                if (resp.ok) {
                    res = await resp.json();
                }
            } catch (networkErr) {
                // Static hosting fallback
            }

            // Fallback for static hosting if API is not available
            if (!res || res.status !== 'ok') {
                const candidateConcepts = extractCandidateConcepts(flavorJa);
                let bestCluster = mapClusters[0];
                let maxScore = -1;

                mapClusters.forEach(c => {
                    let score = 0;
                    const topWords = c.top_words || [];
                    const kw = c.keywords || '';
                    candidateConcepts.forEach(term => {
                        if (topWords.includes(term) || kw.includes(term)) score += 3;
                    });
                    if (score > maxScore) {
                        maxScore = score;
                        bestCluster = c;
                    }
                });

                if (bestCluster) {
                    const fallbackPos = findNearestFreeWorldPosition(bestCluster.cx || 500, bestCluster.cy || 500);
                    res = {
                        status: 'ok',
                        x: fallbackPos.x,
                        y: fallbackPos.y,
                        cluster_id: bestCluster.id,
                        cluster_keywords: bestCluster.keywords
                    };
                }
            }

            if (res && res.status === 'ok') {
                const freePosition = findNearestFreeWorldPosition(res.x, res.y);
                const resolvedX = Math.round(freePosition.x * 100) / 100;
                const resolvedY = Math.round(freePosition.y * 100) / 100;
                document.getElementById('addX').value = resolvedX;
                document.getElementById('addY').value = resolvedY;
                pendingAiClusterId = Number.isInteger(res.cluster_id) ? res.cluster_id : null;
                pendingAiClusterKeywords = res.cluster_keywords || '';

                const predicted = {
                    id: -999,
                    x: resolvedX,
                    y: resolvedY,
                    flavor_text_ja: flavorJa,
                    cluster_id: pendingAiClusterId
                };
                const analysis = extractSimilarityAnalysis(predicted);

                // Show AI Reason Preview in Modal
                const reasonBox = document.getElementById('addAiReasonBox');
                const reasonContent = document.getElementById('addAiReasonContent');
                const topicTags = analysis.topics.map(t => `🏷️ ${t}`).join('・');

                reasonContent.innerHTML = `
                    <div><strong>📍 算出座標:</strong> (X: ${resolvedX}, Y: ${resolvedY})</div>
                    <div style="margin-top:4px;"><strong>🗺️ 領域キーワード:</strong> ${pendingAiClusterKeywords || analysis.clusterKeywords}</div>
                    <div style="margin-top:4px;"><strong>🏷️ 抽出キーワード:</strong> ${topicTags}</div>
                    <div style="margin-top:4px; color:#93c5fd;">💡 ${analysis.reasonSummary}</div>
                `;
                reasonBox.classList.remove('hidden');

                showToast(`AIが最適座標 (X:${resolvedX}, Y:${resolvedY}) を計算しました！`);
            } else {
                throw new Error(res ? res.message : 'Calculation failed');
            }
        } catch (err) {
            console.error('AI Coord Calculation Failed:', err);
            showToast('座標計算に失敗しました', 'error');
        } finally {
            calcBtn.textContent = '🤖 AIで最適座標を自動計算';
            calcBtn.disabled = false;
        }
    }

    function addNewPokemon() {
        const nameJa = document.getElementById('addNameJa').value.trim();
        const nameEn = document.getElementById('addNameEn').value.trim() || 'Custom Element';
        const genusJa = document.getElementById('addGenusJa').value.trim() || 'カスタム分類';
        const flavorJa = document.getElementById('addFlavorTextJa').value.trim();
        const type1 = document.getElementById('addType1').value;
        const type2 = document.getElementById('addType2').value || null;
        const spriteUrl = document.getElementById('addSpriteUrl').value.trim() || 'https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/25.png';
        const x = parseFloat(document.getElementById('addX').value) || 500.0;
        const y = parseFloat(document.getElementById('addY').value) || 500.0;

        if (!nameJa || !flavorJa) {
            showToast('必須項目（名前、説明文）を入力してください', 'error');
            return;
        }

        const nextId = Math.max(...pokemons.map(p => p.id), 500) + 1;

        const newPokemon = {
            id: nextId,
            name_ja: nameJa,
            name_kana: nameJa,
            name_en: nameEn,
            genus_ja: genusJa,
            flavor_text_ja: flavorJa,
            type1: type1,
            type2: type2,
            sprite_url: spriteUrl,
            artwork_url: spriteUrl,
            base_stats_total: 450,
            hp: 70, attack: 80, defense: 70, special_attack: 80, special_defense: 70, speed: 80,
            x: x,
            y: y,
            cluster_id: pendingAiClusterId,
            is_custom: true
        };

        if (!Number.isInteger(newPokemon.cluster_id)) {
            const fallbackCluster = getClosestCluster(newPokemon.x, newPokemon.y);
            newPokemon.cluster_id = fallbackCluster ? fallbackCluster.id : null;
        }

        pokemons.push(newPokemon);
        preloadImages();
        closeAddModal();
        focusOnPokemon(newPokemon);
        showToast(`「${newPokemon.name_ja}」をマップに追加しました！`);
    }

    // Save Map Data to Backend or LocalStorage
    async function saveMapData() {
        const saveBtn = document.getElementById('saveBtn');
        saveBtn.textContent = '⏳ 保存中...';
        saveBtn.disabled = true;

        try {
            const payload = {
                meta: mapMeta,
                clusters: mapClusters,
                pokemons: pokemons
            };
            let savedOnServer = false;
            try {
                const resp = await fetch('/api/pokemon/save', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                if (resp.ok) {
                    const res = await resp.json();
                    if (res.status === 'ok') savedOnServer = true;
                }
            } catch (e) {
                // Static hosting environment
            }

            if (savedOnServer) {
                showToast('マップの座標と変更データを保存しました');
            } else {
                localStorage.setItem('pokedb_custom_map_data', JSON.stringify(payload));
                showToast('ブラウザ（ローカル保存）に変更を保存しました');
            }
        } catch (err) {
            console.error('Save failed:', err);
            showToast('データの保存に失敗しました', 'error');
        } finally {
            saveBtn.textContent = '💾 変更を保存';
            saveBtn.disabled = false;
        }
    }

    // Reset Map Data to Initial state
    async function resetMapData() {
        if (!confirm('マップデータと座標を初期状態（デフォルトの自動計算位置）にリセットしますか？')) return;

        try {
            try {
                await fetch('/api/pokemon/reset', { method: 'POST' });
            } catch (e) {}

            localStorage.removeItem('pokedb_custom_map_data');
            await loadMapData();
            resetView();
            showToast('マップデータを初期状態にリセットしました');
        } catch (err) {
            console.error('Reset failed:', err);
            showToast('リセット処理に失敗しました', 'error');
        }
    }

    // Notification Toast Helper
    function showToast(msg, type = 'info') {
        const toast = document.getElementById('toast');
        toast.textContent = msg;
        toast.style.backgroundColor = type === 'error' ? '#ef4444' : '#10b981';
        toast.classList.remove('hidden');
        setTimeout(() => toast.classList.add('hidden'), 3500);
    }

    // Start App on DOM Ready
    window.addEventListener('DOMContentLoaded', init);
})();
