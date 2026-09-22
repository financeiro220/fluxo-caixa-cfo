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
    .stApp {
        background-color: #0E1117;
        color: #FFFFFF;
    }
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
# MOTOR DE CATEGORIZAÇÃO (CFO ENGINE: ENTRADAS & SAÍDAS)
# ---------------------------------------------------------
def categorizar_plano_contas(row):
    tipo = str(row.get('Tipo', '')).strip().lower()
    plano = str(row.get('Plano de Contas', '')).upper().strip()
    
    # Se for título de RECEBER / ENTRADA
    if 'receber' in tipo or 'entrada' in tipo or 'venda' in tipo:
        if any(k in plano for k in ['IFOOD', 'DELIVERY', 'APP']):
            return "0. RECEITA - DELIVERY / IFOOD"
        elif any(k in plano for k in ['CARTÃO', 'CARTAO', 'PIX', 'DINHEIRO', 'BALCÃO', 'BALCAO']):
            return "0. RECEITA - VENDAS LOJA / BALCÃO"
        else:
            return "0. RECEITA - OUTRAS ENTRADAS"
            
    # Se for título de PAGAR / SAÍDA
    if any(k in plano for k in ['CMV', 'DESCARTÁVEIS', 'DESCARTAVEIS', 'PRODUTO PARA REVENDA', 'LEITE', 'INSUMOS', 'MEC3', 'BOBINAS', 'FRUTAS', 'RIBERFOODS']):
        return "1. FORNECEDORES / MERCADORIAS (CMV)"
    elif any(k in plano for k in ['ICMS', 'IMPOSTO', 'FISCAL', 'DAS', 'TAXAS MUNICIPAIS', 'PIS', 'COFINS']):
        return "2. IMPOSTOS SOBRE VENDAS"
    elif any(k in plano for k in ['ALUGUEL', 'CONDOMÍNIO', 'CONDOMINIO', 'ENERGIA', 'ÁGUA', 'AGUA', 'IPTU', 'SEGURO PREDIAL', 'FUNDO DE PROMOÇÃO', 'LIMPEZA', 'FACHADA']):
        return "3. DESPESAS DE OCUPAÇÃO"
    elif any(k in plano for k in ['SALÁRIO', 'SALARIO', 'VALE', 'FOLHA', 'FGTS', 'FÉRIAS', 'FERIAS', 'DÉCIMO', 'DECIMO', 'AUXÍLIO', 'AUXILIO', 'PREMIAÇÕES', 'PREMIACOES', 'RESCISÃO', 'RESCISAO', 'DSR', 'ADICIONAL', 'PROVENTOS', 'FUNCIONÁRIOS', 'FUNCIONARIOS', 'UNIFORMES']):
        return "4. FOLHA DE PAGAMENTO & ENCARGOS"
    elif any(k in plano for k in ['EMPRÉSTIMO', 'EMPRESTIMO', 'MÚTUO', 'MUTUO', 'CAPITAL DE GIRO', 'SÓCIO', 'SOCIO', 'JUROS', 'MULTA', 'TARIFAS', 'RENEGOCIAÇÃO', 'RENEGOCIACAO', 'INVESTIMENTOS']):
        return "6. AMORTIZAÇÃO DE DÍVIDAS & CAPITAL"
    else:
        return "5. DESPESAS OPERACIONAIS & VENDAS"

@st.cache_data(ttl=3600)
def processar_arquivo_bruto(file):
    df_raw = pd.read_excel(file)
    
    header_idx = None
    for idx, row in df_raw.iterrows():
        row_str = " ".join(row.dropna().astype(str))
        if "Vencimento" in row_str and "Valor Bruto" in row_str:
            header_idx = idx
            break
            
    if header_idx is not None:
        df = df_raw.iloc[header_idx + 1:].copy()
        df.columns = df_raw.iloc[header_idx].values
    else:
        df = df_raw.copy()
        
    df['Valor'] = pd.to_numeric(df['Valor Bruto'], errors='coerce').fillna(0)
    df['Vencimento_dt'] = pd.to_datetime(df['Vencimento'], errors='coerce')
    df['Dia'] = df['Vencimento_dt'].dt.day
    df['Categoria_CFO'] = df.apply(categorizar_plano_contas, axis=1)
    
    # Identificar fluxo: Entradas vs Saídas
    df['Tipo_Fluxo'] = df['Tipo'].astype(str).apply(
        lambda x: "ENTRADA" if any(s in x.lower() for s in ['receber', 'entrada']) else "SAÍDA"
    )
    
    df['Status_Clean'] = df['Status'].astype(str).apply(
        lambda x: "REALIZADO" if any(s in x for s in ['Liquidado', 'Baixado', 'Conciliado']) else "PENDENTE"
    )
    return df

