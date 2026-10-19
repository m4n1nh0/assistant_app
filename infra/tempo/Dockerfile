# Tempo no Railway.
#
# O Railway nao monta arquivo do repositorio numa imagem pronta, entao a configuracao vai para
# dentro da imagem. Os traces ficam no volume montado em /var/tempo (7 dias).
#
# Root Directory: /infra/tempo
FROM grafana/tempo:2.6.1

COPY tempo.yaml /etc/tempo.yaml

CMD ["-config.file=/etc/tempo.yaml"]

EXPOSE 3200 4317 4318
