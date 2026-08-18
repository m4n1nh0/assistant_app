# Identidade INTARQ

A INTARQ é a marca principal do produto. O nome configurável da assistente é
uma persona dentro da plataforma e não substitui a marca. Na interface, a
hierarquia recomendada é `INTARQ | Nome da assistente`.

O produto se apresenta como `INTARQ — AI Assistant`: `AI Assistant` é um
descritor, não parte do wordmark. Ele aparece apenas onde há espaço e ajuda a
identificar o produto — título da janela, metadados do executável Windows
(`INTARQ AI Assistant`, sem travessão por causa do codepage do recurso) e como
subtítulo do lockup no splash e na tela de acesso. Barra superior, relatórios e
demais assinaturas seguem somente com `INTARQ`.

Cada usuário possui sua própria persona. Sem personalização, o nome é
`Assistant`. Nome e pronúncia são campos distintos: a grafia `Hannah` pode usar
`Raná` como pronúncia para ativação e síntese de voz, sem alterar textos,
histórico ou identificação visual. A pronúncia fica no `config` do perfil do
usuário e não é uma configuração global da INTARQ.

## Ativos oficiais

- `docs/assets/branding/intarq-brand-board.png`: prancha recebida e preservada
  como fonte de referência;
- `interface/assets/branding/intarq-icon-transparent.png`: símbolo isolado para
  cabeçalhos e componentes;
- `interface/assets/branding/intarq-lockup-horizontal.png`: lockup completo
  preservado apenas como referência da identidade;
- `interface/assets/branding/intarq-app-icon.png`: versão quadrada para canais
  digitais;
- `interface/windows/runner/resources/app_icon.ico`: ícone multirresolução do
  executável Windows.

Os arquivos derivados são recortes determinísticos da prancha. Uma tentativa
de reconstrução generativa foi descartada porque alterava detalhes do símbolo,
o que não é aceitável para uso de marca.

## Paleta

| Papel | Cor | Hexadecimal |
|---|---|---|
| Azul noite | Fundo principal | `#0A1324` |
| Azul elétrico | Ação e tecnologia | `#00D6FF` |
| Ouro premium | Destaque e arquitetura | `#D4AF37` |
| Prata tecnológica | Texto secundário | `#B8C2CC` |
| Grafite | Superfícies escuras | `#0F141C` |

Os valores ficam centralizados em `IntarqBrand` e são consumidos por
`AssistantTheme`. Vermelho e verde continuam reservados a estados semânticos,
como erro e sucesso, para não prejudicar a compreensão da interface.

## Aplicação

- Splash, acesso, barra superior e relatórios usam o símbolo isolado e o nome
  `INTARQ`, compostos em código para permanecerem legíveis em qualquer tamanho.
  Lema e textos institucionais não acompanham a assinatura do produto; a única
  exceção é o descritor `AI ASSISTANT`, exibido sob o lockup somente no splash
  e na tela de acesso (`IntarqLockup(showDescriptor: true)`).
- Nas superfícies escuras da interface, `INTAR` usa prata clara e o `Q` mantém
  o azul elétrico. Nos relatórios, a assinatura tem fundo branco, `INTAR` em
  azul-noite e `Q` azul, preservando o contraste para impressão.
- O símbolo identifica o Modo Educação.
- Relatórios mantêm corpo e assinatura claros para impressão e exibem somente
  símbolo + `INTARQ`.
- A personalidade configurável continua aparecendo ao lado da marca.
- Não distorcer, recolorir, redesenhar ou usar a prancha completa como logo.

Antes de divulgação comercial, devem ser produzidas versões vetoriais oficiais
(`SVG`, `PDF` vetorial e fonte/curvas do wordmark) a partir do arquivo-fonte da
marca. Os PNGs atuais atendem ao aplicativo e aos documentos, mas não substituem
um pacote vetorial para impressão gráfica de grande formato.
