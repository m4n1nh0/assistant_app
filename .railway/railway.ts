// Observabilidade no Railway: otel-collector, prometheus e grafana.
//
// Este arquivo e uma PARCIAL NOMEADA (`partial` abaixo). Isso e o que impede o `apply` de apagar
// o resto do projeto: "a named partial only deletes resources it owns". Os outros servicos
// (assistant-api, mysql, redis, qdrant...) continuam sendo geridos pelo painel, e nao aparecem
// aqui. O primeiro `apply` assume a posse dos tres servicos e dos dois volumes declarados.
//
// Como usar (a CLI do Railway precisa estar instalada e `railway login` + `railway link` feitos):
//
//   railway config plan --verbose      # so mostra o que mudaria; leia antes de aplicar
//   railway config apply               # pede confirmacao
//
// Antes do primeiro `apply`:
//   1. apague o servico `otel-collector` criado a mao, se existir (o nome e o mesmo);
//   2. crie a variavel compartilhada GRAFANA_ADMIN_PASSWORD (Project Settings > Shared Variables),
//      com uma senha forte: a senha nao fica neste arquivo, que vai para o repositorio;
//   3. confira REGION abaixo: deve ser a regiao dos seus outros servicos (hoje: Virginia).
//
// Pontos que eu nao consegui confirmar na documentacao e que o `plan` vai mostrar:
//   - o argumento `ctx` de defineRailway e o acesso `ctx.shared.NOME` (so vi `ctx.shared.NAME`);
//   - `replicas: { [regiao]: 1 }` como forma de fixar a regiao do servico;
//   - o nome do projeto em project(...), logo abaixo.
//
// O que o IaC nao cobre e continua no painel:
//   - dominio publico do grafana (gerar dominio, porta 3000): dominio gerado pelo Railway nao
//     entra no arquivo, so dominio proprio;
//   - Watch Paths (o campo nao existe no IaC);
//   - as variaveis OTEL_* dos servicos da aplicacao, que estao fora desta parcial.

import { defineRailway, github, project, service, volume } from "railway/iac";

export const partial = "observability";

// Regiao do Railway. O volume e o servico precisam estar na mesma: veja em Settings de um servico
// existente (ex.: "us-west2", "us-east4-eqdc4a", "europe-west4-drams3a", "asia-southeast1-eqsg3a").
const REGION = "us-east4-eqdc4a"; // US East (Virginia): padrao do workspace

const REPO = "m4n1nh0/assistant_app";
const BRANCH = "main";

export default defineRailway((ctx) => {
  // Cada servico sai de uma pasta com um arquivo chamado `Dockerfile`: o IaC nao tem campo para
  // o caminho do Dockerfile, e o Railway detecta o `Dockerfile` da Root Directory.
  const fromRepo = (rootDirectory: string) =>
    github(REPO, { branch: BRANCH, rootDirectory });

  // Recebe traces e metricas da aplicacao (OTLP em 4318) e expoe as metricas em 8889. Sem dominio
  // publico: so a rede privada o alcanca, por `otel-collector.railway.internal`.
  const collector = service("otel-collector", {
    source: fromRepo("infra/otel-collector"),
    replicas: { [REGION]: 1 },
  });

  // Guarda as metricas (busca no collector, porta 8889). A imagem roda sem root e o volume do
  // Railway monta como root: RAILWAY_RUN_UID=0 evita "permission denied" no boot.
  const prometheusData = volume("prometheus-data", { region: REGION, sizeMB: 2048 });
  const prometheus = service("prometheus", {
    source: fromRepo("infra/prometheus"),
    replicas: { [REGION]: 1 },
    env: { RAILWAY_RUN_UID: "0" },
    volumeMounts: { "/prometheus": prometheusData },
  });

  // Painel. Ja sobe com a fonte de dados e o painel "Assistant" provisionados. A senha vem de uma
  // variavel compartilhada, para nao ser escrita aqui.
  const grafanaData = volume("grafana-data", { region: REGION, sizeMB: 512 });
  const grafana = service("grafana", {
    source: fromRepo("infra/grafana"),
    replicas: { [REGION]: 1 },
    env: {
      RAILWAY_RUN_UID: "0",
      GF_SECURITY_ADMIN_PASSWORD: ctx.shared.GRAFANA_ADMIN_PASSWORD,
    },
    volumeMounts: { "/var/lib/grafana": grafanaData },
  });

  // Nome do projeto no Railway (confirmado pelo `railway link`). Se o `plan` propuser renomear o
  // projeto, o nome esta diferente: corrija antes de aplicar.
  return project("dependable-passion", {
    resources: [collector, prometheus, grafana, prometheusData, grafanaData],
  });
});
