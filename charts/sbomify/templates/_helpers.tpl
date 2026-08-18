{{/* vim: set filetype=mustache: */}}

{{- define "sbomify.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "sbomify.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{- define "sbomify.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "sbomify.labels" -}}
helm.sh/chart: {{ include "sbomify.chart" . }}
{{ include "sbomify.selectorLabels" . }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: sbomify
{{- end }}

{{- define "sbomify.selectorLabels" -}}
app.kubernetes.io/name: {{ include "sbomify.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Component-scoped labels. Usage: {{ include "sbomify.componentLabels" (dict "ctx" $ "component" "web") }}
*/}}
{{- define "sbomify.componentLabels" -}}
{{ include "sbomify.labels" .ctx }}
app.kubernetes.io/component: {{ .component }}
{{- end }}

{{- define "sbomify.componentSelectorLabels" -}}
{{ include "sbomify.selectorLabels" .ctx }}
app.kubernetes.io/component: {{ .component }}
{{- end }}

{{- define "sbomify.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "sbomify.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{/*
ServiceAccount for the pre-install migrations hook.

Helm creates ordinary resources only after every pre-install hook has run, so a
chart-created ServiceAccount does not exist yet and the hook has to fall back to
`default`. A ServiceAccount the chart does NOT create already exists, and using
it matters: that is where an IRSA / GKE Workload Identity annotation lives, so
without it the migration Job could not reach an external secret manager or an
IAM-authenticated database.
*/}}
{{- define "sbomify.migrationsServiceAccountName" -}}
{{- if .Values.migrations.serviceAccountName -}}
{{- .Values.migrations.serviceAccountName -}}
{{- else if not .Values.serviceAccount.create -}}
{{- default "default" .Values.serviceAccount.name -}}
{{- else -}}
default
{{- end -}}
{{- end }}

{{/* Name of the Secret holding application credentials. */}}
{{- define "sbomify.secretName" -}}
{{- if .Values.secrets.existingSecret }}
{{- .Values.secrets.existingSecret }}
{{- else }}
{{- printf "%s-secrets" (include "sbomify.fullname" .) }}
{{- end }}
{{- end }}

{{- define "sbomify.configMapName" -}}
{{- printf "%s-config" (include "sbomify.fullname" .) }}
{{- end }}

{{/*
Fully-qualified image reference, digest-pinned when provided.

With no explicit tag this resolves to v<appVersion>, an actual release, rather
than a floating "latest" that changes under a running deployment. Released
images carry the "v" prefix; an explicit image.tag is used verbatim.
*/}}
{{- define "sbomify.image" -}}
{{- if .Values.image.digest }}
{{- printf "%s@%s" .Values.image.repository .Values.image.digest }}
{{- else if .Values.image.tag }}
{{- printf "%s:%s" .Values.image.repository .Values.image.tag }}
{{- else }}
{{- printf "%s:v%s" .Values.image.repository .Chart.AppVersion }}
{{- end }}
{{- end }}

{{/* ------------------------------------------------------------------ */}}
{{/* Connection strings                                                   */}}
{{/* ------------------------------------------------------------------ */}}

{{/*
Percent-encode a value for use in URL userinfo (the user:password part).

`urlquery` is Go's url.QueryEscape, which encodes a space as "+". That is only
space-equivalent inside a query string, in userinfo Python's urllib.parse
(and therefore dj_database_url) reads "+" literally, so a password containing a
space would silently arrive wrong. Re-encode it as %20.
*/}}
{{- define "sbomify.urlEscape" -}}
{{- . | urlquery | replace "+" "%20" -}}
{{- end }}

{{/*
DATABASE_URL. Django's dj_database_url parses this and it takes precedence over
the individual DATABASE_* variables, so it is the single source of truth here.
*/}}
{{- define "sbomify.databaseUrl" -}}
{{- $d := .Values.database -}}
{{- $base := printf "postgresql://%s:%s@%s:%v/%s" $d.username (include "sbomify.urlEscape" $d.password) $d.host $d.port $d.database -}}
{{- if $d.sslMode -}}
{{- printf "%s?sslmode=%s" $base $d.sslMode -}}
{{- else -}}
{{- $base -}}
{{- end -}}
{{- end }}

{{/*
REDIS_URL. Must NOT carry a database number, settings.py derives DB 0/1/2 for
cache, task queue and websocket channels from this base URL.
*/}}
{{- define "sbomify.redisUrl" -}}
{{- $r := .Values.redis -}}
{{- $scheme := ternary "rediss" "redis" $r.tls -}}
{{- if $r.password -}}
{{- printf "%s://:%s@%s:%v" $scheme (include "sbomify.urlEscape" $r.password) $r.host $r.port -}}
{{- else -}}
{{- printf "%s://%s:%v" $scheme $r.host $r.port -}}
{{- end -}}
{{- end }}

{{/* S3 endpoint the application talks to (in-cluster MinIO or external). */}}
{{- define "sbomify.s3Endpoint" -}}
{{- .Values.objectStorage.endpointUrl -}}
{{- end }}

{{- define "sbomify.s3MediaBucketUrl" -}}
{{- if .Values.objectStorage.media.bucketUrl -}}
{{- .Values.objectStorage.media.bucketUrl -}}
{{- else -}}
{{- printf "%s/%s" (include "sbomify.s3Endpoint" .) .Values.objectStorage.media.bucket -}}
{{- end -}}
{{- end }}

{{- define "sbomify.s3SbomsBucketUrl" -}}
{{- if .Values.objectStorage.sboms.bucketUrl -}}
{{- .Values.objectStorage.sboms.bucketUrl -}}
{{- else -}}
{{- printf "%s/%s" (include "sbomify.s3Endpoint" .) .Values.objectStorage.sboms.bucket -}}
{{- end -}}
{{- end }}

{{/*
Keycloak base URL the application talks to, always with a trailing slash.
An explicit auth.keycloak.serverUrl always wins, including when the bundled
Keycloak is enabled: OIDC discovery hands the browser the endpoints it finds at
this URL, so in some setups it must be the public URL rather than the in-cluster
Service name.
*/}}
{{- define "sbomify.keycloakServerUrl" -}}
{{- printf "%s/" (trimSuffix "/" .Values.auth.keycloak.serverUrl) -}}
{{- end }}

{{/*
Normalised to end in exactly one "/".

settings.py builds the discovery URL by bare concatenation,
f"{KEYCLOAK_SERVER_URL}realms/{REALM}/.well-known/openid-configuration", so a
value written the natural way, without a trailing slash, silently yields
"https://sso.example.comrealms/..." and breaks every login. Migration 0004
persists that same string into the SocialApp row, so the damage outlives the
misconfiguration.

There is deliberately no separate browser-facing URL: the application reads only
KEYCLOAK_SERVER_URL, and OIDC discovery hands the browser whatever endpoints it
finds there. A second value would be a knob that silently does nothing.
*/}}

{{/* Public hostname, parsed out of app.baseUrl. */}}
{{- define "sbomify.appHost" -}}
{{- regexReplaceAll "^https?://([^/:]+).*$" .Values.app.baseUrl "${1}" -}}
{{- end }}

{{/* ------------------------------------------------------------------ */}}
{{/* Shared pod plumbing                                                  */}}
{{/* ------------------------------------------------------------------ */}}

{{/*
Environment shared by every sbomify workload (web, worker, scheduler,
migrations). Non-secret values come from the ConfigMap, credentials from the
Secret, so a rotation of either rolls the pods via the checksum annotations.
*/}}
{{- define "sbomify.secretKey" -}}
{{- $ctx := .ctx -}}
{{- get ($ctx.Values.secrets.keys | default dict) .key | default .key -}}
{{- end }}

{{- define "sbomify.env" -}}
{{- $ctx := .ctx -}}
{{- $secretName := .secretName | default (include "sbomify.secretName" $ctx) -}}
- name: SECRET_KEY
  valueFrom:
    secretKeyRef:
      name: {{ $secretName }}
      key: {{ include "sbomify.secretKey" (dict "ctx" $ctx "key" "SECRET_KEY") }}
- name: SIGNED_URL_SALT
  valueFrom:
    secretKeyRef:
      name: {{ $secretName }}
      key: {{ include "sbomify.secretKey" (dict "ctx" $ctx "key" "SIGNED_URL_SALT") }}
- name: DATABASE_URL
  valueFrom:
    secretKeyRef:
      name: {{ $secretName }}
      key: {{ include "sbomify.secretKey" (dict "ctx" $ctx "key" "DATABASE_URL") }}
- name: REDIS_URL
  valueFrom:
    secretKeyRef:
      name: {{ $secretName }}
      key: {{ include "sbomify.secretKey" (dict "ctx" $ctx "key" "REDIS_URL") }}
{{- if not $ctx.Values.objectStorage.useWorkloadIdentity }}
- name: AWS_ACCESS_KEY_ID
  valueFrom:
    secretKeyRef:
      name: {{ $secretName }}
      key: {{ include "sbomify.secretKey" (dict "ctx" $ctx "key" "AWS_SBOMS_ACCESS_KEY_ID") }}
- name: AWS_SECRET_ACCESS_KEY
  valueFrom:
    secretKeyRef:
      name: {{ $secretName }}
      key: {{ include "sbomify.secretKey" (dict "ctx" $ctx "key" "AWS_SBOMS_SECRET_ACCESS_KEY") }}
- name: AWS_MEDIA_ACCESS_KEY_ID
  valueFrom:
    secretKeyRef:
      name: {{ $secretName }}
      key: {{ include "sbomify.secretKey" (dict "ctx" $ctx "key" "AWS_MEDIA_ACCESS_KEY_ID") }}
- name: AWS_MEDIA_SECRET_ACCESS_KEY
  valueFrom:
    secretKeyRef:
      name: {{ $secretName }}
      key: {{ include "sbomify.secretKey" (dict "ctx" $ctx "key" "AWS_MEDIA_SECRET_ACCESS_KEY") }}
- name: AWS_SBOMS_ACCESS_KEY_ID
  valueFrom:
    secretKeyRef:
      name: {{ $secretName }}
      key: {{ include "sbomify.secretKey" (dict "ctx" $ctx "key" "AWS_SBOMS_ACCESS_KEY_ID") }}
- name: AWS_SBOMS_SECRET_ACCESS_KEY
  valueFrom:
    secretKeyRef:
      name: {{ $secretName }}
      key: {{ include "sbomify.secretKey" (dict "ctx" $ctx "key" "AWS_SBOMS_SECRET_ACCESS_KEY") }}
{{- end }}
- name: KEYCLOAK_CLIENT_SECRET
  valueFrom:
    secretKeyRef:
      name: {{ $secretName }}
      key: {{ include "sbomify.secretKey" (dict "ctx" $ctx "key" "KEYCLOAK_CLIENT_SECRET") }}
{{- with $ctx.Values.app.extraEnv }}
{{ toYaml . }}
{{- end }}
{{- end }}

{{- define "sbomify.envFrom" -}}
{{- $ctx := .ctx -}}
- configMapRef:
    name: {{ .configMapName | default (include "sbomify.configMapName" $ctx) }}
{{- with $ctx.Values.app.extraEnvFrom }}
{{ toYaml . }}
{{- end }}
{{- end }}

{{/*
Migration-only environment. Tunes how bin/release.py takes the PostgreSQL
advisory lock that serialises concurrent migration runs, and optionally bounds
how long a migration may sit waiting on a table lock.
*/}}
{{- define "sbomify.migrationEnv" -}}
- name: MIGRATION_LOCK_WAIT_SECONDS
  value: {{ .Values.migrations.lockWaitSeconds | quote }}
{{- with .Values.migrations.lockTimeout }}
- name: MIGRATION_LOCK_TIMEOUT
  value: {{ . | quote }}
{{- end }}
{{- with .Values.migrations.statementTimeout }}
- name: MIGRATION_STATEMENT_TIMEOUT
  value: {{ . | quote }}
{{- end }}
{{- end }}

{{/*
Writable scratch space. The container image runs with a read-only root
filesystem, but Python needs HOME (/tmp) and dramatiq needs its Prometheus
multiprocess directory to be writable.
*/}}
{{- define "sbomify.scratchVolumes" -}}
- name: tmp
  emptyDir: {}
- name: prometheus-multiproc
  emptyDir: {}
{{- end }}

{{- define "sbomify.scratchVolumeMounts" -}}
- name: tmp
  mountPath: /tmp
- name: prometheus-multiproc
  mountPath: /var/lib/dramatiq-prometheus
{{- end }}

{{/*
Annotations that roll every pod when configuration or credentials change.
Without these, a `helm upgrade` that only touches the ConfigMap/Secret would
leave the running pods on stale values.
*/}}
{{- define "sbomify.configChecksums" -}}
checksum/config: {{ include (print $.Template.BasePath "/configmap.yaml") . | sha256sum }}
{{- if not .Values.secrets.existingSecret }}
checksum/secret: {{ include (print $.Template.BasePath "/secret.yaml") . | sha256sum }}
{{- end }}
{{- end }}

{{/*
HTTP probe against the Django health endpoint. The explicit Host header is
required: DynamicHostValidationMiddleware rejects requests whose Host is not a
known hostname, and kubelet probes default to sending the pod IP.
*/}}
{{- define "sbomify.healthProbeHttpGet" -}}
path: /UuPha8mu/
port: http
httpHeaders:
  - name: Host
    value: localhost
{{- end }}

{{/*
Topology spread constraints with a release-scoped labelSelector injected when
the value does not supply one. Hand-writing the selector in values.yaml is
error-prone: a bare `component: web` selector would also match pods from other
sbomify releases in the same namespace.
Usage: {{ include "sbomify.topologySpread" (dict "ctx" $ "component" "web" "constraints" .Values.web.topologySpreadConstraints) }}
*/}}
{{- define "sbomify.topologySpread" -}}
{{- range .constraints }}
- maxSkew: {{ .maxSkew | default 1 }}
  topologyKey: {{ .topologyKey | default "kubernetes.io/hostname" }}
  whenUnsatisfiable: {{ .whenUnsatisfiable | default "ScheduleAnyway" }}
  {{- if .minDomains }}
  minDomains: {{ .minDomains }}
  {{- end }}
  {{- if .nodeAffinityPolicy }}
  nodeAffinityPolicy: {{ .nodeAffinityPolicy }}
  {{- end }}
  labelSelector:
    {{- if .labelSelector }}
    {{- toYaml .labelSelector | nindent 4 }}
    {{- else }}
    matchLabels:
      {{- include "sbomify.componentSelectorLabels" (dict "ctx" $.ctx "component" $.component) | nindent 6 }}
    {{- end }}
{{- end }}
{{- end }}

{{/*
Blocks until Postgres and Redis accept connections. Used as an init container
so a pod does not crash-loop (and burn its restart budget) purely because a
dependency has not finished starting.
*/}}
{{- define "sbomify.waitForDepsInitContainer" -}}
- name: wait-for-dependencies
  # Deliberately the application image, not a postgres one. The node has already
  # pulled this for the main container, so the check costs nothing extra,
  # whereas a postgres image would mean shipping and pulling ~120MB on every
  # node purely to run pg_isready once.
  image: {{ include "sbomify.image" . | quote }}
  imagePullPolicy: {{ .Values.image.pullPolicy }}
  command:
    - python
    - -c
    - |
      import os, socket, sys, time

      # A TCP check rather than a driver-level one on purpose: connecting for
      # real would need the credentials, and would fail closed on TLS details
      # (a private CA, sslmode=verify-full) that this container has no business
      # knowing about. Reachability is all this gate is for. The migration Job
      # and the app surface genuine connection errors themselves.
      deadline = time.monotonic() + float(os.environ.get("WAIT_TIMEOUT_SECONDS", "300"))

      def wait_for(label, host, port):
          port = int(port)
          reported = False
          while True:
              try:
                  with socket.create_connection((host, port), timeout=5):
                      print(f"{label} is ready at {host}:{port}", flush=True)
                      return
              except OSError as exc:
                  if time.monotonic() >= deadline:
                      print(f"timed out waiting for {label} at {host}:{port}: {exc}", flush=True)
                      sys.exit(1)
                  if not reported:
                      print(f"waiting for {label} at {host}:{port}...", flush=True)
                      reported = True
                  time.sleep(2)

      wait_for("postgresql", os.environ["DB_HOST"], os.environ["DB_PORT"])
      wait_for("redis", os.environ["REDIS_HOST"], os.environ["REDIS_PORT"])
  env:
    - name: DB_HOST
      value: {{ .Values.database.host | quote }}
    - name: DB_PORT
      value: {{ .Values.database.port | quote }}
    - name: REDIS_HOST
      value: {{ .Values.redis.host | quote }}
    - name: REDIS_PORT
      value: {{ .Values.redis.port | quote }}
    - name: WAIT_TIMEOUT_SECONDS
      value: {{ .Values.dependencyWaitTimeoutSeconds | quote }}
    - name: HOME
      value: /tmp
  securityContext:
    {{- toYaml .Values.securityContext | nindent 4 }}
  volumeMounts:
    {{- include "sbomify.scratchVolumeMounts" . | nindent 4 }}
  resources:
    requests:
      cpu: 10m
      memory: 64Mi
    limits:
      memory: 128Mi
{{- end }}
