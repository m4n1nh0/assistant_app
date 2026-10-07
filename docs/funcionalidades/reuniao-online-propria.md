# Reunião online própria

Sala de reunião do próprio app, com **câmera e microfone para todos** e **sem gravar**: o
vídeo e o áudio passam por um servidor de mídia e não ficam guardados em lugar nenhum. O
que fica é a **fala transcrita**, de **cada pessoa separadamente**, com o nome de quem
falou. Serve para mentoria e orientação (começa com 20 e vai encolhendo) e para qualquer
reunião pequena.

**Onde:** Modo Educação → **10. Reuniões**.

## Como funciona

1. **Crie a reunião:** título, se aceita **convidados sem matrícula** e o limite de pessoas
   (padrão 30). O app cria a sala e uma gravação do tipo **Reunião**, onde a transcrição vai
   entrando.
2. **Mande o link da turma** (copiar ou QR Code). Quem participa abre no **navegador**, no
   computador ou no celular, sem instalar nada.
3. **Entre como professor** (botão da reunião): abre a mesma sala no navegador, com a chave
   que dá o direito de **encerrar para todos**.
4. **Acompanhe no app:** quem está na sala (online, papel, tempo e quantas falas), e a
   transcrição ao vivo, que se atualiza a cada poucos segundos.
5. **Encerre** (no app ou na página do professor): todos saem, a gravação fecha e a fala
   transcrita fica no **Histórico**, no tipo **Reunião**, pronta para o resumo (decisões,
   encaminhamentos e pendências), a pesquisa no chat e o quiz.

## O que o participante vê

Uma página só: nome (e matrícula, opcional para convidados), o aceite da transcrição e
**Entrar na reunião**. Dentro, a grade de vídeos (quem fala fica com a borda verde),
microfone, câmera, **compartilhar tela** e **Sair**.

- **Com matrícula**, o nome vem do cadastro (o que se digitou como nome é ignorado), e a
  pessoa conta como **aluno** na presença. Matrícula inexistente, de aluno inativo ou de
  outro professor é recusada.
- **Sem matrícula**, entra como **convidado**, só com o nome. Com *Aceitar convidados*
  desligado, a matrícula é obrigatória.
- **Aceite obrigatório:** sem marcar que a fala será transcrita, não entra. O aceite fica
  registrado com a hora.
- **Recarregar a página** é seguro: o aluno volta, a entrada antiga fecha e ele não ocupa
  duas vagas nem aparece duas vezes na presença.

## Sem gravação: o que é guardado e o que não é

| Guardado | **Não** guardado |
|---|---|
| A fala transcrita, em trechos `Nome: texto` | Áudio |
| Quem entrou, quando, por quanto tempo e quantas falas | Vídeo |
| O aceite da transcrição (hora) | Tela compartilhada |

Cada navegador **detecta quando a própria pessoa fala** (microfone ligado e voz acima do
ruído) e manda só esse pedaço, de poucos segundos, ao servidor. O servidor transcreve e
**descarta o pedaço**: ele existe só durante a chamada. Microfone desligado, ninguém envia
nada. Por isso a transcrição já sai **por pessoa**, sem precisar descobrir quem falou.

## Presença

A aba mostra cada pessoa (aluno pela matrícula, convidado pelo nome): **online agora**,
**tempo somado** das entradas e **falas transcritas**. Quem fecha o navegador sem sair deixa
de contar como online em cerca de 45 segundos (o navegador avisa que está presente a cada
15 s). O professor aparece primeiro.

## O servidor de mídia (LiveKit)

O vídeo e o áudio em tempo real usam [LiveKit](https://livekit.io), de código aberto. São
três variáveis no servidor do app:

| Variável | O que é |
|---|---|
| `LIVEKIT_URL` | Endereço do LiveKit, com `wss://` (ex.: `wss://seuprojeto.livekit.cloud`) |
| `LIVEKIT_API_KEY` | Chave da API |
| `LIVEKIT_API_SECRET` | Segredo da API (nunca vai para o navegador) |

Sem as três, a aba mostra o que falta e ninguém consegue entrar. O app **não assina nada de
mídia**: só gera, para cada pessoa, um acesso curto à sala, e derruba a sala no LiveKit
quando a reunião é encerrada.

**Duas formas de ter o servidor:**

- **LiveKit Cloud** (a mais simples): crie um projeto em livekit.io, copie a URL, a chave e o
  segredo para as variáveis. Há plano gratuito para começar e depois paga-se pelo uso.
- **LiveKit próprio**: o mesmo programa numa máquina sua, com as portas de mídia abertas
  (TCP 7881 e UDP 7882, mais 443 com certificado para o navegador). **Não roda na Railway**:
  ela não expõe as portas UDP. Para experimentar na sua máquina:
  `docker run --rm -p 7880:7880 -p 7881:7881 -p 7882:7882/udp livekit/livekit-server --dev`
  (chave `devkey`, segredo `secret`; só para teste).

Trocar de um para o outro é só mudar as três variáveis.

## Limites e cuidados

- **Câmera e microfone exigem HTTPS** no navegador (o link do app em produção já é). Em teste
  local vale `localhost`.
- **Tamanho:** a sala foi pensada para reuniões pequenas, até algumas dezenas de pessoas com
  câmera. Acima de 30 (o padrão), aumente o limite por sala, sabendo que cada participante
  recebe o vídeo de todos.
- **Transcrição:** usa o mesmo Whisper do servidor, que atende uma fala por vez com folga.
  Muita gente falando junto atrasa a transcrição (nunca a reunião).
- **Navegadores:** Chrome, Edge, Firefox e Safari recentes. No celular o navegador pede a
  permissão de câmera e microfone na entrada.
- **Privacidade:** a página avisa, antes da entrada, que a fala é transcrita e que áudio e
  vídeo não são gravados. Avise também a turma de que a **transcrição fica guardada** com o
  nome de cada um.
- **O que o app não faz:** gravar a reunião, legenda ao vivo para os participantes, chat de
  texto, salas separadas por grupo.

## Detalhes técnicos

- **Tabelas:** `meeting_rooms` (título, token do link, chave do professor, convidados,
  limite, estado, gravação ligada) e `meeting_participants` (nome, aluno, papel, aceite,
  entrada, último sinal, saída, falas). Nenhuma coluna guarda áudio ou vídeo.
- **Páginas e rotas públicas** (a chave de quem entrou é a credencial): `GET
  /education/meet/{token}` (a página), `POST .../join`, `.../heartbeat`, `.../leave`,
  `.../end` (só o professor) e `.../audio` (pedaço de fala a transcrever). Erros trazem `code`
  (`consent`, `enrollment`, `enrollment_required`, `full`, `ended`, `host`, `auth`,
  `not_configured`, `stt`, `size`).
- **Do professor (autenticadas):** `GET /education/meetings/config`, `POST/GET
  /education/meetings`, `GET/PATCH /education/meetings/{id}` (presença e fim da transcrição),
  `POST .../end`.
- **Acesso ao LiveKit:** token JWT (HS256) com a identidade da pessoa e a sala; o professor
  leva também o poder de administrar a sala. O encerramento chama `DeleteRoom` do LiveKit.
- **Teste de ponta a ponta:** `backend/e2e/meeting_room/run.sh` sobe um LiveKit e o backend
  em Docker e abre dois navegadores reais (com câmera e microfone falsos): confere vídeo
  chegando, nomes, a fala de cada um virando trecho, presença, saída e o encerramento pelo
  professor.
