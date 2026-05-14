# OCI Free Tier ARM Instance Auto-Claimer

OCI（Oracle Cloud Infrastructure）の Always Free ARM インスタンス（`VM.Standard.A1.Flex` / 4 OCPU / 24 GB RAM）を空きが出るまで自動で申請し続けるツールです。取得に成功したら Discord に通知して停止します。複数の OCI アカウントを並行して申請することもできます。

> **免責事項**: このツールは OCI の利用規約の範囲内で動作します。過度な頻度でのリクエストはアカウント停止の原因になる可能性があります。デフォルトの 5 分間隔での使用を推奨します。

---

## 取得を早めるコツ：Pay As You Go へのアップグレード

OCI の無料トライアルアカウント（Free Tier）のままでは ARM インスタンスの空きが出ても取得できないことがあります。**Pay As You Go（従量課金）にアップグレードすると、優先的に割り当てられるため即座に取得できるケースがあります。**

- Always Free の範囲内で使う限り**料金は発生しません**（4 OCPU / 24 GB RAM まで無料）
- クレジットカードの登録は必要ですが、無料枠を超えない使い方であれば課金されません
- アップグレードは OCI コンソール → 「アップグレードして制限を解除」から行えます

> 課金が心配な方は、下記の **[OCI クレジット監視ツール](https://github.com/AKITO125/oci-credit-monitor)** と組み合わせて使うことを推奨します。コスト上限を超えたらインスタンスを自動停止する機能があります。

---

## 機能

- 全可用性ドメイン（AD）を順番に試行
- キャパシティ不足（"Out of host capacity"）の場合は設定間隔で再試行
- 取得成功・上限超過・レート制限をそれぞれ適切にハンドリング
- 成功時に Discord Webhook で通知
- 複数の OCI アカウントを非同期で並行申請
- イメージ・サブネットの自動選択（手動指定も可能）

---

## 必要なもの

- Python 3.10 以上
- OCI アカウント（[無料登録](https://cloud.oracle.com/free)）
- Discord サーバー（通知用、任意だが推奨）

---

## セットアップ

### Windows

#### 1. Python のインストール

[python.org](https://www.python.org/downloads/) から Python 3.10 以上をダウンロードしてインストールします。
インストール時に **「Add Python to PATH」にチェックを入れる**こと。

確認:

```cmd
python --version
```

#### 2. リポジトリをダウンロード

```cmd
git clone https://github.com/AKITO125/oci-arm-claimer.git
cd oci-arm-claimer
```

または GitHub の「Code → Download ZIP」でダウンロードして展開してください。

#### 3. 依存パッケージのインストール

```cmd
pip install -r requirements.txt
```

#### 4. OCI API キーの設定

1. ブラウザで [OCI コンソール](https://cloud.oracle.com/) にログイン
2. 右上のアイコン → 「マイプロファイル」→「APIキー」→「APIキーの追加」
3. 「APIキー・ペアの生成」→ **秘密キー（.pem）をダウンロード**
4. 「構成ファイルのプレビュー」に表示される内容をコピー
5. `C:\Users\(ユーザー名)\.oci\config` に貼り付けて保存
   - `.oci` フォルダーがなければ作成する
6. `key_file` のパスをダウンロードした `.pem` ファイルの実際のパスに修正

```ini
[DEFAULT]
user=ocid1.user.oc1..xxxxxxxxx
fingerprint=xx:xx:xx:xx:xx:xx:xx:xx:xx:xx:xx:xx:xx:xx:xx:xx
tenancy=ocid1.tenancy.oc1..xxxxxxxxx
region=ap-tokyo-1
key_file=C:\Users\YourName\.oci\oci_api_key.pem
```

設定確認:

```cmd
python -c "import oci; print(oci.config.from_file())"
```

#### 5. SSH キーの準備

インスタンス作成後に SSH 接続するために必要です。

```cmd
:: 既存のキーを確認
type %USERPROFILE%\.ssh\id_rsa.pub

:: キーがない場合は生成
ssh-keygen -t rsa -b 4096
```

#### 6. `.env` ファイルの作成

```cmd
copy .env.example .env
```

`.env` をメモ帳等で開き、`DISCORD_WEBHOOK_URL` と `SSH_PUBLIC_KEY` を設定します。

```env
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
SSH_PUBLIC_KEY=ssh-rsa AAAA...
```

#### 7. `accounts.yaml` の作成

```cmd
copy accounts.yaml.example accounts.yaml
```

1アカウントのみの場合、デフォルトのまま変更不要です（`DEFAULT` プロファイルが使用されます）。

#### 8. 実行

```cmd
python main.py
```

---

### Linux / macOS

#### 1. Python の確認

```bash
python3 --version  # 3.10 以上であること
```

Ubuntu 22.04/24.04 で Python が古い場合:

```bash
sudo add-apt-repository ppa:deadsnakes/ppa
sudo apt install python3.12 python3.12-venv -y
```

#### 2. リポジトリをクローン

```bash
git clone https://github.com/AKITO125/oci-arm-claimer.git
cd oci-arm-claimer
```

#### 3. 仮想環境と依存パッケージ

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

#### 4. OCI API キーの設定

1. ブラウザで [OCI コンソール](https://cloud.oracle.com/) にログイン
2. 右上のアイコン → 「マイプロファイル」→「APIキー」→「APIキーの追加」
3. 「APIキー・ペアの生成」→ **秘密キー（.pem）をダウンロード**
4. `~/.oci/config` を作成（または `oci setup config` コマンドを使用）:

```bash
mkdir -p ~/.oci
cat > ~/.oci/config << 'EOF'
[DEFAULT]
user=ocid1.user.oc1..xxxxxxxxx
fingerprint=xx:xx:xx:xx:xx:xx:xx:xx:xx:xx:xx:xx:xx:xx:xx:xx
tenancy=ocid1.tenancy.oc1..xxxxxxxxx
region=ap-tokyo-1
key_file=~/.oci/oci_api_key.pem
EOF

# ダウンロードした .pem を配置
mv ~/Downloads/oci_api_key.pem ~/.oci/
chmod 600 ~/.oci/oci_api_key.pem
chmod 600 ~/.oci/config
```

設定確認:

```bash
python3 -c "import oci; print(oci.config.from_file())"
```

#### 5. SSH キーの準備

```bash
# 既存のキーを確認
cat ~/.ssh/id_rsa.pub

# キーがない場合は生成
ssh-keygen -t rsa -b 4096
```

#### 6. `.env` ファイルの作成

```bash
cp .env.example .env
nano .env  # または任意のエディタで編集
```

`DISCORD_WEBHOOK_URL` と `SSH_PUBLIC_KEY` を設定します。

#### 7. `accounts.yaml` の作成

```bash
cp accounts.yaml.example accounts.yaml
```

1アカウントのみの場合、デフォルトのまま変更不要です。

#### 8. 実行

```bash
source .venv/bin/activate
python main.py
```

バックグラウンドで長時間実行する場合:

```bash
nohup python main.py > claimer.log 2>&1 &
tail -f claimer.log
```

---

## 複数アカウントの設定

`~/.oci/config` に複数のプロファイルを追加します:

```ini
[DEFAULT]
user=ocid1.user.oc1..aaaaa
fingerprint=xx:xx:...
tenancy=ocid1.tenancy.oc1..aaaaa
region=ap-tokyo-1
key_file=~/.oci/key_account1.pem

[FAMILY1]
user=ocid1.user.oc1..bbbbb
fingerprint=yy:yy:...
tenancy=ocid1.tenancy.oc1..bbbbb
region=ap-osaka-1
key_file=~/.oci/key_account2.pem
```

`accounts.yaml` でアカウントを追加します:

```yaml
accounts:
  - profile: DEFAULT
    name: "メインアカウント（東京）"

  - profile: FAMILY1
    name: "家族アカウント（大阪）"
```

---

## 設定リファレンス

### `.env` の設定項目

| 変数名 | 必須 | 説明 | デフォルト |
|---|---|---|---|
| `DISCORD_WEBHOOK_URL` | 推奨 | 取得成功時の通知先 | （通知なし）|
| `SSH_PUBLIC_KEY` | 推奨 | 接続用 SSH 公開鍵 | （SSH 接続不可）|
| `RETRY_INTERVAL_SECONDS` | 任意 | 再試行間隔（秒） | `300` |
| `INSTANCE_NAME` | 任意 | インスタンス表示名 | `arm-free-instance` |

### `accounts.yaml` の設定項目

| キー | 必須 | 説明 |
|---|---|---|
| `profile` | ✅ | `~/.oci/config` のプロファイル名 |
| `name` | 任意 | ログ表示用の名前（省略時は profile 名）|
| `compartment_id` | 任意 | コンパートメント OCID（省略時: ルートテナント）|
| `subnet_id` | 任意 | サブネット OCID（省略時: 自動検索）|
| `image_id` | 任意 | イメージ OCID（省略時: 最新 Ubuntu ARM を自動選択）|
| `instance_name` | 任意 | インスタンス表示名 |

---

## 実行例

```
============================================================
  OCI Free Tier ARM Instance Auto-Claimer (Multi-Account)
============================================================
  対象アカウント数: 1
    - メインアカウント (プロファイル: DEFAULT)
  シェイプ   : VM.Standard.A1.Flex
  スペック   : 4 OCPU / 24 GB RAM
  再試行間隔 : 300 秒
============================================================

[2026-01-01 12:00:00] [メインアカウント] 可用性ドメイン: AP-TOKYO-1-AD-1
[2026-01-01 12:00:00] [メインアカウント] イメージ: 自動選択完了
[2026-01-01 12:00:00] [メインアカウント] サブネット: 自動選択完了
[2026-01-01 12:00:00] [メインアカウント] 申請ループ開始
[2026-01-01 12:00:00] [メインアカウント] 試行 #1
[2026-01-01 12:00:01] [メインアカウント]   AD AP-TOKYO-1-AD-1: ServiceError 500: Out of host capacity.
[2026-01-01 12:00:01] [メインアカウント] 全AD失敗。300秒後に再試行...
...
[2026-01-01 15:23:45] [メインアカウント] ✅ 取得成功！ OCID: ocid1.instance...
```

---

## よくある質問

**Q: "Out of host capacity" が続く**
A: 正常です。OCI の ARM 無料枠は非常に人気が高く、空きが出るまで数時間〜数日かかることがあります。そのまま実行し続けてください。  
すぐに取得したい場合は、**Pay As You Go（従量課金）アカウント** に切り替えることで確保しやすくなる可能性があります。私の場合は、承認されてすぐにAlways Free枠を取得できました。ただし、無料枠を超える構成やリソースを作成すると料金が発生する場合があるため、設定内容には注意してください。

**Q: "LimitExceeded" エラー**  
A: そのアカウントは Already Free 上限（4 OCPU / 24 GB）に達しています。OCI コンソールで既存インスタンスを確認してください。

**Q: HTTP 429 (Too Many Requests) エラー**  
A: `RETRY_INTERVAL_SECONDS` を `600` 〜 `1800` に増やしてください。

**Q: "404 Not Found" (イメージ/サブネット)**  
A: `accounts.yaml` の `image_id` と `subnet_id` を OCI コンソールで確認して手動設定してください。

**Q: PC をスリープさせたくない**  
A: 長時間実行する場合は、常時稼働のサーバー（別の無料 VPS など）での実行を推奨します。Linux では `nohup` や `screen`/`tmux` を使用してください。

**Q: Windows でバックグラウンド実行したい**  
A: タスクスケジューラを使うか、PowerShell で以下のように実行:
```powershell
Start-Process python -ArgumentList "main.py" -WindowStyle Hidden -RedirectStandardOutput "claimer.log"
```

---

## 関連ツール

- **[oci-credit-monitor](https://github.com/AKITO125/oci-credit-monitor)** — OCI クレジット使用状況の確認・予算アラート登録・コスト超過時のインスタンス自動停止ツール

## ライセンス

MIT License
