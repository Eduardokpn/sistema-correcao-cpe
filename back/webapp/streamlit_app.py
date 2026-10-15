"""Interface web do OMRChecker.

Fluxo: envia o gabarito + o template + as provas -> corrige com o mesmo pipeline
do main.py -> exporta a planilha ResultsByQuestion -> monta o dashboard.

Uso, a partir da raiz do back/: streamlit run webapp/streamlit_app.py
"""
import base64
import io
import shutil
from pathlib import Path

import pandas as pd
import streamlit as st

from webapp import dashboard
from webapp.pipeline import (
    ACERTO,
    ERRO,
    NAO_RESPONDEU,
    QUESTION_COLUMN,
    DEFAULT_MARKING,
    SUPPORTED_IMAGE_EXTENSIONS,
    CorrectionError,
    guess_meta_columns,
    load_results_by_question,
    run_correction,
    split_scores,
    student_columns,
    student_name_from_file,
    summarize_students,
    to_long_format,
)

# Este módulo vive em back/webapp/, mas inputs/ e assets/ ficam na raiz do back/
PROJECT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_INPUTS_DIR = PROJECT_DIR.joinpath("inputs")
ASSETS_DIR = PROJECT_DIR.joinpath("assets")
# A folha de resposta é sempre a mesma, então template e config saem da tela e
# são lidos direto de inputs/
TEMPLATE_PATH = DEFAULT_INPUTS_DIR.joinpath("template.json")
CONFIG_PATH = DEFAULT_INPUTS_DIR.joinpath("config.json")

# Paleta da marca. O azul escuro é a superfície da sidebar; o laranja é o único
# acento, e fica só na moldura (régua, item ativo, botão de ação) - dentro dos
# gráficos ele já significa "erro", e webapp/dashboard.py é dono desse uso.
ORANGE = "#ef7b17"
ORANGE_STRONG = "#d96e10"
SIDEBAR_TOP = "#11385c"
SIDEBAR_BOTTOM = "#0b2947"

# Tokens que mudam com o tema. O corpo da página fica no cinza claro do
# config.toml; aqui entram só as superfícies desenhadas por cima dele.
MODE_TOKENS = {
    "light": {
        "surface": "#ffffff",
        "border": "rgba(17,56,92,0.12)",
        "muted": "#4a5a6e",
    },
    "dark": {
        "surface": "#14263a",
        "border": "rgba(232,238,244,0.14)",
        "muted": "#a8bacd",
    },
}
# A sidebar é azul escura nos dois temas, então o contraste do texto sobre ela
# não depende do modo
SHARED_TOKENS = {
    "orange": ORANGE,
    "orange-strong": ORANGE_STRONG,
    "sidebar-top": SIDEBAR_TOP,
    "sidebar-bottom": SIDEBAR_BOTTOM,
    "on-sidebar": "#d7e5f3",
    "on-sidebar-dim": "#8fb4d8",
}


def brand_asset(*stems):
    """Primeiro arquivo de assets/ que casa com um dos nomes, ou None.

    A marca não fica no repositório, então nada aqui pode depender dela: sem os
    arquivos o app cai no título em texto e segue funcionando.
    """
    if not ASSETS_DIR.exists():
        return None
    for stem in stems:
        for path in sorted(ASSETS_DIR.glob(f"{stem}.*")):
            if path.suffix.lower() in (".png", ".jpg", ".jpeg", ".svg", ".webp"):
                return path
    return None


LOGO_FULL = brand_asset("logo", "logo-cpe", "cpe-usp", "cpe")
LOGO_MARK = brand_asset("simbolo", "symbol", "icone", "icon", "mark")
# A sidebar é azul escura, então quem vai para lá é a versão laranja da marca.
# "17" é o nome que ela tem no kit; os dois primeiros ficam valendo para quando
# o arquivo for renomeado, e sem nenhum dos três o logo padrão assume.
LOGO_SIDEBAR = brand_asset("logo-laranja", "logo-claro", "17") or LOGO_FULL

QUESTION_COLUMN_HINTS = ["questão", "questao", "question", "nº", "numero", "número"]
ANSWER_COLUMN_HINTS = ["gabarito", "answer", "resposta", "correta"]
AREA_HINTS = ["área", "area"]
SUBAREA_HINTS = ["sub-área", "subárea", "sub-area", "subarea", "sub área", "assunto"]

