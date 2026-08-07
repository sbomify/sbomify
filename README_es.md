<!-- hy-mt2-i18n:start -->
[English](./README.md) | [中文](./README_zh-CN.md) | [日本語](./README_ja.md) | **Español**
<!-- hy-mt2-i18n:end -->

[![Logotipo de sbomify](https://sbomify/static/img/sbomify.svg)](https://app.sbomify.com/public/product/eP_4dk8ixV/)

[![sbomified](https://sbomify.com/assets/images/logo/badge.svg)](https://app.sbomify.com/public/product/eP_4dk8ixV/)
[![OpenSSF Scorecard](https://api.securityscorecards.dev/projects/github.com/sbomify/sbomify/badge)](https://securityscorecards.dev/viewer/?uri=github.com/sbomify/sbomify&sort_by=check-score&sort_direction=desc)
[![OpenSSF Best Practices](https://www.bestpractices.dev/projects/10952/badge)](https://www.bestpractices.dev/projects/10952)
[![Slack](https://img.shields.io/badge/Slack-Join%20Community-4A154B?logo=slack)](https://join.slack.com/t/sbomify/shared_invite/zt-3na54pa1f-MXrFWhotmZr0YxXc8sABTw)
[![CI/CD Pipeline](https://github.com/sbomify/sbomify/actions/workflows/ci-cd.yml/badge.svg)](https://github.com/sbomify/sbomify/actions/workflows/ci-cd.yml)
[![OpenGrep](https://github.com/sbomify/sbomify/actions/workflows/opengrep.yaml/badge.svg)](https://github.com/sbomify/sbomify/actions/workflows/opengrep.yaml)

SBOMify es una plataforma de gestión de listas de materiales de software (SBOM) y documentos que puede alojarse de forma propia o accederse a través de [app.sbomify.com](https://app.sbomify.com). La plataforma ofrece un lugar centralizado para cargar y gestionar los SBOM y la documentación relacionada, lo que permite compartirlos con las partes interesadas o hacerlos accesibles al público.

El backend de sbomify se integra con nuestro [módulo GitHub Actions](https://github.com/sbomify/sbomify-action) para generar automáticamente SBOMs a partir de archivos lock y archivos Docker.

Para obtener más información, visite [sbomify.com](https://sbomify.com).

## Funciones

### Gestión de SBOM

- Soporte para los formatos de SBOM CycloneDX y SPDX (incluido SPDX 3.0)  
- Carga de SBOMs a través de la interfaz web o la API  
- Generación de SBOMs agregados para productos y versiones en múltiples formatos:  
  - CycloneDX 1.6, 1.7  
  - SPDX 2.3, 3.0  
- Integración con análisis de vulnerabilidades  
- Controles de acceso público y privado  
- Organización basada en espacios de trabajo

### Plugins de cumplimiento normativo

| Plugin                                  | Type        | Standard                                                                                                                                         |
| --------------------------------------- | ----------- | ------------------------------------------------------------------------------------------------------------------------------------------------ |
| NTIA Minimum Elements (2021)            | Compliance  | [NTIA Minimum Elements for SBOM](https://www.ntia.gov/report/2021/minimum-elements-software-bill-materials-sbom)                                 |
| CISA Minimum Elements (2025 Draft)      | Compliance  | [CISA 2025 SBOM Minimum Elements](https://www.cisa.gov/sites/default/files/2025-08/2025_CISA_SBOM_Minimum_Elements.pdf) _(Public Comment Draft)_ |
| BSI TR-03183-2 v2.1 (EU CRA)            | Compliance  | [BSI TR-03183-2: Cyber Resilience Requirements](https://bsi.bund.de/dok/TR-03183-en)                                                             |
| FDA Medical Device Cybersecurity (2025) | Compliance  | [FDA Cybersecurity in Medical Devices](https://www.fda.gov/media/119933/download)                                                                |
| GitHub Artifact Attestation             | Attestation | [GitHub Artifact Attestations](https://docs.github.com/en/actions/security-for-github-actions/using-artifact-attestations)                       |

### Gestión de documentos

- Subir y gestionar artefactos de documentos (especificaciones, manuales, informes, documentos de cumplimiento, etc.)  
- Asociar documentos con componentes de software  
- Control de versiones para documentos  
- Almacenamiento seguro mediante buckets S3 configurables  
- Compartición de documentos públicos y privados

### Organización

- **Componentes**: Entidades principales que pueden contener SBOM o documentos.  
- **Productos**: Agrupan componentes relacionados (y representan lo que se vende o distribuye).  
- **Versiones**: Capturas versionadas de los componentes de un producto.  
- **Espacios de trabajo**: Controlan el acceso y los permisos.

### API de Intercambio de Transparencia (TEA)

- Implementa la [Transparency Exchange API](https://github.com/CycloneDX/transparency-exchange-api/) v0.3.0-beta.2  
- Descubrimiento estandarizado de SBOM mediante los puntos de conexión `.well-known/tea`  
- Permite el descubrimiento y recuperación automática de SBOM en toda la cadena de suministro

## Registros de Decisiones Arquitectónicas (ADRs)

Utilizamos los registros de decisiones arquitectónicas (ADRs) para documentar las decisiones arquitectónicas importantes tomadas en este proyecto. Los ADR proporcionan el contexto y las razones detrás de dichas decisiones, lo que ayuda a los colaboradores actuales y futuros a comprender por qué se eligieron ciertos enfoques.

Para ver todos los ADR, consulte la carpeta [docs/ADR](docs/ADR).

## Despliegue

Para obtener información detallada sobre el proceso de despliegue, incluyendo:

- Flujo de trabajo CI/CD
- Configuración del entorno
- Configuración del almacenamiento

Consulte [docs/deployment.md](docs/deployment.md).

Para obtener instrucciones completas sobre el despliegue en producción, consulte [la guía de despliegue](docs/deployment.md).

## Desarrollo local

### Autenticación durante el desarrollo

Para el desarrollo local, la autenticación se gestiona a través de la interfaz de administración de Django:

```bash
# Crear un superusuario para el desarrollo local
docker compose \
    -f docker-compose.yml \
    -f docker-compose.dev.yml exec \
    sbomify-backend \
    uv run python manage.py createsuperuser
```

Luego, acceda a la interfaz de administración en `http://localhost:8000/admin` para iniciar sesión.

> **Nota**: Los entornos de producción utilizan métodos de autenticación diferentes. Consulte [docs/deployment.md](docs/deployment.md) para conocer la configuración de autenticación en entornos de producción.

### Requisitos previos para el desarrollo

- Python 3.13+  
- uv (gestor de paquetes de Python)  
- Docker (para ejecutar PostgreSQL y Minio)  
- Bun (para el desarrollo en JavaScript)

#### Instalación de uv

- Instalar uv con el instalador oficial:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

- Verificar la instalación:

```bash
uv --version
```

#### Instalación de dependencias

- Instalar las dependencias de Python con uv:

```bash
# Instalar todas las dependencias, incluidas las de desarrollo
uv sync

# Ejecutar comandos con uv
uv run python manage.py --help
```

- Instalar dependencias de JavaScript con Bun:

```bash
bun install
```

### Documentación de la API

La documentación de la API está disponible en:

- Documentación interactiva de la API (Swagger UI): `http://localhost:8000/api/v1/docs`
- Especificación OpenAPI: `http://localhost:8000/api/v1/openapi.json`

La API ofrece puntos de conexión para gestionar:

- **SBOMs**: Subir, recuperar y gestionar la lista de materiales de software.  
- **Documentos**: Subir, recuperar y gestionar archivos documentales.  
- **Componentes**: Gestionar los componentes que contienen SBOMs o documentos.  
- **Productos**: Organizar y agrupar componentes.  
- **Espacios de trabajo**: Gestión de usuarios y control de acceso.

#### Descargas de SBOM agregadas

Descargar SBOMs agregados para productos y versiones con selección de formato:

```bash
# Descargar la SBOM de la versión en CycloneDX 1.6 (valor predeterminado)
curl "https://app.sbomify.com/api/v1/releases/{release_id}/download"

# Descargar la SBOM de la versión en SPDX 2.3
curl "https://app.sbomify.com/api/v1/releases/{release_id}/download?format=spdx"

# Descargar la SBOM de la versión en SPDX 3.0
curl "https://app.sbomify.com/api/v1/releases/{release_id}/download?format=spdx&version=3.0"

# Descargar la SBOM de la versión en CycloneDX 1.7
curl "https://app.sbomify.com/api/v1/releases/{release_id}/download?format=cyclonedx&version=1.7"

# Descargar la SBOM del producto en SPDX 2.3
curl "https://app.sbomify.com/api/v1/products/{product_id}/download?format=spdx&version=2.3"
```

**Formatos y versiones compatibles:**

| Formato    | Versiones | Predeterminado |
| --------- | -------- | -------------- |
| CycloneDX | 1.6, 1.7 | 1.6           |
| SPDX      | 2.3, 3.0 | 2.3           |

Estos puntos de conexión están disponibles al ejecutar el servidor de desarrollo.

### Configuración

Configure las variables de entorno estableciéndolas en su shell o utilizando archivos de sobrescritura de Docker Compose.

**Importante: Añada esto a `/etc/hosts`**

Para que el entorno de desarrollo funcione correctamente con la autenticación de Keycloak, debe agregar la siguiente entrada al archivo `/etc/hosts`:

```bash
127.0.0.1   keycloak
```

Iniciar el entorno de desarrollo (método recomendado):

```bash
./bin/developer_mode.sh build
./bin/developer_mode.sh up
```

Crear una cuenta de administrador local:

```bash
docker compose \
    -f docker-compose.yml \
    -f docker-compose.dev.yml exec \
    -e DJANGO_SUPERUSER_USERNAME=sbomifyadmin \
    -e DJANGO_SUPERUSER_PASSWORD=sbomifyadmin \
    -e DJANGO SUPERUSER_EMAIL=admin@sbomify.com \
    sbomify-backend \
    uv run python manage.py createsuperuser --noinput
```

Acceder a la aplicación:

- Interfaz de administración: `http://localhost:8000/admin`
- Aplicación principal: `http://localhost:8000`

> **Nota**: Para obtener información sobre el despliegue en producción, consulte [docs/deployment.md](docs/deployment.md).

#### Opción alternativa: Ejecutar localmente (sin Docker para Django)

- Iniciar los servicios necesarios en Docker:

```bash
# Iniciar PostgreSQL y MinIO al mismo tiempo
docker compose up sbomify-db sbomify-minio sbomify-createbuckets -d
```

- Instalar dependencias:

```bash
uv sync
bun install  # para las dependencias de JavaScript
```

- Ejecutar migraciones:

```bash
uv run python manage.py migrate
```

- Iniciar los servidores de desarrollo:

```bash
# En una terminal, inicie Django
uv run python manage.py runserver

# En otra terminal, inicie Vite
bun run dev
```

### Configuración

#### Configuración del servidor de desarrollo

La aplicación utiliza Vite para el desarrollo en JavaScript. Las siguientes variables de entorno controlan los servidores de desarrollo:

```bash
# Configuración de desarrollo de Vite
DJANGO_VITE_DEV_MODE=True
DJANGO_VITE_DEV_SERVER_PORT=5170
DJANGO_VITE_DEV_SERVER_HOST=http://localhost

# Configuración del servidor estático y de desarrollo
STATIC_URL=/static/
DEV_JS_SERVER=http://127.0.0.1:5170
WEBSITE_BASE_URL=http://127.0.0.1:8000
VITE_API_BASE_URL=http://127.0.0.1:8000
VITE_WEBSITE_BASE_URL=http://127.0.0.1:8000
```

Estos parámetros se pueden configurar mediante variables de entorno.

#### Configuración de autenticación de Keycloak

Ahora, Keycloak se gestiona como parte del entorno Docker Compose. No es necesario ejecutar Keycloak manualmente.

El almacenamiento persistente de Keycloak es gestionado por Docker mediante un volumen nombrado (`keycloak_data`).

##### Arranque automático de Keycloak

Al iniciar el entorno de desarrollo con Docker Compose, Keycloak se inicializa automáticamente mediante el script ubicado en `bin/keycloak-bootstrap.sh`. Este script utiliza variables de entorno (como `KEYCLOAK_REALM`, `KEYCLOAK_CLIENT_ID`, `KEYCLOAK_ADMIN_USERNAME`, `KEYCLOAK_ADMIN_PASSWORD`, `KEYCLOAK_CLIENT_SECRET`, etc.) para configurar el reino, el cliente y las credenciales. **No es necesario editar el script en sí**; basta con establecer las variables de entorno adecuadas en la configuración de Docker Compose para controlar el proceso de inicialización.

Al ejecutarse en modo de desarrollo (usando `docker-compose.dev.yml`), el script de arranque automáticamente:

- **Desactiva los requisitos de SSL** para facilitar el desarrollo local.  
- **Crea usuarios de prueba** para las pruebas de autenticación:  
  - **John Doe** - Nombre de usuario: `jdoe`, Contraseña: `foobar123`, Correo electrónico: `jdoe@example.com`  
  - **Steve Smith** - Nombre de usuario: `ssmith`, Contraseña: `foobar123`, Correo electrónico: `ssmith@example.com`

Estas configuraciones específicas para el desarrollo están controladas por la variable de entorno `KEYCLOAK_DEV_MODE` y solo se aplican al ejecutar la pila Docker Compose para desarrollo.

Para iniciar Keycloak (y todos los demás servicios) en modo de desarrollo, basta con ejecutar:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up
```

Keycloak estará disponible en <http://keycloak:8080/>.

#### Almacenamiento S3/Minio

La aplicación utiliza almacenamiento compatible con S3 para guardar archivos y recursos. En entornos de desarrollo, empleamos Minio como sustituto local de S3.

- Al ejecutar con Docker Compose, todo se configura automáticamente.  
- Al ejecutar localmente (Django fuera de Docker):  
  - Asegúrese de que Minio esté en ejecución mediante Docker:  
    `docker compose up sbomify-minio sbomify-createbuckets -d`  
  - Establezca `AWS_ENDPOINT_URL_S3=http://localhost:9000` en sus variables de entorno.  
  - Los buckets necesarios (`sbomify-media`, `sbomify-sboms` y, opcionalmente, `sbomify-documents`) se crearán automáticamente.

##### Contenedores de almacenamiento

La aplicación utiliza buckets S3 separados para diferentes tipos de contenido:

- **Bucket de medios**: Avatares de usuarios, logotipos de espacios de trabajo y otros recursos multimedia.  
- **Bucket de SBOMs**: Archivos de lista de materiales de software.  
- **Bucket de documentos**: Artefactos documentales (especificaciones, manuales, informes, documentos de cumplimiento, etc.).  
  - Si no se configura un bucket separado, los documentos utilizarán automáticamente el bucket de SBOMs.  
  - En entornos de producción, se recomienda usar un bucket dedicado para una mejor organización y control de acceso.

Puede acceder a la consola de Minio en:

- `http://localhost:9001`
- Credenciales predeterminadas: minioadmin/minioadmin

##### Configuración de almacenamiento para entornos de producción

En las implementaciones de producción, puede configurar buckets S3 separados para los documentos:

```bash
# Opcional: Configurar un bucket dedicado para documentos (recomendado para entornos de producción)
export AWS_DOCUMENTS_ACCESS_KEY_ID="tu-clave-de-acceso-para-documentos"
export AWS_DOCUMENTS_SECRET_ACCESS_KEY="tu-clave-secreta-para-documentos"
export AWS_DOCUMENTS_STORAGE_BUCKET_NAME="tu-bucket-de-documentos"
export AWS_DOCUMENTS_STORAGE_BUCKET_URL="https://tu-bucket-de-documentos.s3.region.amazonaws.com"

# Si no se configura, los documentos utilizarán automáticamente el bucket SBOMs
export AWS_SBOMS_ACCESS_KEY_ID="tu-clave-de-acceso-para-SBOMs"
export AWS_SBOMS_SECRET_ACCESS_KEY="tu-clave-secreta-para-SBOMs"
export AWS_SBOMS_STORAGE_BUCKET_NAME="tu-bucket-de-SBOMs"
export AWS_SBOMS_STORAGE_BUCKET_URL="https://tu-bucket-de-SBOMs.s3.region.amazonaws.com"
```

Beneficios de utilizar buckets separados:

- **Seguridad**: Políticas de acceso distintas para los SBOMs y los documentos.  
- **Organización**: Separación clara entre los diferentes tipos de contenido.  
- **Copias de seguridad**: Estrategias independientes de copia de seguridad para cada tipo de dato.

#### Integración con Dependency Track

sbomify admite la integración con [Dependency Track](https://dependencytrack.org/) para una gestión y análisis avanzado de vulnerabilidades. La integración con Dependency Track está disponible en los planes Business y Enterprise.

**Nota:** Dependency Track solo admite SBOM en formato CycloneDX. Los SBOM de tipo SPDX utilizarán automáticamente el escaneo OSV, independientemente de la configuración del espacio de trabajo.

##### Nombrado de proyectos según el entorno

Al utilizar una instancia compartida de Dependency Track en varios entornos (desarrollo, pruebas, producción), sbomify agrega automáticamente un prefijo con el nombre del entorno a los nombres de los proyectos para ayudar a diferenciarlos:

**Ejemplos:**

- **Producción** (`https://app.sbomify.com`): `prod-sbomify-{component-id}`
- **Pruebas** (`https://staging.sbomify.com`): `staging-sbomify-{component-id}`
- **Desarrollo** (`https://dev.sbomify.com`): `dev-sbomify-{component-id}`
- **Local** (`http://localhost:8000`): `local-sbomify-{component-id}`

**Prefijo personalizado del entorno:**
Puede anular la detección automática estableciendo la variable de entorno `DT_ENVIRONMENT_PREFIX`:

```bash
export DT_ENVIRONMENT_PREFIX="mi-entorno-personalizado"
# El resultado será: mi-entorno-personalizado-sbomify-{component-id}
```

Esto facilita la identificación del entorno al que pertenece un proyecto al visualizar el panel de control de Dependency Track.

##### Permisos requeridos

Para integrarse con Dependency Track, es necesario crear un token de API con los siguientes permisos:

- `BOM_UPLOAD`
- `PROJECT_CREATION_UPLOAD`
- `VIEW_PORTFOLIO`
- `VIEW_VULNERABILITY`

Puede crear un token en **Administración → Gestión de accesos** de su instancia de Dependency Track (utilizando la interfaz de gestión de espacios de trabajo allí).

##### Configuración de DT

1. **Añadir servidor de Dependency Track** mediante la interfaz administrativa de Django:
   - Vaya a `/admin/vulnerability_scanning/dependencytrackserver/`
   - Haga clic en “Añadir servidor de Dependency Track”
   - Complete los detalles del servidor:
     - **Nombre**: Nombre amigable para el servidor
     - **URL**: URL base de su instancia de Dependency Track
     - **API Key**: Token con los permisos requeridos
     - **Prioridad**: Números más bajos = mayor prioridad para el equilibrio de carga
     - **Max Concurrent Scans**: Número máximo de cargas simultáneas de SBOM

2. **Configurar opciones del espacio de trabajo**:
   - Los espacios de trabajo de tipo Business/Enterprise pueden seleccionar Dependency Track en **Settings → Integrations**
   - Los espacios de trabajo de tipo Enterprise pueden configurar, de forma opcional, instancias personalizadas de Dependency Track
   - Los espacios de trabajo de tipo Business utilizan el conjunto compartido de servidores

##### Funciones de DT

- **Escaneo automático de vulnerabilidades**:
  - Espacios de trabajo comunitarios: Escaneos semanales de vulnerabilidades mediante OSV
  - Espacios de trabajo empresariales: Actualizaciones de vulnerabilidades cada 12 horas usando Dependency Track
- **Equilibrio de carga**: Distribución de los escaneos entre varios servidores de Dependency Track
- **Monitoreo del estado**: Verificaciones automáticas del estado de los servidores y gestión de capacidad
- **Seguimiento histórico**: Historial completo de los resultados de los escaneos para el análisis de tendencias
- **Resultados unificados**: Formato consistente de datos de vulnerabilidades tanto en OSV como en Dependency Track

### Ejecución de casos de prueba

Antes de ejecutar las pruebas, es necesario levantar el contenedor de docker-compose.tests.yml:

```bash
docker compose -f docker-compose.tests.yml up -d
```

Ejecutar las pruebas utilizando el perfil de pruebas de Django:

```bash
# Ejecutar todas las pruebas con medición de cobertura
uv run coverage run -m pytest

# Ejecutar grupos específicos de pruebas
uv run coverage run -m pytest core/tests/
uv run coverage run -m pytest sboms/tests/
uv run coverage run -m pytest teams/tests/

# Ejecutar con depurador en caso de error
uv run coverage run -m pytest --pdb -x -s

# Generar el informe de cobertura
uv run coverage report
```

El porcentaje de cobertura de pruebas debe ser de al menos el 80 % para superar las verificaciones de CI.

### Pruebas de captura de pantalla (E2E)

El proyecto incluye pruebas de captura de pantalla de tipo end-to-end que toman capturas de la interfaz de usuario y las comparan con imágenes de referencia. Esto ayuda a garantizar la consistencia visual en diferentes tamaños de pantalla y después de realizar cambios en el código.

#### Requisitos previos para las pruebas E2E

Antes de ejecutar las pruebas de captura de pantalla de tipo E2E, es necesario:

**Compilar recursos JavaScript:**

```bash
bun run build
```

Esto garantiza que todos los recursos estáticos (JavaScript, CSS) estén actualizados antes de tomar las capturas de pantalla.

#### Cómo escribir pruebas de captura de pantalla

Aquí hay un ejemplo simplificado de cómo escribir una prueba de captura de pantalla:

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
        # Navegar a la página que se desea probar
        authenticated_page.goto("/your-page")
        authenticated_page.wait_for_load_state("networkidle")

        # Obtener o crear la captura de pantalla de referencia (almacenada en __snapshots__)
        baseline = snapshot.get_or_create_baseline_screenshot(authenticated_page, width=width)

        # Tomar la captura de pantalla actual
        current = snapshot.take_screenshot(authenticated_page, width=width)

        # Comparar las capturas de pantalla
        snapshot.assert_screenshot(baseline.as_posix(), current.as_posix())
```

**Componentes clave:**

- Utilice `@pytest.mark.django_db` para habilitar el acceso a la base de datos.  
- Utilice `@pytest.mark.parametrize("width", [...])` para probar múltiples tamaños de pantalla.  
- Inyecte el fixture `authenticated_page` para la automatización del navegador.  
- Inyecte el fixture `snapshot` para la gestión de capturas de pantalla.  
- Utilice `get_or_create_baseline_screenshot()` para obtener la imagen de referencia (creándola si no está disponible).  
- Utilice `take_screenshot()` para capturar el estado actual.  
- Utilice `assert_screenshot()` para compararlas.

#### Ejecución de pruebas de captura de pantalla E2E

Después de compilar los recursos, puede utilizar la pila dedicada E2E de docker-compose para ejecutar las pruebas de captura de pantalla:

```bash
# Iniciar la pila de pruebas (contenedor de base de datos, Chromium y pruebas)
docker compose -f docker-compose.tests.yml up -d

# Ejecutar todas las pruebas de captura de pantalla E2E dentro del contenedor de pruebas
docker compose -f docker-compose.tests.yml exec tests uv run pytest sbomify/apps/<APP>/tests/e2e/

# Ejecutar una sola prueba de captura de pantalla E2E (ejemplo)
docker compose -f docker-compose.tests.yml exec tests uv run pytest \
  sbomify/apps/<APP>/tests/e2e/test_your_page.py::TestYourPageSnapshot::test_your_page_snapshot[1920]
```

#### Trabajar con pruebas de captura de estado

**Pruebas nuevas**
Cuando escriba una nueva prueba de captura de estado, se crearán automáticamente capturas de referencia en el directorio `__snapshots__` (ubicado en `sbomify/apps/<APP_NAME>/tests/e2e/__snapshots__/`). Simplemente ejecute la prueba y verifique que las capturas generadas se vean correctas.

**Tests existentes: que pasan**  
Si la prueba ya existe y pasa, todo funciona como se esperaba. No es necesario tomar ninguna acción.

**Pruebas existentes: fallidas**
Si una prueba falla, revise el directorio `__diffs__` (ubicado en `sbomify/apps/<APP_NAME>/tests/e2e/__diffs__/`) para ver qué cambió. Las imágenes de diferencias muestran las diferencias entre la captura de pantalla de referencia y la actual.

**Actualización de snapshots obsoletos**  
Si la captura de pantalla de diferencias en `__diffs__` muestra que el nuevo estado visual es correcto (es decir, que el snapshot de referencia está obsoleto), es necesario actualizar la referencia:

1. Elimine el archivo de snapshot obsoleto de `__snapshots__`.  
2. Ejecute nuevamente la prueba; esta creará automáticamente una nueva captura de pantalla como referencia con el estado actual.

**Ejemplo:**

```bash
# Eliminar la captura de pantalla obsoleta
rm sbomify/apps/<APP_NAME>/tests/e2e/__snapshots__/test_your_page_snapshot[1920].jpg

# Volver a ejecutar la prueba para crear una nueva línea base
uv run pytest sbomify/apps/<APP_NAME>/tests/e2e/test_your_page.py::TestYourPageSnapshot::test_your_page_snapshot
```

Para ver un ejemplo en entornos reales, consulte `sbomify/apps/core/tests/e2e/test_dashboard.py`.

### Gestión de datos de prueba

La aplicación incluye comandos de administración para ayudar a configurar y gestionar los datos de prueba en su entorno de desarrollo:

```bash
# Crear un entorno de prueba con datos SBOM de ejemplo
# Si no se especifica ningún espacio de trabajo, se utilizará el primero de la base de datos
# (la orden de gestión mantiene el nombre antiguo de la bandera --team-id por compatibilidad)
python manage.py create_test_sbom_environment

# Crear un entorno de prueba para un espacio de trabajo específico (todavía utiliza la bandera antigua --team-id)
python manage.py create_test_sbom_environment --team-id=your_team_id

# Limpiar los datos de prueba existentes y crear un entorno nuevo
python manage.py create_test_sbom_environment --clean

# Limpiar todos los datos de prueba de todos los espacios de trabajo
python manage.py cleanup_test_sbom_environment

# Limpiar los datos de prueba de un espacio de trabajo específico (todavía utiliza la bandera antigua --team-id)
python manage.py cleanup_test_sbom_environment --team-id=your_team_id

# Ver qué se eliminaría (ejecución en modo de prueba)
python manage.py cleanup_test_sbom_environment --dry-run
```

Estos comandos permitirán:

1. Crear productos y componentes de prueba  
2. Cargar datos reales de SBOM desde archivos de prueba (en formatos SPDX y CycloneDX)  
3. Establecer las relaciones adecuadas entre todas las entidades  
4. Permitir la limpieza de los datos de prueba cuando sea necesario

Los datos de prueba se agrupan por fuente (por ejemplo, hello-world y sbomify) en lugar de por formato, por lo que cada componente tendrá asociadas tanto SBOMs en formato SPDX como CycloneDX.

Nota: Es necesario que exista al menos un espacio de trabajo en la base de datos para poder utilizar estos comandos sin especificar la opción heredada `--team-id`.

### Herramientas de compilación para JS

Para el trabajo con JavaScript en el frontend, es necesario configurar las herramientas de JS.

#### Bun

```bash
curl -fsSL https://bun.sh/install | bash
```

En la carpeta del proyecto, al mismo nivel que `package.json`:

```bash
bun install
```

#### Revisión de formato del código

Para la revisión de estilo de JavaScript/TypeScript:

```bash
# Verificar problemas de formato (se utiliza en CI y se puede ejecutar localmente)
bun lint

# Corregir automáticamente los problemas de formato (solo para desarrollo local)
bun lint-fix
```

#### Ejecutar el servidor de desarrollo de Vite

```bash
bun run dev
```

#### Verificaciones de pre-commit

El proyecto utiliza ganchos de pre-commit para garantizar la calidad y coherencia del código. Estos ganchos verifican:

- Formateo de código (ruff-format)
- Linting de Python (ruff)
- Problemas de seguridad (bandit)
- Formateo de Markdown
- Verificación de tipos en TypeScript
- Linting de JavaScript/TypeScript
- Conflictos de fusión
- Instrucciones de depuración

Para configurar pre-commit:

- Instalar los ganchos de pre-commit:

```bash
uv run pre-commit install
```

- Ejecutar las comprobaciones de pre-commit manualmente:

```bash
# Verificar todos los archivos
uv run pre-commit run --all-files

# Verificar solo los archivos seleccionados
uv run pre-commit run
```

## Despliegue en producción

### Requisitos previos para producción

- Docker y Docker Compose  
- Almacenamiento compatible con S3 (como Amazon S3 o Google Cloud Storage)  
- Base de datos PostgreSQL  
- Proxy inverso (p. ej., Nginx) para despliegues en producción

### Configuración de Docker Compose

Existe un archivo `docker-compose.prod.yml` para configuraciones similares a las de producción. **Nota:** Esta configuración no ha sido probada completamente y no se recomienda utilizarla tal cual en entornos de producción reales. Los parámetros proporcionados son únicamente para fines de demostración y pruebas, y se actualizarán y mejorarán en el futuro.

Para las implementaciones en producción, genere una sal de firma segura para las URL firmadas:

```bash
# Generar una sal de firma segura para las URL firmadas
export SIGNED_URL_SALT="$(openssl rand -hex 32)"
```

El parámetro `SIGNED_URL_SALT` se utiliza para firmar las URL de descarga de los componentes privados en los SBOM de los productos.

Para probar un entorno similar al de producción:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml build
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

Será necesario configurar las variables de entorno adecuadas y asegurarse de que su proxy inverso, almacenamiento y base de datos estén configurados de forma segura.

> **Advertencia:** No utilice la configuración de Docker Compose para entornos de producción proporcionada tal cual en despliegues reales. Revise y refuerce todos los ajustes, datos confidenciales y puntos de exposición de red antes de emplearla en producción.
