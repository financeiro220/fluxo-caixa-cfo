import streamlit as st
import pandas as pd
import numpy as np

# ---------------------------------------------------------
# CONFIGURAÇÃO DA PÁGINA E TEMA
# ---------------------------------------------------------
st.set_page_config(
    page_title="Fluxo de Caixa Executivo - CFO",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Estilização Personalizada (CSS)
st.markdown("""
<style>
    .main-header { font-size: 26px; font-weight: bold; color: #1B365D; margin-bottom: 5px; }
    .sub-header { font-size: 14px; color: #555; margin-bottom: 25px; }
    .welcome-card {
        background-color: #F8F9FA;
        border: 1px solid #E9ECEF;
        border-left: 6px solid #1B365D;
        border-radius: 8px;
        padding: 25px;
        margin-top: 15px;
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
# CABEÇALHO FIXO DA APLICAÇÃO
# ---------------------------------------------------------
st.markdown("<div class='main-header'>📊 Painel Executivo - Fluxo de Caixa do Grupo</div>", unsafe_allow_html=True)
st.markdown("<div class='sub-header'>Gestão Estratégica de Liquidez e Governança Financeira</div>", unsafe_allow_html=True)

# BARRA LATERAL
with st.sidebar:
    st.header("⚙️ Parâmetros")
    saldo_inicial = st.number_input("Saldo Inicial em Conta (R$)", value=36945.97, step=1000.0, format="%.2f")
    st.divider()
    st.header("📥 Carga de Dados")
    uploaded_file = st.file_uploader("Anexe o relatório (.xlsx)", type=["xlsx", "xls"])

# ---------------------------------------------------------
# RENDERIZAÇÃO DA TELA
# ---------------------------------------------------------
if uploaded_file is not None:
    try:
        df = processar_arquivo_bruto(uploaded_file)
        
        # Filtros no topo
        col_f1, col_f2 = st.columns(2)
        with col_f1:
            lojas_sel = st.multiselect(
                "Unidades / Lojas:",
                options=df['Empresa'].dropna().unique(),
                default=df['Empresa'].dropna().unique()
            )
        with col_f2:
            dias_sel = st.slider("Período (Dias do Mês):", min_value=1, max_value=31, value=(1, 31))
            
        df_filtered = df[
            (df['Empresa'].isin(lojas_sel)) & 
            (df['Dia'] >= dias_sel[0]) & 
            (df['Dia'] <= dias_sel[1])
        ].copy()
        
        # KPIs
        tot_previsto = df_filtered['Valor'].sum()
        tot_realizado = df_filtered[df_filtered['Status_Clean'] == 'REALIZADO']['Valor'].sum()
        tot_pendente = df_filtered[df_filtered['Status_Clean'] == 'PENDENTE']['Valor'].sum()
        
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Saldo Inicial", f"R$ {saldo_inicial:,.2f}")
        k2.metric("Total Previsto", f"R$ {tot_previsto:,.2f}")
        k3.metric("Total Liquidado", f"R$ {tot_realizado:,.2f}")
        k4.metric("Total Pendente", f"R$ {tot_pendente:,.2f}")
        
        st.divider()
        
        tab1, tab2, tab3, tab4 = st.tabs(["📋 DRE de Caixa", "📅 Fluxo Diário", "🏪 Por Loja", "🔍 Base Tratada"])
        
        with tab1:
            st.subheader("Demonstrativo do Fluxo de Caixa (Previsto vs. Realizado)")
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
            st.subheader("Matriz Diária de Vencimentos")
            pivot_daily = df_filtered.pivot_table(index='Categoria_CFO', columns='Dia', values='Valor', aggfunc='sum', fill_value=0)
            st.dataframe(pivot_daily.style.format("R$ {:,.2f}"), use_container_width=True)
            
            st.subheader("Curva Diária de Saídas")
            daily_chart = df_filtered.groupby('Dia')['Valor'].sum().reset_index()
            st.line_chart(daily_chart.set_index('Dia'))
            
        with tab3:
            st.subheader("Comparativo por Unidade de Negócio")
            pivot_store = df_filtered.pivot_table(index='Categoria_CFO', columns='Empresa', values='Valor', aggfunc='sum', fill_value=0)
            st.dataframe(pivot_store.style.format("R$ {:,.2f}"), use_container_width=True)
            st.bar_chart(pivot_store)
            
        with tab4:
            st.subheader("Lançamentos Categorizados")
            st.dataframe(df_filtered[['Número', 'Empresa', 'Cliente / Fornecedor', 'Vencimento', 'Valor', 'Plano de Contas', 'Categoria_CFO', 'Status_Clean']], use_container_width=True, hide_index=True)

    except Exception as e:
        st.error(f"Erro ao processar o arquivo: {e}")
else:
    # CARDE DE BOAS-VINDAS QUANDO NÃO HÁ ARQUIVO
    st.markdown("""
    <div class='welcome-card'>
        <h3>👋 Bem-vindo ao Sistema de Fluxo de Caixa Executivo</h3>
        <p>Para carregar os indicadores, relatórios e gráficos das lojas, siga os passos:</p>
        <ol>
            <li>Acesse o menu lateral à esquerda <b>(📥 Carga de Dados)</b>.</li>
            <li>Clique em <b>Browse files</b> e selecione o relatório <b>.xlsx</b> do ERP.</li>
            <li>O sistema processará as categorias e exibirá o painel automaticamente.</li>
        </ol>
    </div>
    """, unsafe_allow_html=True)