# Ordem do menu na sidebar e o cabeçalho de cada seção
SECOES = {
    "correcao": {
        "titulo": "Correção",
        "icone": ":material/edit_document:",
        "descricao": "Envie o gabarito e as provas escaneadas e corrija tudo de uma vez.",
    },
    "dashboard": {
        "titulo": "Dashboard",
        "icone": ":material/insert_chart:",
        "descricao": "Acompanhe o desempenho da turma por área, questão e aluno.",
    },
    "dados": {
        "titulo": "Dados e downloads",
        "icone": ":material/download:",
        "descricao": "Confira as planilhas geradas e baixe os resultados.",
    },
}

st.set_page_config(
    page_title="Corretor de Provas OMR",
    page_icon=str(LOGO_MARK or LOGO_FULL) if (LOGO_MARK or LOGO_FULL) else "🖊️",
    layout="wide",
    initial_sidebar_state="expanded",
)


# --------------------------------------------------------------------------- #
# Identidade visual
# --------------------------------------------------------------------------- #
# As fontes da marca vêm do Google Fonts; o config.toml já as declara para os
# componentes do Streamlit, e o @import cobre o que é desenhado em HTML aqui.
CSS = """
@import url('https://fonts.googleapis.com/css2?family=League+Spartan:wght@600;700&family=Open+Sans:wght@400;600;700&display=swap');

/* ------------------------------- sidebar ------------------------------- */
[data-testid="stSidebar"] {
    background: linear-gradient(180deg, var(--cpe-sidebar-top) 0%, var(--cpe-sidebar-bottom) 100%);
    border-right: 3px solid var(--cpe-orange);
}
/* O menu é o único conteúdo da sidebar, então clarear tudo de uma vez é
   suficiente - as regras dos botões abaixo têm especificidade maior. */
[data-testid="stSidebar"] * { color: var(--cpe-on-sidebar); }
[data-testid="stSidebarHeader"] { padding-bottom: 0; }
[data-testid="stSidebarUserContent"] { padding-top: 0.5rem; }

/* A marca laranja tem contraste suficiente para ficar direto sobre o azul, sem
   cartão nenhum por baixo. */
.cpe-brand { padding: 0.4rem 0.5rem; text-align: center; }
.cpe-brand img { width: 100%; max-width: 150px; display: block; margin: 0 auto; }
.cpe-brand span {
    font-family: 'League Spartan', sans-serif; font-weight: 700;
    font-size: 1.5rem; letter-spacing: -0.01em; color: var(--cpe-orange);
}
.cpe-rule {
    height: 3px; border-radius: 2px; background: var(--cpe-orange);
    margin: 1rem 0 1.3rem 0;
}
.cpe-nav-label {
    font-family: 'Open Sans', sans-serif; font-size: 0.72rem; font-weight: 700;
    letter-spacing: 0.14em; text-transform: uppercase;
    color: var(--cpe-on-sidebar-dim); margin: 0 0 0.45rem 0.15rem;
}
.cpe-foot {
    margin-top: 1.6rem; padding-top: 0.9rem;
    border-top: 1px solid rgba(255, 255, 255, 0.14);
    font-family: 'Open Sans', sans-serif; font-size: 0.75rem; line-height: 1.5;
    color: var(--cpe-on-sidebar-dim);
}

/* Menu: botões sem moldura, com a barra laranja marcando o item ativo */
[data-testid="stSidebar"] [data-testid^="stBaseButton-"] {
    font-family: 'Open Sans', sans-serif; font-weight: 600; font-size: 0.95rem;
    padding: 0.55rem 0.85rem;
    background: transparent;
    border: 1px solid transparent;
    border-left: 4px solid transparent;
    border-radius: 8px;
    box-shadow: none;
    transition: background 120ms ease, border-color 120ms ease;
}
/* O rótulo mora em um filho que ocupa a largura toda, então o alinhamento à
   esquerda precisa valer para o botão e para esse filho */
[data-testid="stSidebar"] [data-testid^="stBaseButton-"],
[data-testid="stSidebar"] [data-testid^="stBaseButton-"] > div {
    justify-content: flex-start;
    text-align: left;
}
[data-testid="stSidebar"] [data-testid^="stBaseButton-"]:hover {
    background: rgba(255, 255, 255, 0.08);
    border-left-color: rgba(239, 123, 23, 0.55);
}
[data-testid="stSidebar"] [data-testid="stBaseButton-secondary"],
[data-testid="stSidebar"] [data-testid="stBaseButton-secondary"] p { color: #c6d9ec; }
[data-testid="stSidebar"] [data-testid^="stBaseButton-primary"],
[data-testid="stSidebar"] [data-testid^="stBaseButton-primary"] p { color: #ffffff; }
[data-testid="stSidebar"] [data-testid^="stBaseButton-primary"] {
    background: rgba(255, 255, 255, 0.13);
    border-left-color: var(--cpe-orange);
}
[data-testid="stSidebar"] [data-testid^="stBaseButton-primary"]:hover {
    background: rgba(255, 255, 255, 0.18);
    border-left-color: var(--cpe-orange);
}

/* -------------------------------- corpo -------------------------------- */
/* O padding do topo precisa continuar livrando a barra de ferramentas do
   Streamlit, senão a linha de apoio do cabeçalho fica cortada */
[data-testid="stMainBlockContainer"] { padding-top: 3.6rem; max-width: 1400px; }

.cpe-header {
    border-left: 6px solid var(--cpe-orange);
    padding: 0.2rem 0 0.2rem 1rem;
    margin-bottom: 1.4rem;
}
.cpe-header .cpe-eyebrow {
    font-family: 'Open Sans', sans-serif; font-size: 0.72rem; font-weight: 700;
    letter-spacing: 0.14em; text-transform: uppercase; color: var(--cpe-orange);
    margin: 0 0 0.15rem 0;
}
.cpe-header h1 {
    font-family: 'League Spartan', sans-serif; font-weight: 700;
    font-size: 2.1rem; line-height: 1.1; letter-spacing: -0.01em; margin: 0;
}
.cpe-header p.cpe-sub {
    font-family: 'Open Sans', sans-serif; font-size: 0.95rem;
    color: var(--cpe-muted); margin: 0.3rem 0 0 0;
}

/* O quadradinho laranja marca o início de cada bloco da seção */
[data-testid="stMain"] h3::before {
    content: ""; display: inline-block; vertical-align: middle;
    width: 9px; height: 9px; border-radius: 2px;
    background: var(--cpe-orange); margin-right: 0.6rem;
}

[data-testid="stMetric"] {
    background: var(--cpe-surface);
    border: 1px solid var(--cpe-border);
    border-radius: 10px;
    padding: 0.85rem 1rem;
    /* só o card de "Respostas" tem a linha de apoio - sem isso os quatro
       ficam com alturas diferentes */
    height: 100%;
}
[data-testid="stMetricLabel"] p { font-weight: 600; color: var(--cpe-muted); }

[data-testid="stFileUploaderDropzone"] {
    background: var(--cpe-surface);
    border: 1.5px dashed var(--cpe-border);
    border-radius: 10px;
}

/* A ação principal de cada seção é o único laranja cheio da tela */
[data-testid="stMain"] [data-testid^="stBaseButton-primary"] {
    background: var(--cpe-orange);
    border-color: var(--cpe-orange);
}
[data-testid="stMain"] [data-testid^="stBaseButton-primary"],
[data-testid="stMain"] [data-testid^="stBaseButton-primary"] p { color: #ffffff; }
[data-testid="stMain"] [data-testid^="stBaseButton-primary"]:hover:not(:disabled) {
    background: var(--cpe-orange-strong);
    border-color: var(--cpe-orange-strong);
}
[data-testid="stMain"] [data-testid^="stBaseButton-primary"]:disabled { opacity: 0.45; }
"""


