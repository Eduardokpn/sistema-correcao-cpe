import streamlit as st
import pandas as pd
import plotly.express as px

# 1. Configuração da Página
st.set_page_config(page_title="Dashboard do Simulado", layout="wide", page_icon="📊")
st.title("📊 Correção do Simulado 1")
st.markdown("Análise de desempenho dos alunos com base na planilha de correção.")

# 2. Carregamento e Tratamento dos Dados
@st.cache_data
def carregar_dados():
    df = pd.read_csv("Planilha.csv")
    
    # Padronizar a coluna de resultados para facilitar a leitura no gráfico
    df['Resultado'] = df['Resultado agrupado'].map({
        'A': 'Acerto', 
        'E': 'Erro', 
        '-': 'Não Respondeu'
    }).fillna(df['Resultado agrupado']) 
    
    return df

df = carregar_dados()

# --- FILTROS LATERAIS ---
st.sidebar.header("🔍 Filtros")

# Filtro 1: Turno
turnos_disponiveis = df['vespertino/noturno'].dropna().unique()
turno_selecionado = st.sidebar.multiselect(
    "Turno:", 
    options=turnos_disponiveis, 
    default=turnos_disponiveis
)

# Filtro 2: Área
areas_disponiveis = df['Área'].dropna().unique()
area_selecionada = st.sidebar.multiselect(
    "Área de Conhecimento:", 
    options=areas_disponiveis, 
    default=areas_disponiveis
)

# Filtro 3: Aluno
# Se a sua coluna tiver outro nome (ex: "Aluno" ou "Nome do aluno"), mude apenas o texto abaixo:
coluna_aluno = "Nome do Aluno" 

# Filtro em cascata: mostra apenas os alunos do turno selecionado
alunos_disponiveis = df[df['vespertino/noturno'].isin(turno_selecionado)][coluna_aluno].dropna().unique()
aluno_selecionado = st.sidebar.multiselect(
    "Aluno:", 
    options=alunos_disponiveis, 
    default=alunos_disponiveis
)

# Aplicando todos os filtros no dataframe
df_filtrado = df[
    (df['vespertino/noturno'].isin(turno_selecionado)) &
    (df['Área'].isin(area_selecionada)) &
    (df[coluna_aluno].isin(aluno_selecionado))
]


# --- AVISO DE DADOS VAZIOS ---
# Evita que o app quebre se o usuário desmarcar todos os filtros
if df_filtrado.empty:
    st.warning("Nenhum dado encontrado com os filtros atuais. Selecione ao menos uma opção no menu lateral.")
else:
    st.divider()

    # Gráfico 1: Desempenho por Área
    st.subheader("1. Desempenho por Área")
    fig_area = px.histogram(
        df_filtrado, 
        x="Área", 
        color="Resultado", 
        barmode="group",
        text_auto=True,
        color_discrete_map={'Acerto': '#28a745', 'Erro': '#dc3545', 'Não Respondeu': '#6c757d'},
        labels={"Área": "Área de Conhecimento", "count": "Quantidade"}
    )
    fig_area.update_layout(yaxis_title="Quantidade", xaxis_title="Área")
    st.plotly_chart(fig_area, use_container_width=True)

    # Gráfico 2: Desempenho por Subárea
    st.subheader("2. Desempenho por Subárea")
    fig_subarea = px.histogram(
        df_filtrado, 
        x="Subárea", 
        color="Resultado", 
        barmode="group",
        text_auto=True,
        color_discrete_map={'Acerto': '#28a745', 'Erro': '#dc3545', 'Não Respondeu': '#6c757d'}
    )
    fig_subarea.update_layout(yaxis_title="Quantidade", xaxis_title="Subárea")
    fig_subarea.update_xaxes(tickangle=-45) 
    st.plotly_chart(fig_subarea, use_container_width=True)

    # Gráfico 3: Acertos por Questão
    st.subheader("3. Volume de Acertos por Questão")
    df_acertos = df_filtrado[df_filtrado['Resultado'] == 'Acerto']
    
    # Verifica se há algum acerto para evitar erro na geração do gráfico
    if not df_acertos.empty:
        acertos_por_questao = df_acertos.groupby('Número da questão').size().reset_index(name='Quantidade de Acertos')

        fig_questao = px.bar(
            acertos_por_questao, 
            x='Número da questão', 
            y='Quantidade de Acertos', 
            text_auto=True,
            color_discrete_sequence=['#17a2b8']
        )
        fig_questao.update_xaxes(type='category')
        fig_questao.update_layout(xaxis_title="Número da Questão", yaxis_title="Total de Acertos")
        st.plotly_chart(fig_questao, use_container_width=True)
    else:
        st.info("Não houve acertos para os filtros selecionados.")