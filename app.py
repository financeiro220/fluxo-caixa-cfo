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
# FUNÇÕES DE PROCESSAMENTO E CONVERSÃO
# ---------------------------------------------------------
def converter_valor_ptbr(val):
    if pd.isna(val): return 0.0
    if isinstance(val, (int, float)): return float(val)
    val_str = str(val).replace('.', '').replace(',', '.')
    try:
        return float(val_str)
    except:
        return 0.0

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
def processar_relatorio_receitas(file, nome_loja):
    df_raw = pd.read_excel(file)
    df_raw.columns = [str(c).strip().upper() for c in df_raw.columns]
    
    col_total = 'TOTAL COM PRAZO' if 'TOTAL COM PRAZO' in df_raw.columns else 'TOTAL SEM PRAZO'
    if col_total not in df_raw.columns:
        col_total = [c for c in df_raw.columns if 'TOTAL' in c][0]
        
    df_receitas = pd.DataFrame()
    df_receitas['Valor'] = df_raw[col_total].apply(converter_valor_ptbr)
    df_receitas['Vencimento_dt'] = pd.to_datetime(df_raw['DATA'], dayfirst=True, errors='coerce')
    df_receitas['Dia'] = df_receitas['Vencimento_dt'].dt.day
    df_receitas['Empresa'] = nome_loja
    df_receitas['Tipo_Fluxo'] = 'ENTRADA'
    df_receitas['Categoria_CFO'] = '0. RECEITA DE VENDAS (LOJAS)'
    df_receitas['Status_Clean'] = 'REALIZADO'
    df_receitas['Cliente / Fornecedor'] = 'CLIENTES BALCÃO / DELIVERY'
    df_receitas['Plano de Contas'] = 'VENDAS LOJA'
    df_receitas['Número'] = 'VENDAS-DIA'
    
    return df_receitas.dropna(subset=['Vencimento_dt'])

@st.cache_data(ttl=3600)
def processar_arquivo_despesas(file):
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
        
    df = df[df['Tipo'].astype(str).str.contains('A Pagar|Pagar', case=False, na=False)].copy()
    df['Valor'] = pd.to_numeric(df['Valor Bruto'], errors='coerce').fillna(0)
    df['Vencimento_dt'] = pd.to_datetime(df['Vencimento'], errors='coerce')
    df['Dia'] = df['Vencimento_dt'].dt.day
    df['Categoria_CFO'] = df['Plano de Contas'].apply(categorizar_plano_contas)
    df['Tipo_Fluxo'] = 'SAÍDA'
    df['Status_Clean'] = df['Status'].astype(str).apply(
        lambda x: "REALIZADO" if any(s in str(x) for s in ['Liquidado', 'Baixado', 'Conciliado']) else "PENDENTE"
    )
    return df

# ---------------------------------------------------------
# CABEÇALHO DA PÁGINA
# ---------------------------------------------------------
st.markdown("<div class='main-title'>🍦 Gelateria Borelli - Gestão de Fluxo de Caixa</div>", unsafe_allow_html=True)
st.markdown("<div class='main-subtitle'>Acompanhamento de liquidez, governança e DRE Previsto vs. Realizado</div>", unsafe_allow_html=True)

# BARRA LATERAL
with st.sidebar:
    st.header("⚙️ Parâmetros")
    saldo_inicial = st.number_input("Saldo Inicial em Conta (R$)", value=36945.97, step=1000.0, format="%.2f")
    
    st.divider()
    st.header("📥 Relatório ERP (Despesas)")
    uploaded_file = st.file_uploader("Anexe o Rateio de Títulos (.xlsx)", type=["xlsx", "xls"])
    
    st.divider()
    st.header("🍦 Faturamento Lojas (Receitas)")
    file_pantanal = st.file_uploader("Vendas Pantanal (.xlsx)", type=["xlsx", "xls"], key="p")
    file_goiabeiras = st.file_uploader("Vendas Goiabeiras (.xlsx)", type=["xlsx", "xls"], key="g")
    file_estacao = st.file_uploader("Vendas Estação (.xlsx)", type=["xlsx", "xls"], key="e")

if 'filtro_kpi' not in st.session_state:
    st.session_state.filtro_kpi = "PENDENTE"

