# Runbook de Incidentes — Canary

## Sintomas criticos

| Sintoma | Severidad | Accion inmediata |
|---------|-----------|------------------|
| 5xx rate > 1% | P0 | Rollback DNS |
| P95 latency > 1s | P1 | Investigar, rollback si persiste |
| Health check fail > 2 | P1 | Verificar container, restart |
| CPU > 80% | P2 | Escalar instancia |
| Memory > 85% | P2 | Escalar instancia |

## Pasos inmediatos

1. Ejecutar `infra/rollback_canary.sh`
2. Notificar on-call (Slack: #REEMPLAZAR_AQUI)
3. Recolectar logs: `aws logs filter-log-events --log-group-name REEMPLAZAR_AQUI --filter-pattern ERROR`

## Diagnostico rapido

```bash
curl -sf https://api.REEMPLAZAR_DOMAIN/health
docker ps
docker logs --tail 50 ai-recruiter
```

## Escalado

```bash
# Lightsail
aws lightsail update-instance --instance-name REEMPLAZAR_AQUI --bundle-id medium_2_0

# ECS
aws ecs update-service --cluster ai-recruiter-cluster --service ai-recruiter-api --desired-count 3
```

## Contactos

- On-call: REEMPLAZAR_AQUI
- Slack: #REEMPLAZAR_AQUI
- Escalado: REEMPLAZAR_AQUI
