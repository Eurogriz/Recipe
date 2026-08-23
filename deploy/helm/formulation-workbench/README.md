# Formulation Workbench — Helm chart

Deploys the headless REST + CLI service (`formulation-api`) with production
defaults: non-root pod, hardened container security context, HPA, PDB,
NetworkPolicy, ConfigMap/Secret separation, and pod-security-standards
`restricted` compatibility.

## Install

```bash
helm upgrade --install formulation ./deploy/helm/formulation-workbench \
    --namespace formulation-workbench \
    --create-namespace \
    --set image.tag=1.1.3 \
    --set-file secret.values.FW_JWT_SECRET=/dev/stdin <<< "$(openssl rand -hex 32)"
```

## Values

See [`values.yaml`](values.yaml) — every field carries an inline comment.
The most common overrides:

| Key | Meaning |
| --- | --- |
| `image.tag` | Container image tag (default: `.Chart.AppVersion`). |
| `replicaCount` | Ignored when `autoscaling.enabled=true`. |
| `secret.create=false` + `secret.existingName` | Use an ExternalSecret / SealedSecret instead. |
| `ingress.enabled=true` | Publish the API via ingress-nginx (or your `ingressClassName`). |
| `resources` | Requests / limits — the defaults fit a `t3.small` node. |
| `autoscaling.min/maxReplicas` | HPA bounds. |

## Sealing secrets

We recommend **ExternalSecrets Operator** or **Sealed Secrets** rather than
`secret.values.*` for anything real. Example wiring for ESO:

```yaml
# values.yaml
secret:
  create: false
  existingName: formulation-workbench   # populated by an ExternalSecret

---
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: formulation-workbench
spec:
  refreshInterval: 1h
  secretStoreRef:
    name: aws-secretsmanager
    kind: SecretStore
  target:
    name: formulation-workbench
  data:
    - secretKey: FW_JWT_SECRET
      remoteRef:
        key: formulation/prod
        property: jwt_secret
    - secretKey: FW_DATABASE_URL
      remoteRef:
        key: formulation/prod
        property: db_url
```
