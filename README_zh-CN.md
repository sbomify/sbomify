<!-- hy-mt2-i18n:start -->
[English](./README.md) | **中文** | [日本語](./README_ja.md) | [Español](./README_es.md)
<!-- hy-mt2-i18n:end -->

![sbomify 徽标](sbomify/static/img/sbomify.svg)

[![sbomified](https://sbomify.com/assets/images/logo/badge.svg)](https://app.sbomify.com/public/product/eP_4dk8ixV/)
[![OpenSSF Scorecard](https://api.securityscorecards.dev/projects/github.com/sbomify/sbomify/badge)](https://securityscorecards.dev/viewer/?uri=github.com/sbomify/sbomify&sort_by=check-score&sort_direction=desc)
[![OpenSSF Best Practices](https://www.bestpractices.dev/projects/10952/badge)](https://www.bestpractices.dev/projects/10952)
[![Slack](https://img.shields.io/badge/Slack-Join%20Community-4A154B?logo=slack)](https://join.slack.com/t/sbomify/shared_invite/zt-3na54pa1f-MXrFWhotmZr0YxXc8sABTw)
[![CI/CD Pipeline](https://github.com/sbomify/sbomify/actions/workflows/ci-cd.yml/badge.svg)](https://github.com/sbomify/sbomify/actions/workflows/ci-cd.yml)
[![OpenGrep](https://github.com/sbomify/sbomify/actions/workflows/opengrep.yaml/badge.svg)](https://github.com/sbomify/sbomify/actions/workflows/opengrep.yaml)

SBomify 是一款软件物料清单（SBOM）及文档管理平台，支持自主托管，也可通过 [app.sbomify.com](https://app.sbomify.com) 进行访问。该平台提供了一个集中式位置，用于上传和管理您的 SBOM 及相关文档，让您能够与利益相关方共享这些内容，或将其公开发布。

sbomify后端与我们[GitHub Actions模块](https://github.com/sbomify/sbomify-action)相集成，能够自动从锁定文件和Docker文件中生成SBOM。

如需了解更多信息，请访问 [sbomify.com](https://sbomify.com)。

## 功能特性

### SBOM 管理

- 支持 CycloneDX 和 SPDX SBOM 格式（包括 SPDX 3.0）
- 通过网页界面或 API 上传 SBOM
- 为产品和版本生成多种格式的汇总 SBOM：
  - CycloneDX 1.6、1.7
  - SPDX 2.3、3.0
- 集成漏洞扫描功能
- 公开与私有访问控制
- 基于工作区的组织管理

### 合规插件

| 插件                                      | 类型       | 标准                                                                                                                                         |
| ----------------------------------------- | ---------- | ------------------------------------------------------------------------------------------------------------------------------------------------ |
| NTIA 最低要素标准（2021版）               | 合规性     | [NTIA 软件物料 SBOM 最低要素要求](https://www.ntia.gov/report/2021/minimum-elements-software-bill-materials-sbom)                                 |
| CISA 最低要素标准（2025年草案）           | 合规性     | [CISA 2025年 SBOM 最低要素要求](https://www.cisa.gov/sites/default/files/2025-08/2025_CISA_SBOM_Minimum_Elements.pdf) _(公开征求意见草案)_ |
| BSI TR-03183-2 v2.1（欧盟网络弹性要求）     | 合规性     | [BSI TR-03183-2：网络弹性要求](https://bsi.bund.de/dok/TR-03183-en)                                                             |
| FDA 医疗设备网络安全标准（2025版）         | 合规性     | [FDA 医疗设备网络安全要求](https://www.fda.gov/media/119933/download)                                                                |
| GitHub 构建产物认证                      | 认证       | [GitHub 构建产物认证功能](https://docs.github.com/en/actions/security-for-github-actions/using-artifact-attestations)                       |

### 文档管理

- 上传并管理文档工件（规格书、手册、报告、合规文件等）
- 将文档与软件组件关联
- 文档版本控制
- 基于可配置的 S3 存储桶实现安全存储
- 公开与私有的文档共享

### 组织结构

- **组件**：可包含 SBOM 或文档的核心实体  
- **产品**：将相关组件汇总在一起（并代表您所销售或分发的内容）  
- **版本发布**：产品组件的带版本号的快照  
- **工作空间**：用于控制访问权限

### 透明度交换 API (TEA)

- 实现了 [Transparency Exchange API](https://github.com/CycloneDX/transparency-exchange-api/) v0.3.0-beta.2版本  
- 通过`.well-known/tea`端点实现标准化的SBOM检索功能  
- 支持在整个供应链中自动发现并获取SBOM数据

## 架构决策记录（ADRs）

我们使用架构决策记录（ADRs）来记载该项目中做出的重要架构决策。ADRs会为这些决策提供背景说明与依据，帮助当前及未来的贡献者理解为何选择特定的方案。

所有架构决策记录均可在 [docs/ADR](docs/ADR) 文件夹中查看。

## 部署

有关部署流程的详细信息，包括：

- CI/CD 工作流
- 环境配置
- 存储设置

参见[docs/deployment.md](docs/deployment.md)。

如需完整的生产环境部署说明，请参阅[部署指南](docs/deployment.md)。

## 本地开发

### 开发过程中的身份认证

在本地开发时，身份验证是通过 Django 的管理界面来处理的：

```bash
# 为本地开发创建超级用户
docker compose \
    -f docker-compose.yml \
    -f docker-compose.dev.yml exec \
    sbomify-backend \
    uv run python manage.py createsuperuser
```

随后通过 `http://localhost:8000/admin` 访问管理界面进行登录。

> **注意**：生产环境会采用不同的认证方式。有关生产环境的认证配置，请参阅[docs/deployment.md](docs/deployment.md)。

### 开发前置条件

- Python 3.13及以上版本
- uv（Python包管理器）
- Docker（用于运行PostgreSQL和Minio）
- Bun（用于JavaScript开发）

#### 安装 uv

- 使用官方安装脚本安装 uv：

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

- 验证安装情况：

```bash
uv --version
```

#### 安装依赖项

- 使用 uv 安装 Python 依赖项：

```bash
# 安装所有依赖项，包括开发依赖项
uv sync

# 使用 uv 运行命令
uv run python manage.py --help
```

- 使用 Bun 安装 JavaScript 依赖项：

```bash
bun install
```

### API 文档

API 文档地址如下：

- 交互式 API 文档（Swagger UI）：`http://localhost:8000/api/v1/docs`
- OpenAPI 规范：`http://localhost:8000/api/v1/openapi.json`

该 API 提供用于管理以下内容的接口端点：

- **SBOMs**：上传、检索及管理软件物料清单  
- **Documents**：上传、检索及管理文档资源  
- **Components**：管理包含 SBOM 或文档的组件  
- **Products**：对组件进行整理与分组  
- **Workspaces**：用户管理及访问控制

#### 聚合 SBOM 下载

按格式选择下载产品和版本对应的聚合 SBOM：

```bash
# 下载格式为 CycloneDX 1.6（默认）的版本 SBOM
curl "https://app.sbomify.com/api/v1/releases/{release_id}/download"

# 下载格式为 SPDX 2.3 的版本 SBOM
curl "https://app.sbomify.com/api/v1/releases/{release_id}/download?format=spdx"

# 下载格式为 SPDX 3.0 的版本 SBOM
curl "https://app.sbomify.com/api/v1/releases/{release_id}/download?format=spdx&version=3.0"

# 下载格式为 CycloneDX 1.7 的版本 SBOM
curl "https://app.sbomify.com/api/v1/releases/{release_id}/download?format=cyclonedx&version=1.7"

# 下载格式为 SPDX 2.3 的产品 SBOM
curl "https://app.sbomify.com/api/v1/products/{product_id}/download?format=spdx&version=2.3"
```

**支持的格式与版本：**

| 格式    | 版本     | 默认值 |
| --------- | -------- | ------- |
| CycloneDX | 1.6, 1.7 | 1.6     |
| SPDX      | 2.3, 3.0 | 2.3     |

运行开发服务器时即可使用这些接口。

### 设置

你可以在shell中设置环境变量，或使用Docker Compose覆盖文件来配置它们。

**重要提示：请将其添加到 `/etc/hosts` 文件中**

为使开发环境能够通过 Keycloak 认证正常运行，您必须在 `/etc/hosts` 文件中添加以下条目：

```bash
127.0.0.1   keycloak
```

启动开发环境（推荐方法）：

```bash
./bin/developer_mode.sh build
./bin/developer_mode.sh up
```

创建本地管理员账户：

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

访问应用程序：

- 管理界面：`http://localhost:8000/admin`
- 主应用：`http://localhost:8000`

> **注意**：有关生产环境部署的信息，请参阅 [docs/deployment.md](docs/deployment.md)。

#### 备选方案：本地运行（Django 部分不使用 Docker）

- 在 Docker 中启动所需服务：

```bash
# 同时启动 PostgreSQL 和 MinIO
docker compose up sbomify-db sbomify-minio sbomify-createbuckets -d
```

- 安装依赖项：

```bash
uv sync
bun install  # 用于安装 JavaScript 依赖项
```

- 运行迁移：

```bash
uv run python manage.py migrate
```

- 启动开发服务器：

```bash
# 在一个终端中启动 Django
uv run python manage.py runserver

# 在另一个终端中启动 Vite
bun run dev
```

### 配置

#### 开发服务器配置

该应用使用 Vite 进行 JavaScript 开发。以下环境变量用于控制开发服务器：

```bash
# Vite 开发设置
DJANGO_VITE_DEV_MODE=True
DJANGO_VITE_DEV_SERVER_PORT=5170
DJANGO_VITE_DEV_SERVER_HOST=http://localhost

# 静态文件及开发服务器设置
STATIC_URL=/static/
DEV_JS_SERVER=http://127.0.0.1:5170
WEBSITE_BASE_URL=http://127.0.0.1:8000
VITE_API_BASE_URL=http://127.0.0.1:8000
VITE_WEBSITE_BASE_URL=http://127.0.0.1:8000
```

这些设置可以通过环境变量进行配置。

#### Keycloak 认证配置

Keycloak 现已作为 Docker Compose 环境的一部分进行管理，无需手动启动 Keycloak。

Keycloak 的持久化存储由 Docker 通过命名卷（`keycloak_data`）来管理。

##### Keycloak 启动流程

当您使用 Docker Compose 启动开发环境时，系统会通过 `bin/keycloak-bootstrap.sh` 脚本自动完成 Keycloak 的启动工作。该脚本会利用环境变量（如 `KEYCLOAK_REALM`、`KEYCLOAK_CLIENT_ID`、`KEYCLOAK_ADMIN_USERNAME`、`KEYCLOAK_ADMIN_PASSWORD`、`KEYCLOAK_CLIENT_SECRET` 等）来配置领域、客户端以及相关凭证。**您无需直接编辑该脚本本身**——只需在 Docker Compose 配置中设置相应的环境变量，即可控制启动流程。

在开发模式运行时（使用 `docker-compose.dev.yml`），引导脚本会自动：

- **禁用SSL要求**，以便更便捷地进行本地开发
- **创建测试用户**用于身份验证测试：
  - **John Doe** - 用户名：`jdoe`，密码：`foobar123`，邮箱：`jdoe@example.com`
  - **Steve Smith** - 用户名：`ssmith`，密码：`foobar123`，邮箱：`ssmith@example.com`

这些专为开发环境设计的配置由 `KEYCLOAK_DEV_MODE` 环境变量控制，且仅在运行开发版的 Docker Compose 集群时才会生效。

要在开发模式下启动 Keycloak（以及所有其他服务），只需运行以下命令：

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up
```

Keycloak 的访问地址为 <http://keycloak:8080/>。

#### S3/Minio 存储

该应用使用兼容 S3 的存储方式来保存文件和资源。在开发环境中，我们使用 Minio 作为本地的 S3 替代方案。

- 使用 Docker Compose 运行时，所有配置都会自动完成  
- 在本地运行（Docker 之外的 Django 环境）时：  
  - 确保 Minio 已通过 Docker 启动：  
    `docker compose up sbomify-minio sbomify-createbuckets -d`  
  - 在环境变量中设置 `AWS_ENDPOINT_URL_S3=http://localhost:9000`  
  - 所需的存储桶（`sbomify-media`、`sbomify-sboms`，以及可选的 `sbomify-documents`）将会自动创建

##### 存储桶

该应用为不同类型的内容使用独立的 S3 存储桶：

- **媒体资源存储桶**：用户头像、工作区标志以及其他媒体资源  
- **SBOM存储桶**：软件物料清单文件  
- **文档存储桶**：各类文档资料（规格书、手册、报告、合规文件等）  
  - 若未单独配置，文档将自动使用SBOM存储桶  
  - 在生产环境中，建议使用独立的存储桶以实现更好的组织管理与访问控制

您可以通过以下地址访问 Minio 控制台：

- `http://localhost:9001`
- 默认凭据：minioadmin/minioadmin

##### 生产环境存储配置

在正式生产环境中，您可以分别为文档配置独立的 S3 存储桶：

```bash
# 可选：配置专用的文档存储桶（生产环境推荐）
export AWS_DOCUMENTS_ACCESS_KEY_ID="your-documents-access-key"
export AWS_DOCUMENTS_SECRET_ACCESS_KEY="your-documents-secret-key"
export AWS_DOCUMENTS_STORAGE_BUCKET_NAME="your-documents-bucket"
export AWS_DOCUMENTS_STORAGE_BUCKET_URL="https://your-documents-bucket.s3.region.amazonaws.com"

# 若未进行配置，文档将自动使用 SBOMs 存储桶
export AWS_SBOMS_ACCESS_KEY_ID="your-sboms-access-key"
export AWS_SBOMS_SECRET_ACCESS_KEY="your-sboms-secret-key"
export AWS_SBOMS_STORAGE_BUCKET_NAME="your-sboms-bucket"
export AWS_SBOMS_STORAGE_BUCKET_URL="https://your-sboms-bucket.s3.region.amazonaws.com"
```

使用独立存储桶的优势：

- **安全性**：SBOM与文档采用不同的访问策略  
- **管理有序**：各类内容实现清晰分离  
- **备份便捷**：不同类型的数据拥有独立的备份方案

#### Dependency Track 集成

sbomify 支持与 [Dependency Track](https://dependencytrack.org/) 集成，以实现更高级的漏洞管理与分析功能。该集成功能适用于 Business 和 Enterprise 套餐。

**注意：** Dependency Track仅支持CycloneDX格式的SBOM。无论工作空间配置如何，SPDX格式的SBOM都将自动使用OSV进行扫描。

##### 基于环境的项目命名

当在多个环境（开发、测试、生产）中共享同一个 Dependency Track 实例时，sbomify 会自动在项目名称前加上环境标识，以便区分这些项目。

**示例：**

- **生产环境**（`https://app.sbomify.com`）：`prod-sbomify-{component-id}`  
- **测试环境**（`https://staging.sbomify.com`）：`staging-sbomify-{component-id}`  
- **开发环境**（`https://dev.sbomify.com`）：`dev-sbomify-{component-id}`  
- **本地环境**（`http://localhost:8000`）：`local-sbomify-{component-id}`

**自定义环境前缀：**
您可以通过设置 `DT_ENVIRONMENT_PREFIX` 环境变量来覆盖自动检测的结果。

```bash
export DT_ENVIRONMENT_PREFIX="my-custom-env"
# 最终生成的项目名称格式为：my-custom-env-sbomify-{component-id}
```

这样一来，在查看 Dependency Track 仪表板时，就能轻松判断出某个项目属于哪个环境。

##### 所需权限

若要与 Dependency Track 集成，您需要创建一个具备以下权限的 API 令牌：

- `BOM_UPLOAD`：BOM上传
- `PROJECT_CREATION_UPLOAD`：项目创建上传
- `VIEW_PORTFOLIO`：查看作品集
- `VIEW_VULNERABILITY`：查看漏洞信息

您可以在 Dependency Track 实例的 **Administration → Access Management** 页面中创建令牌（使用该处的工作空间管理界面）。

##### DT 配置

1. 通过 Django 管理界面**添加 Dependency Track 服务器**：
   - 进入 `/admin/vulnerability_scanning/dependencytrackserver/` 页面
   - 点击“Add Dependency Track Server”
   - 填写服务器详细信息：
     - **名称**：服务器的友好名称
     - **URL**：您的 Dependency Track 实例的基地址
     - **API 密钥**：具备所需权限的令牌
     - **优先级**：数值越低，负载均衡时的优先级越高
     - **最大并发扫描数**：同时进行的 SBOM 上传的最大数量

2. **配置工作区设置**：
   - 商业/企业级工作区可在**设置 → 集成**中选择Dependency Track
   - 企业级工作区还可根据需要配置自定义的Dependency Track实例
   - 商业级工作区则使用共享的服务器池

##### Dependency Track功能

- **自动漏洞扫描**：
  - 社区版工作空间：使用 OSV 每周进行一次漏洞扫描
  - 商业版/企业版工作空间：使用 Dependency Track 每 12 小时更新一次漏洞信息
- **负载均衡**：在多台 Dependency Track 服务器之间分配扫描任务
- **健康监控**：自动检测服务器运行状态并管理容量
- **历史追踪**：提供完整的扫描结果记录以用于趋势分析
- **统一结果**：确保 OSV 和 Dependency Track 输出的漏洞数据格式一致

### 运行测试用例

在运行测试之前，您需要先启动 docker-compose.tests.yml：

```bash
docker compose -f docker-compose.tests.yml up -d
```

使用 Django 的测试配置运行测试：

```bash
# 运行所有测试并统计代码覆盖率
uv run coverage run -m pytest

# 运行特定的测试组
uv run coverage run -m pytest core/tests/
uv run coverage run -m pytest sboms/tests/
uv run coverage run -m pytest teams/tests/

# 出现错误时启用调试器运行
uv run coverage run -m pytest --pdb -x -s

# 生成代码覆盖率报告
uv run coverage report
```

测试覆盖率必须达到至少80%，才能通过CI检查。

### 端到端快照（截图）测试

该项目包含端到端快照测试，这类测试会截取界面截图并将其与基准图片进行比对，从而确保在不同屏幕尺寸以及代码变更后界面的视觉一致性。

#### E2E 测试的先决条件

在运行端到端截图测试之前，你需要：

**构建 JavaScript 资产：**

```bash
bun run build
```

这样可以确保在截取屏幕截图之前，所有的静态资源（JavaScript、CSS）都已是最新的版本。

#### 编写快照测试

以下是编写快照测试的一个简化示例：

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
        # 导航到需要测试的页面
        authenticated_page.goto("/your-page")
        authenticated_page.wait_for_load_state("networkidle")

        # 获取或创建基准截图（存储在 __snapshots__ 中）
        baseline = snapshot.get_or_create_baseline_screenshot(authenticated_page, width=width)

        # 截取当前屏幕截图
        current = snapshot.take_screenshot(authenticated_page, width=width)

        # 比较两张截图
        snapshot.assert_screenshot(baseline.as_posix(), current.as_posix())
```

**核心组件：**

- 使用 `@pytest.mark.django_db` 来启用数据库访问功能  
- 使用 `@pytest.mark.parametrize("width", [...])` 来测试多种屏幕尺寸  
- 注入 `authenticated_page` 固定装置以实现浏览器自动化操作  
- 注入 `snapshot` 固定装置以进行截图管理  
- 调用 `get_or_create_baseline_screenshot()` 方法获取基准截图（若不存在则创建）  
- 调用 `take_screenshot()` 方法截取当前页面状态  
- 调用 `assert_screenshot()` 方法对比两者是否一致

#### 运行端到端截图测试

在构建完资源文件后，您可以使用专用的 E2E docker-compose 测试环境来运行截图测试：

```bash
# 启动测试环境栈（包含数据库、Chromium 浏览器及测试容器）
docker compose -f docker-compose.tests.yml up -d

# 在测试容器内运行所有端到端截图测试
docker compose -f docker-compose.tests.yml exec tests uv run pytest sbomify/apps/<APP>/tests/e2e/

# 运行单个端到端截图测试（示例）
docker compose -f docker-compose.tests.yml exec tests uv run pytest \
  sbomify/apps/<APP>/tests/e2e/test_your_page.py::TestYourPageSnapshot::test_your_page_snapshot[1920]
```

#### 使用快照测试

**新测试**
当您编写新的快照测试时，系统会自动在 `__snapshots__` 目录（位于 `sbomify/apps/<APP_NAME>/tests/e2e/__snapshots__/`）中生成基准截图。只需运行该测试，然后确认生成的截图显示正常即可。

**现有测试 - 通过**
如果该测试已存在且通过，则一切运行正常，无需采取任何操作。

**现有测试 - 失败**
如果测试失败，请查看 `__diffs__` 目录（位于 `sbomify/apps/<APP_NAME>/tests/e2e/__diffs__/`），以了解发生了哪些变化。差分图片会显示基准截图与当前截图之间的差异。

**更新过时的快照**
如果 `__diffs__` 目录中的差异截图显示新的视觉状态是正确的（即基准快照已过时），则需更新该基准快照：

1. 从 `__snapshots__` 中删除过期的快照文件。
2. 重新运行测试——它将自动使用当前状态创建新的基准截图。

**示例：**

```bash
# 删除过期的快照
rm sbomify/apps/<APP_NAME>/tests/e2e/__snapshots__/test_your_page_snapshot[1920].jpg

# 重新运行测试以生成新的基准截图
uv run pytest sbomify/apps/<APP_NAME>/tests/e2e/test_your_page.py::TestYourPageSnapshot::test_your_page_snapshot
```

如需实际示例，请查看 `sbomify/apps/core/tests/e2e/test_dashboard.py`。

### 测试数据管理

该应用提供了管理命令，可帮助你在开发环境中搭建及管理测试数据：

```bash
# 使用示例 SBOM 数据创建测试环境
# 如果未指定工作空间，则会使用数据库中的第一个工作空间
#（为保持兼容性，该管理命令仍沿用了旧版的 --team-id 标志名称）
python manage.py create_test_sbom_environment

# 为特定工作空间创建测试环境（仍使用旧版的 --team-id 标志）
python manage.py create_test_sbom_environment --team-id=your_team_id

# 清理现有测试数据并创建全新环境
python manage.py create_test_sbom_environment --clean

# 清理所有工作空间中的所有测试数据
python manage.py cleanup_test_sbom_environment

# 清理特定工作空间的测试数据（仍使用旧版的 --team-id 标志）
python manage.py cleanup_test_sbom_environment --team-id=your_team_id

# 预览将要被删除的内容（模拟运行）
python manage.py cleanup_test_sbom_environment --dry-run
```

这些命令将：

1. 创建测试产品与组件
2. 从测试文件中加载真实的 SBOM 数据（包括 SPDX 和 CycloneDX 格式）
3. 建立所有实体之间的正确关联
4. 允许在需要时清理测试数据

测试数据是按来源（例如 hello-world 和 sbomify）而非格式进行分类的，因此每个组件都会同时关联 SPDX 和 CycloneDX 格式的 SBOM。

注意：若要在不指定旧版 `--team-id` 参数的情况下使用这些命令，数据库中必须至少存在一个工作空间。

### JS 构建工具

对于前端 JS 开发工作，需要配置相应的 JS 工具链。

#### Bun 工具

```bash
curl -fsSL https://bun.sh/install | bash
```

在与 `package.json` 同级的项目文件夹中：

```bash
bun install
```

#### 代码检查

针对 JavaScript/TypeScript 的代码检查：

```bash
# 检查代码格式问题（用于持续集成，也可本地运行）
bun lint

# 自动修复代码格式问题（仅限本地开发）
bun lint-fix
```

#### 运行 Vite 开发服务器

```bash
bun run dev
```

### pre-commit 检查

该项目通过预提交钩子来确保代码的质量与一致性。这些钩子会检查：

- 代码格式化（ruff-format）
- Python 代码检查（ruff）
- 安全问题检测（bandit）
- Markdown 格式化
- TypeScript 类型检查
- JavaScript/TypeScript 代码检查
- 合并冲突
- 调试语句

要配置预提交检查：

- 安装 pre-commit 钩子：

```bash
uv run pre-commit install
```

- 手动运行预提交检查：

```bash
# 检查所有文件
uv run pre-commit run --all-files

# 仅检查已暂存文件
uv run pre-commit run
```

## 生产环境部署

### 生产环境前置条件

- Docker 及 Docker Compose  
- 兼容 S3 的存储服务（如 Amazon S3 或 Google Cloud Storage）  
- PostgreSQL 数据库  
- 用于生产环境部署的反向代理（例如 Nginx）

### Docker Compose 配置

有一个 `docker-compose.prod.yml` 文件可用于模拟生产环境的环境配置。**注意：**该配置尚未经过全面测试，不建议直接在真实的生产环境中使用。目前提供的设置仅用于演示和预发布阶段，未来将会进行更新与优化。

在正式生产环境部署时，需为签名 URL 生成安全的签名盐值：

```bash
# 为签名 URL 生成安全的签名盐值
export SIGNED_URL_SALT="$(openssl rand -hex 32)"
```

`SIGNED_URL_SALT` 用于对产品 SBOM 中私有组件的下载 URL 进行签名。

要体验类似生产环境的架构：

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml build
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

您需要设置合适的环境变量，并确保您的反向代理、存储及数据库都经过安全配置。

> **警告：** 不要直接将提供的生产环境 Docker Compose 配置用于实际部署。在实际使用前，请仔细检查并强化所有设置、敏感信息以及网络暴露风险。
