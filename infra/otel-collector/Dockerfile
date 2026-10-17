# Collector no Railway.
#
# O compose monta o otel-collector.yaml por volume; o Railway nao monta arquivo do repositorio
# numa imagem pronta. Aqui o mesmo arquivo e copiado para dentro da imagem, e a versao do
# collector e a mesma do compose.
#
# O arquivo se chama `Dockerfile` e esta na propria pasta do servico porque o Railway so detecta
# um Dockerfile com esse nome dentro da Root Directory (e o IaC nao tem campo para outro caminho).
#
# Root Directory: /infra/otel-collector
FROM otel/opentelemetry-collector-contrib:0.115.1

COPY otel-collector.yaml /etc/otelcol-contrib/config.yaml

EXPOSE 4317 4318
