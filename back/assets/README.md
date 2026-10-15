# Marca

Coloque aqui os arquivos do logo CPE USP. O app procura por, nesta ordem:

| Uso | Nomes aceitos (qualquer extensão `.png`, `.jpg`, `.svg`, `.webp`) |
|---|---|
| Logo completo | `logo`, `logo-cpe`, `cpe-usp`, `cpe` |
| Símbolo isolado (favicon / ícone recolhido) | `simbolo`, `symbol`, `icone`, `icon`, `mark` |
| Logo da sidebar, sobre o azul escuro | `logo-laranja`, `logo-claro`, `17` |

Exemplo: `logo.png` e `simbolo.png`.

A sidebar precisa da versão laranja porque o logo padrão é azul escuro e
desapareceria no fundo. Hoje esse arquivo é o `17.png` do kit; renomeando para
`logo-laranja.png` ele continua sendo encontrado. Sem nenhum dos três nomes a
sidebar cai no logo completo.

Sem esses arquivos o app funciona normalmente — cai no título em texto e no
ícone `🖊️`. Nada no código depende da presença da marca.

A paleta e as fontes não vivem aqui: ficam em `../.streamlit/config.toml`
(interface) e em `../webapp/dashboard.py` (gráficos).
