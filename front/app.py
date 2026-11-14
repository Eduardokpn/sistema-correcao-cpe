"""Corretor de Provas OMR - interface web (Streamlit).

Frontend fino: toda a correção e persistência acontecem no backend (FastAPI +
banco). Este app apenas envia provas para correção, lê os resultados em formato
longo pela API e desenha os gráficos (desempenho por área/subárea, taxa de
acerto por questão, ranking por aluno e evolução da turma).

Uso: streamlit run app.py
A URL da API vem de CPE_API_URL (padrão http://localhost:8001).
"""
import base64
import datetime as dt
import io
import re
from pathlib import Path

import pandas as pd
import streamlit as st

import charts
from api_client import APIError, CPEClient

FRONT_DIR = Path(__file__).resolve().parent
# A marca fica em front/assets/ (é o que vai para a imagem Docker do front);
# rodando do repositório, back/assets/ serve de reserva.
ASSETS_DIRS = (FRONT_DIR / "assets", FRONT_DIR.parent / "back" / "assets")

# Um template por tamanho de prova, escolhido no backend (back/folha-cpe/). A
# prova de 72 questões usa a folha de 90 e para na q72. Manter em sincronia com
# grading.sheets.QUESTION_COUNTS.
QUESTION_COUNTS = (72, 80, 90)
DEFAULT_QUESTION_COUNT = 80

SUPPORTED_IMAGE_EXTENSIONS = ("png", "jpg", "jpeg")

QUESTION_COLUMN_HINTS = ["questão", "questao", "question", "nº", "numero", "número"]
ANSWER_COLUMN_HINTS = ["gabarito", "answer", "resposta", "correta"]

# Portuguese name connectors kept lowercase when deriving a name from a file.
_NAME_CONNECTORS = {"da", "de", "do", "das", "dos", "e"}