# ---------------------------------------------------------
# RENDERIZAÇÃO
# ---------------------------------------------------------
if uploaded_file is not None:
    try:
        dfs_consolidados = []
        
        # 1. Processar Despesas
        df_desp = processar_arquivo_despesas(uploaded_file)
        dfs_consolidados.append(df_desp)
        
        # 2. Processar Receitas das Lojas
        if file_pantanal is not None:
            dfs_consolidados.append(processar_relatorio_receitas(file_pantanal, "4- PANTANAL"))
        if file_goiabeiras is not None:
            dfs_consolidados.append(processar_relatorio_receitas(file_goiabeiras, "8 - GOIABEIRAS"))
        if file_estacao is not None:
            dfs_consolidados.append(processar_relatorio_receitas(file_estacao, "5- ESTAÇÃO"))
            
        df = pd.concat(dfs_consolidados, ignore_index=True)
        
        min_date = df['Vencimento_dt'].min().date() if not df['Vencimento_dt'].isnull().all() else pd.to_datetime('today').date()
        max_date = df['Vencimento_dt'].max().date() if not df['Vencimento_dt'].isnull().all() else pd.to_datetime('today').date()

        # FILTROS SUPERIORES
        col_filtro1, col_filtro2 = st.columns([2, 1])
        
        with col_filtro1:
            st.caption("🏢 **Unidade / Loja:**")
            lojas_disponiveis = list(df_desp['Empresa'].dropna().unique())
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
            df_desp_filtered = df_desp.copy()
        else:
            df_filtered = df[df['Empresa'] == loja_selecionada].copy()
            df_desp_filtered = df_desp[df_desp['Empresa'] == loja_selecionada].copy()

        if isinstance(date_range, tuple) and len(date_range) == 2:
            start_date, end_date = date_range
            df_filtered = df_filtered[
                (df_filtered['Vencimento_dt'].dt.date >= start_date) & 
                (df_filtered['Vencimento_dt'].dt.date <= end_date)
            ]
            df_desp_filtered = df_desp_filtered[
                (df_desp_filtered['Vencimento_dt'].dt.date >= start_date) & 
                (df_desp_filtered['Vencimento_dt'].dt.date <= end_date)
            ]

        st.divider()

        # CÁLCULO DOS KPIS
        tot_receitas = df_filtered[df_filtered['Tipo_Fluxo'] == 'ENTRADA']['Valor'].sum()
        tot_previsto = df_desp_filtered['Valor'].sum()
        tot_realizado = df_desp_filtered[df_desp_filtered['Status_Clean'] == 'REALIZADO']['Valor'].sum()
        tot_pendente = df_desp_filtered[df_desp_filtered['Status_Clean'] == 'PENDENTE']['Valor'].sum()
        
        geracao_caixa = (saldo_inicial + tot_receitas) - tot_realizado

        st.caption("👇 **Clique nos botões para filtrar os títulos na tabela inferior:**")

        # KPIS COMO BOTÕES INTERATIVOS
        k1, k2, k3, k4, k5 = st.columns(5)
        
        with k1:
            st.metric("Saldo Inicial", f"R$ {saldo_inicial:,.2f}")

        with k2:
            if st.button(f"📊 PAGAMENTOS PREVISTOS\nR$ {tot_previsto:,.2f}", use_container_width=True):
                st.session_state.filtro_kpi = "TODOS"

        with k3:
            if st.button(f"🟢 PAGAMENTOS LIQUIDADOS\nR$ {tot_realizado:,.2f}", use_container_width=True):
                st.session_state.filtro_kpi = "REALIZADO"

        with k4:
            if st.button(f"🔴 PAGAMENTOS EM ABERTO\nR$ {tot_pendente:,.2f}", use_container_width=True):
                st.session_state.filtro_kpi = "PENDENTE"

        with k5:
            delta_label = f"Vendas: R$ {tot_receitas:,.2f}" if tot_receitas > 0 else None
            st.metric("Geração de Caixa", f"R$ {geracao_caixa:,.2f}", delta=delta_label)

        st.markdown("<br>", unsafe_allow_html=True)

        # 1. VISÕES CONSOLIDADAS (DRE, DIÁRIO, LOJA)
        tab1, tab2, tab3 = st.tabs(["📋 DRE de Caixa Integrada", "📅 Fluxo Diário (Calendário)", "🏪 Comparativo Por Loja"])
        
        with tab1:
            st.subheader("Demonstrativo do Fluxo de Caixa (Receitas vs. Despesas)")
            
            dre_list = []
            # Linha de Receitas
            dre_list.append({
                "Categoria CFO": "0. RECEITA DE VENDAS (LOJAS)",
                "Previsto (R$)": f"R$ {tot_receitas:,.2f}",
                "Realizado (R$)": f"R$ {tot_receitas:,.2f}",
                "Variação (R$)": "R$ 0.00",
                "% do Total": "100.0%"
            })
            
            # Linhas de Despesas
            cats = [
                "1. FORNECEDORES / MERCADORIAS (CMV)",
                "2. IMPOSTOS SOBRE VENDAS",
                "3. DESPESAS DE OCUPAÇÃO",
                "4. FOLHA DE PAGAMENTO & ENCARGOS",
                "5. DESPESAS OPERACIONAIS & VENDAS",
                "6. AMORTIZAÇÃO DE DÍVIDAS & CAPITAL"
            ]
            
            for c in cats:
                p = df_desp_filtered[df_desp_filtered['Categoria_CFO'] == c]['Valor'].sum()
                r = df_desp_filtered[(df_desp_filtered['Categoria_CFO'] == c) & (df_desp_filtered['Status_Clean'] == 'REALIZADO')]['Valor'].sum()
                v = r - p
                pct = (p / tot_receitas * 100) if tot_receitas > 0 else ((p / tot_previsto * 100) if tot_previsto > 0 else 0)
                dre_list.append({
                    "Categoria CFO": f"   (-) {c}",
                    "Previsto (R$)": f"R$ {p:,.2f}",
                    "Realizado (R$)": f"R$ {r:,.2f}",
                    "Variação (R$)": f"R$ {v:,.2f}",
                    "% do Total": f"{pct:.1f}%"
                })
                
            # Resultado Líquido
            res_prev = tot_receitas - tot_previsto
            res_real = tot_receitas - tot_realizado
            dre_list.append({
                "Categoria CFO": "(=) RESULTADO LÍQUIDO OPERACIONAL",
                "Previsto (R$)": f"R$ {res_prev:,.2f}",
                "Realizado (R$)": f"R$ {res_real:,.2f}",
                "Variação (R$)": f"R$ {res_real - res_prev:,.2f}",
                "% do Total": f"{(res_real / tot_receitas * 100) if tot_receitas > 0 else 0:.1f}%"
            })
            
            st.dataframe(pd.DataFrame(dre_list), use_container_width=True, hide_index=True)
            
        with tab2:
            st.subheader("Matriz Diária de Caixa no Mês (Receitas e Despesas)")
            pivot_daily = df_filtered.pivot_table(index='Categoria_CFO', columns='Dia', values='Valor', aggfunc='sum', fill_value=0)
            st.dataframe(pivot_daily.style.format("R$ {:,.2f}"), use_container_width=True)
            
        with tab3:
            st.subheader("Matriz Comparativa entre Lojas")
            if loja_selecionada != "Ver Todas as Lojas":
                st.info(f"Você está visualizando apenas a unidade **{loja_selecionada}**. Para comparar todas as unidades lado a lado, selecione **'Ver Todas as Lojas'** no filtro do topo.")
            pivot_store = df_filtered.pivot_table(index='Categoria_CFO', columns='Empresa', values='Valor', aggfunc='sum', fill_value=0)
            st.dataframe(pivot_store.style.format("R$ {:,.2f}"), use_container_width=True)

        st.divider()

        # 2. DETALHAMENTO DOS TÍTULOS
        if st.session_state.filtro_kpi == "REALIZADO":
            df_titulos = df_desp_filtered[df_desp_filtered['Status_Clean'] == 'REALIZADO'].copy()
            titulo_tabela = f"🟢 Exibindo {len(df_titulos)} Títulos LIQUIDADOS (R$ {tot_realizado:,.2f})"
        elif st.session_state.filtro_kpi == "PENDENTE":
            df_titulos = df_desp_filtered[df_desp_filtered['Status_Clean'] == 'PENDENTE'].copy()
            titulo_tabela = f"🔴 Exibindo {len(df_titulos)} Títulos PENDENTES (R$ {tot_pendente:,.2f})"
        else:
            df_titulos = df_desp_filtered.copy()
            titulo_tabela = f"📊 Exibindo Todos os {len(df_titulos)} Títulos PREVISTOS (R$ {tot_previsto:,.2f})"

        st.subheader(titulo_tabela)
        
        df_display = df_titulos.copy()
        df_display['Vencimento'] = df_display['Vencimento_dt'].dt.strftime('%d/%m/%Y')
        
        st.dataframe(
            df_display[['Número', 'Empresa', 'Cliente / Fornecedor', 'Vencimento', 'Valor', 'Plano de Contas', 'Categoria_CFO', 'Status_Clean']],
            use_container_width=True,
            hide_index=True
        )

    except Exception as e:
        st.error(f"Erro ao processar o arquivo: {e}")
else:
    st.markdown("""
    <div class='welcome-card'>
        <h3>🍦 Painel de Fluxo de Caixa Executivo - Gelateria Borelli</h3>
        <p>Aguardando carga dos relatórios no menu lateral para inicializar o processamento.</p>
        <ol>
            <li>Anexe o arquivo de despesas no menu lateral <b>(📥 Relatório ERP)</b>.</li>
            <li>Anexe os arquivos de faturamento das lojas <b>(Pantanal, Goiabeiras, Estação)</b>.</li>
        </ol>
    </div>
    """, unsafe_allow_html=True)