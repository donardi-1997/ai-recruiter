# Verificacion de Despliegue y SSH

## Obtener endpoint

```bash
# Container Service
URL=$(aws lightsail get-container-services --service-name REEMPLAZAR_AQUI --region REEMPLAZAR_AWS_REGION --query "containerServices[0].url" --output text)

# Instance + LB
DNS=$(aws lightsail get-load-balancers --region REEMPLAZAR_AWS_REGION --query "loadBalancers[0].dnsName" --output text)
```

## Verificar health

```bash
curl -sf "$URL/health" | python -m json.tool
# Esperado: {"status":"ok","db":true}
```

## SSH

```bash
ssh -i ~/.ssh/REEMPLAZAR_KEY_PAIR.pem ubuntu@REEMPLAZAR_AQUI
docker ps
docker logs --tail 50 ai-recruiter
docker exec -it ai-recruiter sh
```

## Verificar deployment

```bash
aws lightsail get-container-services --service-name REEMPLAZAR_AQUI --region REEMPLAZAR_AWS_REGION --query "containerServices[0].{State:state,Url:url}"
```

## Notas de seguridad

```bash
chmod 600 ~/.ssh/REEMPLAZAR_KEY_PAIR.pem
echo "*.pem" >> .gitignore
```
