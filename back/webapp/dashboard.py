"""Charts for the corrected sheets.

Same story the dashboards-automatizados app tells (desempenho por área, por
subárea e por questão), built from the ResultsByQuestion sheet instead of a
hand-made spreadsheet.
"""
import plotly.express as px
import plotly.graph_objects as go

from webapp.pipeline import ACERTO, ERRO, NAO_RESPONDEU, RESULT_ORDER

# Status palette - fixed roles, never reused as series colors. The legend and the
# direct labels carry the meaning too, so nothing rides on hue alone.
#
# Steps derived from the CPE USP palette (#3676bb blue, #ef7b17 orange) and then
# snapped until every check passed against the surfaces below. Blue vs orange
# instead of the green/red this used to carry: that pair measured only ΔE 4.1
# under deuteranopia, far below the 6-8 floor, while blue/orange clears 16.
RESULT_COLORS = {
    "light": {ACERTO: "#2f6cae", ERRO: "#d96e10", NAO_RESPONDEU: "#748ba3"},
    "dark": {ACERTO: "#4a8ed0", ERRO: "#d1740f", NAO_RESPONDEU: "#7f93a8"},
}
# Texture repeats the distinction for print and forced-colors, where hue is lost
# entirely - the palette no longer depends on it, but the fallback stays.
RESULT_PATTERNS = {ACERTO: "", ERRO: "/", NAO_RESPONDEU: "."}
ACCENT = {"light": "#3676bb", "dark": "#4a8ed0"}
# Texto escrito por dentro do segmento. Cada fundo pede o seu: branco sobre o
# azul claro perde contraste, escuro sobre o azul escuro também - os valores
# abaixo são os que passam de 4.5:1 em cada combinação.
INSIDE_TEXT = {
    "light": {ACERTO: "#ffffff", ERRO: "#0d1b2a", NAO_RESPONDEU: "#0d1b2a"},
    "dark": {ACERTO: "#0d1b2a", ERRO: "#0d1b2a", NAO_RESPONDEU: "#0d1b2a"},
}

GRID_COLOR = {"light": "rgba(17,56,92,0.12)", "dark": "rgba(232,238,244,0.12)"}
TEXT_COLOR = {"light": "#4a5a6e", "dark": "#a8bacd"}
# The page background set in .streamlit/config.toml - used as the spacer between
# stacked segments and as the pattern background
SURFACE = {"light": "#f6f6f6", "dark": "#0d1b2a"}


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


