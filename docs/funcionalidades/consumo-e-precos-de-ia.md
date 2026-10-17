# Consumo e preços de IA

Quantas chamadas a modelos de IA foram feitas, quantos tokens gastaram e quanto custaram
(estimado), por provedor, por modelo ou por dia. O administrador também vê **quanto cada cliente
usou**.

**Onde:** Configurações → **Consumo de IA** → *Abrir consumo e preços*. A janela tem duas abas:
**Consumo** e **Preços**.

## Consumo

- **Período:** últimos 7, 30 ou 90 dias.
- **Agrupar por:** provedor, modelo ou dia. O administrador, na visão *Todos os clientes*, também
  agrupa por **cliente**.
- **Cada conta vê o próprio consumo.** Só o administrador soma todos os clientes e vê o de cada um
  (com o e-mail da conta).
- **Tokens são exatos**, os que o provedor informou. **O custo é uma estimativa**: tokens
  multiplicados pelo preço de tabela do modelo, e o valor real depende do seu contrato.
- Se houver chamadas **sem preço ou sem token informado**, a tela avisa e diz quantas são, para um
  total que parece completo não enganar.

O consumo é gravado **a partir das chamadas feitas depois que esta função entrou no ar**. Não há
histórico de antes.

### O que conta, e como

O consumo é somado por **dia, cliente, provedor e modelo**: meses de uso cabem em poucas linhas, e
somar um período é barato. O cliente é o dono da conta que fez a chamada, o mesmo que fornece a
chave do provedor. Isso vale para tudo que passa por um modelo do backend: chat, resumo de aula,
quiz, melhoria de material e as demais funções.

| Caso | O que acontece |
|---|---|
| **Provedor de nuvem** (Claude, OpenAI, Gemini, DeepSeek, Grok...) | Tokens contados; custo calculado com o preço do modelo. |
| **Modelo local** (`localai`, `llama`) | Tokens contados; custo **zero** (custa energia, não token). |
| **Agente conectado** (Codex, Claude Code) | Roda no computador do professor: o backend **não vê os tokens**. Conta só a **chamada**, sem token e sem custo, e ela entra no aviso de "sem preço". |
| **Plano gratuito de um provedor de nuvem** (Gemini, Groq...) | Os tokens são contados, mas o app não sabe que a sua chave é gratuita: o custo sai a preço de tabela. Para zerar, cadastre o preço `0` e `0` do modelo. |
| **Modelo `:free` do OpenRouter** | Idem, e a tabela pública não cobre o OpenRouter: cadastre o preço `0` do modelo. |
| **Chamada sem conta** (processo sem usuário) | Aparece como *(sem conta)*. |

## Preços

O custo de uma chamada é `tokens × preço`. O preço é **por modelo**, porque cada cliente escolhe o
seu e o mesmo provedor vende modelos de preços muito diferentes. A aba **Preços** lista a tabela,
por 1 milhão de tokens, em dólar.

**Como o preço de uma chamada é escolhido**, do mais específico ao mais geral:

1. o preço do **modelo** na tabela (aba Preços);
2. o preço do modelo no `LLM_PRICING` do ambiente (reserva);
3. o preço **padrão do provedor** na tabela (linha com o modelo vazio);
4. o padrão do provedor no `LLM_PRICING`;
5. a tabela embutida no código, que só dá a ordem de grandeza por provedor.

O id do modelo que o provedor devolve costuma trazer a data da versão (`claude-sonnet-4-5-20250929`,
`gpt-4o-2024-08-06`). Ele casa com o preço do nome sem a data, e **não** casa com um nome diferente
que começa igual: o `gpt-4o-mini` nunca herda o preço do `gpt-4o`.

Preço `0` e `0` marca um modelo gratuito: o custo dele sai zero de verdade.

### Importar da internet

O administrador clica em **ATUALIZAR DA INTERNET**. O backend baixa a tabela pública de preços da
comunidade (LiteLLM, um arquivo no GitHub com o custo por token de milhares de modelos) e importa os
modelos de chat dos provedores do app.

Medido na tabela real (outubro de 2026): **286 modelos** entram, de 4.201 entradas — Claude 22,
OpenAI 85, Gemini 40, DeepSeek 10, Grok/xAI/Groq 43 e Together 86.

- **Preço digitado à mão nunca é sobrescrito.** A importação só mexe nas linhas que ela mesma criou.
- **Sem rede**, ou com a fonte fora do ar, a importação falha com a causa e os preços que já
  estavam no banco continuam valendo.
- **É preço de tabela, não o do seu contrato.** O custo continua sendo uma estimativa.
- **Não cobre todo provedor:** o **OpenRouter** e o **Hugging Face** não vêm na tabela pública, e o
  Groq vem com poucos modelos. Para esses, digite o preço (botão **NOVO PREÇO**).

**Por que não pedir a uma IA que procure o preço:** um modelo de linguagem não consulta a internet
por conta própria e, quando "lembra" um preço, pode errar sem avisar, e custo errado parece certo.
Uma fonte pública que se baixa e se confere é previsível; o administrador ainda corrige à mão o que
quiser.

Os preços ficam no banco e são relidos a cada 5 minutos por todos os processos, então editar um
preço vale em poucos minutos, sem redeploy.

## Rotas

Autenticadas, em `/observability`:

| Rota | Quem | Para quê |
|---|---|---|
| `GET /usage?days=&group_by=&scope=` | cada conta; `scope=all` e `group_by=tenant` só administrador | Consumo do período, total e por grupo. |
| `GET /prices` | qualquer conta | A tabela de preços. |
| `PUT /prices` | administrador | Grava um preço à mão. |
| `DELETE /prices/{id}` | administrador | Apaga um preço (o modelo volta ao padrão do provedor). |
| `POST /prices/sync` | administrador | Importa a tabela pública. |

## Limites conhecidos

- O consumo só existe a partir de agora, e a **resposta em streaming** do chat ainda não é contada.
- Um modelo **sem preço próprio** usa o padrão do provedor, que é só uma ordem de grandeza: o
  custo dele pode estar bem errado se for um modelo muito mais caro ou mais barato que o padrão.
- O painel do **Grafana** (ver [deploy-railway.md](../arquitetura/deploy-railway.md)) continua
  somando todos os clientes; o consumo **por cliente** está só aqui, no app. A métrica de custo do
  Grafana usa a mesma tabela de preços.
- O consumo por cliente depende de a chamada rodar com a conta do cliente ativa. Chamadas em
  segundo plano sem essa conta aparecem como *(sem conta)*.
