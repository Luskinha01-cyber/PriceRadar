# DESIGN.md — Especificação de UI/UX e Design System do PriceRadar

Este documento descreve as decisões visuais, tokens de cor, tipografia e padrões de interação adotados no frontend do **PriceRadar**.

---

## 1. Filosofia Visual

O **PriceRadar** adota uma estética de **Minimalismo Técnico em Dark Mode**, inspirada em interfaces de software de engenharia e finanças como **Linear**, **Vercel** e **Fey**:

- **Exclusivamente Dark Mode:** Elimina distrações visuais e fadiga ocular através de camadas de carbono/zinco de baixo brilho (`#09090b` a `#141418`).
- **Estrutura por Hairlines (`1px`):** Em vez de sombras pesadas ou gradientes decorativos, a hierarquia espacial é definida por bordas sutis de `1px` (`rgba(255, 255, 255, 0.07)`).
- **Zero Ornamentos Artificiais:** Todos os ícones são vetores SVG monocromáticos com traço preciso (`1.6px` a `2px`). Cores vibrantes são reservadas estritamente para estados semânticos (como `#10b981` quando uma cotação atinge a meta).

---

## 2. Paleta de Cores (Design Tokens)

| Token CSS | Valor Hex / RGBA | Função na Interface |
| :--- | :--- | :--- |
| `--bg-canvas` | `#09090b` | Plano de fundo principal da aplicação |
| `--bg-surface` | `#0e0e11` | Superfície de painéis, ledger de métricas e cards de produtos |
| `--bg-elevated` | `#141418` | Elementos elevados, botões secundários e área de preview |
| `--bg-input` | `#0a0a0c` | Fundo de campos de entrada e matrizes de cotação |
| `--border-hairline` | `rgba(255, 255, 255, 0.07)` | Divisórias estruturais de `1px` |
| `--border-strong` | `rgba(255, 255, 255, 0.14)` | Bordas de inputs e estado `:hover` de cards |
| `--text-primary` | `#f4f4f5` | Títulos, valores principais e textos ativos |
| `--text-secondary` | `#a1a1aa` | Descrições, rótulos secundários e navegação |
| `--text-muted` | `#71717a` | Metadados técnicos, timestamps e cabeçalhos de tabela |
| `--cta-bg` / `--cta-fg` | `#f4f4f5` / `#09090b` | Botão de ação primária de alto contraste |
| `--emerald` | `#10b981` | Indicador semântico de queda de preço / meta atingida |
| `--danger` | `#ef4444` | Ações destrutivas (exclusão de monitoramento) |

---

## 3. Tipografia e Precisão Tabular

1. **Interface Geral (`--font-sans`):** `Inter` (`400`, `500`, `600`, `700`) — Garante leitura limpa em rótulos, títulos de produtos e modais.
2. **Dados e Cotações (`--font-mono`):** `JetBrains Mono` com `font-variant-numeric: tabular-nums` — Aplicada em todos os preços (`R$`), variações percentuais (`-18%`), timestamps (`DD/MM · HH:MM`) e contadores, assegurando alinhamento vertical perfeito.

---

## 4. Componentes e Padrões de Interação

- **Header de 3 Zonas:** Logotipo e indicador de status à esquerda, navegação principal centralizada e ações globais (*Alertas SMTP* e *Sincronizar*) à direita.
- **Metric Ledger Strip:** Barra superior contínua de 4 colunas separadas por linhas verticais de `1px`, apresentando os KPIs de monitoramento sem poluição visual.
- **Dual Numeric Controls (Slider + Input):** Todos os controles numéricos de configuração (Preço Alvo e Intervalo do Worker) possuem sincronização bidirecional instantânea entre `<input type="range">` e `<input type="number">`.
- **Microanimações em Puro CSS/JS:**
  - `.fx-shine`: Varredura translúcida sutil inclinada a `25°` nos botões primários.
  - `.fx-ripple`: Feedback tátil calculado a partir das coordenadas exatas do clique (`clientX`, `clientY`).
- **Responsividade Universal:** Colapso progressivo das grades multidimensionais nos breakpoints `@media (max-width: 992px)` e `@media (max-width: 600px)`.
