# Marca

Coloque aqui os arquivos do logo CPE USP. O app procura por, nesta ordem:

| Uso | Nomes aceitos (qualquer extensão `.png`, `.jpg`, `.svg`, `.webp`) |
|---|---|
| Logo completo (cabeçalho) | `logo`, `logo-cpe`, `cpe-usp`, `cpe` |
| Símbolo isolado (favicon / ícone recolhido) | `simbolo`, `symbol`, `icone`, `icon`, `mark` |

Exemplo: `logo.png` e `simbolo.png`.

Sem esses arquivos o app funciona normalmente — cai no título em texto e no
ícone `🖊️`. Nada no código depende da presença da marca.

A paleta e as fontes não vivem aqui: ficam em `../.streamlit/config.toml`
(interface) e em `../webapp/dashboard.py` (gráficos).
