# Pesquisas científicas

Cadastre uma pesquisa, deixe a **IA propor o plano de etapas**, ligue os participantes e
acompanhe prazos e andamento em um só lugar.

**Onde:** Modo Educação → **3. Pesquisas** (logo depois de Mentorias).

## Fase 1 (disponível)

1. **Nova pesquisa.** Título, tema e objetivo, área, duração (8 a 52 semanas) e data de
   início. **Gerar plano com IA** propõe de 5 a 10 etapas, já com prazo calculado a partir do
   início. As etapas voltam **editáveis**: ajuste o texto e a data, apague ou acrescente
   antes de criar. Nada é gravado até você clicar em **Criar pesquisa**. Se a IA não
   responder, entram 6 etapas padrão (revisão bibliográfica, metodologia, coleta, análise,
   redação e submissão), sem prazo.
2. **Participantes.** Alunos da casa ou pessoas de fora, com papel de **orientando**,
   **coorientador** ou **colaborador**; nome, e-mail, telefone, matrícula e instituição. A
   matrícula **não é validada**: ela só marca **ALUNO CONHECIDO** quando casa com um aluno
   ativo cadastrado. A mesma matrícula não entra duas vezes; quem sai pode voltar depois.
3. **Etapas e prazos.** O ícone de cada etapa muda a situação (a fazer, fazendo, feita).
   Etapa com prazo vencido e não concluída fica **atrasada**, em vermelho. Concluir registra
   a data; reabrir limpa.
4. **Andamento.** A pesquisa mostra o percentual de etapas feitas, quantas estão atrasadas e
   o próximo prazo. A situação da pesquisa (planejamento, em andamento, pausada, concluída)
   muda na hora pelo seletor. A tela se atualiza sozinha a cada 30 s.

Apagar uma pesquisa apaga as etapas e os participantes dela.

## Rotas

Autenticadas, em `/education/research`: `POST /generate-plan`, `POST`, `GET`, `GET /{id}`,
`PATCH /{id}`, `DELETE /{id}`, `POST /{id}/participants`,
`PATCH|DELETE /participants/{id}`, `POST /{id}/stages`, `PATCH|DELETE /stages/{id}`.

## Próximas fases

- **Referências e leituras:** biblioteca de artigos por pesquisa; a IA lê o PDF (o OCR já
  existe) e gera resumo, metodologia e pontos principais.
- **Entregas e relatórios:** versões de relatórios e rascunhos de artigo, com feedback seu e
  revisão da IA (clareza, estrutura, citações).
- **Eventos e submissões:** congressos e periódicos com prazos e lembretes.
- **Visão geral:** cartão da pesquisa no painel inicial.
