import streamlit as st
import pandas as pd
import numpy as np

# ---------------------------------------------------------
# CONFIGURAÇÃO DA PÁGINA E TEMA BORELLI
# ---------------------------------------------------------
st.set_page_config(
    page_title="Gelateria Borelli - Fluxo de Caixa CFO",
    page_icon="🟢",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Estilização CSS Personalizada (Identidade Borelli)
st.markdown("""
<style>
    /* Fundo Global */
    .stApp {
        background-color: #0E1117;
        color: #FFFFFF;
    }
    
    /* Cabeçalho Principal */
    .main-title {
        font-size: 28px;
        font-weight: bold;
        color: #00875A;
        margin-bottom: 5px;
    }
    .main-subtitle {
        font-size: 14px;
        color: #A0AAB0;
        margin-bottom: 20px;
    }

    /* Cards de KPIs */
    .kpi-card {
        background-color: #161B22;
        border: 1px solid #30363D;
        border-radius: 8px;
        padding: 18px;
        text-align: left;
    }
    .kpi-label {
        font-size: 13px;
        color: #8B949E;
        font-weight: 600;
        text-transform: uppercase;
    }
    .kpi-value {
        font-size: 24px;
        font-weight: bold;
        color: #FFFFFF;
        margin-top: 5px;
    }
    .kpi-green { border-left: 5px solid #00875A; }
    .kpi-red { border-left: 5px solid #FF4D4D; }
    .kpi-blue { border-left: 5px solid #3182CE; }
    
    /* Card de Boas-Vindas */
    .welcome-card {
        background-color: #161B22;
        border: 1px solid #30363D;
        border-left: 6px solid #00875A;
        border-radius: 8px;
        padding: 25px;
        margin-top: 20px;
    }
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------
# MOTOR DE CATEGORIZAÇÃO (CFO ENGINE)
# ---------------------------------------------------------
def categorizar_plano_contas(plano):
    if pd.isna(plano):
        return "5. DESPESAS OPERACIONAIS & VENDAS"
    
    p = str(plano).upper().strip()
    
    if any(k in p for k in ['CMV', 'DESCARTÁVEIS', 'DESCARTAVEIS', 'PRODUTO PARA REVENDA', 'LEITE', 'INSUMOS', 'MEC3', 'BOBINAS', 'FRUTAS', 'RIBERFOODS']):
        return "1. FORNECEDORES / MERCADORIAS (CMV)"
    elif any(k in p for k in ['ICMS', 'IMPOSTO', 'FISCAL', 'DAS', 'TAXAS MUNICIPAIS', 'PIS', 'COFINS']):
        return "2. IMPOSTOS SOBRE VENDAS"
    elif any(k in p for k in ['ALUGUEL', 'CONDOMÍNIO', 'CONDOMINIO', 'ENERGIA', 'ÁGUA', 'AGUA', 'IPTU', 'SEGURO PREDIAL', 'FUNDO DE PROMOÇÃO', 'LIMPEZA', 'FACHADA']):
        return "3. DESPESAS DE OCUPAÇÃO"
    elif any(k in p for k in ['SALÁRIO', 'SALARIO', 'VALE', 'FOLHA', 'FGTS', 'FÉRIAS', 'FERIAS', 'DÉCIMO', 'DECIMO', 'AUXÍLIO', 'AUXILIO', 'PREMIAÇÕES', 'PREMIACOES', 'RESCISÃO', 'RESCISAO', 'DSR', 'ADICIONAL', 'PROVENTOS', 'FUNCIONÁRIOS', 'FUNCIONARIOS', 'UNIFORMES']):
        return "4. FOLHA DE PAGAMENTO & ENCARGOS"
    elif any(k in p for k in ['EMPRÉSTIMO', 'EMPRESTIMO', 'MÚTUO', 'MUTUO', 'CAPITAL DE GIRO', 'SÓCIO', 'SOCIO', 'JUROS', 'MULTA', 'TARIFAS', 'RENEGOCIAÇÃO', 'RENEGOCIACAO', 'INVESTIMENTOS']):
        return "6. AMORTIZAÇÃO DE DÍVIDAS & CAPITAL"
    else:
        return "5. DESPESAS OPERACIONAIS & VENDAS"

@st.cache_data(ttl=3600)
def processar_arquivo_bruto(file):
    df_raw = pd.read_excel(file)
    
    header_idx = None
    for idx, row in df_raw.iterrows():
        row_str = " ".join(row.dropna().astype(str))
        if "Tipo" in row_str and "Vencimento" in row_str and "Valor Bruto" in row_str:
            header_idx = idx
            break
            
    if header_idx is not None:
        df = df_raw.iloc[header_idx + 1:].copy()
        df.columns = df_raw.iloc[header_idx].values
    else:
        df = df_raw.copy()
        
    df = df[df['Tipo'] == 'A Pagar'].copy()
    df['Valor'] = pd.to_numeric(df['Valor Bruto'], errors='coerce').fillna(0)
    df['Vencimento_dt'] = pd.to_datetime(df['Vencimento'], errors='coerce')
    df['Dia'] = df['Vencimento_dt'].dt.day
    df['Categoria_CFO'] = df['Plano de Contas'].apply(categorizar_plano_contas)
    df['Status_Clean'] = df['Status'].astype(str).apply(
        lambda x: "REALIZADO" if any(s in x for s in ['Liquidado', 'Baixado', 'Conciliado']) else "PENDENTE"
    )
    return df

# ---------------------------------------------------------
# CABEÇALHO DA PÁGINA
# ---------------------------------------------------------
st.markdown("<div class='main-title'>🍦 Gelateria Borelli - Gestão de Fluxo de Caixa</div>", unsafe_allow_html=True)
st.markdown("<div class='main-subtitle'>Acompanhamento diário de liquidez e gestão estratégica financeira</div>", unsafe_allow_html=True)

# BARRA LATERAL
with st.sidebar:
    st.header("⚙️ Parâmetros")
    saldo_inicial = st.number_input("Saldo Inicial em Conta (R$)", value=36945.97, step=1000.0, format="%.2f")
    st.divider()
    st.header("📥 Carga de Dados")
    uploaded_file = st.file_uploader("Anexe o relatório (.xlsx)", type=["xlsx", "xls"])

# ---------------------------------------------------------
# RENDERIZAÇÃO
# ---------------------------------------------------------
if uploaded_file is not None:
    try:
        df = processar_arquivo_bruto(uploaded_file)
        
        # Obter intervalo de datas do arquivo
        min_date = df['Vencimento_dt'].min().date() if not df['Vencimento_dt'].isnull().all() else pd.to_datetime('today').date()
        max_date = df['Vencimento_dt'].max().date() if not df['Vencimento_dt'].isnull().all() else pd.to_datetime('today').date()

        # FILTROS SUPERIORES (Estilo Borelli Dashboard)
        col_filtro1, col_filtro2 = st.columns([2, 1])
        
        with col_filtro1:
            st.caption("🏢 **Filtrar por Unidade / Loja:**")
            lojas_disponiveis = list(df['Empresa'].dropna().unique())
            lojas_opcoes = ["Ver Todas as Lojas"] + lojas_disponiveis
            loja_selecionada = st.radio("", lojas_opcoes, horizontal=True)

        with col_filtro2:
            st.caption("📅 **Período de Vencimento:**")
            date_range = st.date_input(
                "",
                value=(min_date, max_date),
                min_value=min_date,
                max_value=max_date,
                format="DD/MM/YYYY"
            )

        # Aplicação dos Filtros
        if loja_selecionada == "Ver Todas as Lojas":
            df_filtered = df.copy()
        else:
            df_filtered = df[df['Empresa'] == loja_selecionada].copy()

        if isinstance(date_range, tuple) and len(date_range) == 2:
            start_date, end_date = date_range
            df_filtered = df_filtered[
                (df_filtered['Vencimento_dt'].dt.date >= start_date) & 
                (df_filtered['Vencimento_dt'].dt.date <= end_date)
            ]

        st.divider()

        # KPIs REESTILIZADOS
        tot_previsto = df_filtered['Valor'].sum()
        tot_realizado = df_filtered[df_filtered['Status_Clean'] == 'REALIZADO']['Valor'].sum()
        tot_pendente = df_filtered[df_filtered['Status_Clean'] == 'PENDENTE']['Valor'].sum()

        k1, k2, k3, k4 = st.columns(4)
        with k1:
            st.markdown(f"""
            <div class='kpi-card kpi-blue'>
                <div class='kpi-label'>Saldo Inicial</div>
                <div class='kpi-value'>R$ {saldo_inicial:,.2f}</div>
            </div>
            """, unsafe_allow_html=True)
        with k2:
            st.markdown(f"""
            <div class='kpi-card kpi-green'>
                <div class='kpi-label'>Total Previsto</div>
                <div class='kpi-value'>R$ {tot_previsto:,.2f}</div>
            </div>
            """, unsafe_allow_html=True)
        with k3:
            st.markdown(f"""
            <div class='kpi-card kpi-red'>
                <div class='kpi-label'>Total Liquidado</div>
                <div class='kpi-value'>R$ {tot_realizado:,.2f}</div>
            </div>
            """, unsafe_allow_html=True)
        with k4:
            st.markdown(f"""
            <div class='kpi-card kpi-green'>
                <div class='kpi-label'>Total Pendente</div>
                <div class='kpi-value'>R$ {tot_pendente:,.2f}</div>
            </div>
            """, unsafe_allow_html=True)

        st.markdown("<br>", unsafe_allow_html=True)

        # ABAS DE RELATÓRIO
        tab1, tab2, tab3, tab4 = st.tabs(["📋 DRE de Caixa", "📅 Fluxo Diário", "🏪 Por Loja", "🔍 Base Tratada"])
        
        with tab1:
            st.subheader("Demonstrativo de Saídas (Previsto vs. Realizado)")
            cats = [
                "1. FORNECEDORES / MERCADORIAS (CMV)",
                "2. IMPOSTOS SOBRE VENDAS",
                "3. DESPESAS DE OCUPAÇÃO",
                "4. FOLHA DE PAGAMENTO & ENCARGOS",
                "5. DESPESAS OPERACIONAIS & VENDAS",
                "6. AMORTIZAÇÃO DE DÍVIDAS & CAPITAL"
            ]
            dre_list = []
            for c in cats:
                p = df_filtered[df_filtered['Categoria_CFO'] == c]['Valor'].sum()
                r = df_filtered[(df_filtered['Categoria_CFO'] == c) & (df_filtered['Status_Clean'] == 'REALIZADO')]['Valor'].sum()
                v = r - p
                dre_list.append({
                    "Categoria CFO": c,
                    "Previsto (R$)": f"R$ {p:,.2f}",
                    "Realizado (R$)": f"R$ {r:,.2f}",
                    "Variação (R$)": f"R$ {v:,.2f}",
                    "% do Total": f"{(p/tot_previsto*100) if tot_previsto>0 else 0:.1f}%"
                })
            st.dataframe(pd.DataFrame(dre_list), use_container_width=True, hide_index=True)
            
        with tab2:
            st.subheader("Vencimentos Diários")
            pivot_daily = df_filtered.pivot_table(index='Categoria_CFO', columns='Dia', values='Valor', aggfunc='sum', fill_value=0)
            st.dataframe(pivot_daily.style.format("R$ {:,.2f}"), use_container_width=True)
            
            st.subheader("Curva de Desembolso")
            daily_chart = df_filtered.groupby('Dia')['Valor'].sum().reset_index()
            st.line_chart(daily_chart.set_index('Dia'))
            
        with tab3:
            st.subheader("Comparativo entre Lojas")
            pivot_store = df_filtered.pivot_table(index='Categoria_CFO', columns='Empresa', values='Valor', aggfunc='sum', fill_value=0)
            st.dataframe(pivot_store.style.format("R$ {:,.2f}"), use_container_width=True)
            st.bar_chart(pivot_store)
            
        with tab4:
            st.subheader("Base de Dados Tratada")
            st.dataframe(df_filtered[['Número', 'Empresa', 'Cliente / Fornecedor', 'Vencimento', 'Valor', 'Plano de Contas', 'Categoria_CFO', 'Status_Clean']], use_container_width=True, hide_index=True)

    except Exception as e:
        st.error(f"Erro ao processar o arquivo: {e}")
else:
    st.markdown("""
    <div class='welcome-card'>
        <h3>🍦 Painel de Fluxo de Caixa Executivo - Gelateria Borelli</h3>
        <p>Aguardando carga do relatório para inicializar o processamento.</p>
        <ol>
            <li>Acesse o menu lateral à esquerda <b>(📥 Carga de Dados)</b>.</li>
            <li>Faça o upload do arquivo <b>.xlsx</b> retirado do ERP.</li>
        </ol>
    </div>
    """, unsafe_allow_html=True)