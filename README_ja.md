<!-- hy-mt2-i18n:start -->
[English](./README.md) | [中文](./README_zh-CN.md) | **日本語** | [Español](./README_es.md)
<!-- hy-mt2-i18n:end -->

[![sbomifyのロゴ](sbomify/static/img/sbomify.svg)](https://app.sbomify.com/public/product/eP_4dk8ixV/)

[![sbomified](https://sbomify.com/assets/images/logo/badge.svg)](https://app.sbomify.com/public/product/eP_4dk8ixV/)
[![OpenSSF Scorecard](https://api.securityscorecards.dev/projects/github.com/sbomify/sbomify/badge)](https://securityscorecards.dev/viewer/?uri=github.com/sbomify/sbomify&sort_by=check-score&sort_direction=desc)
[![OpenSSF Best Practices](https://www.bestpractices.dev/projects/10952/badge)](https://www.bestpractices.dev/projects/10952)
[![Slack](https://img.shields.io/badge/Slack-Join%20Community-4A154B?logo=slack)](https://join.slack.com/t/sbomify/shared_invite/zt-3na54pa1f-MXrFWhotmZr0YxXc8sABTw)
[![CI/CD Pipeline](https://github.com/sbomify/sbomify/actions/workflows/ci-cd.yml/badge.svg)](https://github.com/sbomify/sbomify/actions/workflows/ci-cd.yml)
[![OpenGrep](https://github.com/sbomify/sbomify/actions/workflows/opengrep.yaml/badge.svg)](https://github.com/sbomify/sbomify/actions/workflows/opengrep.yaml)

sbomifyは、ソフトウェア部品表（SBOM）および文書管理プラットフォームであり、自社でホストすることも、[app.sbomify.com](https://app.sbomify.com)を通じて利用することも可能です。このプラットフォームではSBOMや関連文書を一元管理でき、ステークホルダーと共有したり、公開して閲覧可能にしたりすることができます。

sbomifyのバックエンドは、[github actionsモジュール](https://github.com/sbomify/sbomify-action)と連携し、ロックファイルやDockerファイルから自動的にSBOMを生成します。

詳細については、[sbomify.com](https://sbomify.com) をご覧ください。

## 機能

### SBOM管理

- CycloneDXおよびSPDX SBOM形式（SPDX 3.0を含む）のサポート
- ウェブインターフェースまたはAPI経由でSBOMのアップロード
- 製品やリリースに関する集約済みSBOMを複数の形式で生成：
  - CycloneDX 1.6、1.7
  - SPDX 2.3、3.0
- 脆弱性スキャンとの連携
- 公開/非公開アクセス制御
- ワークスペースベースの組織構造

### コンプライアンスプラグイン

| プラグイン                                | タイプ      | 標準                                                                                                                                         |
| --------------------------------------- | ----------- | ------------------------------------------------------------------------------------------------------------------------------------------------ |
| NTIA Minimum Elements (2021)            | コンプライアンス | [SBOMのためのNTIA最低要素](https://www.ntia.gov/report/2021/minimum-elements-software-bill-materials-sbom)                                 |
| CISA Minimum Elements (2025 Draft)      | コンプライアンス | [CISA 2025 SBOM最低要素](https://www.cisa.gov/sites/default/files/2025-08/2025_CISA_SBOM_Minimum_Elements.pdf) _(公開コメント案)_ |
| BSI TR-03183-2 v2.1 (EU CRA)            | コンプライアンス | [BSI TR-03183-2: サイバー回復力要件](https://bsi.bund.de/dok/TR-03183-en)                                                             |
| FDA Medical Device Cybersecurity (2025) | コンプライアンス | [医療機器におけるFDAのサイバーセキュリティ](https://www.fda.gov/media/119933/download)                                                                |
| GitHub Artifact Attestation             | 認証        | [GitHub Artifact Attestations](https://docs.github.com/en/actions/security-for-github-actions/using-artifact-attestations)                       |

### 文書管理

- ドキュメントアーティファクト（仕様書、マニュアル、レポート、コンプライアンス文書など）のアップロードおよび管理  
- ドキュメントとソフトウェアコンポーネントの関連付け  
- ドキュメントのバージョン管理  
- 設定可能なS3バケットを活用した安全なストレージ  
- 公開および非公開のドキュメント共有

### 組織構造

- **Components**：SBOMやドキュメントを含めることができるコアエンティティ  
- **Products**：関連するComponentsをまとめたもので（販売または配布する製品を表す）  
- **Releases**：製品のComponentsのバージョン管理されたスナップショット  
- **Workspaces**：アクセスと権限の管理

### Transparency Exchange API (TEA)

- [Transparency Exchange API](https://github.com/CycloneDX/transparency-exchange-api/) v0.3.0-beta.2の実装  
- `.well-known/tea`エンドポイントを通じたSBOM検出の標準化  
- サプライチェーン全体におけるSBOMの自動検出および取得の実現

## アーキテクチャ決定記録 (ADRs)

当プロジェクトで下された重要なアーキテクチャ上の決定事項を記録するために、Architecture Decision Records (ADRs) を利用しています。ADRsはそれらの決定の背景や根拠を提供し、現在および将来の貢献者がなぜ特定のアプローチが選ばれたのかを理解するのに役立ちます。

すべてのADRについては、[docs/ADR](docs/ADR)フォルダをご覧ください。

## 部署

デプロイメントプロセスに関する詳細な情報については、以下を含みます：

- CI/CDワークフロー
- 環境設定
- ストレージ構成

[docs/deployment.md](docs/deployment.md)をご覧ください。

本番環境でのデプロイメント手順の詳細については、[デプロイメントガイド](docs/deployment.md)をご覧ください。

## ローカル開発

### 開発時の認証

ローカル開発では、認証はDjangoの管理インターフェースを通じて処理されます：

```bash
# ローカル開発用のスーパーユーザーを作成する
docker compose \
    -f docker-compose.yml \
    -f docker-compose.dev.yml exec \
    sbomify-backend \
    uv run python manage.py createsuperuser
```

その後、`http://localhost:8000/admin` にある管理インターフェースにアクセスしてログインしてください。

> **注**: 実環境では別の認証方法が使用されます。実環境での認証設定については、[docs/deployment.md](docs/deployment.md)を参照してください。

### 開発に必要な環境

- Python 3.13以上
- uv（Pythonパッケージマネージャ）
- Docker（PostgreSQLおよびMinioの実行用）
- Bun（JavaScript開発用）

#### uvのインストール

- 公式インストーラを使用してuvをインストールする：

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

- インストールを確認する：

```bash
uv --version
```

#### 依存関係のインストール

- uvを使用してPythonの依存関係をインストールする：

```bash
# 開発用依存関係を含むすべての依存関係をインストールする
uv sync

# uvを使用してコマンドを実行する
uv run python manage.py --help
```

- Bunを使用してJavaScriptの依存関係をインストールする：

```bash
bun install
```

### APIドキュメント

APIドキュメントは以下の URL でご覧いただけます：

- インタラクティブなAPIドキュメント（Swagger UI）: `http://localhost:8000/api/v1/docs`
- OpenAPI仕様: `http://localhost:8000/api/v1/openapi.json`

このAPIは、以下の管理に必要なエンドポイントを提供します：

- **SBOMs**: ソフトウェア部品リストのアップロード、取得、および管理  
- **Documents**: ドキュメントファイルのアップロード、取得、および管理  
- **Components**: SBOMやドキュメントを含むコンポーネントの管理  
- **Products**: コンポーネントの整理とグループ化  
- **Workspaces**: ユーザー管理とアクセス制御

#### 複合 SBOM のダウンロード

製品およびリリースの集約済みSBOMを、形式を指定してダウンロードする：

```bash
# CycloneDX 1.6（デフォルト）形式でリリースのSBOMをダウンロード
curl "https://app.sbomify.com/api/v1/releases/{release_id}/download"

# SPDX 2.3形式でリリースのSBOMをダウンロード
curl "https://app.sbomify.com/api/v1/releases/{release_id}/download?format=spdx"

# SPDX 3.0形式でリリースのSBOMをダウンロード
curl "https://app.sbomify.com/api/v1/releases/{release_id}/download?format=spdx&version=3.0"

# CycloneDX 1.7形式でリリースのSBOMをダウンロード
curl "https://app.sbomify.com/api/v1/releases/{release_id}/download?format=cyclonedx&version=1.7"

# SPDX 2.3形式でプロダクトのSBOMをダウンロード
curl "https://app.sbomify.com/api/v1/products/{product_id}/download?format=spdx&version=2.3"
```

# サポートされている形式とバージョン:**

| フォーマット | バージョン | デフォルト |
| --------- | -------- | ------- |
| CycloneDX | 1.6, 1.7 | 1.6     |
| SPDX      | 2.3, 3.0 | 2.3     |

開発サーバーを実行している状態では、これらのエンドポイントを利用できます。

### 設定

シェルで環境変数を設定するか、Docker Composeのオーバーライドファイルを使用して環境変数を構成します。

**重要：/etc/hosts に追加してください**

開発環境がKeycloak認証を正しく利用できるようにするため、`/etc/hosts`ファイルに次のエントリを追加する必要があります：

```bash
127.0.0.1   keycloak
```

開発環境の起動（推奨方法）：

```bash
./bin/developer_mode.sh build
./bin/developer_mode.sh up
```

ローカルの管理者アカウントを作成する：

```bash
docker compose \
    -f docker-compose.yml \
    -f docker-compose.dev.yml exec \
    -e DJANGO_SUPERUSER_USERNAME=sbomifyadmin \
    -e DJANGO_SUPERUSER_PASSWORD=sbomifyadmin \
    -e DJANGO_SUPERUSER_EMAIL=admin@sbomify.com \
    sbomify-backend \
    uv run python manage.py createsuperuser --noinput
```

アプリケーションにアクセスするには：

- 管理者インターフェース: `http://localhost:8000/admin`
- メインアプリケーション: `http://localhost:8000`

> **注記**: 実環境でのデプロイメントに関する情報は、[docs/deployment.md](docs/deployment.md) をご覧ください。

#### 代替案：ローカルでの実行（Dockerを使用しないDjango版）

- Docker内で必要なサービスを起動する：

```bash
# PostgreSQLとMinIOの両方を起動する
docker compose up sbomify-db sbomify-minio sbomify-createbuckets -d
```

- 依存関係のインストール：

```bash
uv sync
bun install  # JavaScriptの依存関係用
```

- マイグレーションの実行：

```bash
uv run python manage.py migrate
```

- 開発サーバーを起動する：

```bash
# 別のターミナルでDjangoを起動します
uv run python manage.py runserver

# もう一つのターミナルでViteを起動します
bun run dev
```

### 設定

#### 開発サーバーの設定

このアプリケーションではJavaScript開発にViteを使用しています。以下の環境変数が開発サーバーを制御します：

```bash
# Vite開発設定
DJANGO_VITE_DEV_MODE=True
DJANGO_VITE_DEV_SERVER_PORT=5170
DJANGO_VITE_DEV_SERVER_HOST=http://localhost

# スタティックサーバーおよび開発サーバーの設定
STATIC_URL=/static/
DEV_JS_SERVER=http://127.0.0.1:5170
WEBSITE_BASE_URL=http://127.0.0.1:8000
VITE_API_BASE_URL=http://127.0.0.1:8000
VITE_WEBSITE_BASE_URL=http://127.0.0.1:8000
```

これらの設定は環境変数を使用して構成できます。

#### Keycloak認証の設定

Keycloakは現在、Docker Compose環境の一部として管理されています。手動でKeycloakを起動する必要はありません。

Keycloakの永続ストレージは、Dockerによって名前付きボリューム（`keycloak_data`）を使用して管理されます。

##### Keycloakの起動処理

Docker Composeを使用して開発環境を起動すると、`bin/keycloak-bootstrap.sh`にあるスクリプトによってKeycloakが自動的に起動されます。このスクリプトは、`KEYCLOAK_REALM`、`KEYCLOAK_CLIENT_ID`、`KEYCLOAK_ADMIN_USERNAME`、`KEYCLOAK_ADMIN_PASSWORD`、`KEYCLOAK_CLIENT_SECRET`といった環境変数を利用して、リールム、クライアント、および認証情報を設定します。**スクリプト自体を編集する必要はありません**——起動処理を制御するには、Docker Composeの設定で適切な環境変数を設定するだけでよいのです。

開発モードで実行する場合（`docker-compose.dev.yml` を使用）、ブートストラップスクリプトは自動的に以下の処理を行います：

- ローカル開発を容易にするために、**SSL要件を無効化**します  
- 認証テスト用の**テストユーザーを作成**します：  
  - **John Doe** – ユーザー名: `jdoe`、パスワード: `foobar123`、メールアドレス: `jdoe@example.com`  
  - **Steve Smith** – ユーザー名: `ssmith`、パスワード: `foobar123`、メールアドレス: `ssmith@example.com`

これらの開発専用設定は、`KEYCLOAK_DEV_MODE`という環境変数によって制御され、開発用のDocker Composeスタックを実行する際にのみ適用されます。

開発モードでKeycloak（およびその他すべてのサービス）を起動するには、次のコマンドを実行するだけです：

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up
```

Keycloakは<http://keycloak:8080/>で利用可能になります。

#### S3/Minioストレージ

このアプリケーションは、ファイルやアセットを保存するためにS3互換のストレージを利用しています。開発環境では、ローカルでのS3の代わりとしてMinioを使用しています。

- Docker Composeを使用して実行する場合、すべてが自動的に設定されます。
- ローカルで実行する場合（Docker外のDjango）：
  - Docker経由でMinioが動作していることを確認してください：
    `docker compose up sbomify-minio sbomify-createbuckets -d`
  - 環境変数に`AWS_ENDPOINT_URL_S3=http://localhost:9000`を設定してください。
  - 必要なバケット（`sbomify-media`、`sbomify-sboms`、および任意で`sbomify-documents`）が自動的に作成されます。

##### ストレージバケット

このアプリケーションでは、異なる種類のコンテンツごとに別々のS3バケットを使用しています：

- **メディアバケット**: ユーザーアバター、ワークスペースのロゴ、その他のメディア資産  
- **SBOMsバケット**: ソフトウェア部品表ファイル  
- **ドキュメントバケット**: 諸々のドキュメントアーティファクト（仕様書、マニュアル、レポート、コンプライアンス文書など）  
  - 別途設定しない場合、ドキュメントは自動的にSBOMsバケットを使用します  
  - 実運用環境では、より適切な整理とアクセス制御のために別のバケットを使用することが推奨されます

Minioコンソールには以下のアドレスからアクセスできます：

- `http://localhost:9001`
- デフォルトの認証情報：minioadmin/minioadmin

##### プロダクション環境でのストレージ設定

本番環境でのデプロイの場合、ドキュメント用に別途S3バケットを設定することができます：

```bash
# オプション：専用のドキュメントバケットを設定する（本番環境で推奨）
export AWS_DOCUMENTS_ACCESS_KEY_ID="your-documents-access-key"
export AWS_DOCUMENTS_SECRET_ACCESS_KEY="your-documents-secret-key"
export AWS_DOCUMENTS_STORAGE_BUCKET_NAME="your-documents-bucket"
export AWS_DOCUMENTS_STORAGE_BUCKET_URL="https://your-documents-bucket.s3.region.amazonaws.com"

# 設定しない場合、ドキュメントは自動的にSBOMsバケットが使用されます
export AWS_SBOMS_ACCESS_KEY_ID="your-sboms-access-key"
export AWS_SBOMS_SECRET_ACCESS_KEY="your-sboms-secret-key"
export AWS_SBOMS_STORAGE_BUCKET_NAME="your-sboms-bucket"
export AWS_SBOMS_STORAGE_BUCKET_URL="https://your-sboms-bucket.s3.region.amazonaws.com"
```

別々のバケットを使用する利点：

- **セキュリティ**：SBOMとドキュメントで異なるアクセスポリシーを適用  
- **整理**：コンテンツタイプを明確に分離  
- **バックアップ**：異なるデータタイプごとに独立したバックアップ戦略を採用

#### Dependency Trackとの連携

sbomifyは、高度な脆弱性管理および分析のために[Dependency Track](https://dependencytrack.org/)との連携をサポートしています。Dependency Trackとの連携機能は、BusinessプランおよびEnterpriseプランで利用可能です。

**注:** Dependency TrackはCycloneDX形式のSBOMのみをサポートしています。workspaceの設定に関係なく、SPDX形式のSBOMは自動的にOSVスキャンが適用されます。

##### 環境別プロジェクト名の付け方

複数の環境（開発、ステージング、本番）で共有されたDependency Trackインスタンスを使用する場合、sbomifyはプロジェクト名の先頭に自動的に環境名を付加し、それらを区別しやすくします：

**例:**

- **本番環境** (`https://app.sbomify.com`): `prod-sbomify-{component-id}`
- **ステージング環境** (`https://staging.sbomify.com`): `staging-sbomify-{component-id}`
- **開発環境** (`https://dev.sbomify.com`): `dev-sbomify-{component-id}`
- **ローカル環境** (`http://localhost:8000`): `local-sbomify-{component-id}`

**カスタム環境プレフィックス:**
`DT_ENVIRONMENT_PREFIX` 環境変数を設定することで、自動検出を上書きできます。

```bash
export DT_ENVIRONMENT_PREFIX="my-custom-env"
# 結果として：my-custom-env-sbomify-{component-id} となります
```

これにより、Dependency Trackのダッシュボードを閲覧する際に、プロジェクトがどの環境に属しているかを簡単に識別できます。

##### 必要な権限

Dependency Trackと連携するには、以下の権限を持つAPIトークンを作成する必要があります：

- `BOM_UPLOAD`
- `PROJECT_CREATION_UPLOAD`
- `VIEW_PORTFOLIO`
- `VIEW_VULNERABILITY`

Dependency Trackインスタンス内の**Administration → Access Management**からトークンを作成できます（そちらにあるワークスペース管理インターフェースを使用してください）。

##### DT設定

1. Django adminを通じて**Dependency Trackサーバーを追加する**：
   - `/admin/vulnerability_scanning/dependencytrackserver/`に移動します
   - 「Add Dependency Track Server」をクリックします
   - サーバーの詳細情報を入力します：
     - **Name**：サーバーの親しみやすい名称
     - **URL**：ご使用のDependency TrackインスタンスのベースURL
     - **API Key**：必要な権限を持つトークン
     - **Priority**：数値が小さいほど負荷分散時の優先度が高くなります
     - **Max Concurrent Scans**：同時に行えるSBOMアップロードの最大数

2. **ワークスペース設定の構成**：
   - Business/Enterpriseワークスペースでは、**Settings → Integrations**でDependency Trackを選択できます。
   - Enterpriseワークスペースでは、必要に応じてカスタムのDependency Trackインスタンスを構成できます。
   - Businessワークスペースは共有されたサーバープールを利用します。

##### DTの機能

- **自動脆弱性スキャン**:
  - コミュニティワークスペース：OSVを使用した週1回の脆弱性スキャン
  - ビジネス/エンタープライズワークスペース：Dependency Trackを使用した12時間ごとの脆弱性更新
- **負荷分散**：複数のDependency Trackサーバー間でスキャンを分散処理
- **健全性監視**：サーバーの自動健全性チェックおよび容量管理
- **履歴追跡**：傾向分析のための完全なスキャン結果履歴
- **統一された結果**：OSVおよびDependency Trackの両方で一貫した脆弱性データ形式

### テストケースの実行

テストを実行する前に、まず docker-compose.tests.yml を起動する必要があります：

```bash
docker compose -f docker-compose.tests.yml up -d
```

Djangoのテストプロファイルを使用してテストを実行します：

```bash
# カバレッジを含めてすべてのテストを実行
uv run coverage run -m pytest

# 特定のテストグループを実行
uv run coverage run -m pytest core/tests/
uv run coverage run -m pytest sboms/tests/
uv run coverage run -m pytest teams/tests/

# 失敗時にデバッガーを使って実行
uv run coverage run -m pytest --pdb -x -s

# カバレッジレポートを生成
uv run coverage report
```

CIチェックに合格するためには、テストのカバレッジ率は80％以上でなければなりません。

### E2Eスナップショット（スクリーンショット）テスト

このプロジェクトには、UIのスクリーンショットを撮影し、ベースライン画像と比較するエンドツーエンドのスナップショットテストが含まれています。これにより、さまざまな画面サイズやコード変更後でも視覚的な一貫性が保たれます。

#### E2Eテストの前提条件

E2Eスナップショットテストを実行する前に、以下の作業が必要です：

**JavaScriptアセットのビルド:**

```bash
bun run build
```

これにより、スクリーンショットを撮影する前にすべての静的アセット（JavaScript、CSS）が最新の状態であることが保証されます。

#### スナップショットテストの記述方法

スナップショットテストの記述方法を示す抽象的な例は次の通りです：

```python
@pytest.mark.django_db
@pytest.mark.parametrize("width", [1920, 992, 576, 375])
class TestYourPageSnapshot:
    def test_your_page_snapshot(
        self,
        authenticated_page,
        your_test_fixtures,  # noqa: F811
        snapshot,
        width: int,
    ) -> None:
        # テスト対象のページに移動する
        authenticated_page.goto("/your-page")
        authenticated_page.wait_for_load_state("networkidle")

        # 基準となるスクリーンショットを取得または作成する（__snapshots__ に保存される）
        baseline = snapshot.get_or_create_baseline_screenshot(authenticated_page, width=width)

        # 現在のスクリーンショットを撮影する
        current = snapshot.take_screenshot(authenticated_page, width=width)

        # スクリーンショットを比較する
        snapshot.assert_screenshot(baseline.as_posix(), current.as_posix())
```

**主要なコンポーネント:**

- データベースへのアクセスを有効にするには `@pytest.mark.django_db` を使用します  
- 複数の画面サイズでテストを行うには `@pytest.mark.parametrize("width", [...])` を使用します  
- ブラウザ自動化のために `authenticated_page` フィックスチャを注入します  
- スクリーンショット管理のために `snapshot` フィックスチャを注入します  
- ベースライン画像を取得するには `get_or_create_baseline_screenshot()` を使用します（存在しない場合は自動的に作成されます）  
- 現在の状態をキャプチャするには `take_screenshot()` を使用します  
- 両者を比較するには `assert_screenshot()` を使用します

#### E2Eスナップショットテストの実行

アセットのビルドが完了したら、専用のE2E docker-composeスタックを使用してスナップショットテストを実行できます：

```bash
# テストスタック（データベース、Chromium、テストコンテナ）を起動する
docker compose -f docker-compose.tests.yml up -d

# テストコンテナ内で全てのE2Eスナップショットテストを実行する
docker compose -f docker-compose.tests.yml exec tests uv run pytest sbomify/apps/<APP>/tests/e2e/

# 単一のE2Eスナップショットテストを実行する（例）
docker compose -f docker-compose.tests.yml exec tests uv run pytest \
  sbomify/apps/<APP>/tests/e2e/test_your_page.py::TestYourPageSnapshot::test_your_page_snapshot[1920]
```

#### スナップショットテストの利用方法

**新規テスト**  
新しいスナップショットテストを作成すると、`__snapshots__` ディレクトリ（場所：`sbomify/apps/<APP_NAME>/tests/e2e/__snapshots__/`）に自動的にベースラインのスクリーンショットが作成されます。テストを実行し、生成されたスクリーンショットが正しく表示されているか確認してください。

**既存のテスト - 実行成功**
テストが既に存在し実行に成功している場合、すべてが予想通りに動作しています。特に操作は必要ありません。

**既存のテスト - 失敗する場合**
テストが失敗した場合は、何が変更されたかを確認するために`__diffs__`ディレクトリ（`sbomify/apps/<APP_NAME>/tests/e2e/__diffs__/`にあります）をチェックしてください。差分画像には、ベースラインスクリーンショットと現在のスクリーンショットとの違いが表示されます。

**古くなったスナップショットの更新**
`__diffs__` 内の差分スクリーンショットで新しい視覚状態が正しいことが確認できた場合（つまり、ベースラインのスナップショットが古くなっている場合）、ベースラインを更新する必要があります：

1. `__snapshots__` 内の古くなったスナップショットファイルを削除します。  
2. テストを再実行すると、現在の状態に合わせたベースラインスクリーンショットが自動的に作成されます。

**例:**

```bash
# 古いスナップショットを削除する
rm sbomify/apps/<APP_NAME>/tests/e2e/__snapshots__/test_your_page_snapshot[1920].jpg

# テストを再実行して新しいベースラインを作成する
uv run pytest sbomify/apps/<APP_NAME>/tests/e2e/test_your_page.py::TestYourPageSnapshot::test_your_page_snapshot
```

実際の例については、`sbomify/apps/core/tests/e2e/test_dashboard.py` をご覧ください。

### テストデータの管理

このアプリケーションには、開発環境内のテストデータの設定や管理を支援する管理コマンドが含まれています：

```bash
# サンプルSBOMデータを使用してテスト環境を作成する
# ワークスペースが指定されていない場合は、データベース内の最初のワークスペースが使用される
# （互換性のため、管理コマンドでは古い形式の--team-idフラグ名がそのまま使われている）
python manage.py create_test_sbom_environment

# 特定のワークスペース用のテスト環境を作成する（依然として古い形式の--team-idフラグを使用）
python manage.py create_test_sbom_environment --team-id=your_team_id

# 既存のテストデータを削除し、新しい環境を作成する
python manage.py create_test_sbom_environment --clean

# すべてのワークスペースにあるテストデータをすべて削除する
python manage.py cleanup_test_sbom_environment

# 特定のワークスペースのテストデータを削除する（依然として古い形式の--team-idフラグを使用）
python manage.py cleanup_test_sbom_environment --team-id=your_team_id

# 削除される内容を事前に確認する（ドライラン）
python manage.py cleanup_test_sbom_environment --dry-run
```

これらのコマンドは以下の操作を行います：

1. テスト用の製品およびコンポーネントを作成する  
2. テストファイルから実際のSBOMデータ（SPDXおよびCycloneDX形式の両方）を読み込む  
3. すべてのエンティティ間の適切な関係を設定する  
4. 必要に応じてテストデータを削除できるようにする

テストデータは形式ではなくソース別（例：hello-world および sbomify）にグループ分けされているため、各コンポーネントには SPDX と CycloneDX の両方の SBOM が添付されます。

注：データベースに少なくとも1つのワークスペースが存在している場合のみ、古い`--team-id`フラグを指定しなくてもこれらのコマンドを使用できます。

### JSビルドツール

フロントエンドのJS開発を行うには、JSツールのセットアップが必要です。

#### Bun

```bash
curl -fsSL https://bun.sh/install | bash
```

`package.json` と同じレベルにあるプロジェクトフォルダ内で：

```bash
bun install
```

#### リンティング

JavaScript/TypeScriptのリンティングについては：

```bash
# リンティングの問題をチェックする（CIで使用され、ローカルでも実行可能）
bun lint

# リンティングの問題を自動的に修正する（ローカル開発専用）
bun lint-fix
```

#### Viteデバッグサーバーを起動する

```bash
bun run dev
```

### Pre-commitチェック

このプロジェクトでは、コードの品質と一貫性を確保するためにpre-commit hooksを使用しています。これらのhooksは以下の項目をチェックします：

- コードフォーマット（ruff-format）
- Pythonのリンティング（ruff）
- セキュリティ問題の検出（bandit）
- Markdownのフォーマット
- TypeScriptの型チェック
- JavaScript/TypeScriptのリンティング
- マージコンフリクト
- デバッグステートメント

pre-commitを設定するには：

- pre-commitフックのインストール：

```bash
uv run pre-commit install
```

- 手動でプリコミットチェックを実行する：

```bash
# すべてのファイルをチェックする
uv run pre-commit run --all-files

# ステージングされたファイルのみをチェックする
uv run pre-commit run
```

## 実環境でのデプロイメント

### 実環境での動作に必要な条件

- DockerおよびDocker Compose  
- Amazon S3やGoogle Cloud StorageなどのS3互換ストレージ  
- PostgreSQLデータベース  
- 実環境でのデプロイメント用リバースプロキシ（例：Nginx）

### Docker Composeの設定

本番環境に近い構成のために `docker-compose.prod.yml` ファイルが用意されています。**注意：** この設定は十分にテストされておらず、そのまま実際の本番環境で使用することは推奨されません。記載されている設定値はデモンストレーションやステージング目的のみであり、将来的に更新・改善される予定です。

本番環境でのデプロイの際は、署名済みURL用に安全な署名サルトを生成してください：

```bash
# 署名済みURL用の安全な署名サルトを生成する
export SIGNED_URL_SALT="$(openssl rand -hex 32)"
```

`SIGNED_URL_SALT`は、製品のSBOMに含まれるプライベートコンポーネントのダウンロードURLに署名するために使用されます。

本番環境に近い構成を試すには：

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml build
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

適切な環境変数を設定し、リバースプロキシ、ストレージ、データベースが安全に構成されていることを確認する必要があります。

> **警告:** 実際のデプロイメントでは、提供されている本番向けのdocker compose設定をそのまま使用しないでください。本番環境で利用する前に、すべての設定、機密情報、ネットワーク接続の仕組みを十分に確認し、安全性を高めてください。