def theme_mode():
    try:
        if st.context.theme.type == "dark":
            return "dark"
        return "light"
    except Exception:
        return "dark" if st.get_option("theme.base") == "dark" else "light"


@st.cache_data(show_spinner=False)
def image_data_uri(path):
    """Logo embutido no HTML - st.image não alcança o cartão da sidebar."""
    suffix = Path(path).suffix.lower().lstrip(".")
    mime = "svg+xml" if suffix == "svg" else {"jpg": "jpeg"}.get(suffix, suffix)
    encoded = base64.b64encode(Path(path).read_bytes()).decode("ascii")
    return f"data:image/{mime};base64,{encoded}"


MODE = theme_mode()
st.markdown(
    "<style>:root{"
    + "".join(
        f"--cpe-{name}:{value};"
        for name, value in {**SHARED_TOKENS, **MODE_TOKENS[MODE]}.items()
    )
    + "}"
    + CSS
    + "</style>",
    unsafe_allow_html=True,
)


def pick_column(columns, hints, exclude=()):
    """First column whose name looks like one of the hints."""
    for hint in hints:
        for column in columns:
            if column in exclude:
                continue
            if hint in str(column).strip().lower():
                return column
    return None


def read_answer_key(uploaded_file):
    """Reads the answer key from a csv (any common separator) or xlsx upload."""
    suffix = Path(uploaded_file.name).suffix.lower()
    if suffix in (".xlsx", ".xls"):
        answer_key = pd.read_excel(uploaded_file, dtype=str)
    else:
        answer_key = pd.read_csv(
            io.BytesIO(uploaded_file.getvalue()),
            sep=None,
            engine="python",
            encoding="utf-8-sig",
            dtype=str,
            keep_default_na=False,
        )
    answer_key.columns = [str(column).strip() for column in answer_key.columns]
    return answer_key.fillna("").apply(lambda column: column.astype(str).str.strip())


