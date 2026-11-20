# sistema-correcao-cpe

Correção automática de provas por OMR (Optical Mark Recognition) e dashboards de
desempenho para professores. O sistema lê folhas de resposta escaneadas, corrige
contra o gabarito, guarda tudo em um banco de dados e mostra o desempenho por
aluno, turma, área e ao longo do tempo.

## Arquitetura

Três camadas, com fronteiras claras:

```
┌─────────────┐      HTTP/JSON      ┌──────────────────────────────┐
│   front/    │ ──────────────────> │            back/             │
│  Streamlit  │                     │                              │
│  (UI fina)  │ <────────────────── │  api/     FastAPI (HTTP)     │
└─────────────┘   long-format rows  │  grading/ pipeline OMR +     │
                                    │           ingestão           │
                                    │  db/      SQLAlchemy + banco │
                                    │  omrchecker/  motor OMR      │
                                    └────────────────┬─────────────┘
                                                     │
                                              ┌──────┴───────┐
                                              │  Banco de    │
                                              │  dados       │
                                              │ (SQLite /    │
                                              │  PostgreSQL) │
                                              └──────────────┘
``

- **`front/`** — aplicativo Streamlit voltado ao professor. Não acessa o banco
  direto: fala com o backend pela API HTTP. Contém os gráficos de sempre
  (desempenho por área e subárea, taxa de acerto por questão, ranking por
  aluno) mais a seção de evolução da turma no tempo.
- **`back/api/`** — serviço FastAPI. Expõe correção, resultados em formato longo
  e as respostas para as perguntas dos professores.
- **`back/grading/`** — roda o pipeline OMR sobre as imagens e transforma a
  planilha `ResultsByQuestion` em registros do banco.
- **`back/db/`** — modelos SQLAlchemy, sessão e camada de repositório
  (reutilizável pela API e por scripts). Migrações via Alembic.
- **`back/omrchecker/`** — o motor OMR (cópia do OMRChecker), no layout original
  do projeto e praticamente intocado: código em `omrchecker/src/`, mais as
  amostras, a documentação e a licença dele. Só `back/grading/pipeline.py`
  importa o motor.

### Modelo de dados

Relacional. As entidades: `Class` (turma) → `Student`; `Exam` (simulado, com data
e sequência para o eixo do tempo) → `Question` (carrega o gabarito + área/subárea)
e `Sheet` (a prova de um aluno) → `Answer` (o que o aluno marcou + veredito
correct/incorrect/unmarked). O gabarito mora junto das questões, não em um CSV.

As perguntas frequentes dos professores viram consultas diretas:

| Pergunta | Endpoint |
| --- | --- |
| Desempenho de um aluno numa área | `GET /performance/student-subject` |
| Desempenho de um aluno num simulado | `GET /performance/student-exam` |
| Desempenho da turma num simulado | `GET /performance/class-exam` |
| A turma está melhorando com o tempo? | `GET /trends/class/{class_id}` |

## Como rodar

Pré-requisitos: Python 3.12 (a versão das imagens Docker e a usada nos testes) e o stack do OMRChecker (OpenCV etc.) para a correção
de imagens. Ver `back/omrchecker/README.md` para as dependências de sistema do OpenCV.

O backend e o frontend são serviços separados e cada um usa seu próprio ambiente
virtual (eles pedem versões incompatíveis de `starlette`, então não compartilham
o mesmo venv). Os exemplos usam [`uv`](https://docs.astral.sh/uv/); com o `venv`
padrão do Python funciona igual (`python3 -m venv .venv` + `pip install`), desde
que o pacote `python3-venv` esteja instalado.

### 1. Backend (API + banco)

```bash
cd back
uv venv .venv                       # cria o ambiente isolado (sem mexer no Python do sistema)
source .venv/bin/activate
uv pip install -r requirements.txt -r requirements-dev.txt

# Cria/atualiza o banco. Sem CPE_DATABASE_URL, usa um SQLite local (back/cpe_omr.db)
alembic upgrade head

# Sobe a API em http://localhost:8001 (porta padrão do projeto)
python -m api.app
# ou, escolhendo a porta explicitamente:
#   uvicorn api.app:app --reload --port 8001
```

Para usar PostgreSQL em vez de SQLite, basta apontar a variável de ambiente antes
de rodar o Alembic e o uvicorn (nenhuma mudança de código):

```bash
export CPE_DATABASE_URL="postgresql+psycopg://user:senha@host:5432/cpe"
```

### 2. Frontend (Streamlit)

Em outro terminal, com seu próprio ambiente:

```bash
cd front
uv venv .venv
source .venv/bin/activate
uv pip install -r requirements.txt -r requirements-dev.txt

# A API padrão é http://localhost:8001. Se usar outra, informe aqui:
#   export CPE_API_URL="http://localhost:8001"

