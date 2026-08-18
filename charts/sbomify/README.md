# sbomify Helm chart

Deploys [sbomify](https://sbomify.com) on Kubernetes: SBOM and compliance
document management.

The chart deploys **the application only**: Caddy at the edge, a
gunicorn/uvicorn web tier, a pool of Dramatiq workers, a singleton cron
scheduler, and a migration step that runs before any of them serve traffic.
Static assets are served by WhiteNoise from inside the app, so there is no
separate static tier.

It does **not** deploy PostgreSQL, Redis, object storage or Keycloak. You point
it at ones you provide, and it refuses to render if you have not. See
*Backing services* below.

There is also **no Ingress and no ingress controller**. See *Why Caddy and not
an Ingress*.

## Quick start (local kind cluster)

```bash
./bin/kind-up.sh
```

That creates a three-node [kind](https://kind.sigs.k8s.io/) cluster, applies
[`deploy/local/dependencies.yaml`](../../deploy/local/dependencies.yaml),
throwaway PostgreSQL, Redis, MinIO and Keycloak for the laptop, and then
installs this chart with `values-local.yaml` pointed at them. Caddy issues its
own certificates from its internal CA, so there is nothing to pre-generate.

Note the local setup provisions the datastores *outside* the chart, exactly as
production does. There is no separate "all-in-one" code path to drift.

```text
sbomify   https://sbomify.localtest.me      (Caddy internal CA, so the browser warns)
Keycloak  http://keycloak.localtest.me      (admin / admin)
Logins    jdoe / foobar123, ssmith / foobar123
```

Tear it down with `./bin/kind-up.sh --down`.

## Production install

Provide the backing services first (see below), then:

```bash
helm install sbomify ./charts/sbomify \
  --namespace sbomify --create-namespace \
  --set app.baseUrl=https://sbom.example.com \
  --set database.host=pg.internal \
  --set database.password=... \
  --set redis.host=redis.internal \
  --set objectStorage.endpointUrl=https://fly.storage.tigris.dev \
  --set objectStorage.sboms.accessKeyId=... \
  --set objectStorage.sboms.secretAccessKey=... \
  --set objectStorage.media.accessKeyId=... \
  --set objectStorage.media.secretAccessKey=... \
  --set auth.keycloak.serverUrl=https://sso.example.com/ \
  --set auth.keycloak.clientSecret=... \
  --set secrets.secretKey="$(openssl rand -base64 48)" \
  --set secrets.signedUrlSalt="$(openssl rand -base64 32)" \
  --set caddy.acme.email=ops@example.com
```

On AWS you can drop the four storage credentials by setting
`objectStorage.useWorkloadIdentity=true`. See *Keyless object storage* below.

`secretKey` and `signedUrlSalt` are required. The chart will not invent them.
Losing them logs out every user and invalidates every signed URL, so generate
once and store them like any other credential (see *External secret managers*).

Then point DNS for your domain, and every workspace custom domain, at the
`-caddy` Service's external address.

In practice, put credentials in a Secret you manage (External Secrets, SOPS,
Vault) and reference it:

```yaml
secrets:
  existingSecret: sbomify-credentials
```

That Secret must provide `SECRET_KEY`, `SIGNED_URL_SALT`, `DATABASE_URL`,
`REDIS_URL`, `KEYCLOAK_CLIENT_SECRET`, and the four `AWS_{MEDIA,SBOMS}_*` keys.

## What the chart deploys

| Component | Kind | Notes |
| --- | --- | --- |
| `-web` | Deployment | gunicorn + uvicorn workers, behind Caddy |
| `-worker` | Deployment | `manage.py rundramatiq` |
| `-scheduler` | Deployment | `manage.py crontab`, pinned to 1 replica |
| `-migrations` | Job | `bin/release.py`. See *Migrations* below |
| `-caddy` | Deployment + Service | TLS termination, routing, on-demand certificates |

## Backing services

The chart requires four things to already exist. It does not stand them up:
stateful services have their own operational lifecycle (backups, restores,
failover, version upgrades, storage tuning), and coupling that to an application
release means every `helm upgrade` of the app is also a change window for the
database. Owning them separately also keeps the blast radius of a bad app
release away from your data.

| Service | Value | Suggested |
| --- | --- | --- |
| PostgreSQL 17 | `database.*` | A managed service (RDS, Cloud SQL, Neon), or the [CloudNativePG](https://cloudnative-pg.io/) operator in-cluster |
| Redis | `redis.*` | A managed service (ElastiCache, Upstash), or an operator |
| S3-compatible storage | `objectStorage.*` | S3, Cloudflare R2, Tigris, or a MinIO you operate |
| Keycloak | `auth.keycloak.*` | The [Keycloak Operator](https://www.keycloak.org/guides) |

On Keycloak: the project **deliberately does not publish an official Helm
chart**. The Operator is its official Kubernetes path. Community charts exist
(codecentric, Bitnami and others) if you prefer Helm, but they are not
maintained by the Keycloak project.

Two constraints worth knowing:

- **PostgreSQL and Redis must be reachable before `helm install`.** The
  migration hook runs before any ordinary resource in the release, so it cannot
  wait for something the same release would create. Every workload also has an
  init container that blocks until both answer, so a slow-starting service
  delays the rollout rather than crash-looping it.
- **`redis.host` must point at the server, not a database.** sbomify uses DB 0
  for cache, 1 for the task queue and 2 for websocket channels, and derives all
  three from this one endpoint.

## External secret managers

The chart never needs to own your secrets. Point it at a Secret something else
materialises: External Secrets Operator (Google Secret Manager, AWS Secrets
Manager, Azure Key Vault), the Vault Agent injector, vault-secrets-operator,
Sealed Secrets, or your platform's own tooling:

```yaml
secrets:
  existingSecret: sbomify-credentials
```

The chart only *reads* that Secret. It does not create, mutate or delete it, so
rotation stays entirely in your system's hands.

### Required keys

`SECRET_KEY`, `SIGNED_URL_SALT`, `DATABASE_URL`, `REDIS_URL` and
`KEYCLOAK_CLIENT_SECRET`, plus `AWS_MEDIA_ACCESS_KEY_ID`,
`AWS_MEDIA_SECRET_ACCESS_KEY`, `AWS_SBOMS_ACCESS_KEY_ID` and
`AWS_SBOMS_SECRET_ACCESS_KEY` unless `objectStorage.useWorkloadIdentity` is
set, in which case the chart neither reads nor injects them.

External stores rarely let you pick key names freely, so you do not have to
match these. Remap only what differs:

```yaml
secrets:
  existingSecret: sbomify-credentials
  keys:
    DATABASE_URL: db-connection-string
    SECRET_KEY: django-secret
```

### External Secrets Operator (Google Secret Manager)

```yaml
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata:
  name: sbomify-credentials
spec:
  refreshInterval: 1h
  secretStoreRef: {name: gcp-secret-manager, kind: ClusterSecretStore}
  target:
    name: sbomify-credentials      # -> secrets.existingSecret
  data:
    - secretKey: DATABASE_URL
      remoteRef: {key: sbomify-db-url}
    - secretKey: SECRET_KEY
      remoteRef: {key: sbomify-django-secret}
    # ...one entry per required key
```

### Vault Agent injector

The injector writes rendered files into the pod, so give the workloads the
annotations and let the app read the file:

```yaml
web:
  podAnnotations:
    vault.hashicorp.com/agent-inject: "true"
    vault.hashicorp.com/role: sbomify
    vault.hashicorp.com/agent-inject-secret-env: secret/data/sbomify
```

Note the migration Job needs the same annotations via `migrations.podAnnotations`.
It runs as a Helm hook, separately from the Deployments.

### Secrets Store CSI driver

Mount the provider volume on every workload; `web`, `worker`, `scheduler` and
`migrations` all take `extraVolumes` / `extraVolumeMounts`:

```yaml
web:
  extraVolumes:
    - name: secrets-store
      csi:
        driver: secrets-store.csi.k8s.io
        readOnly: true
        volumeAttributes: {secretProviderClass: sbomify}
  extraVolumeMounts:
    - {name: secrets-store, mountPath: /mnt/secrets, readOnly: true}
```

A `SecretProviderClass` with `secretObjects` also synthesises a normal Secret,
which you can then name in `secrets.existingSecret`.

### Workload identity (IRSA / GKE Workload Identity)

Annotate a ServiceAccount and stop the chart creating its own:

```yaml
serviceAccount:
  create: false
  name: sbomify            # you manage this, annotated for IRSA / WI
  automountServiceAccountToken: true
```

This matters for the migration Job specifically. It runs as a `pre-install`
hook, before Helm creates any ordinary resource, so a chart-created
ServiceAccount does not exist yet and the Job falls back to `default`. A
ServiceAccount you manage already exists, so the Job uses it and keeps its cloud
identity. `migrations.serviceAccountName` overrides it independently if you want
a separate, more privileged identity for schema changes.

### Keyless object storage

> **Not yet usable.** The chart side is ready, the application is not.
> `object_store.py` reads `AWS_*_ACCESS_KEY_ID` / `SECRET_ACCESS_KEY` from
> settings, which default to `""`, and passes them to boto3 explicitly. boto3
> treats an explicit empty string as a credential rather than as absent, so it
> never reaches its default chain. Enabling this against a current image breaks
> object storage and presigned URLs. It works once phase 1 of
> [ADR-0007](../../docs/ADR/0007-gcs-support-and-cloud-workload-identity.md)
> ships, which makes those credentials optional.

Static storage keys can then be dropped entirely where the platform can vouch
for the workload:

```yaml
objectStorage:
  useWorkloadIdentity: true    # EKS IRSA or Pod Identity
serviceAccount:
  create: false
  name: sbomify                # you manage it, annotated with the cloud role
```

The chart then omits every `AWS_*_ACCESS_KEY_ID` / `SECRET_ACCESS_KEY`
variable, which is what lets boto3 reach its default credential chain. Omitting
them is the whole point: setting them to empty strings leaves boto3 holding
blank credentials instead. Bucket names and the endpoint are still configured
normally, only the credentials become implicit.

### Supplemental variables

Anything the chart does not model (Stripe, Sentry) goes through `extraEnvFrom`,
which is applied to every workload:

```yaml
app:
  extraEnvFrom:
    - secretRef: {name: sbomify-stripe}
```

## Why Caddy and not an Ingress

A workspace can bring its own domain (`Team.custom_domain`), so **the set of TLS
hostnames is unbounded and changes at runtime**. Ingress and Gateway API both
require hostnames to be declared ahead of time, in an object someone has to
apply. Neither can serve a domain a customer added a minute ago.

Caddy's on-demand TLS can: on the first TLS handshake for an unknown hostname it
calls `/api/v1/internal/domains?domain=…`, and the app answers `200` for domains
it recognises (main domain, trust-center subdomains, and custom domains on
Business/Enterprise plans) or `404` otherwise. A certificate appears without a
redeploy, and an unrecognised domain gets nothing, which is what stops the
endpoint from becoming a way to burn ACME rate limits.

Two secondary benefits: it is the same proxy and the same `Caddyfile` semantics
as `docker-compose.yml`, so local, compose and Kubernetes behave alike; and it
avoids [ingress-nginx](https://www.kubernetes.io/blog/2026/01/29/ingress-nginx-statement/),
which reached end of life in March 2026 and no longer receives security patches.

Worth knowing before you scale it:

- **The ask is proxied through a loopback listener.** The app validates `Host`
  against a fixed set of names, so a request addressed to the web Service comes
  back `400` and every certificate is refused. Caddy therefore asks
  `127.0.0.1:9080`, a listener bound inside the pod that forwards only the ask
  path and rewrites `Host` to `localhost`. Nothing outside the pod can reach it.
- **More than one Caddy replica needs shared certificate storage.** With the
  default `file` storage each replica keeps its own certificates and runs its own
  ACME issuance for the same domains. Set `caddy.storage.module` (e.g. `redis`)
  and point `caddy.image` at a Caddy build that includes that plugin. The
  upstream image has none. The chart refuses `replicaCount > 1` otherwise.
- **The certificate PVC is marked `helm.sh/resource-policy: keep`**, so
  `helm uninstall` leaves it. Re-issuing every certificate from scratch is a fast
  route into Let's Encrypt rate limits.
- **`externalTrafficPolicy: Local`** on the LoadBalancer preserves the client IP,
  which the app's rate limiting and logging depend on.
- **`caddy.trustUpstreamTls` is off by default.** Turn it on only when something
  in front genuinely terminates TLS (a Cloudflare Tunnel, a cloud LB): it makes
  Caddy serve plain-HTTP requests carrying `X-Forwarded-Proto: https` instead of
  redirecting them. That header is client-settable, so leaving it on
  unconditionally would let any caller skip the HTTPS redirect, which is why it
  is paired with `fromCidrs`, restricting the behaviour to the proxy that
  actually does the termination.

## Design notes

**Migrations gate the rollout.** The Job is a `pre-install,pre-upgrade` hook: it
runs to completion before any new pod starts, so new code never serves traffic
against an un-migrated schema, and a failed migration fails the release.

Helm runs *all* pre-install hooks before it creates *any* ordinary resource, so
the Job cannot mount the release's own ConfigMap/Secret. They do not exist yet.
It gets short-lived hook copies instead (`-migrations-config` /
`-migrations-secrets`, weight `-10`) that delete themselves once the hook
succeeds. Annotating the real ones as hooks would also work, but hook resources
are untracked: `helm uninstall` would strip the release and leave them behind,
and the next install would fail with *invalid ownership metadata*.

This same ordering rule is why the database has to exist before install. See
*Backing services*.

**Only one runner can migrate at a time.** Django does not serialise `migrate`,
and a Kubernetes Job is *at least once*. A node partition can leave the original
pod running while a replacement starts, and two concurrent runs deadlock or
double-apply. `bin/release.py` therefore wraps the whole step in a PostgreSQL
session-level advisory lock, and the Job sets `podReplacementPolicy: Failed` so a
replacement pod waits for its predecessor to terminate. The lock is session
scoped, so a killed pod releases it automatically rather than wedging future
deploys. Covered by `sbomify/apps/core/tests/test_release_script.py`.

**Set `migrations.lockTimeout` in production.** A migration needing
`ACCESS EXCLUSIVE` queues behind in-flight queries, and once queued it blocks
every query arriving after it. One slow reader turns a millisecond
`ALTER TABLE` into a site-wide stall. With `lock_timeout` the migration fails
fast, the Job retries, and traffic is never held hostage.

**Migrations are forward-only.** `helm rollback` reverts manifests, not schema.
Deploying a rollback against a migrated database only works if the previous
release tolerates the new schema, which is the usual argument for
expand/contract: add columns nullable, backfill, switch reads, drop later, so
old and new code overlap safely. The chart cannot enforce this; `release.py`
logs `migrate --plan` before applying so a destructive step is visible in the
deploy log.

**`activeDeadlineSeconds` is unset by default.** When it fires Kubernetes kills
the pod mid-statement; atomic migrations roll back cleanly, but a non-atomic one
(this repo has two) can leave partial state. Helm's own `--timeout` already
bounds the release.

**The dependency-wait init container reuses the application image.** Every
workload blocks until PostgreSQL and Redis accept connections, but doing that
with a postgres image would mean shipping and pulling ~120MB on every node just
to run `pg_isready` once. The application image is already on the node, so the
check is free. It is a TCP reachability check rather than a driver-level one on
purpose: connecting for real would need credentials in the init container and
would fail closed on TLS details (a private CA, `sslmode=verify-full`) it has no
business knowing about.

**Probes send an explicit `Host` header.** `DynamicHostValidationMiddleware`
rejects requests whose `Host` it does not recognise, and kubelet probes default
to the pod IP, which would return `400`, not `200`. Every probe therefore sets
`Host: localhost`, one of the app's statically allowed hosts.

**The scheduler is a singleton with a `Recreate` strategy.** `dramatiq-crontab`
takes a Redis lock and a second instance exits immediately. A rolling update
would surge a second pod that CrashLoops until the old one finally exited.

**Workers get a long grace period.** 300s by default, because a Dramatiq worker
stops consuming on `SIGTERM` and then drains in-flight messages, and a
vulnerability scan can run for minutes. Killing it early just means the task is
redelivered and redone.

**The web tier drains before it dies.** `maxUnavailable: 0` plus a `preStop`
sleep gives Caddy time to drop the pod from its endpoint list before gunicorn
stops accepting, so a rollout does not drop in-flight requests.

**Caddy does no active health checking of the web tier.** The compose Caddyfile
does, because Docker offers nothing better. Here the upstream is a Service, and
kubelet readiness probes already remove unhealthy pods from the endpoint list.
Worse, an active probe carries the upstream's own name in `Host`, which the
app's host validation answers with `400`, so every backend would be marked
permanently down.

**Pods are hardened.** The upstream image is distroless and runs as UID 65532,
so the chart asserts `runAsNonRoot`, `readOnlyRootFilesystem`, `drop: [ALL]` and
`seccompProfile: RuntimeDefault`. Two `emptyDir`s cover the only paths the app
writes to: `/tmp` (its `HOME`) and `/var/lib/dramatiq-prometheus`. The app never
calls the Kubernetes API, so its ServiceAccount token is not mounted.

**`/api/v1/internal/*` is blocked at the edge**, by a flat deny rather than a
private-CIDR allow list. Behind a NodePort, or any load balancer that does not
preserve the source IP, every request arrives wearing a private node address,
so an allow list of RFC1918 ranges would wave the whole internet through. Add
CIDRs to `caddy.internalApiAllowedCidrs` only after confirming they arrive
un-translated. Blocking this path does not affect on-demand TLS: Caddy reaches
the ask endpoint over the Service, not back through the listener.

**`SECRET_KEY` and `SIGNED_URL_SALT` are required, not generated.** Generating
them was wrong three ways: the Secret template renders more than once per release
(the Secret itself, the migration hook's copy, and the `checksum/secret`
annotation), and `randAlphaNum` runs afresh each time, so the three disagreed;
`helm template` became non-deterministic, making diffs unreadable; and a value
only Helm knows is one `helm uninstall` away from logging out every user and
invalidating every signed URL. They are credentials: keep them where the
database password lives.

## Configuration

See [`values.yaml`](values.yaml). Every key is commented. The most important:

| Key | Default | Purpose |
| --- | --- | --- |
| `app.baseUrl` | `https://sbomify.example.com` | Public URL; validated against the `Host` header |
| `image.tag` / `image.digest` | `v<appVersion>` | Defaults to a real release, not `latest`; pin a digest in production |
| `web.replicaCount` / `web.autoscaling` | `2` / off | Web tier sizing |
| `worker.replicaCount` / `worker.autoscaling` | `2` / off | Worker pool sizing |
| `caddy.acme.email` | `admin@example.com` | Must be a real address; the chart refuses the placeholder |
| `caddy.onDemandTLS.enabled` | `true` | Certificates for workspace custom domains |
| `caddy.storage.module` | `file` | Set to a shared module to run more than one Caddy replica |
| `migrations.lockTimeout` | `""` | PostgreSQL `lock_timeout` for migrations, set this in production |
| `networkPolicy.enabled` | `false` | Needs a CNI that enforces policies |
| `database.*` / `redis.*` | required | Backing services you provide |
| `objectStorage.*` / `auth.keycloak.*` | required | Backing services you provide |

## Verifying a release

```bash
helm test sbomify -n sbomify
```

Runs two Pods: one calls the app's health endpoint through the Service, the
other exercises the Caddy edge (edge health, the app health path proxied
through it, the internal-API block, and the HTTPS redirect) and fails on any
unexpected status. The Pod is deliberately kept after a successful run so
that `helm test --logs` has something to read. The next run replaces it. One
consequence: `helm uninstall` leaves that one Completed Pod behind.

## Caveats

- `deploy/local/dependencies.yaml` is laptop scaffolding: single replica, no
  backups, no TLS, credentials committed to the repo. Never point a real
  deployment at it.
- kind's default CNI (kindnet) does not enforce NetworkPolicy, so
  `networkPolicy.enabled` is off in `values-local.yaml` rather than providing
  isolation that is not actually there.
- Caddy runs a single replica by default. Raising it requires shared certificate
  storage and a custom Caddy image. See *Why Caddy and not an Ingress*.
- The application exposes no Prometheus `/metrics` endpoint today, so the chart
  ships no ServiceMonitor.
- Keycloak's issuer URL has to resolve identically for the browser and for the
  app pods. `bin/kind-up.sh` handles that locally with a CoreDNS rewrite; in a
  real cluster it is simply a public DNS name.

## CI

`.github/workflows/helm.yml` runs on any change under `charts/`, to
`bin/kind-up.sh` or to `bin/release.py`:

- **lint**, `helm lint` against both value sets, `kubeconform` over the rendered
  manifests, `caddy validate` on the generated Caddyfile in three
  configurations, and assertions that the chart still *rejects* each invalid
  combination it is supposed to catch.
- **install**. A real kind cluster, `helm install`, `helm test`, then edge
  checks through Caddy (HTTPS redirect, health, the internal-API block, Keycloak
  routing), a migration check, and an idempotent `helm upgrade`.