def csv_download(dataframe):
    return dataframe.to_csv(index=False).encode("utf-8-sig")


def students_frame(columns, previous=None):
    """Editable table mapping each uploaded sheet to a student name and turma."""
    previous = previous if previous is not None else pd.DataFrame()
    known = (
        previous.set_index("Arquivo").to_dict("index")
        if "Arquivo" in previous.columns
        else {}
    )
    return pd.DataFrame(
        [
            {
                "Arquivo": column,
                "Nome do Aluno": known.get(column, {}).get(
                    "Nome do Aluno", student_name_from_file(column)
                ),
                "Turma": known.get(column, {}).get("Turma", "Não informado"),
            }
            for column in columns
        ]
    )


def name_and_group_maps(students):
    if students is None or students.empty:
        return {}, {}
    names = dict(zip(students["Arquivo"], students["Nome do Aluno"]))
    groups = dict(zip(students["Arquivo"], students["Turma"]))
    return names, groups


def store_results(results_by_question, scores, correction=None):
    """Keeps one active result set - from a correction run or an upload."""
    previous = st.session_state.get("correction")
    if previous is not None and previous.work_dir and previous is not correction:
        shutil.rmtree(previous.work_dir, ignore_errors=True)

    st.session_state["correction"] = correction
    st.session_state["results_by_question"] = results_by_question
    st.session_state["scores"] = scores
    st.session_state["meta_columns"] = guess_meta_columns(results_by_question, scores)
    st.session_state["students"] = students_frame(
        student_columns(results_by_question, st.session_state["meta_columns"]),
        st.session_state.get("students"),
    )
    # O recorte dos filtros é do conjunto anterior: com a navegação por menu a
    # aba de dados pode ser aberta antes do dashboard rodar de novo
    st.session_state.pop("filtered_results", None)


# --------------------------------------------------------------------------- #
# Sidebar: marca + navegação
# --------------------------------------------------------------------------- #
def select_section(slug):
    st.session_state["secao"] = slug


st.session_state.setdefault("secao", next(iter(SECOES)))

with st.sidebar:
    if LOGO_SIDEBAR:
        brand = f'<img src="{image_data_uri(str(LOGO_SIDEBAR))}" alt="CPE USP">'
    else:
        brand = "<span>CPE USP</span>"
    st.markdown(
        f'<div class="cpe-brand">{brand}</div><div class="cpe-rule"></div>',
        unsafe_allow_html=True,
    )

    st.markdown('<p class="cpe-nav-label">Navegação</p>', unsafe_allow_html=True)
    for slug, secao in SECOES.items():
        st.button(
            secao["titulo"],
            key=f"nav_{slug}",
            icon=secao["icone"],
            # O tipo primário é o que marca o item ativo: mesmo que o CSS não
            # aplique, o tema do Streamlit ainda distingue os dois estados
            type="primary" if st.session_state["secao"] == slug else "secondary",
            width="stretch",
            on_click=select_section,
            args=(slug,),
        )

    st.markdown(
        '<div class="cpe-foot">Corretor de Provas OMR<br>CPE USP</div>',
        unsafe_allow_html=True,
    )

