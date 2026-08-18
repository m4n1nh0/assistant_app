# Identidade INTARQ

A INTARQ é a marca principal do produto. O nome configurável da assistente é
uma persona dentro da plataforma e não substitui a marca. Na interface, a
hierarquia recomendada é `INTARQ | Nome da assistente`.

## Ativos oficiais

- `docs/assets/branding/intarq-brand-board.png`: prancha recebida e preservada
  como fonte de referência;
- `interface/assets/branding/intarq-icon-transparent.png`: símbolo isolado para
  cabeçalhos e componentes;
- `interface/assets/branding/intarq-lockup-horizontal.png`: logomarca usada na
  interface e nos relatórios;
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

- O lockup aparece no splash, acesso e barra superior.
- O símbolo identifica o Modo Educação.
- Relatórios mantêm corpo claro para impressão e exibem a marca em uma placa
  azul-noite compacta; o documento inteiro não recebe fundo escuro.
- A personalidade configurável continua aparecendo ao lado da marca.
- Não distorcer, recolorir, redesenhar ou usar a prancha completa como logo.

Antes de divulgação comercial, devem ser produzidas versões vetoriais oficiais
(`SVG`, `PDF` vetorial e fonte/curvas do wordmark) a partir do arquivo-fonte da
marca. Os PNGs atuais atendem ao aplicativo e aos documentos, mas não substituem
um pacote vetorial para impressão gráfica de grande formato.
