{{/*
Fail fast on misconfiguration, at template time, with a message that says what
to set, rather than letting the pods come up and crash-loop on a missing
connection string. Included from configmap.yaml so it always runs.
*/}}
{{- define "sbomify.validateValues" -}}

{{- if not .Values.app.baseUrl }}
{{- fail "sbomify: app.baseUrl is required. The app validates the Host header against it and builds absolute URLs from it" }}
{{- end }}

{{- if not (regexMatch "^https?://" .Values.app.baseUrl) }}
{{- fail (printf "sbomify: app.baseUrl must include a scheme (http:// or https://), got %q" .Values.app.baseUrl) }}
{{- end }}

{{/*
The backing services are deliberately not bundled. See values.yaml. Each of
these is a hard requirement, so say plainly what is missing.
*/}}
{{- if not .Values.database.host }}
{{- fail "sbomify: database.host is required. This chart does not run PostgreSQL for you: point it at a managed instance or one provisioned separately (e.g. the CloudNativePG operator). See charts/sbomify/README.md." }}
{{- end }}

{{/*
Only when the chart builds DATABASE_URL itself. With secrets.existingSecret the
whole connection string comes from outside. An external secret manager is
exactly where a database password should live, so requiring it here too would
block the configuration this chart is meant to encourage. database.host stays
required either way: the dependency-wait init container needs an address, and it
never sees the Secret.
*/}}
{{- if and (not .Values.secrets.existingSecret) (not .Values.database.password) }}
{{- fail "sbomify: database.password is required (or supply DATABASE_URL via secrets.existingSecret)" }}
{{- end }}

{{- if not .Values.redis.host }}
{{- fail "sbomify: redis.host is required. This chart does not run Redis for you: point it at a managed instance or one provisioned separately. See charts/sbomify/README.md." }}
{{- end }}

{{- if not .Values.objectStorage.endpointUrl }}
{{- fail "sbomify: objectStorage.endpointUrl is required: S3, R2, Tigris, or a MinIO you operate" }}
{{- end }}

{{- if not .Values.auth.keycloak.serverUrl }}
{{- fail "sbomify: auth.keycloak.serverUrl is required. This chart does not run Keycloak for you: deploy it with the Keycloak Operator (the project's official Kubernetes path) and point this at it. See charts/sbomify/README.md." }}
{{- end }}

{{- if and (not .Values.secrets.existingSecret) (not .Values.secrets.secretKey) }}
{{- fail "sbomify: secrets.secretKey is required (or supply SECRET_KEY via secrets.existingSecret). Generate one with: openssl rand -base64 48. Keep it, because losing it invalidates every session and every signed URL." }}
{{- end }}

{{- if and (not .Values.secrets.existingSecret) (not .Values.secrets.signedUrlSalt) }}
{{- fail "sbomify: secrets.signedUrlSalt is required (or supply SIGNED_URL_SALT via secrets.existingSecret). Generate one with: openssl rand -base64 32. Rotating it invalidates outstanding download links." }}
{{- end }}

{{- if and .Values.caddy.trustUpstreamTls.enabled (not .Values.caddy.trustUpstreamTls.fromCidrs) }}
{{- fail "sbomify: caddy.trustUpstreamTls.enabled requires caddy.trustUpstreamTls.fromCidrs. X-Forwarded-Proto is client-settable, so with no source restriction ANY caller can have the app served over plain HTTP, and Django's SECURE_PROXY_SSL_HEADER would believe the connection was secure, so its own HTTPS redirect would not fire either. List the CIDRs of the proxy that terminates TLS. If you genuinely need to accept it from anywhere (the listener is unreachable except through that proxy), say so explicitly with fromCidrs: [\"0.0.0.0/0\", \"::/0\"]." }}
{{- end }}

{{/*
Previously these could be left blank and the chart would happily inject empty
AWS_* variables, which fails at runtime in a way that points nowhere near the
configuration. Either supply keys, or say you are using the workload's own
identity.
*/}}
{{- if and (not .Values.secrets.existingSecret) (not .Values.objectStorage.useWorkloadIdentity) }}
{{- if or (not .Values.objectStorage.sboms.accessKeyId) (not .Values.objectStorage.sboms.secretAccessKey) }}
{{- fail "sbomify: objectStorage.sboms.accessKeyId and secretAccessKey are required, or supply them via secrets.existingSecret. Set objectStorage.useWorkloadIdentity=true to skip them and use the workload's own cloud identity instead." }}
{{- end }}
{{- if or (not .Values.objectStorage.media.accessKeyId) (not .Values.objectStorage.media.secretAccessKey) }}
{{- fail "sbomify: objectStorage.media.accessKeyId and secretAccessKey are required, or supply them via secrets.existingSecret. Set objectStorage.useWorkloadIdentity=true to skip them and use the workload's own cloud identity instead." }}
{{- end }}
{{- end }}

{{/*
The health path is not ours to choose. Django registers it in urls.py and
exempts that exact prefix in SECURE_REDIRECT_EXEMPT, so a different value here
points the kubelet probes and the edge at a 404 while the chart still renders.
It stays a value because three templates need it, not because it is tunable.
*/}}
{{- if ne .Values.caddy.healthPath "/UuPha8mu/" }}
{{- fail "sbomify: caddy.healthPath must stay /UuPha8mu/. The application hardcodes that path in urls.py and SECURE_REDIRECT_EXEMPT, so changing it here only breaks the probes and the edge health route." }}
{{- end }}

{{- if and (not .Values.secrets.existingSecret) (not .Values.auth.keycloak.clientSecret) }}
{{- fail "sbomify: set auth.keycloak.clientSecret (the OIDC client secret), or supply it via secrets.existingSecret" }}
{{- end }}

{{- if and .Values.app.billing (not .Values.app.extraEnvFrom) (not .Values.app.extraEnv) }}
{{- fail "sbomify: app.billing=true needs the STRIPE_* variables: supply them via app.extraEnvFrom (a Secret ref) or app.extraEnv" }}
{{- end }}

{{- if and (gt (int .Values.caddy.replicaCount) 1) (eq .Values.caddy.storage.module "file") }}
{{- fail "sbomify: caddy.replicaCount > 1 needs shared certificate storage. With the default `file` storage each replica keeps its own certificates and runs its own ACME issuance for the same domains, which duplicates certificates and burns rate limits. Set caddy.storage.module (e.g. redis) and point caddy.image at a Caddy build that includes that storage plugin, or keep replicaCount at 1." }}
{{- end }}

{{- if and .Values.caddy.onDemandTLS.enabled (not .Values.caddy.onDemandTLS.ask) }}
{{- fail "sbomify: caddy.onDemandTLS.enabled requires caddy.onDemandTLS.ask. Without the ask endpoint Caddy will attempt issuance for ANY hostname pointed at it, which is an open door to ACME rate-limit exhaustion." }}
{{- end }}

{{- if and .Values.caddy.onDemandTLS.enabled (not .Values.caddy.localCerts) (or (not .Values.caddy.acme.email) (eq .Values.caddy.acme.email "admin@example.com")) }}
{{- fail "sbomify: set caddy.acme.email to a real address: Let's Encrypt sends expiry and revocation notices there. Use caddy.localCerts=true for local clusters that should not touch a public CA." }}
{{- end }}

{{- end -}}
