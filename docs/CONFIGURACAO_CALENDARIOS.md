# Configuração de calendários

Este guia configura o Google Calendar e o Microsoft Outlook/Teams para o
Assistente consultar compromissos e criar eventos após a confirmação do
usuário.

O Assistente trabalha com eventos:

- no Google, usa a agenda principal da conta conectada;
- na Microsoft, usa o calendário padrão da conta conectada;
- mostra título, data, horário e conta antes de criar o evento;
- só envia a criação depois do clique em **Criar evento**.

A integração não cria uma nova agenda separada. Ela cria compromissos dentro
da agenda existente.

## URLs de callback

O callback deve apontar para o endereço público do **backend**. Em um deploy no
Railway, use o domínio público `*.up.railway.app`, nunca o domínio privado
`*.railway.internal`.

| Ambiente | Google | Microsoft |
|---|---|---|
| Local | `http://localhost:8000/calendar/google/oauth-callback` | `http://localhost:8000/calendar/microsoft/oauth-callback` |
| Railway | `https://SEU-BACKEND.up.railway.app/calendar/google/oauth-callback` | `https://SEU-BACKEND.up.railway.app/calendar/microsoft/oauth-callback` |
| Domínio próprio | `https://SEU-DOMINIO/calendar/google/oauth-callback` | `https://SEU-DOMINIO/calendar/microsoft/oauth-callback` |

Substitua o domínio de exemplo pela mesma URL definida no Assistente em
**Configurações > Sistema > Conexão com o backend**.

A URL cadastrada no provedor deve ser idêntica à utilizada pelo backend:

- mantenha `https` em produção;
- mantenha a porta quando ela fizer parte do endereço;
- não coloque `/` no final;
- trate `localhost` e `127.0.0.1` como endereços diferentes.

## Google Calendar

O Google usa o seguinte escopo:

```text
https://www.googleapis.com/auth/calendar.events
```

Esse escopo permite ao Assistente consultar e criar eventos. Não é necessário
adicionar outros escopos do Google Calendar.

### 1. Criar o projeto e ativar a API

