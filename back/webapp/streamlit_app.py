"""Interface web do OMRChecker.

Fluxo: envia o gabarito + o template + as provas -> corrige com o mesmo pipeline
do main.py -> exporta a planilha ResultsByQuestion -> monta o dashboard.

Uso, a partir da raiz do back/: streamlit run webapp/streamlit_app.py
"""
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

# O laranja da marca entra só como acento na régua do cabeçalho. O azul não
# aparece aqui porque já vem do textColor/primaryColor do config.toml, que tem
# um passo próprio para cada modo.
ORANGE = "#ef7b17"


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

QUESTION_COLUMN_HINTS = ["questão", "questao", "question", "nº", "numero", "número"]
ANSWER_COLUMN_HINTS = ["gabarito", "answer", "resposta", "correta"]
AREA_HINTS = ["área", "area"]
SUBAREA_HINTS = ["sub-área", "subárea", "sub-area", "subarea", "sub área", "assunto"]

st.set_page_config(
    page_title="Corretor de Provas OMR",
    page_icon=str(LOGO_MARK or LOGO_FULL) if (LOGO_MARK or LOGO_FULL) else "🖊️",
    layout="wide",
)

if LOGO_FULL:
    st.logo(str(LOGO_FULL), icon_image=str(LOGO_MARK or LOGO_FULL), size="large")

# As fontes da marca vêm do Google Fonts; o config.toml já as declara para os
# componentes do Streamlit, e o @import cobre o que é desenhado em HTML aqui.
st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=League+Spartan:wght@600;700&family=Open+Sans:wght@400;600&display=swap');

    .cpe-header {
        display: flex; align-items: center; gap: 1rem; flex-wrap: wrap;
        border-left: 6px solid """ + ORANGE + """;
        padding: 0.35rem 0 0.35rem 1rem; margin-bottom: 0.5rem;
    }
    .cpe-header h1 {
        font-family: 'League Spartan', sans-serif; font-weight: 700;
        font-size: 2.1rem; line-height: 1.1; letter-spacing: -0.01em; margin: 0;
    }
    .cpe-header p {
        font-family: 'Open Sans', sans-serif; font-size: 0.95rem;
        opacity: 0.75; margin: 0.2rem 0 0 0;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


def theme_mode():
    try:
        if st.context.theme.type == "dark":
            return "dark"
        return "light"
    except Exception:
        return "dark" if st.get_option("theme.base") == "dark" else "light"


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


st.markdown(
    """
    <div class="cpe-header">
      <div>
        <h1>Corretor de Provas OMR</h1>
        <p>Envie o gabarito e as provas escaneadas, corrija tudo de uma vez e
        acompanhe o desempenho da turma.</p>
      </div>
    </div>
    """,
    unsafe_allow_html=True,
)

tab_correcao, tab_dashboard, tab_dados = st.tabs(
    ["1️⃣ Correção", "2️⃣ Dashboard", "3️⃣ Dados e downloads"]
)


# --------------------------------------------------------------------------- #
# 1. Correção
# --------------------------------------------------------------------------- #
with tab_correcao:
    if not TEMPLATE_PATH.exists():
        st.error(
            f"O template da folha não foi encontrado em `inputs/{TEMPLATE_PATH.name}`. "
            "Coloque o arquivo lá para poder corrigir as provas."
        )

    st.subheader("📄 Gabarito")
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
    st.subheader("📸 Provas escaneadas")
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
    if st.button("✅ Corrigir provas", type="primary", disabled=not ready):
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
                "Confira o dashboard na próxima aba."
            )

    correction = st.session_state.get("correction")
    if correction is not None:
        st.divider()
        st.subheader("👥 Alunos")
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
            "⬇️ Baixar ResultsByQuestion.csv",
            data=correction.raw_csv.encode("utf-8-sig"),
            file_name="ResultsByQuestion.csv",
            mime="text/csv",
            type="primary",
        )
        with st.expander("📋 Log da correção"):
            st.code(correction.log or "Sem mensagens.")


# --------------------------------------------------------------------------- #
# 2. Dashboard
# --------------------------------------------------------------------------- #
with tab_dashboard:
    if st.session_state.get("results_by_question") is None:
        st.info(
            "Corrija as provas na aba anterior ou envie uma planilha ResultsByQuestion já gerada."
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
            mode = theme_mode()
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

            if area_column:
                st.subheader("1. Desempenho por área")
                st.plotly_chart(
                    dashboard.performance_by_dimension(filtered, area_column, mode),
                    width="stretch",
                )

            if subarea_column:
                st.subheader("2. Desempenho por subárea")
                st.plotly_chart(
                    dashboard.performance_by_dimension(
                        filtered, subarea_column, mode, height=460
                    ),
                    width="stretch",
                )

            st.subheader("3. Taxa de acerto por questão")
            ordem = st.radio(
                "Ordenar por",
                ["Número da questão", "Taxa de acerto"],
                horizontal=True,
                label_visibility="collapsed",
            )
            st.plotly_chart(
                dashboard.accuracy_by_question(
                    filtered, mode, sort_by_rate=ordem == "Taxa de acerto"
                ),
                width="stretch",
            )

            st.subheader("4. Desempenho por aluno")
            st.plotly_chart(
                dashboard.ranking_by_student(filtered, mode),
                width="stretch",
            )


# --------------------------------------------------------------------------- #
# 3. Dados e downloads
# --------------------------------------------------------------------------- #
with tab_dados:
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
            "⬇️ ResultsByQuestion.csv",
            data=(
                correction.raw_csv.encode("utf-8-sig")
                if correction is not None
                else csv_download(results_by_question)
            ),
            file_name="ResultsByQuestion.csv",
            mime="text/csv",
        )
        download_columns[1].download_button(
            "⬇️ Resumo por aluno.csv",
            data=csv_download(summary),
            file_name="ResumoPorAluno.csv",
            mime="text/csv",
        )
        download_columns[2].download_button(
            "⬇️ Respostas (uma linha por questão).csv",
            data=csv_download(
                long_results.drop(columns=[QUESTION_COLUMN], errors="ignore")
            ),
            file_name="RespostasPorQuestao.csv",
            mime="text/csv",
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
