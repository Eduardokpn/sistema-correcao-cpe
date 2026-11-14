# Backend

Duas coisas moram aqui: o aplicativo do CPE e, dentro de `omrchecker/`, o motor
de leitura de folhas (uma cópia do projeto aberto OMRChecker).

| Pasta | O que é |
| --- | --- |
| `api/` | Serviço FastAPI. `app.py` monta o app; as rotas ficam em `api/routers/` (uma por área) e os contratos JSON em `schemas.py`. |
| `grading/` | Correção: escolhe o template da folha (`sheets.py`), roda o motor (`pipeline.py`, `bridge.py`), interpreta a planilha de resultados (`results.py`), grava no banco (`ingest.py`) e guarda os arquivos de cada correção (`artifacts.py`). |
| `db/` | Modelos SQLAlchemy, sessão, migrações Alembic e a camada de repositório (`db/repositories/`: `writes.py`, `queries.py`, `stats.py`). |
| `folha-cpe/` | Templates das folhas de resposta do CPE (72, 80 e 90 questões). |
| `assets/` | Logos do CPE, usados pelo front como reserva. |
| `samples/demo-test/` | Planilhas de exemplo para popular o banco sem imagens. |
| `omrchecker/` | O motor OMR, no layout original do OMRChecker (`src/`, `main.py`, amostras, docs, licença). Não é editado no dia a dia; só `grading/pipeline.py` o importa. |

As dependências apontam em uma direção só: `api` → `grading` → `db`, e
`grading` → `omrchecker`.

## Rodar

```bash
cd back
python -m db.migrate     # cria/atualiza o banco
python -m api.app        # API em http://localhost:8001
```

## Testes

```bash
cd back && python -m pytest              # db, grading e api
cd back/omrchecker && python -m pytest   # suíte do motor OMR
```

Instalação, variáveis de ambiente e deploy estão no [README da raiz](../README.md).
