# Grafana no Railway, ja com a fonte de dados e o painel provisionados.
#
# Nada precisa ser configurado na interface: ao subir, a fonte `Prometheus` aponta para o servico
# `prometheus` do projeto e o painel "Assistant · consumo de IA e saude" ja esta la. O painel fica
# em /etc/grafana/dashboards, e nao em /var/lib/grafana, porque este ultimo e o volume e um
# volume montado esconderia o que a imagem pusesse nele.
#
# Root Directory: /infra/grafana
# Dockerfile Path: /infra/grafana/Dockerfile
FROM grafana/grafana-oss:11.3.0

# Business Charts (Apache ECharts): desenha o "Fluxo ao vivo" do painel do mapa. Precisa de rede
# no build. Fica em /usr/share/grafana-plugins, e nao no /var/lib/grafana/plugins padrao, pelo
# mesmo motivo do painel: la o volume montado esconderia o plugin instalado na imagem.
USER root
RUN mkdir -p /usr/share/grafana-plugins \
    && grafana cli --pluginsDir /usr/share/grafana-plugins plugins install volkovlabs-echarts-panel \
    && chown -R 472:0 /usr/share/grafana-plugins
USER grafana

COPY provisioning /etc/grafana/provisioning
COPY dashboards /etc/grafana/dashboards

# Porta fixa: o dominio publico do Railway aponta para ela.
ENV GF_PATHS_PLUGINS=/usr/share/grafana-plugins \
    GF_SERVER_HTTP_PORT=3000 \
    GF_USERS_ALLOW_SIGN_UP=false \
    GF_ANALYTICS_REPORTING_ENABLED=false \
    GF_ANALYTICS_CHECK_FOR_UPDATES=false

EXPOSE 3000