SECAO = st.session_state["secao"]
st.markdown(
    f"""
    <div class="cpe-header">
      <p class="cpe-eyebrow">Corretor de Provas OMR</p>
      <h1>{SECOES[SECAO]["titulo"]}</h1>
      <p class="cpe-sub">{SECOES[SECAO]["descricao"]}</p>
    </div>
    """,
    unsafe_allow_html=True,
)


# --------------------------------------------------------------------------- #
# 1. Correção
# --------------------------------------------------------------------------- #
if SECAO == "correcao":
    if not TEMPLATE_PATH.exists():
        st.error(
            f"O template da folha não foi encontrado em `inputs/{TEMPLATE_PATH.name}`. "
            "Coloque o arquivo lá para poder corrigir as provas."
        )

    st.subheader("Gabarito")
    answer_key_file = st.file_uploader(
        "Planilha do gabarito (csv ou xlsx)",
        type=["csv", "xlsx", "xls"],
        help="Precisa ter ao menos uma coluna com o número/rótulo da questão e outra com a resposta correta.",
    )
    # O layout da planilha é sempre o mesmo, então as colunas são detectadas pelo
    # nome e a pontuação usa o critério padrão - nada disso vai para a tela
    answer_key = read_answer_key(answer_key_file) if answer_key_file else None
    question_column = answer_column = None
    extra_columns = []
    if answer_key is not None and not answer_key.empty:
        columns = list(answer_key.columns)
        question_column = pick_column(columns, QUESTION_COLUMN_HINTS)
        answer_column = pick_column(
            columns, ANSWER_COLUMN_HINTS, exclude={question_column}
        )
        extra_columns = [column for column in columns if column != question_column]
        if question_column is None or answer_column is None:
            st.error(
                "Não encontrei as colunas de questão e gabarito na planilha. "
                f"Colunas lidas: {', '.join(columns)}"
            )
        else:
            st.caption(
                f"{len(answer_key)} questões · questão em **{question_column}** · "
                f"resposta correta em **{answer_column}**"
            )
    else:
        st.info("Envie o gabarito para continuar.")

    st.divider()
    st.subheader("Provas escaneadas")
    exam_files = st.file_uploader(
        "Imagens das folhas de resposta",
        type=[extension.lstrip(".") for extension in SUPPORTED_IMAGE_EXTENSIONS],
        accept_multiple_files=True,
    )
    if exam_files:
        st.caption(f"{len(exam_files)} arquivo(s) prontos para correção.")

    ready = (
        TEMPLATE_PATH.exists()
        and question_column is not None
        and answer_column is not None
        and bool(exam_files)
    )
    if st.button(
        "Corrigir provas",
        icon=":material/task_alt:",
        type="primary",
        disabled=not ready,
    ):
        with st.spinner("Corrigindo as provas..."):
            try:
                correction = run_correction(
                    images=[(f.name, f.getvalue()) for f in exam_files],
                    template_bytes=TEMPLATE_PATH.read_bytes(),
                    answer_key=answer_key,
                    question_column=question_column,
                    answer_column=answer_column,
                    extra_columns=extra_columns,
                    marking=DEFAULT_MARKING,
                    config_bytes=CONFIG_PATH.read_bytes()
                    if CONFIG_PATH.exists()
                    else None,
                )
            except CorrectionError as error:
                correction = None
                st.error("Não foi possível corrigir as provas.")
                st.code(str(error))

        if correction is not None:
            store_results(correction.results_by_question, correction.scores, correction)
            st.success(
                f"{len(correction.scores)} prova(s) corrigida(s). "
                "Confira o dashboard no menu ao lado."
            )

    correction = st.session_state.get("correction")
    if correction is not None:
        st.divider()
        st.subheader("Alunos")
        st.caption(
            "O nome vem do arquivo enviado - ajuste aqui e informe a turma para usar nos filtros."
        )
        edited = st.data_editor(
            st.session_state["students"],
            width="stretch",
            hide_index=True,
            disabled=["Arquivo"],
            key="students_editor",
        )
        st.session_state["students"] = edited

        st.download_button(
            "Baixar ResultsByQuestion.csv",
            icon=":material/download:",
            data=correction.raw_csv.encode("utf-8-sig"),
            file_name="ResultsByQuestion.csv",
            mime="text/csv",
        )
        with st.expander("Log da correção"):
            st.code(correction.log or "Sem mensagens.")


