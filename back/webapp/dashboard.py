"""Charts for the corrected sheets.

Same story the dashboards-automatizados app tells (desempenho por área, por
subárea e por questão), built from the ResultsByQuestion sheet instead of a
hand-made spreadsheet.
"""
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from webapp.pipeline import ACERTO, ERRO, NAO_RESPONDEU, RESULT_ORDER

# Status palette - fixed roles, never reused as series colors. The legend and the
# direct labels carry the meaning too, so nothing rides on hue alone.
RESULT_COLORS = {
    ACERTO: "#0ca30c",
    ERRO: "#d03b3b",
    NAO_RESPONDEU: "#8a8a80",
}
# Acerto/erro are green vs red - the pair a deuteranope cannot separate by hue.
# Texture carries the same distinction, so nothing depends on color alone.
RESULT_PATTERNS = {ACERTO: "", ERRO: "/", NAO_RESPONDEU: "."}
ACCENT = {"light": "#2a78d6", "dark": "#3987e5"}

GRID_COLOR = {"light": "rgba(11,11,11,0.10)", "dark": "rgba(255,255,255,0.12)"}
TEXT_COLOR = {"light": "#52514e", "dark": "#c3c2b7"}
# Streamlit's own page background - used as the spacer between stacked segments
SURFACE = {"light": "#ffffff", "dark": "#0e1117"}


def style(fig, mode="light", height=420, showlegend=True, bargap=0.4):
    """Recessive grid and axes, transparent surface so it sits on the app's own."""
    fig.update_layout(
        template="plotly_dark" if mode == "dark" else "plotly_white",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        height=height,
        margin=dict(l=8, r=8, t=8, b=8),
        font=dict(color=TEXT_COLOR[mode], size=13),
        showlegend=showlegend,
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="left",
            x=0,
            title_text="",
            traceorder="normal",
        ),
        bargap=bargap,
        bargroupgap=0.08,
        hovermode="closest",
    )
    fig.update_xaxes(showgrid=False, zeroline=False, linecolor=GRID_COLOR[mode])
    fig.update_yaxes(
        showgrid=True, gridcolor=GRID_COLOR[mode], zeroline=False, linecolor="rgba(0,0,0,0)"
    )
    return fig


def _result_bars(long_results, dimension, mode, height, tickangle=0):
    # Every result gets a slot in every group, so an absent combination reads as
    # zero instead of shifting the remaining bars sideways
    categories = sorted(long_results[dimension].dropna().unique())
    counts = (
        long_results.groupby([dimension, "Resultado"], dropna=False)
        .size()
        .reindex(
            pd.MultiIndex.from_product(
                [categories, RESULT_ORDER], names=[dimension, "Resultado"]
            ),
            fill_value=0,
        )
        .reset_index(name="Quantidade")
    )
    fig = px.bar(
        counts,
        x=dimension,
        y="Quantidade",
        color="Resultado",
        pattern_shape="Resultado",
        barmode="group",
        text="Quantidade",
        category_orders={"Resultado": RESULT_ORDER},
        color_discrete_map=RESULT_COLORS,
        pattern_shape_map=RESULT_PATTERNS,
    )
    fig.update_traces(
        marker_cornerradius=6,
        marker_line_width=0,
        marker_pattern_size=7,
        marker_pattern_solidity=0.22,
        marker_pattern_fgcolor=SURFACE[mode],
        textposition="outside",
        cliponaxis=False,
        hovertemplate="<b>%{x}</b><br>%{fullData.name}: %{y}<extra></extra>",
    )
    fig.update_xaxes(title_text="", tickangle=tickangle)
    fig.update_yaxes(title_text="Questões")
    return style(fig, mode, height=height)


def performance_by_dimension(long_results, dimension, mode="light", height=420):
    """Acerto / erro / em branco per área or subárea."""
    tickangle = -30 if long_results[dimension].nunique() > 5 else 0
    return _result_bars(long_results, dimension, mode, height, tickangle)


def accuracy_by_question(long_results, mode="light", height=430, sort_by_rate=False):
    """Taxa de acerto per question.

    A percentage rather than a headcount: with a handful of sheets the raw count
    only ever spans 0-3 and says nothing about which questions were hard.
    """
    per_question = (
        long_results.groupby(["Número da questão", "Questão"], dropna=False)
        .agg(
            Acertos=("Resultado", lambda values: (values == ACERTO).sum()),
            Respostas=("Resultado", "size"),
        )
        .reset_index()
    )
    per_question["Taxa"] = (
        per_question["Acertos"] / per_question["Respostas"].replace(0, 1) * 100
    ).round(1)
    per_question = per_question.sort_values(
        "Taxa" if sort_by_rate else "Número da questão"
    )
    overall = round(
        (long_results["Resultado"] == ACERTO).sum() / max(len(long_results), 1) * 100, 1
    )

    fig = px.bar(
        per_question,
        x="Questão",
        y="Taxa",
        custom_data=["Acertos", "Respostas"],
        color_discrete_sequence=[ACCENT[mode]],
    )
    fig.update_traces(
        marker_cornerradius=6,
        marker_line_width=0,
        hovertemplate=(
            "<b>%{x}</b><br>Taxa de acerto: %{y}%"
            "<br>%{customdata[0]} de %{customdata[1]} alunos<extra></extra>"
        ),
    )
    fig.add_hline(
        y=overall,
        line=dict(color=TEXT_COLOR[mode], width=1, dash="dash"),
        annotation_text=f"média geral {overall}%",
        annotation_position="top right",
        annotation_font=dict(color=TEXT_COLOR[mode], size=12),
    )
    fig.update_xaxes(
        type="category",
        title_text="",
        tickangle=-90,
        tickfont=dict(size=10),
    )
    fig.update_yaxes(title_text="Taxa de acerto (%)", range=[0, 105], dtick=25)
    return style(fig, mode, height=height, showlegend=False, bargap=0.25)


def ranking_by_student(long_results, mode="light", height=None):
    """Stacked acerto / erro / em branco per student, longest bar on top."""
    counts = (
        long_results.groupby(["Nome do Aluno", "Resultado"], dropna=False)
        .size()
        .unstack("Resultado", fill_value=0)
        .reindex(columns=RESULT_ORDER, fill_value=0)
        .sort_values(ACERTO)
    )
    fig = go.Figure()
    for result in RESULT_ORDER:
        fig.add_bar(
            y=counts.index,
            x=counts[result],
            name=result,
            orientation="h",
            marker=dict(
                color=RESULT_COLORS[result],
                line=dict(width=2, color=SURFACE[mode]),
                pattern=dict(
                    shape=RESULT_PATTERNS[result],
                    size=7,
                    solidity=0.22,
                    fgcolor=SURFACE[mode],
                ),
            ),
            hovertemplate="<b>%{y}</b><br>" + result + ": %{x}<extra></extra>",
        )
    fig.update_layout(barmode="stack")
    fig.update_xaxes(title_text="Questões", showgrid=True, gridcolor=GRID_COLOR[mode])
    fig.update_yaxes(title_text="", showgrid=False)
    return style(
        fig, mode, height=height or max(240, 44 * len(counts) + 100), bargap=0.45
    )