# ---------------------------------------------------------
# CABEÇALHO DA PÁGINA
# ---------------------------------------------------------
st.markdown("<div class='main-title'>🍦 Gelateria Borelli - Gestão Integrada de Fluxo de Caixa</div>", unsafe_allow_html=True)
st.markdown("<div class='main-subtitle'>Visão Consolidada de Entradas (Receitas), Saídas (Despesas) e Liquidez Real</div>", unsafe_allow_html=True)

# BARRA LATERAL
with st.sidebar:
    st.header("⚙️ Parâmetros")
    saldo_inicial = st.number_input("Saldo Inicial em Conta (R$)", value=36945.97, step=1000.0, format="%.2f")
    st.divider()
    st.header("📥 Carga de Dados")
    uploaded_file = st.file_uploader("Anexe o relatório completo (.xlsx)", type=["xlsx", "xls"])

if 'filtro_kpi' not in st.session_state:
    st.session_state.filtro_kpi = "TODOS"

# ---------------------------------------------------------
# RENDERIZAÇÃO
# ---------------------------------------------------------
if uploaded_file is not None:
    try:
        df = processar_arquivo_bruto(uploaded_file)
        
        min_date = df['Vencimento_dt'].min().date() if not df['Vencimento_dt'].isnull().all() else pd.to_datetime('today').date()
        max_date = df['Vencimento_dt'].max().date() if not df['Vencimento_dt'].isnull().all() else pd.to_datetime('today').date()

        # FILTROS SUPERIORES
        col_filtro1, col_filtro2 = st.columns([2, 1])
        
        with col_filtro1:
            st.caption("🏢 **Unidade / Loja:**")
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

        # Filtragem de Dados
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

        # CÁLCULO DOS KPIS DE FLUXO GLOBAL
        tot_receitas = df_filtered[df_filtered['Tipo_Fluxo'] == 'ENTRADA']['Valor'].sum()
        tot_despesas = df_filtered[df_filtered['Tipo_Fluxo'] == 'SAÍDA']['Valor'].sum()
        resultado_liquido = tot_receitas - tot_despesas
        saldo_final = saldo_inicial + resultado_liquido

        st.caption("👇 **Clique nos cartões de KPI abaixo para filtrar os títulos:**")

        # PAINEL SUPERIOR DE KPIS
        k1, k2, k3, k4, k5 = st.columns(5)
        
        with k1:
            st.metric("Saldo Inicial", f"R$ {saldo_inicial:,.2f}")

        with k2:
            if st.button(f"🟢 RECEITAS (ENTRADAS)\nR$ {tot_receitas:,.2f}", use_container_width=True):
                st.session_state.filtro_kpi = "ENTRADA"

        with k3:
            if st.button(f"🔴 DESPESAS (SAÍDAS)\nR$ {tot_despesas:,.2f}", use_container_width=True):
                st.session_state.filtro_kpi = "SAÍDA"

        with k4:
            color_res = "normal" if resultado_liquido >= 0 else "inverse"
            st.metric("Geração de Caixa", f"R$ {resultado_liquido:,.2f}", delta=f"{resultado_liquido:,.2f}")

        with k5:
            st.metric("Saldo Final Projetado", f"R$ {saldo_final:,.2f}")

        st.markdown("<br>", unsafe_allow_html=True)

        # 1. ABAS EXECUTIVAS CONSOLIDADAS
        tab1, tab2, tab3 = st.tabs(["📋 DRE de Caixa Integrada", "📅 Fluxo Diário de Caixa", "🏪 Comparativo Por Loja"])
        
        with tab1:
            st.subheader("Demonstrativo do Fluxo de Caixa Completo (Entradas vs. Saídas)")
            
            # Estruturação da DRE
            dre_data = []
            
            # Receitas
            dre_data.append({"Item": "1. RECEITAS OPERACIONAIS (ENTRADAS)", "Valor (R$)": f"R$ {tot_receitas:,.2f}", "% Vendas": "100.0%"})
            
            # Despesas por Categoria
            cats_saida = [
                "1. FORNECEDORES / MERCADORIAS (CMV)",
                "2. IMPOSTOS SOBRE VENDAS",
                "3. DESPESAS DE OCUPAÇÃO",
                "4. FOLHA DE PAGAMENTO & ENCARGOS",
                "5. DESPESAS OPERACIONAIS & VENDAS",
                "6. AMORTIZAÇÃO DE DÍVIDAS & CAPITAL"
            ]
            
            for c in cats_saida:
                val = df_filtered[df_filtered['Categoria_CFO'] == c]['Valor'].sum()
                pct = (val / tot_receitas * 100) if tot_receitas > 0 else 0
                dre_data.append({"Item": f"   (-) {c}", "Valor (R$)": f"R$ {val:,.2f}", "% Vendas": f"{pct:.1f}%"})
                
            dre_data.append({"Item": "(=) RESULTADO LÍQUIDO OPERACIONAL", "Valor (R$)": f"R$ {resultado_liquido:,.2f}", "% Vendas": f"{(resultado_liquido/tot_receitas*100) if tot_receitas>0 else 0:.1f}%"})
            
            st.dataframe(pd.DataFrame(dre_data), use_container_width=True, hide_index=True)
            
        with tab2:
            st.subheader("Evolução Diária de Caixa (Receitas x Despesas)")
            daily_pivot = df_filtered.pivot_table(index='Dia', columns='Tipo_Fluxo', values='Valor', aggfunc='sum', fill_value=0)
            st.line_chart(daily_pivot)
            
        with tab3:
            st.subheader("Geração de Caixa Por Unidade")
            if loja_selecionada != "Ver Todas as Lojas":
                st.info(f"Exibindo apenas a unidade **{loja_selecionada}**. Para comparar todas as lojas lado a lado, selecione **'Ver Todas as Lojas'** no topo.")
            pivot_store = df_filtered.pivot_table(index='Tipo_Fluxo', columns='Empresa', values='Valor', aggfunc='sum', fill_value=0)
            st.dataframe(pivot_store.style.format("R$ {:,.2f}"), use_container_width=True)
            st.bar_chart(pivot_store)

        st.divider()

        # 2. INSPEÇÃO DE TÍTULOS ABAIXO DAS RELATÓRIOS
        if st.session_state.filtro_kpi == "ENTRADA":
            df_titulos = df_filtered[df_filtered['Tipo_Fluxo'] == 'ENTRADA'].copy()
            titulo_tabela = f"🟢 Exibindo {len(df_titulos)} Títulos de RECEITA / ENTRADA (R$ {tot_receitas:,.2f})"
        elif st.session_state.filtro_kpi == "SAÍDA":
            df_titulos = df_filtered[df_filtered['Tipo_Fluxo'] == 'SAÍDA'].copy()
            titulo_tabela = f"🔴 Exibindo {len(df_titulos)} Títulos de DESPESA / SAÍDA (R$ {tot_despesas:,.2f})"
        else:
            df_titulos = df_filtered.copy()
            titulo_tabela = f"📊 Exibindo Todos os {len(df_titulos)} Lançamentos de Caixa"

        st.subheader(titulo_tabela)
        st.dataframe(
            df_titulos[['Número', 'Empresa', 'Cliente / Fornecedor', 'Vencimento', 'Valor', 'Tipo_Fluxo', 'Plano de Contas', 'Categoria_CFO', 'Status_Clean']],
            use_container_width=True,
            hide_index=True
        )

    except Exception as e:
        st.error(f"Erro ao processar o arquivo: {e}")
else:
    st.markdown("""
    <div class='welcome-card'>
        <h3>🍦 Painel de Fluxo de Caixa Executivo - Gelateria Borelli</h3>
        <p>Aguardando carga do relatório financeiro do ERP (Contas a Pagar e Contas a Receber).</p>
        <ol>
            <li>Acesse o menu lateral à esquerda <b>(📥 Carga de Dados)</b>.</li>
            <li>Anexe o arquivo <b>.xlsx</b>.</li>
        </ol>
    </div>
    """, unsafe_allow_html=True)