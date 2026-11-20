# Sample para teste rápido

Este diretório contém exemplos de dados para testar a aplicação sem precisar
de imagens de provas escaneadas.

## gabarito.csv

Planilha com o gabarito do simulado (colunas obrigatórias: `questão`, `resposta`).
Opcionalmente inclua `área` e `subárea` para desagregar o desempenho.

## ResultsByQuestion.csv

Planilha de respostas pronta para ser importada no banco. O formato é:

- `question` — identificador da questão (ex.: q1, q2…)
- `Área`, `Subárea`, `Gabarito` — meta-dados (copiados do gabarito, mas aqui
  cada linha pode repeti-los)
- Colunas com nomes de arquivo (ex.: `aluno1.png`) → cada uma é uma prova
- Células com os vereditos: `correct-X`, `incorrect-X`, `unmarked`

### Como testar com ResultsByQuestion.csv

1. Certifique-se que a API está rodando:

   ```bash
   cd back && source .venv/bin/activate && python -m api.app
   ```

2. Importe o sample via a API:

   ```bash
   # No terminal, na raiz do projeto:
   curl -X POST http://localhost:8001/gradings/results-csv \
     -F "results_csv=@back/samples/demo-test/ResultsByQuestion.csv" \
     -F "exam_name=Demo 1" \
     -F "sequence=1" \
     -F "applied_on=2026-10-02" \
     -F 'student_names={"aluno1.png":"Ana Silva","aluno2.png":"Bruno Lima","aluno3.png":"Carla Oliveira"}' \
     -F 'student_classes={"aluno1.png":"3A","aluno2.png":"3A","aluno3.png":"3A"}' \
     -F 'class_turnos={"3A":"vespertino"}'
   ```

3. No frontend, selecione o simulado "Demo 1" no dashboard para ver os gráficos.

4. Teste os filtros e a aba "Evolução" (adicione outro simulado e compare).

### Como testar com imagens reais

Se você tiver imagens escaneadas das provas:

1. Coloque-as em `samples/demo-test/` com nomes semelhantes (`aluno1.png`, etc.)
2. Garanta que `inputs/template.json` exista (copie de outro sample existente)
3. Use a aba "Correção" do frontend para carregar o gabarito e as imagens

---

Para mais exemplos, veja `back/omrchecker/samples/` (o OMRChecker traz
diversos samples com template e imagens reais).

## ResultsByQuestion_2.csv

Demo 2 com desempenho melhorado para ilustrar a evolução da turma:

- Ana Silva: subiu de 2/5 para 3/5 acertos (40% → 60%)
- Bruno Lima: manteve 3/5 (60%)
- Carla Oliveira: subiu de 1/5 para 2/5 acertos (20% → 40%)

**Turma no Demo 2:** 8/15 = 53.3% (vs 46.7% no Demo 1)

Importe assim:

```bash
curl -X POST http://localhost:8001/gradings/results-csv \
  -F "results_csv=@back/samples/demo-test/ResultsByQuestion_2.csv" \
  -F "exam_name=Demo 2" \
  -F "sequence=2" \
  -F "applied_on=2026-11-02" \
  -F 'student_names={"aluno1.png":"Ana Silva","aluno2.png":"Bruno Lima","aluno3.png":"Carla Oliveira"}' \
  -F 'student_classes={"aluno1.png":"3A","aluno2.png":"3A","aluno3.png":"3A"}' \
  -F 'class_turnos={"3A":"vespertino"}'
```

---

Para mais exemplos, veja `back/omrchecker/samples/` (o OMRChecker traz
diversos samples com template e imagens reais).
