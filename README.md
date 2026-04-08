
# SQL_Injection_tool

A hands-on SQL injection testing toolkit for web application security assessments. Built for researchers and penetration testers who need granular control over their payloads.

---

## English

### What this is

This started as a personal project to automate repetitive SQLi testing workflows without relying on heavy frameworks. It grew into something more flexible — a modular tool that lets you craft, obfuscate, and fire payloads at different injection points (URL params, POST data, cookies, headers) while keeping you in the loop for every request.

### Key stuff it does

- **Multi-vector targeting** — Test URL parameters, POST fields (auto-detected forms), cookies, or headers
- **Blind SQLi automation** — Boolean-based, error-based, and time-based detection with configurable thresholds
- **UNION helper** — Column counting, data type probing, version fingerprinting
- **Payload obfuscation** — Built-in encoder supporting case randomization, inline comments, hex/char encoding, string splitting, and multi-layer encoding (URL, base64, unicode)
- **Target management** — Save frequently tested URLs with labels and notes in a local JSON file
- **Browser integration** — Optional Playwright support to open suspicious responses in Chromium for manual inspection
- **Modular payloads** — Load custom payload dictionaries from external Python files

### Quick start

```bash
git clone https://github.com/sudoxs/SQL_Injection_tool.git
cd SQL_Injection_tool
pip install requests beautifulsoup4
# Optional: for browser features
pip install playwright && playwright install chromium

python SQLI.py
```

### Basic workflow

1. Set your target URL (or pick from saved targets)
2. Select injection point type and specific parameters
3. Choose your attack mode — blind testing, UNION enumeration, or custom payload batch
4. Review responses (status codes, timing, content hashes) and optionally open in browser

### Payload obfuscation example

The tool includes an `Obfuscator` class that can transform simple payloads into WAF-evading variants:

```
Input:  ' OR '1'='1' --
Output variations might include:
- '/**/OR/**/'1'=CHAR(49)/**/--+ 
- %27%20%4f%52%20%27%31%27%3d%27%31%27%20%2d%2d%20
- ' OR '1'='1' /*!50000AND*/ '2'='2' #
```

### File structure

```
SQL_Injection_tool/
├── SQLI.py              # Main interactive tool
├── targets.json         # Auto-generated target storage
├── payloads/            # Your custom payload dictionaries
└── errors/              # Regex patterns for error detection
```

### Requirements

- Python 3.8+
- `requests`, `beautifulsoup4`
- `playwright` (optional, for browser features)

---

## 日本語

### これは何？

重いフレームワークに頼らず、SQLインジェクションの繰り返し作業を自動化したいと思って作った個人プロジェクトです。段々と機能を足していって、今ではペイロードの作成から難読化、複数の注入ポイント（URLパラメータ、POSTデータ、Cookie、ヘッダー）への送信まで、細かく制御できるモジュール型ツールになっています。

### 主な機能

- **マルチベクター対応** — URLパラメータ、POSTフィールド（フォーム自動検出）、Cookie、ヘッダーのテスト
- **ブラインドSQLi自動化** — 真偽値ベース、エラーベース、タイムベースの検出（閾値設定可能）
- **UNIONヘルパー** — カラム数カウント、データ型判定、バージョン特定
- **ペイロード難読化** — 大文字小文字ランダム化、インラインコメント、16進数/文字コード変換、文字列分割、多層エンコーディング（URL、base64、unicode）に対応
- **ターゲット管理** — よくテストするURLをラベルとメモ付きでローカルJSONに保存
- **ブラウザ連携** — 怪しいレスポンスをChromiumで開いて手動確認（Playwrightオプション）
- **モジュール型ペイロード** — 外部Pythonファイルからカスタムペイロード辞書を読み込み

### クイックスタート

```bash
git clone https://github.com/sudoxs/SQL_Injection_tool.git
cd SQL_Injection_tool
pip install requests beautifulsoup4
# オプション：ブラウザ機能を使う場合
pip install playwright && playwright install chromium

python SQLI.py
```

### 基本的な使い方

1. ターゲットURLを設定（または保存済みターゲットから選択）
2. 注入ポイントのタイプと具体的なパラメータを選択
3. 攻撃モードを選択 — ブラインドテスト、UNION列挙、カスタムペイロードバッチ
4. レスポンスを確認（ステータスコード、タイミング、コンテンツハッシュ）して、必要に応じてブラウザで開く

### ペイロード難読化の例

ツールに含まれる`Obfuscator`クラスは、単純なペイロードをWAF回避バリアントに変換できます：

```
入力:  ' OR '1'='1' --
出力例:
- '/**/OR/**/'1'=CHAR(49)/**/--+ 
- %27%20%4f%52%20%27%31%27%3d%27%31%27%20%2d%2d%20
- ' OR '1'='1' /*!50000AND*/ '2'='2' #
```

### ファイル構成

```
SQL_Injection_tool/
├── SQLI.py              # メインの対話型ツール
├── targets.json         # 自動生成されるターゲット保存ファイル
├── payloads/            # カスタムペイロード辞書
└── errors/              # エラー検出用正規表現パターン
```

### 必要なもの

- Python 3.8以上
- `requests`、`beautifulsoup4`
- `playwright`（オプション、ブラウザ機能用）

---

## Disclaimer / 免責事項

**English:** This tool is for authorized security testing only. Always obtain proper permission before testing any system you don't own. The author is not responsible for misuse or damage caused by this tool.

**日本語:** 本ツールは許可されたセキュリティテスト専用です。自分が所有していないシステムをテストする前に、必ず適切な許可を得てください。作者は本ツールの誤用やそれによって生じた損害について責任を負いません。

---

Built with Python, caffeine, and too many late nights debugging regex patterns.
```
