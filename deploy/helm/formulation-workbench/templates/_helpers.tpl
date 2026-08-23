{{/*
Chart helpers.  Standard naming borrowed from `helm create`.
*/}}

{{- define "formulation-workbench.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "formulation-workbench.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name (include "formulation-workbench.name" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}

{{- define "formulation-workbench.labels" -}}
app.kubernetes.io/name: {{ include "formulation-workbench.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: formulation-workbench
app.kubernetes.io/version: {{ .Values.image.tag | default .Chart.AppVersion | quote }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | quote }}
{{- end -}}

{{- define "formulation-workbench.selectorLabels" -}}
app.kubernetes.io/name: {{ include "formulation-workbench.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{- define "formulation-workbench.serviceAccountName" -}}
{{- if .Values.serviceAccount.create -}}
{{ include "formulation-workbench.fullname" . }}
{{- else -}}
default
{{- end -}}
{{- end -}}

{{- define "formulation-workbench.secretName" -}}
{{- if and (not .Values.secret.create) .Values.secret.existingName -}}
{{ .Values.secret.existingName }}
{{- else -}}
{{ include "formulation-workbench.fullname" . }}
{{- end -}}
{{- end -}}