# --------------------------------------------------------------------------- #
# 2. Dashboard
# --------------------------------------------------------------------------- #
elif SECAO == "dashboard":
    if st.session_state.get("results_by_question") is None:
        st.info(
            "Corrija as provas na seção anterior ou envie uma planilha ResultsByQuestion já gerada."
        )
        uploaded_results = st.file_uploader(
            "ResultsByQuestion.csv", type=["csv"], key="results_upload"
        )
        if uploaded_results is not None:
            results = load_results_by_question(io.BytesIO(uploaded_results.getvalue()))
            scores, results = split_scores(results)
            store_results(results, scores)
            st.rerun()
    else:
        results_by_question = st.session_state["results_by_question"]
        meta_columns = st.session_state["meta_columns"]
        names, groups = name_and_group_maps(st.session_state.get("students"))
        long_results = to_long_format(results_by_question, meta_columns, names, groups)

        area_column = pick_column(meta_columns, AREA_HINTS)
        subarea_column = pick_column(
            meta_columns, SUBAREA_HINTS, exclude={area_column} if area_column else ()
        )
        # 'Área' matches the subárea hints too, so resolve the more specific one first
        if area_column and subarea_column and area_column == subarea_column:
            subarea_column = None

        # --- filtros, em uma linha acima dos gráficos ---
        filter_columns = st.columns(4)
        turmas = sorted(long_results["Turma"].dropna().unique())
        turma_selecionada = filter_columns[0].multiselect(
            "Turma", turmas, default=turmas
        )

        visible = long_results[long_results["Turma"].isin(turma_selecionada)]

        alunos = sorted(visible["Nome do Aluno"].dropna().unique())
        aluno_selecionado = filter_columns[1].multiselect("Aluno", alunos, default=alunos)

        if area_column:
            areas = sorted(long_results[area_column].dropna().unique())
            area_selecionada = filter_columns[2].multiselect(
                "Área", areas, default=areas
            )
        else:
            area_selecionada = None
            filter_columns[2].caption("Sem coluna de área no gabarito.")

        if subarea_column:
            subareas = sorted(long_results[subarea_column].dropna().unique())
            subarea_selecionada = filter_columns[3].multiselect(
                "Subárea", subareas, default=subareas
            )
        else:
            subarea_selecionada = None
            filter_columns[3].caption("Sem coluna de subárea no gabarito.")

        filtered = visible[visible["Nome do Aluno"].isin(aluno_selecionado)]
        if area_selecionada is not None:
            filtered = filtered[filtered[area_column].isin(area_selecionada)]
        if subarea_selecionada is not None:
            filtered = filtered[filtered[subarea_column].isin(subarea_selecionada)]

        st.session_state["filtered_results"] = filtered

        if filtered.empty:
            st.warning(
                "Nenhum dado com os filtros atuais. Selecione ao menos uma opção em cada filtro."
            )
        else:
            total = len(filtered)
            acertos = int((filtered["Resultado"] == ACERTO).sum())
            erros = int((filtered["Resultado"] == ERRO).sum())
            em_branco = int((filtered["Resultado"] == NAO_RESPONDEU).sum())

            kpis = st.columns(4)
            kpis[0].metric("Alunos", filtered["Nome do Aluno"].nunique())
            kpis[1].metric("Questões por prova", filtered["Questão"].nunique())
            kpis[2].metric("Taxa de acerto", f"{acertos / total * 100:.1f}%")
            kpis[3].metric(
                "Respostas",
                f"{acertos} acertos",
                delta=f"{erros} erros · {em_branco} em branco",
                delta_color="off",
            )

            st.divider()

            # Numeração corrida: o gabarito pode não trazer área nem subárea, e
            # aí a primeira seção passa a ser a de questões
            secao = 0

            # Área e subárea contam a mesma história em recortes diferentes, então
            # dividem uma seção e alternam no rádio, como a ordenação da seção
            # seguinte. Só aparece o rádio quando as duas existem.
            dimensoes = {
                nome: coluna
                for nome, coluna in (("Área", area_column), ("Subárea", subarea_column))
                if coluna
            }
            if dimensoes:
                secao += 1
                recortes = " e ".join(nome.lower() for nome in dimensoes)
                st.subheader(f"{secao}. Desempenho por {recortes}")
                st.caption(
                    "Cada barra é 100% das respostas da área, dividida entre "
                    "acerto, erro e em branco."
                )
                recorte = next(iter(dimensoes))
                if len(dimensoes) > 1:
                    recorte = st.radio(
                        "Agrupar por",
                        list(dimensoes),
                        horizontal=True,
                        label_visibility="collapsed",
                    )
                st.plotly_chart(
                    dashboard.performance_by_dimension(
                        filtered, dimensoes[recorte], MODE
                    ),
                    width="stretch",
                )

            secao += 1
            st.subheader(f"{secao}. Taxa de acerto por questão")
            ordem = st.radio(
                "Ordenar por",
                ["Número da questão", "Taxa de acerto"],
                horizontal=True,
                label_visibility="collapsed",
            )
            st.plotly_chart(
                dashboard.accuracy_by_question(
                    filtered, MODE, sort_by_rate=ordem == "Taxa de acerto"
                ),
                width="stretch",
            )

            secao += 1
            st.subheader(f"{secao}. Desempenho por aluno")
            st.plotly_chart(
                dashboard.ranking_by_student(filtered, MODE),
                width="stretch",
            )