1. Acesse o [Google Cloud Console](https://console.cloud.google.com/).
2. Crie um projeto ou selecione o projeto do Assistente.
3. Abra **APIs e serviços > Biblioteca**.
4. Procure por **Google Calendar API**.
5. Clique em **Ativar**.
6. Abra **APIs e serviços > Credenciais** e inicie a criação das credenciais.

### 2. Tipo de credencial

Na primeira tela, selecione:

| Campo | Valor |
|---|---|
| **Qual API você usa?** | **Google Calendar API** |
| **Que dados você acessará?** | **Dados do usuário** |

Clique em **Próxima**.

### 3. Tela de permissão OAuth

Preencha as informações exibidas aos usuários:

| Campo | Valor sugerido |
|---|---|
| **Nome do app** | `Assistente Calendar` |
| **E-mail para suporte do usuário** | Seu e-mail Google |
| **Logotipo do app** | Opcional |
| **Dados de contato do desenvolvedor** | Seu e-mail |

Clique em **Salvar e continuar**.

### 4. Escopos

1. Clique em **Adicionar ou remover escopos**.
2. Procure por **Google Calendar API**.
3. Selecione somente:

   ```text
   https://www.googleapis.com/auth/calendar.events
   ```

4. Confirme que a descrição informa que o aplicativo pode ver e editar
   eventos.
5. Clique em **Atualizar** e depois em **Salvar e continuar**.

O escopo pode aparecer na categoria **Confidenciais**.

### 5. Criar o ID do cliente OAuth

Abra **Google Auth Platform > Clientes** e clique em **Criar cliente**.

Preencha:

| Campo | Valor |
|---|---|
| **Tipo de aplicativo** | **Aplicativo da Web** |
| **Nome** | `Assistente Cliente` |
| **Origens JavaScript autorizadas** | Deixe vazio |

Em **URIs de redirecionamento autorizados**, adicione os endereços usados pela
sua instalação. Para um backend no Railway:

```text
https://SEU-BACKEND.up.railway.app/calendar/google/oauth-callback
```

Para executar também com o backend local, adicione:

```text
http://localhost:8000/calendar/google/oauth-callback
```

Clique em **Criar** e guarde imediatamente:

- **ID do cliente**;
- **Client Secret**.

O Client Secret é uma credencial privada. Não envie o valor em mensagens, não
o publique no GitHub e não o inclua em arquivos versionados.

### 6. Configurar o público

Abra **Google Auth Platform > Público** e defina quem pode conectar uma conta:

| Uso | Tipo de público |
|---|---|
| Contas Gmail pessoais ou usuários externos | **Externo** |
| Usuários da mesma organização Google Workspace | **Interno** |

Se o aplicativo estiver com status **Teste**, adicione cada conta Google em
**Usuários de teste**. Nesse status, a autorização de um usuário de teste pode
expirar após sete dias. Para disponibilizar a integração continuamente a
outros usuários, configure o status de produção e cumpra as exigências de
verificação apresentadas pelo Google.

### 7. Conectar ao Assistente

1. Abra **Configurações > Sistema > Conexão com o backend**.
2. Confirme que o endereço é a URL pública do backend no Railway ou o endereço
   local utilizado.
3. Abra **Configurações > Agendas > Google Calendar**.
4. Cole o **ID do cliente** e o **Client Secret**.
5. Clique em **Conectar Google Agenda**.
6. No navegador, escolha a conta Google e aceite a permissão solicitada.
7. Volte ao Assistente e confirme que a conta aparece como conectada.

## Microsoft Outlook e Teams

O Microsoft Graph usa permissões delegadas:

```text
Calendars.ReadWrite
offline_access
```

`Calendars.ReadWrite` permite consultar e criar eventos em nome do usuário
conectado. `offline_access` permite renovar a sessão da integração.

### 1. Registrar o aplicativo

1. Acesse o [Microsoft Entra admin center](https://entra.microsoft.com/).
2. Abra **Entra ID > Registros de aplicativo**.
3. Clique em **Novo registro**.
4. Informe o nome `Assistente Calendar`.
5. Escolha o tipo de conta:
   - **Contas em qualquer diretório organizacional e contas Microsoft
     pessoais** para Microsoft 365, Outlook.com e Hotmail;
   - **Contas somente neste diretório organizacional** para uso exclusivo de
     uma organização.
6. Clique em **Registrar**.
7. Na página **Visão geral**, copie o **ID do aplicativo (cliente)**.
8. Para uma organização específica, copie também o **ID do diretório
   (locatário)**.

### 2. Configurar o callback

1. Abra **Autenticação**.
2. Clique em **Adicionar uma plataforma**.
3. Selecione **Web**.
4. Adicione o callback do backend. Para Railway:

   ```text
   https://SEU-BACKEND.up.railway.app/calendar/microsoft/oauth-callback
   ```

5. Para desenvolvimento local, adicione também:

   ```text
   http://localhost:8000/calendar/microsoft/oauth-callback
   ```

6. Salve a configuração.

O Assistente usa o fluxo Authorization Code. Não é necessário habilitar
**Concessão implícita**.

### 3. Adicionar as permissões

1. Abra **Permissões de API > Adicionar uma permissão**.
2. Selecione **Microsoft Graph**.
3. Selecione **Permissões delegadas**.
4. Adicione `Calendars.ReadWrite`.
5. Adicione `offline_access`.
6. Salve.

Uma organização pode exigir que um administrador conceda consentimento às
permissões. O Assistente utiliza permissões **delegadas**, não permissões de
aplicativo.

### 4. Criar o Client Secret

1. Abra **Certificados e segredos > Segredos do cliente**.
2. Clique em **Novo segredo do cliente**.
3. Informe uma descrição e a validade.
4. Clique em **Adicionar**.
5. Copie imediatamente o conteúdo da coluna **Valor**.

No Assistente, use o **Valor** como Client Secret. O **ID do segredo** não é a
credencial. Anote a data de expiração para substituir o segredo antes do
vencimento.

### 5. Definir o tenant

| Tipo de conta do registro | Tenant no Assistente |
|---|---|
| Organizações e contas pessoais | `common` |
| Somente uma organização | ID do diretório (tenant) |
| Somente organizações, multitenant | `organizations` |

### 6. Conectar ao Assistente

1. Abra **Configurações > Agendas > Microsoft (Teams + Outlook)**.
2. Preencha:
   - **Client ID**: ID do aplicativo (cliente);
   - **Client Secret**: conteúdo da coluna Valor;
   - **Tenant**: valor correspondente ao registro.
3. Clique em **Conectar Outlook**.
4. Entre com a conta Microsoft e aceite as permissões.
5. Volte ao Assistente e confirme que a conta aparece como conectada.

## Usar o calendário pela conversa

### Consultar a agenda

O Assistente usa um provedor de IA disponível para interpretar a intenção, o
período, o provedor e um possível termo de busca. Exemplos:

```text
O que tenho na agenda hoje?
Quais são meus compromissos amanhã depois das 14h?
Quando é minha próxima reunião?
Mostre os eventos do Google Calendar na próxima semana.
Tenho alguma reunião com João nos próximos sete dias?
```

A interpretação gera internamente um plano `calendar_query`. O backend valida
o plano, limita o período a 31 dias e consulta somente as contas pertencentes
ao usuário autenticado. A resposta da conversa é montada exclusivamente com
os eventos devolvidos pelo Google ou pela Microsoft.

Client Secrets, tokens OAuth e eventos não são enviados ao provedor de IA. A
IA recebe a pergunta, o contexto recente da conversa, a data atual e o fuso
horário. Se a interpretação por IA falhar, o Assistente reconhece diretamente
períodos comuns como hoje, amanhã, dias da semana e próxima semana.

Consultas são somente leitura e não precisam de confirmação. Se uma conta
falhar e outra responder, os eventos disponíveis são mostrados junto de um
aviso de sincronização parcial. Uma agenda vazia e uma falha de conexão são
informadas com mensagens diferentes.

### Criar eventos

Informe título, data e horário. Exemplos:

```text
Agende reunião com João amanhã às 14h.
Marque dentista dia 10/08 às 09:30 por 30 minutos no Google Calendar.
Crie Planejamento na sexta das 14h às 15h no Outlook.
```

Por padrão, o Assistente apresenta a proposta de evento. Confira:

- título;
- início e término;
- fuso horário;
- provedor e conta de destino.

Clique em **Criar evento** para confirmar. Fechar ou cancelar a janela não
altera o calendário.

#### Criação automática

Em **Configurações > Agendas > Criação de eventos**, ative **Autorizar criação
automática** para não abrir a janela de confirmação a cada pedido. A opção vem
desligada por segurança e é salva por usuário.

Quando ela está ativa:

- somente pedidos explícitos com título, data e horário podem criar eventos;
- a primeira conta compatível com o provedor solicitado é utilizada;
- quando o pedido não informa Google ou Microsoft, a conta Google conectada tem
  preferência;
- o Assistente informa no chat em qual agenda o evento foi criado.

Desative a opção quando quiser revisar título, horário, descrição e conta de
destino antes de cada criação.

## Criar a agenda semanal das turmas

No **Modo Aula > 5. Presença**, use o botão com o ícone de calendário no quadro
**Relatórios e aulas do dia**. O Assistente reúne automaticamente as turmas
ativas do semestre corrente que possuem dia e horário cadastrados. Escolha uma
das contas conectadas, confira o início e o fim do semestre e confirme uma única
vez.

Cada horário de turma é criado como uma série semanal recorrente no Google
Calendar ou Outlook. Repetir a sincronização, com a mesma conta e o mesmo fim
de semestre, não duplica as séries mesmo em outro dia. Turmas sem horário inicial são informadas como
falha e não geram eventos com hora inventada.

Depois da criação, os próximos encontros entram no painel lateral na
sincronização automática, que ocorre a cada cinco minutos. As opções de
notificação já configuradas continuam valendo: lembrete 15 minutos antes, no
horário, Telegram e/ou WhatsApp. A aplicação mantém somente um temporizador por
evento para não repetir o aviso a cada atualização do calendário.

## Teste da integração

1. Confirme que a conta aparece em **Configurações > Agendas**.
2. Crie diretamente no Google ou Outlook um compromisso para hoje.
3. Pergunte no chat `O que tenho na agenda hoje?` e confirme que o compromisso
   aparece na resposta.
4. Solicite ao Assistente um evento para alguns minutos ou horas no futuro.
5. Revise a proposta e clique em **Criar evento**, ou confirme que a criação
   ocorreu diretamente quando a autorização automática estiver ativa.
6. Abra o Google Calendar ou Outlook e confirme o novo compromisso.
7. Volte à tela principal do Assistente e atualize a agenda.

O painel lateral consulta até 25 eventos dos próximos sete dias. Uma consulta
pela conversa pode usar um período de até 31 dias e retorna no máximo 25
eventos por resposta.

## Solução de problemas

### `redirect_uri_mismatch` no Google

Compare a URL apresentada no erro com a cadastrada em **Google Auth Platform >
Clientes > URIs de redirecionamento autorizados**. Protocolo, domínio, porta,
caminho e barra final precisam coincidir.

### `access_denied` no Google

Confirme que:

- a Google Calendar API está ativada no mesmo projeto do cliente OAuth;
- a conta está em **Público > Usuários de teste**, quando o app está em teste;
- o escopo `calendar.events` está configurado e foi aceito.

### Callback com HTTP ou domínio interno no Railway

Use a URL pública HTTPS do backend no Assistente e no provedor. Verifique no
Railway se o serviço expõe um domínio público e encaminha corretamente os
cabeçalhos `X-Forwarded-Host` e `X-Forwarded-Proto`.

### `AADSTS50011` na Microsoft

Confira em **Autenticação > Web** se o callback Microsoft é idêntico ao enviado
pelo backend.

### `invalid_client` na Microsoft

Confirme que o Client ID e o Client Secret pertencem ao mesmo registro, que o
segredo não expirou e que foi usado o conteúdo da coluna **Valor**.

### Permissão insuficiente para criar um evento

Confira se a conta conectada concedeu:

- Google: `https://www.googleapis.com/auth/calendar.events`;
- Microsoft: `Calendars.ReadWrite` delegada.

Remova a conexão no Assistente, conecte novamente e aceite as permissões
apresentadas.

## Segurança

- Não coloque Client Secrets ou tokens no repositório.
- Não compartilhe credenciais em mensagens ou capturas de tela.
- Use HTTPS no Railway e em qualquer ambiente publicado.
- Restrinja os usuários de teste e o público do aplicativo ao necessário.
- Remova no provedor as credenciais que não estiverem em uso.

As credenciais e os tokens das contas conectadas são armazenados pelo backend
no banco de dados e separados por usuário do Assistente.

## Referências oficiais

- [Google Calendar: escopos OAuth](https://developers.google.com/workspace/calendar/api/auth)
- [Google OAuth para aplicações de servidor web](https://developers.google.com/identity/protocols/oauth2/web-server?hl=pt-BR)
- [Google Auth Platform: público e usuários de teste](https://support.google.com/cloud/answer/15549945)
- [Microsoft Entra: registrar um aplicativo](https://learn.microsoft.com/entra/identity-platform/quickstart-register-app)
- [Microsoft Entra: configurar Redirect URI](https://learn.microsoft.com/entra/identity-platform/how-to-add-redirect-uri)
- [Microsoft Graph: permissões](https://learn.microsoft.com/graph/permissions-reference)
