# sistema-correcao-cpe

Correção automática das folhas de resposta (gabarito de bolinhas) dos simulados da CPE. Você envia o gabarito e as folhas escaneadas, o sistema lê as marcações, calcula a nota de cada aluno e monta um dashboard com os resultados.

Por baixo, o sistema usa o [OMRChecker](https://github.com/Udayraj123/OMRChecker), adaptado para a folha da CPE. Todo o código fica em [back/](back/).

## Requisitos

- Python 3.11
- As dependências de [back/requirements.txt](back/requirements.txt)

## Instalação (uma vez só)

No terminal, a partir da raiz do repositório:

```bash
cd back
python -m venv .venv

# Windows (PowerShell)
.venv\Scripts\Activate.ps1
# Linux / macOS
source .venv/bin/activate

pip install -r requirements.txt
```

O app lê os templates da folha e a configuração direto de [back/folha-cpe/](back/folha-cpe/). Não é preciso copiar nada.

## Como rodar o app web

Com o ambiente ativado, a partir da pasta `back/`:

```bash
streamlit run webapp/streamlit_app.py
```

O navegador abre em http://localhost:8501. Se não abrir, acesse esse endereço manualmente. Para encerrar, use `Ctrl+C` no terminal.

### Como corrigir uma prova

1. **Gabarito:** envie uma planilha `.csv` ou `.xlsx` com uma coluna de questão e outra de resposta correta. O app reconhece as colunas pelo nome:
   - questão: o nome deve conter `Questão`, `question`, `nº` ou `número`;
   - resposta: o nome deve conter `Gabarito`, `resposta`, `correta` ou `answer`.

   Os valores da coluna de questão precisam ser **`q1`, `q2`, `q3`…**, os mesmos rótulos do template. Colunas extras, como `Área` e `Sub-Área`, são aproveitadas no dashboard.

   | Questão | Gabarito | Área | Sub-Área |
   |---|---|---|---|
   | q1 | E | Matemática | Funções |
   | q2 | B | Física | Cinemática |

2. **Tamanho da prova:** escolha **72, 80 ou 90 questões**. O app já sugere a opção que bate com o número de linhas do gabarito enviado.

   | Opção | Folha impressa | Exemplo |
   |---|---|---|
   | 72 questões | folha de 90, lida só até a q72 | UNICAMP 1ª fase |
   | 80 questões | folha de 80 | FUVEST |
   | 90 questões | folha de 90 | UNESP 1ª fase |

   Se o gabarito tiver questões que a folha escolhida não tem (por exemplo, `q85` numa prova de 80, ou números sem o `q`), o app mostra o erro e bloqueia a correção. Se a folha tiver questões que faltam no gabarito, o app só avisa.

3. **Provas escaneadas:** envie as imagens das folhas em `.jpg`, `.jpeg` ou `.png`. O nome do arquivo vira o nome do aluno (`Beatriz_Venancio_Bezerra.jpg` aparece como "Beatriz Venancio Bezerra"), e você pode corrigir os nomes na tela depois.
4. Clique em **Corrigir provas**. Em seguida, veja o resultado nas seções **Dashboard** e **Dados e downloads**.

## Cuidados no scan

Antes de ler as bolhas, o sistema localiza os **4 marcadores pretos em forma de "L" nos cantos da folha** e alinha a imagem por eles. Por isso, o mesmo template funciona mesmo que a folha saia deslocada, girada ou com tamanho diferente no scanner.

- **Os 4 marcadores dos cantos precisam aparecer inteiros na imagem.** Se o scan cortar algum, a folha não é corrigida e aparece um erro com a mensagem `Corner marks not found`. Nesse caso, escaneie a folha de novo.
- Use uma resolução de pelo menos 150 dpi. Tons de cinza ou colorido funcionam.
- Rabiscos ou manchas perto dos cantos podem atrapalhar a localização dos marcadores.

## Rodar pela linha de comando (sem o app)

Útil para corrigir uma pasta inteira ou investigar um problema. Coloque na mesma pasta:

- as imagens;
- o template do tamanho da prova, copiado de `folha-cpe/template_72.json`, `template_80.json` ou `template_90.json` e **renomeado para `template.json`**;
- o `folha-cpe/config.json`;
- se quiser a nota, o `evaluation.json` com o gabarito.

Depois rode, a partir de `back/`:

```bash
python main.py -i caminho/da/pasta -o caminho/da/saida
```

Os resultados ficam em:

- `saida/Results/`: respostas e nota de cada folha (`.csv`);
- `saida/CheckedOMRs/`: as folhas com as marcações lidas desenhadas por cima, para conferência visual;
- `saida/Manual/ErrorFiles/`: folhas que não puderam ser lidas, por exemplo com um marcador de canto cortado.

## Se o modelo da folha mudar

Os templates em [back/folha-cpe/](back/folha-cpe/) descrevem onde ficam as bolhas, com coordenadas medidas a partir dos marcadores dos cantos. Medidas assim, as folhas de 80 e de 90 têm as bolhas exatamente nas mesmas posições; a de 90 só acrescenta o bloco 81–90. Por isso, os três templates compartilham as mesmas coordenadas e diferem apenas nos blocos de questões.

Eles valem para qualquer scan **destas** folhas. Só precisam ser refeitos se o layout impresso mudar, por exemplo com colunas em outra posição ou uma folha de outro fornecedor. Para um tamanho novo de prova que use uma das folhas atuais, basta criar um `template_N.json` com os blocos certos e acrescentar `N` em `QUESTION_COUNTS`, em [back/webapp/streamlit_app.py](back/webapp/streamlit_app.py).

Para conferir se o template está certo, rode a correção pela linha de comando e abra as imagens de `CheckedOMRs/`: cada marcação lida deve ficar exatamente sobre a bolha correspondente.

O alinhamento pelos cantos é feito pelo pré-processador [CropOnCornerMarks](back/src/processors/CropOnCornerMarks.py), ativado no template pela seção `preProcessors`.