def performance_by_dimension(long_results, dimension, mode="light", height=None):
    """Acerto / erro / em branco por área ou subárea, em percentual.

    Mesma leitura do gráfico por aluno - uma barra dividida entre os três
    resultados -, só que em percentual em vez de contagem: as áreas têm números
    diferentes de questões, e na contagem a maior sempre parecia a pior.
    """
    counts = (
        long_results.groupby([dimension, "Resultado"], dropna=False)
        .size()
        .unstack("Resultado", fill_value=0)
        # Um resultado que não apareceu em nenhuma área ainda precisa de coluna
        .reindex(columns=RESULT_ORDER, fill_value=0)
    )
    if counts.empty:
        return style(go.Figure(), mode, height=height or 240, showlegend=False)

    respostas = counts.sum(axis=1)
    shares = counts.div(respostas.replace(0, 1), axis=0) * 100
    # Mesma ordem do gráfico por aluno: maior acerto no topo, já que em barra
    # horizontal a primeira linha vai para baixo
    shares = shares.sort_values(ACERTO)
    counts, respostas = counts.loc[shares.index], respostas.loc[shares.index]

    # A porcentagem sozinha esconde o tamanho da amostra - 100% de uma questão
    # só não é a mesma notícia que 100% de doze
    questoes = long_results.groupby(dimension)["Questão"].nunique()
    labels = [
        f"{name}<br>{total} {'questão' if total == 1 else 'questões'}"
        for name, total in ((name, questoes.get(name, 0)) for name in shares.index)
    ]

    fig = go.Figure()
    for result in RESULT_ORDER:
        fig.add_bar(
            y=labels,
            x=shares[result],
            name=result,
            orientation="h",
            marker=dict(
                color=RESULT_COLORS[mode][result],
                line=dict(width=2, color=SURFACE[mode]),
                pattern=dict(
                    shape=RESULT_PATTERNS[result],
                    size=7,
                    solidity=0.22,
                    fgcolor=SURFACE[mode],
                ),
            ),
            # Some quando o segmento fica estreito demais para o texto
            text=[f"{share:.0f}%" if share >= 10 else "" for share in shares[result]],
            textposition="inside",
            insidetextanchor="middle",
            textfont=dict(color=INSIDE_TEXT[mode][result], size=13),
            customdata=list(zip(counts[result], respostas)),
            hovertemplate=(
                "<b>%{y}</b><br>"
                + result
                + ": %{x:.0f}% (%{customdata[0]} de %{customdata[1]} respostas)"
                "<extra></extra>"
            ),
        )

    overall = counts[ACERTO].sum() / max(respostas.sum(), 1) * 100
    fig.add_vline(
        x=overall,
        line=dict(color=TEXT_COLOR[mode], width=1, dash="dash"),
        annotation_text=f"média da turma {overall:.0f}%",
        # Para o lado com espaço, senão o texto sai do gráfico quando a média
        # fica perto de uma das bordas
        annotation_position="top left" if overall >= 50 else "top right",
        annotation_font=dict(color=TEXT_COLOR[mode], size=12),
        annotation_bgcolor=SURFACE[mode],
        annotation_borderpad=3,
        # Acima da primeira barra, senão o texto cai em cima dela
        annotation_yshift=14,
    )

    fig.update_layout(barmode="stack")
    fig.update_xaxes(
        title_text="",
        range=[0, 100],
        dtick=25,
        ticksuffix="%",
        showgrid=True,
        gridcolor=GRID_COLOR[mode],
    )
    # automargin porque o rótulo de duas linhas é mais largo que a margem fixa
    fig.update_yaxes(title_text="", showgrid=False, automargin=True)
    fig = style(
        fig,
        mode,
        height=height or max(260, 64 * len(shares) + 110),
        bargap=0.45,
    )
    # Depois do style, que redefine a margem: espaço no topo para a anotação da
    # média não encostar na primeira barra, e à direita para o tick de 100%
    return fig.update_layout(margin_t=30, margin_r=28)


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
        # À esquerda para não encostar na borda, e sobre a superfície da página
        # para continuar legível quando uma barra alta passar por baixo
        annotation_position="top left",
        annotation_font=dict(color=TEXT_COLOR[mode], size=12),
        annotation_bgcolor=SURFACE[mode],
        annotation_borderpad=3,
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
    questoes = counts.sum(axis=1)
    shares = counts.div(questoes.replace(0, 1), axis=0) * 100

    fig = go.Figure()
    for result in RESULT_ORDER:
        fig.add_bar(
            y=counts.index,
            x=counts[result],
            name=result,
            orientation="h",
            marker=dict(
                color=RESULT_COLORS[mode][result],
                line=dict(width=2, color=SURFACE[mode]),
                pattern=dict(
                    shape=RESULT_PATTERNS[result],
                    size=7,
                    solidity=0.22,
                    fgcolor=SURFACE[mode],
                ),
            ),
            # Percentual e quantidade de questões em cada cor; segmento vazio
            # fica sem texto
            text=[
                f"{share:.0f}% ({count})" if count else ""
                for share, count in zip(shares[result], counts[result])
            ],
            textposition="inside",
            insidetextanchor="middle",
            textfont=dict(color=INSIDE_TEXT[mode][result], size=12),
            customdata=list(zip(shares[result], questoes)),
            hovertemplate=(
                "<b>%{y}</b><br>"
                + result
                + ": %{x} de %{customdata[1]} questões (%{customdata[0]:.0f}%)"
                "<extra></extra>"
            ),
        )
    # Texto que não cabe no segmento some em vez de encolher até ficar ilegível;
    # o hover continua com o número completo
    fig.update_layout(barmode="stack", uniformtext_minsize=10, uniformtext_mode="hide")
    fig.update_xaxes(title_text="Questões", showgrid=True, gridcolor=GRID_COLOR[mode])
    fig.update_yaxes(title_text="", showgrid=False)
    return style(
        fig, mode, height=height or max(240, 44 * len(counts) + 100), bargap=0.45
    )
