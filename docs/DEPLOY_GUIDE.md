# PokeDB 静的サイト公開ガイド（無料）

PokeDB のポケモン類似度2次元マップを **完全無料** で Web 上に公開・共有する手順です。
以下のどちらかの方法で数分で公開できます。

---

## 🌟 方法1: GitHub Pages で公開（最もおすすめ・簡単）

すでにリポジトリ内に自動デプロイ用のワークフロー（`.github/workflows/deploy.yml`）が準備されているため、**GitHub に Push して設定を1箇所変更するだけ** で自動公開されます。

### 手順

1. **Git の初期化とコミット**
   PowerShell / ターミナルで以下を実行します：
   ```bash
   git init
   git add .
   git commit -m "Initial commit for PokeDB static map"
   ```

2. **GitHub で新しいリポジトリを作成**
   - [GitHub](https://github.com/new) にアクセスし、新しいリポジトリを作成します（例: `pokedb`、Public 推奨）。

3. **リモートリポジトリへ Push**
   ```bash
   git branch -M main
   git remote add origin https://github.com/<あなたのユーザー名>/<リポジトリ名>.git
   git push -u origin main
   ```

4. **GitHub Pages の設定を有効化**
   - 作成した GitHub リポジトリの **[Settings]** タブを開きます。
   - 左メニューの **[Pages]** をクリックします。
   - **「Build and deployment」>「Source」** のプルダウンを **`GitHub Actions`** に変更します。

5. **公開完了！**
   - リポジトリの **[Actions]** タブでデプロイ処理が自動で走り、数十秒で完了します。
   - `https://<あなたのユーザー名>.github.io/<リポジトリ名>/` にアクセスすると、世界中からマップを閲覧・操作できます。

---

## ⚡ 方法2: Vercel で公開（Push するだけで即デプロイ）

Vercel を使うと、超高速な CDN で配信され、独自ドメインの設定も無料で可能です。

### 手順

1. 上記の方法1の手順 1〜3 で GitHub にコードを Push します。
2. [Vercel](https://vercel.com/) にログイン（GitHub アカウントでログイン）。
3. **「Add New...」>「Project」** を選択し、先ほど作成した GitHub リポジトリを選択（Import）します。
4. 設定は何も変更せず（`vercel.json` が配置されているため自動認識されます）、そのまま **[Deploy]** ボタンを押します。
5. 数十秒で `https://<プロジェクト名>.vercel.app` の公開 URL が発行されます。

---

## 💡 静的公開版の機能について

- **探索・検索・ズーム・パン**: 100% 完全動作（高速）
- **詳細サイドバー・クラスター理由表示**: 100% 完全動作
- **タイプ別フィルター**: 100% 完全動作
- **ポケモンの追加・保存**: ブラウザの LocalStorage に自動保存され、リロード後も保持されます。
- **AI 座標自動計算**: サーバーがない環境でも、テキストの形態素・概念解析によるクライアント側フォールバックで類似領域に自動配置されます。
