# Prometheus no Railway.
#
# O Railway nao monta arquivo do repositorio numa imagem pronta, entao a configuracao vai para
# dentro da imagem. O historico fica no volume montado em /prometheus e e mantido por 30 dias.
#
# Root Directory: /infra/prometheus
# Dockerfile Path: /infra/prometheus/Dockerfile
FROM prom/prometheus:v2.55.1

COPY prometheus.yml /etc/prometheus/prometheus.yml

CMD [ \
  "--config.file=/etc/prometheus/prometheus.yml", \
  "--storage.tsdb.path=/prometheus", \
  "--storage.tsdb.retention.time=30d", \
  "--web.listen-address=0.0.0.0:9090" \
]

EXPOSE 9090
