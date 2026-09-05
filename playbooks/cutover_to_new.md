# Playbook de Cutover a 100% NEW

## Secuencia de weights

| Paso | OLD | NEW | Espera |
|------|-----|-----|--------|
| 0 | 100 | 0 | Baseline |
| 1 | 90 | 10 | 15 min |
| 2 | 75 | 25 | 15 min |
| 3 | 50 | 50 | 15 min |
| 4 | 25 | 75 | 15 min |
| 5 | 0 | 100 | 5 min |
| 6 | Eliminar OLD | — | — |

## Comandos por paso

```bash
# Paso 1: 90/10
aws route53 change-resource-record-sets --hosted-zone-id REEMPLAZAR_AQUI \
  --change-batch file://infra/canary-90-10.json

# Paso 2: 75/25
# Editar canary-90-10.json: OLD=75, NEW=25, luego:
aws route53 change-resource-record-sets --hosted-zone-id REEMPLAZAR_AQUI \
  --change-batch file://infra/canary-90-10.json

# Paso 3: 50/50 → Paso 4: 25/75 → Paso 5: 0/100
# Mismo patrón, cambiar weights en el JSON

# Paso 6: Eliminar registros OLD
aws route53 change-resource-record-sets --hosted-zone-id REEMPLAZAR_AQUI \
  --change-batch file://infra/rollback-100-old.json  # revertir a eliminar OLD
```

## Criterios de rollback en cada paso

- 5xx rate > 1% → rollback inmediato
- P95 latency > 1s por 5 min → rollback
- Health check fail > 2 en 5 min → rollback
- CPU > 80% → escalar primero, rollback si persiste