streamlit run app.py
```

No app, o menu lateral leva às seções: **Correção** para enviar o gabarito e as
imagens das provas; **Dashboard** para o desempenho do simulado escolhido;
**Evolução** para acompanhar a turma ao longo dos simulados; **Dados e
downloads** para as tabelas, as exportações (incluindo o `ResultsByQuestion.csv`
bruto) e as folhas com a leitura marcada, para conferência visual.

## Como corrigir uma prova

1. **Gabarito:** envie uma planilha `.csv` ou `.xlsx` com uma coluna de questão e
   outra de resposta correta. As colunas são reconhecidas pelo nome:
   - questão: o nome deve conter `Questão`, `question`, `nº` ou `número`;
   - resposta: o nome deve conter `Gabarito`, `resposta`, `correta` ou `answer`.

   Os valores da coluna de questão precisam ser **`q1`, `q2`, `q3`…**, os mesmos
   rótulos do template. Colunas extras, como `Área` e `Sub-Área`, são
   aproveitadas no dashboard.

   | Questão | Gabarito | Área | Sub-Área |
   |---|---|---|---|
   | q1 | E | Matemática | Funções |
   | q2 | B | Física | Cinemática |

2. **Tamanho da prova:** escolha **72, 80 ou 90 questões**. O app já sugere a
   opção que bate com o número de linhas do gabarito enviado.

   | Opção | Folha impressa | Exemplo |
   |---|---|---|
   | 72 questões | folha de 90, lida só até a q72 | UNICAMP 1ª fase |
   | 80 questões | folha de 80 | FUVEST |
   | 90 questões | folha de 90 | UNESP 1ª fase |

   Se o gabarito tiver questões que a folha escolhida não tem (por exemplo,
   `q85` numa prova de 80, ou números sem o `q`), o app mostra o erro e bloqueia
   a correção (a API também recusa, com 422). Se a folha tiver questões que
   faltam no gabarito, o app só avisa.

3. **Provas escaneadas:** envie as imagens das folhas em `.jpg`, `.jpeg` ou
   `.png`. O nome do arquivo vira o nome do aluno (`Beatriz_Venancio_Bezerra.jpg`
   aparece como "Beatriz Venancio Bezerra"); ajuste os nomes e informe a turma na
   tabela antes de corrigir.
4. Clique em **Corrigir provas** e veja o resultado em **Dashboard** e **Dados e
   downloads**.

### Cuidados no scan

Antes de ler as bolhas, o sistema localiza os **4 marcadores pretos em forma de
"L" nos cantos da folha** e alinha a imagem por eles. Por isso, o mesmo template
funciona mesmo que a folha saia deslocada, girada ou com tamanho diferente no
scanner.

- **Os 4 marcadores dos cantos precisam aparecer inteiros na imagem.** Se o scan
  cortar algum, a folha não é corrigida e o log da correção traz
  `Corner marks not found`. Nesse caso, escaneie a folha de novo.
- Use uma resolução de pelo menos 150 dpi. Tons de cinza ou colorido funcionam.
- Rabiscos ou manchas perto dos cantos podem atrapalhar a localização dos
  marcadores.

### Se o modelo da folha mudar

Os templates em [back/folha-cpe/](back/folha-cpe/) (`template_72.json`,
`template_80.json`, `template_90.json` e o `config.json`) descrevem onde ficam
as bolhas, com coordenadas medidas a partir dos marcadores dos cantos. Medidas
assim, as folhas de 80 e de 90 têm as bolhas nas mesmas posições; a de 90 só
acrescenta o bloco 81–90. Eles valem para qualquer scan **destas** folhas e só
precisam ser refeitos se o layout impresso mudar.

Para um tamanho novo de prova que use uma das folhas atuais, crie um
`template_N.json` com os blocos certos e acrescente `N` em `QUESTION_COUNTS`, em
[back/grading/sheets.py](back/grading/sheets.py) e em
[front/app.py](front/app.py).

O alinhamento pelos cantos é feito pelo pré-processador
[CropOnCornerMarks](back/omrchecker/src/processors/CropOnCornerMarks.py), ativado no
template pela seção `preProcessors`. Para conferir um template, rode a correção
pela linha de comando (em `back/omrchecker/`: `python main.py -i pasta -o saida`, com o template
copiado para a pasta como `template.json`) e abra as imagens de
`saida/CheckedOMRs/`: cada marcação lida deve ficar sobre a bolha correspondente.

## Variáveis de ambiente

| Variável | Onde | Padrão | Para quê |
| --- | --- | --- | --- |
| `CPE_DATABASE_URL` | back | `sqlite:///back/cpe_omr.db` | Conexão do banco (troque para PostgreSQL sem mexer no código) |
| `CPE_ARTIFACTS_DIR` | back | `back/outputs/gradings` | Onde ficam o `ResultsByQuestion.csv` e as folhas marcadas de cada simulado |
| `CPE_API_HOST` | back | `127.0.0.1` | Host em que a API escuta (`python -m api.app`) |
| `CPE_API_PORT` | back | `8001` | Porta em que a API escuta (`python -m api.app`) |
| `CPE_API_URL` | front | `http://localhost:8001` | URL do backend que o Streamlit consome |

## Testes

Com cada venv ativado (ver acima):

```bash
# Backend (banco, grading, api)
cd back && python -m pytest

# Frontend (gráficos + app)
cd front && python -m pytest tests

# Suite do motor OMR (precisa do stack OpenCV; roda de dentro da pasta dele)
cd back/omrchecker && python -m pytest
```

> As amostras em `back/omrchecker/src/tests/test_all_samples.py` comparam a saída do pipeline com
> snapshots (`syrupy`). O nome dos arquivos de saída inclui a hora local, então
> `src/tests/conftest.py` fixa o fuso em que os snapshots foram gravados. Depois
> de uma mudança intencional no formato de saída, regrave com
> `python -m pytest --snapshot-update` (em `back/omrchecker/`) e revise o diff.

## Migrações do banco

O schema é gerenciado **exclusivamente** pelo Alembic. A API nunca cria tabelas
sozinha, então `alembic upgrade head` é sempre a forma de preparar o banco.

```bash
cd back
alembic upgrade head                         # aplica as migrações
alembic revision --autogenerate -m "mudança" # gera uma nova após editar db/models.py
alembic downgrade -1                          # desfaz a última
```

### "table ... already exists" ao rodar upgrade

Se você tem um banco criado por uma versão antiga (quando a API ainda criava as
tabelas na inicialização), ele tem as tabelas mas a `alembic_version` vazia.
Marque-o como já migrado uma única vez e siga normalmente:

```bash
alembic stamp head
alembic upgrade head
```
