# Guía de Monitorización y Alertas — Canary

## Variables

```bash
export AWS_REGION="REEMPLAZAR_AWS_REGION"
export SNS_TOPIC_ARN="REEMPLAZAR_AQUI"
export OLD_LOG_GROUP="/ecs/ai-recruiter-api"
export NEW_LOG_GROUP="/ecs/ai-recruiter-api-v2"
```

---

## 1. Métricas a recolectar

| Métrica | Fuente | Umbral alerta |
|---------|--------|---------------|
| Latencia P95 | CloudWatch ALB | > 1s |
| Tasa de errores 5xx | CloudWatch ALB | > 1% en 5 min |
| Health check failures | Lightsail/ECS | > 2 en 5 min |
| CPU usage | Lightsail/ECS | > 80% |
| Memory usage | Lightsail/ECS | > 85% |
| Request count | CloudWatch ALB | Anomalía > 50% |

---

## 2. Enviar logs a CloudWatch

### Opción A: CloudWatch Agent (Lightsail)

```bash
# Instalar en la instancia
sudo apt-get install -y amazon-cloudwatch-agent

# Configurar
cat > /opt/aws/amazon-cloudwatch-agent/etc/config.json << 'EOF'
{
  "logs": {
    "logs_collected": {
      "files": {
        "collect_list": [
          {
            "file_path": "/var/log/docker/ai-recruiter.log",
            "log_group_name": "REEMPLAZAR_AQUI",
            "log_stream_name": "{instance_id}",
            "retention_in_days": 7
          }
        ]
      }
    }
  }
}
EOF

sudo /opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl \
  -a fetch-config -m ec2 -s -c file:/opt/aws/amazon-cloudwatch-agent/etc/config.json
```

### Opción B: Push desde la app (logging driver)

```bash
# En docker run, usar logging driver
docker run -d \
  --log-driver=awslogs \
  --log-opt awslogs-group="REEMPLAZAR_AQUI" \
  --log-opt awslogs-region="$AWS_REGION" \
  --log-opt awslogs-stream-prefix="ai-recruiter" \
  ...
```

---

## 3. Alarmas CloudWatch

### Crear alarma de error rate

```bash
aws cloudwatch put-metric-alarm \
  --alarm-name "ai-recruiter-5xx-rate" \
  --alarm-description "Error rate > 1% for 5 minutes" \
  --metric-name "HTTPCode_Target_5XX_Count" \
  --namespace "AWS/ApplicationELB" \
  --statistic Sum \
  --period 300 \
  --evaluation-periods 1 \
  --threshold 10 \
  --comparison-operator GreaterThanThreshold \
  --dimensions Name=LoadBalancer,Value="REEMPLAZAR_AQUI" \
  --alarm-actions "$SNS_TOPIC_ARN" \
  --region "$AWS_REGION"
```

### Crear alarma de latencia P95

```bash
aws cloudwatch put-metric-alarm \
  --alarm-name "ai-recruiter-latency-p95" \
  --alarm-description "P95 latency > 1s" \
  --metric-name "TargetResponseTime" \
  --namespace "AWS/ApplicationELB" \
  --extended-statistic "p95" \
  --period 300 \
  --evaluation-periods 1 \
  --threshold 1.0 \
  --comparison-operator GreaterThanThreshold \
  --dimensions Name=LoadBalancer,Value="REEMPLAZAR_AQUI" \
  --alarm-actions "$SNS_TOPIC_ARN" \
  --region "$AWS_REGION"
```

### Crear alarma de CPU

```bash
aws cloudwatch put-metric-alarm \
  --alarm-name "ai-recruiter-cpu-high" \
  --alarm-description "CPU > 80%" \
  --metric-name "CPUUtilization" \
  --namespace "AWS/Lightsail" \
  --statistic Average \
  --period 300 \
  --evaluation-periods 1 \
  --threshold 80 \
  --comparison-operator GreaterThanThreshold \
  --dimensions Name=ServiceName,Value="REEMPLAZAR_AQUI" \
  --alarm-actions "$SNS_TOPIC_ARN" \
  --region "$AWS_REGION"
```

---

## 4. Dashboard de CloudWatch

```bash
aws cloudwatch put-dashboard \
  --dashboard-name "ai-recruiter-canary" \
  --dashboard-body '{
    "widgets": [
      {
        "type": "metric",
        "properties": {
          "title": "5xx Errors",
          "metrics": [["AWS/ApplicationELB", "HTTPCode_Target_5XX_Count", "LoadBalancer", "REEMPLAZAR_AQUI"]],
          "period": 60
        }
      },
      {
        "type": "metric",
        "properties": {
          "title": "Latency P95",
          "metrics": [["AWS/ApplicationELB", "TargetResponseTime", "LoadBalancer", "REEMPLAZAR_AQUI", {"stat": "p95"}]],
          "period": 60
        }
      },
      {
        "type": "log",
        "properties": {
          "title": "Errors",
          "query": "fields @timestamp, @message | filter @message like /ERROR/ | sort @timestamp desc | limit 20",
          "region": "REEMPLAZAR_AWS_REGION",
          "logGroupNames": ["REEMPLAZAR_AQUI"]
        }
      }
    ]
  }' \
  --region "$AWS_REGION"
```

---

## 5. Playbook de respuesta rápida

| Señal | Acción | Responsable |
|-------|--------|-------------|
| 5xx > 1% | Rollback DNS inmediato | SRE |
| P95 > 1s | Investigar logs, rollback si persiste | SRE |
| CPU > 80% | Escalar instancia | DevOps |
| Health fail > 2 | Verificar container, restart | DevOps |
| Logs sin errores | Monitorear 15 min más | SRE |