# --------------------------------------------------------------------------- #
# 3. Dados e downloads
# --------------------------------------------------------------------------- #
elif SECAO == "dados":
    results_by_question = st.session_state.get("results_by_question")
    if results_by_question is None:
        st.info("Nenhum resultado carregado ainda.")
    else:
        scores = st.session_state.get("scores", {})
        filtered = st.session_state.get("filtered_results")
        names, groups = name_and_group_maps(st.session_state.get("students"))
        long_results = (
            filtered
            if filtered is not None and not filtered.empty
            else to_long_format(
                results_by_question, st.session_state["meta_columns"], names, groups
            )
        )

        st.subheader("Resumo por aluno")
        summary = summarize_students(long_results, scores)
        st.dataframe(summary, width="stretch", hide_index=True)

        st.subheader("Planilha por questão (ResultsByQuestion)")
        st.dataframe(results_by_question, width="stretch", hide_index=True)

        download_columns = st.columns(3)
        correction = st.session_state.get("correction")
        download_columns[0].download_button(
            "ResultsByQuestion.csv",
            icon=":material/download:",
            data=(
                correction.raw_csv.encode("utf-8-sig")
                if correction is not None
                else csv_download(results_by_question)
            ),
            file_name="ResultsByQuestion.csv",
            mime="text/csv",
            width="stretch",
        )
        download_columns[1].download_button(
            "Resumo por aluno.csv",
            icon=":material/download:",
            data=csv_download(summary),
            file_name="ResumoPorAluno.csv",
            mime="text/csv",
            width="stretch",
        )
        download_columns[2].download_button(
            "Respostas (uma linha por questão).csv",
            icon=":material/download:",
            data=csv_download(
                long_results.drop(columns=[QUESTION_COLUMN], errors="ignore")
            ),
            file_name="RespostasPorQuestao.csv",
            mime="text/csv",
            width="stretch",
        )

        if correction is not None and correction.marked_images:
            st.subheader("Folhas com a leitura marcada")
            image_columns = st.columns(3)
            for index, (file_name, path) in enumerate(
                sorted(correction.marked_images.items())
            ):
                image_columns[index % 3].image(
                    str(path), caption=file_name, width="stretch"
                )