# Paleta da marca. O azul escuro é a superfície da sidebar; o laranja é o único
# acento, e fica só na moldura (régua, item ativo, botão de ação) - dentro dos
# gráficos ele já significa "erro", e charts.py é dono desse uso.
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

    Nada aqui pode depender da marca: sem os arquivos o app cai no título em
    texto e segue funcionando.
    """
    for assets_dir in ASSETS_DIRS:
        if not assets_dir.exists():
            continue
        for stem in stems:
            for path in sorted(assets_dir.glob(f"{stem}.*")):
                if path.suffix.lower() in (".png", ".jpg", ".jpeg", ".svg", ".webp"):
                    return path
    return None


LOGO_FULL = brand_asset("logo", "logo-cpe", "cpe-usp", "cpe")
LOGO_MARK = brand_asset("simbolo", "symbol", "icone", "icon", "mark")
# A sidebar é azul escura, então quem vai para lá é a versão laranja da marca.
# "17" é o nome que ela tem no kit; sem nenhum dos três o logo padrão assume.
LOGO_SIDEBAR = brand_asset("logo-laranja", "logo-claro", "17") or LOGO_FULL

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
    "evolucao": {
        "titulo": "Evolução",
        "icone": ":material/trending_up:",
        "descricao": "A turma está melhorando com o tempo? Compare os simulados, no geral e por área.",
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


def student_name_from_file(file_name):
    """Derive a readable student name from a sheet file name.

    `Ana_Carolina_Matias_de_Melo.jpg` -> `Ana Carolina Matias de Melo`.
    Underscores/hyphens become spaces, each word is title-cased, and Portuguese
    connectors (da, de, do...) stay lowercase. Mirrors the backend's fallback so
    the editor shows the same name that would be stored.
    """
    stem = Path(str(file_name)).stem
    words = re.sub(r"[_\-]+", " ", stem).strip().split()
    return " ".join(
        word.title() if index == 0 or word.lower() not in _NAME_CONNECTORS else word.lower()
        for index, word in enumerate(words)
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
    """Reads the answer key from a csv (any common separator) or xlsx upload.

    Só para conferir o gabarito na tela antes do envio - quem corrige é o
    backend, que lê o arquivo original de novo.
    """
    suffix = Path(uploaded_file.name).suffix.lower()
    if suffix in (".xlsx", ".xls"):
        answer_key = pd.read_excel(io.BytesIO(uploaded_file.getvalue()), dtype=str)
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


def answer_key_mismatch(answer_key, question_column, question_count):
    """Questões do gabarito que a folha não tem, e questões da folha sem gabarito."""
    sheet_questions = [f"q{number}" for number in range(1, question_count + 1)]
    key_questions = answer_key[question_column].tolist()
    outside_sheet = [q for q in key_questions if q not in set(sheet_questions)]
    without_answer = [q for q in sheet_questions if q not in set(key_questions)]
    return outside_sheet, without_answer


def short_list(items, limit=6):
    shown = ", ".join(str(item) for item in items[:limit])
    return shown + (f" e mais {len(items) - limit}" if len(items) > limit else "")


def csv_download(dataframe):
    return dataframe.to_csv(index=False).encode("utf-8-sig")


@st.cache_resource
def get_client() -> CPEClient:
    return CPEClient()


client = get_client()


@st.cache_data(show_spinner=False, max_entries=200)
def marked_sheet_image(exam_id, file_name):
    """Uma folha marcada, baixada da API uma vez por sessão do servidor."""
    return client.marked_sheet(exam_id, file_name)


def _mapping_from_editor(students_df):
    """Turn the editor table into {file: name} and {file: turma} maps."""
    names, classes = {}, {}
    if students_df is None or students_df.empty:
        return names, classes
    for _index, row in students_df.iterrows():
        file_name = row.get("Arquivo")
        if not file_name:
            continue
        if str(row.get("Nome do Aluno") or "").strip():
            names[file_name] = row["Nome do Aluno"].strip()
        if str(row.get("Turma") or "").strip():
            classes[file_name] = row["Turma"].strip()
    return names, classes


def _summarize(long_results: pd.DataFrame) -> pd.DataFrame:
    """One row per student: acertos, erros, em branco and accuracy."""
    if long_results.empty:
        return pd.DataFrame()
    counts = (
        long_results.pivot_table(
            index=["Nome do Aluno", "Turma"],
            columns="Resultado",
            values="Questão",
            aggfunc="count",
            fill_value=0,
        )
        .reindex(columns=charts.RESULT_ORDER, fill_value=0)
        .reset_index()
    )
    counts["Questões"] = counts[charts.RESULT_ORDER].sum(axis=1)
    counts["% de acerto"] = (
        counts[charts.ACERTO] / counts["Questões"].replace(0, pd.NA) * 100
    ).round(1)
    return counts.sort_values(charts.ACERTO, ascending=False).reset_index(drop=True)


def _has_values(frame, column):
    """A dimensão só vira filtro/gráfico quando alguma questão a informa."""
    values = frame[column].dropna().astype(str).str.strip()
    return bool((values != "").any())


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
if SECAO not in SECOES:
    SECAO = st.session_state["secao"] = next(iter(SECOES))
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

# Health banner - a clear message beats a stack trace when the API is down
if not client.health():
    st.error(
        f"Não consegui falar com a API em `{client.base_url}`. "
        "Inicie o backend (uvicorn api.app:app) e recarregue a página."
    )


# --------------------------------------------------------------------------- #
# 1. Correção
# --------------------------------------------------------------------------- #
if SECAO == "correcao":
    st.subheader("Dados do simulado")
    meta_columns = st.columns([2, 1, 1])
    exam_name = meta_columns[0].text_input(
        "Nome do simulado", value="Simulado 1", help="Ex.: Simulado 1, ENEM Treino 2..."
    )
    applied_on = meta_columns[1].date_input("Data de aplicação", value=dt.date.today())
    sequence = meta_columns[2].number_input(
        "Nº na sequência", min_value=1, value=1, step=1,
        help="Ordem no tempo, usada para acompanhar a evolução da turma.",
    )

    st.divider()
    st.subheader("Gabarito")
    answer_key_file = st.file_uploader(
        "Planilha do gabarito (csv ou xlsx)",
        type=["csv", "xlsx", "xls"],
        help="Precisa ter ao menos uma coluna com o número/rótulo da questão e outra com a resposta correta.",
    )
    # O layout da planilha é sempre o mesmo, então as colunas são detectadas pelo
    # nome. A leitura aqui é só uma prévia: se ela falhar, o backend ainda
    # valida o arquivo na correção.
    answer_key = None
    answer_key_checked = False
    question_column = answer_column = None
    if answer_key_file:
        try:
            answer_key = read_answer_key(answer_key_file)
        except Exception as error:
            st.warning(
                "Não consegui pré-visualizar o gabarito; ele será conferido na "
                f"correção. ({error})"
            )
    if answer_key is not None and not answer_key.empty:
        answer_key_checked = True
        columns = list(answer_key.columns)
        question_column = pick_column(columns, QUESTION_COLUMN_HINTS)
        answer_column = pick_column(
            columns, ANSWER_COLUMN_HINTS, exclude={question_column}
        )
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
    elif not answer_key_file:
        st.info("Envie o gabarito para continuar.")
    columns_found = question_column is not None and answer_column is not None

    st.divider()
    st.subheader("Tamanho da prova")
    key_size = len(answer_key) if columns_found else None
    question_count = st.radio(
        "Quantidade de questões",
        QUESTION_COUNTS,
        # Começa no tamanho do gabarito enviado; a chave muda com o arquivo para
        # que um gabarito novo volte a escolher sozinho
        index=QUESTION_COUNTS.index(
            key_size if key_size in QUESTION_COUNTS else DEFAULT_QUESTION_COUNT
        ),
        format_func=lambda count: f"{count} questões",
        horizontal=True,
        key=f"question_count_{answer_key_file.name if answer_key_file else ''}",
        help="A prova de 72 questões usa a folha de 90 e só lê até a questão 72.",
    )

    outside_sheet = []
    if columns_found:
        outside_sheet, without_answer = answer_key_mismatch(
            answer_key, question_column, question_count
        )
        if outside_sheet:
            st.error(
                f"O gabarito tem questões que a folha de {question_count} não tem: "
                f"{short_list(outside_sheet)}. As questões precisam se chamar q1, q2, … "
                f"até q{question_count}."
            )
        elif without_answer:
            st.warning(
                f"A folha de {question_count} questões vai ler "
                f"{short_list(without_answer)}, que não estão no gabarito. "
                "Confira se o tamanho da prova está certo."
            )

    st.divider()
    st.subheader("Provas escaneadas")
    exam_files = st.file_uploader(
        "Imagens das folhas de resposta",
        type=list(SUPPORTED_IMAGE_EXTENSIONS),
        accept_multiple_files=True,
    )

    # Optional per-sheet student/turma mapping
    students_df = None
    if exam_files:
        st.caption(f"{len(exam_files)} arquivo(s) prontos para correção.")
        st.subheader("Alunos (opcional)")
        st.caption(
            "O nome vem do arquivo enviado - ajuste aqui e informe a turma para "
            "usar nos filtros e na evolução."
        )
        default_rows = [
            {
                "Arquivo": f.name,
                "Nome do Aluno": student_name_from_file(f.name),
                "Turma": "",
            }
            for f in exam_files
        ]
        students_df = st.data_editor(
            pd.DataFrame(default_rows),
            width="stretch",
            hide_index=True,
            disabled=["Arquivo"],
            key="students_editor",
        )

    ready = (
        bool(answer_key_file)
        and bool(exam_files)
        # Um gabarito que a prévia leu precisa ter as colunas e caber na folha
        and (not answer_key_checked or (columns_found and not outside_sheet))
    )
    if st.button(
        "Corrigir provas",
        icon=":material/task_alt:",
        type="primary",
        disabled=not ready,
    ):
        names, classes = _mapping_from_editor(students_df)
        with st.spinner("Corrigindo as provas..."):
            try:
                result = client.grade_images(
                    images=[(f.name, f.getvalue()) for f in exam_files],
                    answer_key_bytes=answer_key_file.getvalue(),
                    answer_key_name=answer_key_file.name,
                    exam_name=exam_name,
                    applied_on=applied_on,
                    sequence=int(sequence),
                    student_names=names or None,
                    student_classes=classes or None,
                    question_count=int(question_count),
                )
            except APIError as error:
                result = None
                st.error("Não foi possível corrigir as provas.")
                st.code(str(error))

        if result is not None:
            st.session_state["last_exam_id"] = result["exam_id"]
            st.session_state.pop("filtered_results", None)
            st.success(
                f"{result['sheets_ingested']} prova(s) corrigida(s) e salvas. "
                "Confira o dashboard no menu ao lado."
            )
            if len(exam_files) > result["sheets_ingested"]:
                st.warning(
                    f"{len(exam_files) - result['sheets_ingested']} folha(s) não "
                    "puderam ser lidas. Confira no log se os 4 marcadores dos "
                    "cantos aparecem inteiros no scan (`Corner marks not found`)."
                )
            for warning in result.get("warnings") or []:
                st.warning(warning)
            if result.get("log"):
                with st.expander("Log da correção"):
                    st.code(result["log"])

    with st.expander("Já tem uma planilha ResultsByQuestion.csv?"):
        st.caption(
            "Se as provas já foram corrigidas, envie a planilha direto para o banco."
        )
        results_csv = st.file_uploader(
            "ResultsByQuestion.csv", type=["csv"], key="results_csv_upload"
        )
        if results_csv is not None and st.button("Enviar planilha"):
            try:
                res = client.ingest_results_csv(
                    csv_bytes=results_csv.getvalue(),
                    exam_name=exam_name,
                    applied_on=applied_on,
                    sequence=int(sequence),
                )
                st.session_state["last_exam_id"] = res["exam_id"]
                st.session_state.pop("filtered_results", None)
                st.success(f"{res['sheets_ingested']} prova(s) importada(s).")
                for warning in res.get("warnings") or []:
                    st.warning(warning)
            except APIError as error:
                st.error(str(error))


# --------------------------------------------------------------------------- #
# 2. Dashboard
# --------------------------------------------------------------------------- #
elif SECAO == "dashboard":
    try:
        exams = client.exams()
    except APIError as error:
        exams = []
        st.error(str(error))

    if not exams:
        st.info("Nenhum simulado no banco ainda. Corrija provas na seção Correção.")
    else:
        exam_labels = {f"{e['name']}": e["id"] for e in exams}
        default_index = 0
        last_exam_id = st.session_state.get("last_exam_id")
        if last_exam_id in exam_labels.values():
            default_index = list(exam_labels.values()).index(last_exam_id)

        # --- filtros, em uma linha acima dos gráficos ---
        top = st.columns([2, 2, 2, 2])
        chosen_label = top[0].selectbox(
            "Simulado", list(exam_labels.keys()), index=default_index
        )
        exam_id = exam_labels[chosen_label]
        st.session_state["last_exam_id"] = exam_id

        long_results = client.long_format_dataframe(exam_id=exam_id)

        if long_results.empty:
            st.session_state.pop("filtered_results", None)
            st.warning("Este simulado ainda não tem respostas.")
        else:
            turmas = sorted(long_results["Turma"].dropna().unique())
            turma_sel = top[1].multiselect("Turma", turmas, default=turmas)
            visible = long_results[long_results["Turma"].isin(turma_sel)]

            alunos = sorted(visible["Nome do Aluno"].dropna().unique())
            aluno_sel = top[2].multiselect("Aluno", alunos, default=alunos)
            filtered = visible[visible["Nome do Aluno"].isin(aluno_sel)]

            # O gabarito pode não trazer área nem subárea
            has_area = _has_values(long_results, "Área")
            has_subarea = _has_values(long_results, "Subárea")

            if has_area:
                areas = sorted(long_results["Área"].dropna().unique())
                area_sel = top[3].multiselect("Área", areas, default=areas)
                filtered = filtered[filtered["Área"].isin(area_sel)]
            else:
                top[3].caption("Sem coluna de área no gabarito.")

            if has_subarea:
                subareas = sorted(long_results["Subárea"].dropna().unique())
                subarea_sel = st.multiselect("Subárea", subareas, default=subareas)
                filtered = filtered[filtered["Subárea"].isin(subarea_sel)]

            st.session_state["filtered_results"] = filtered

            if filtered.empty:
                st.warning(
                    "Nenhum dado com os filtros atuais. Selecione ao menos uma "
                    "opção em cada filtro."
                )
            else:
                total = len(filtered)
                acertos = int((filtered["Resultado"] == charts.ACERTO).sum())
                erros = int((filtered["Resultado"] == charts.ERRO).sum())
                em_branco = int((filtered["Resultado"] == charts.NAO_RESPONDEU).sum())

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

                # Numeração corrida: sem área nem subárea, a primeira seção
                # passa a ser a de questões
                secao = 0

                # Área e subárea contam a mesma história em recortes diferentes,
                # então dividem uma seção e alternam no rádio. Só aparece o
                # rádio quando as duas existem.
                dimensoes = [
                    nome
                    for nome, presente in (("Área", has_area), ("Subárea", has_subarea))
                    if presente
                ]
                if dimensoes:
                    secao += 1
                    recortes = " e ".join(nome.lower() for nome in dimensoes)
                    st.subheader(f"{secao}. Desempenho por {recortes}")
                    st.caption(
                        "Cada barra é 100% das respostas da área, dividida entre "
                        "acerto, erro e em branco."
                    )
                    recorte = dimensoes[0]
                    if len(dimensoes) > 1:
                        recorte = st.radio(
                            "Agrupar por",
                            dimensoes,
                            horizontal=True,
                            label_visibility="collapsed",
                        )
                    st.plotly_chart(
                        charts.performance_by_dimension(filtered, recorte, MODE),
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
                    charts.accuracy_by_question(
                        filtered, MODE, sort_by_rate=ordem == "Taxa de acerto"
                    ),
                    width="stretch",
                )

                secao += 1
                st.subheader(f"{secao}. Desempenho por aluno")
                st.caption(
                    "Em cada cor, o percentual das questões do aluno e, entre "
                    "parênteses, quantas foram."
                )
                st.plotly_chart(
                    charts.ranking_by_student(filtered, MODE),
                    width="stretch",
                )


# --------------------------------------------------------------------------- #
# 3. Evolução (longitudinal)
# --------------------------------------------------------------------------- #
elif SECAO == "evolucao":
    try:
        classes = client.classes()
    except APIError as error:
        classes = []
        st.error(str(error))

    if not classes:
        st.info(
            "Nenhuma turma no banco ainda. Corrija provas informando a turma de "
            "cada aluno para acompanhar a evolução."
        )
    else:
        class_labels = {c["name"]: c["id"] for c in classes}
        chosen_class = st.selectbox("Turma", list(class_labels.keys()))
        class_id = class_labels[chosen_class]

        try:
            trend = client.class_trend(class_id)
        except APIError as error:
            trend = {"points": []}
            st.error(str(error))

        points = trend.get("points", [])
        if len(points) < 1:
            st.warning("Esta turma ainda não tem simulados corrigidos.")
        elif len(points) < 2:
            st.info(
                "Só há um simulado para esta turma. Corrija outro simulado para "
                "ver a evolução ao longo do tempo."
            )
            st.plotly_chart(
                charts.class_improvement(points, MODE), width="stretch"
            )
        else:
            first = points[0]["overall"]["taxa_acerto"]
            last = points[-1]["overall"]["taxa_acerto"]
            delta = round(last - first, 1)
            kpis = st.columns(3)
            kpis[0].metric("Simulados", len(points))
            kpis[1].metric("Taxa de acerto atual", f"{last:.1f}%")
            kpis[2].metric(
                "Variação desde o 1º",
                f"{delta:+.1f} pts",
                delta=f"{delta:+.1f}",
                delta_color="normal",
            )

            st.divider()
            st.subheader("Evolução geral da turma")
            st.plotly_chart(
                charts.class_improvement(points, MODE), width="stretch"
            )

            st.subheader("Evolução por área")
            st.plotly_chart(
                charts.class_improvement(points, MODE, per_subject=True),
                width="stretch",
            )


# --------------------------------------------------------------------------- #
# 4. Dados e downloads
# --------------------------------------------------------------------------- #
elif SECAO == "dados":
    try:
        exams = client.exams()
    except APIError as error:
        exams = []
        st.error(str(error))
    exam_ids = [e["id"] for e in exams]
    last_exam_id = st.session_state.get("last_exam_id")
    # O simulado aberto no dashboard, ou o primeiro quando ele ainda não rodou
    exam_id = (
        last_exam_id if last_exam_id in exam_ids else (exam_ids[0] if exam_ids else None)
    )

    filtered = st.session_state.get("filtered_results")
    if (filtered is None or filtered.empty) and exam_id is not None:
        # Com a navegação por menu esta seção pode abrir antes do dashboard:
        # sem um recorte de filtros, mostra o simulado inteiro
        try:
            filtered = client.long_format_dataframe(exam_id=exam_id)
        except APIError as error:
            filtered = None
            st.error(str(error))

    if filtered is None or filtered.empty:
        st.info("Nenhum resultado carregado ainda.")
    else:
        exam_name = next((e["name"] for e in exams if e["id"] == exam_id), None)
        if exam_name:
            st.caption(f"Simulado: **{exam_name}**")

        st.subheader("Resumo por aluno")
        summary = _summarize(filtered)
        st.dataframe(summary, width="stretch", hide_index=True)

        st.subheader("Respostas (uma linha por questão)")
        st.dataframe(filtered, width="stretch", hide_index=True)

        # Os arquivos da correção por imagem; um simulado importado por planilha
        # não tem nenhum dos dois
        raw_csv, sheet_names = None, []
        if exam_id is not None:
            try:
                raw_csv = client.results_by_question_csv(exam_id)
                sheet_names = client.marked_sheets(exam_id)
            except APIError as error:
                st.error(str(error))

        downloads = [
            ("Resumo por aluno.csv", csv_download(summary), "ResumoPorAluno.csv"),
            (
                "Respostas (uma linha por questão).csv",
                csv_download(filtered),
                "RespostasPorQuestao.csv",
            ),
        ]
        if raw_csv:
            downloads.insert(0, ("ResultsByQuestion.csv", raw_csv, "ResultsByQuestion.csv"))
        for column, (label, data, file_name) in zip(st.columns(len(downloads)), downloads):
            column.download_button(
                label,
                icon=":material/download:",
                data=data,
                file_name=file_name,
                mime="text/csv",
                width="stretch",
            )

        if sheet_names:
            st.subheader("Folhas com a leitura marcada")
            st.caption(
                "Cada marcação lida deve ficar sobre a bolha correspondente. "
                f"{len(sheet_names)} folha(s) neste simulado."
            )
            # As imagens só são baixadas da API quando alguém pede para ver
            if st.toggle("Mostrar as folhas", key=f"show_sheets_{exam_id}"):
                image_columns = st.columns(3)
                for index, file_name in enumerate(sheet_names):
                    try:
                        content = marked_sheet_image(exam_id, file_name)
                    except APIError as error:
                        content = None
                        image_columns[index % 3].error(str(error))
                    if content:
                        image_columns[index % 3].image(
                            content, caption=file_name, width="stretch"
                        )
