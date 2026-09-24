import streamlit as st
import pandas as pd
import numpy as np
import requests
import json
from datetime import datetime, date, timedelta

# ---------------------------------------------------------
# CONFIGURAÇÃO DA PÁGINA E TEMA BORELLI
# ---------------------------------------------------------
st.set_page_config(
    page_title="Gelateria Borelli - Gestão de Fluxo de Caixa",
    page_icon="🟢",
    layout="wide",
    initial_sidebar_state="expanded"
)

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

# TOKEN API F360 E MAPA DE CNPJS
F360_TOKEN = "11001cbb-792d-45e5-b2f9-03ffc46fe7ed"

MAPA_CNPJ_LOJA = {
    "36.240.923/0001-68": "4- PANTANAL",
    "36.240.923/0002-49": "5- ESTAÇÃO",
    "36.240.923/0003-20": "8 - GOIABEIRAS"
}

# ---------------------------------------------------------
# AUTENTICAÇÃO E BUSCA DIRETA DE VENCIMENTOS F360
# ---------------------------------------------------------
def autenticar_f360(token_api):
    url = "https://financas.f360.com.br/PublicLoginAPI/DoLogin"
    headers = {"Content-Type": "application/json"}
    payload = {"token": token_api}
    try:
        r = requests.post(url, json=payload, headers=headers, timeout=10)
        if r.status_code == 200:
            res = r.json()
            if isinstance(res, dict):
                return res.get("Token") or res.get("Result") or res.get("token")
            return res
        return None
    except:
        return None

def categorizar_plano_contas(plano):
    if pd.isna(plano):
        return "5. DESPESAS OPERACIONAIS & VENDAS"
    
    p = str(plano).upper().strip()
    
    if any(k in p for k in ['MÚTUO', 'MUTUO', 'TRANSFERÊNCIA', 'TRANSFERENCIA', 'MUMTUO']):
        return "7. TRANSFERÊNCIAS INTERCOMPANY / MÚTUO"
    elif any(k in p for k in ['CMV', 'DESCARTÁVEIS', 'DESCARTAVEIS', 'PRODUTO PARA REVENDA', 'LEITE', 'INSUMOS', 'MEC3', 'BOBINAS', 'FRUTAS', 'RIBERFOODS']):
        return "1. FORNECEDORES / MERCADORIAS (CMV)"
    elif any(k in p for k in ['ICMS', 'IMPOSTO', 'FISCAL', 'DAS', 'TAXAS MUNICIPAIS', 'PIS', 'COFINS']):
        return "2. IMPOSTOS SOBRE VENDAS"
    elif any(k in p for k in ['ALUGUEL', 'CONDOMÍNIO', 'CONDOMINIO', 'ENERGIA', 'ÁGUA', 'AGUA', 'IPTU', 'SEGURO PREDIAL', 'FUNDO DE PROMOÇÃO', 'LIMPEZA', 'FACHADA']):
        return "3. DESPESAS DE OCUPAÇÃO"
    elif any(k in p for k in ['SALÁRIO', 'SALARIO', 'VALE', 'FOLHA', 'FGTS', 'FÉRIAS', 'FERIAS', 'DÉCIMO', 'DECIMO', 'AUXÍLIO', 'AUXILIO', 'PREMIAÇÕES', 'PREMIACOES', 'RESCISÃO', 'RESCISAO', 'DSR', 'ADICIONAL', 'PROVENTOS', 'FUNCIONÁRIOS', 'FUNCIONARIOS', 'UNIFORMES']):
        return "4. FOLHA DE PAGAMENTO & ENCARGOS"
    elif any(k in p for k in ['EMPRÉSTIMO', 'EMPRESTIMO', 'CAPITAL DE GIRO', 'JUROS', 'MULTA', 'TARIFAS', 'RENEGOCIAÇÃO', 'RENEGOCIACAO', 'INVESTIMENTOS']):
        return "6. AMORTIZAÇÃO DE DÍVIDAS & CAPITAL"
    else:
        return "5. DESPESAS OPERACIONAIS & VENDAS"

# ---------------------------------------------------------
# LEITURA DE EXCEL (RATEIO DE TÍTULOS COM VENCIMENTO REAL)
# ---------------------------------------------------------
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
    status_invalidos = ['cancelado', 'baixado']
    df = df[~df['Status'].astype(str).str.lower().apply(lambda x: any(s in x for s in status_invalidos))].copy()
    
    df['Valor'] = pd.to_numeric(df['Valor Bruto'], errors='coerce').fillna(0)
    df['Vencimento_dt'] = pd.to_datetime(df['Vencimento'], errors='coerce')
    df = df.dropna(subset=['Vencimento_dt']).copy()
    df['Vencimento_dt'] = pd.to_datetime(df['Vencimento_dt'])
    df['Dia'] = df['Vencimento_dt'].dt.day
    df['Categoria_CFO'] = df['Plano de Contas'].apply(categorizar_plano_contas)
    
    df['Status_Clean'] = df['Status'].astype(str).apply(
        lambda x: "REALIZADO" if any(s in str(x) for s in ['Liquidado', 'Conciliado']) else "PENDENTE"
    )
    return df

@st.cache_data(ttl=3600)
def processar_fluxo_caixa_loja(file, nome_loja):
    xls = pd.ExcelFile(file)
    sheet_name = 'Fluxo de Caixa' if 'Fluxo de Caixa' in xls.sheet_names else xls.sheet_names[0]
    df_raw = pd.read_excel(file, sheet_name=sheet_name)
    
    header_row = None
    for idx, row in df_raw.iterrows():
        row_str = " ".join(row.dropna().astype(str))
        if "Data" in row_str and "Total" in row_str:
            header_row = idx
            break
            
    if header_row is not None:
        df = df_raw.iloc[header_row + 1:].copy()
        df.columns = df_raw.iloc[header_row].values
    else:
        df = df_raw.copy()
        
    df.columns = [str(c).strip() for c in df.columns]
    df['Vencimento_dt'] = pd.to_datetime(df['Data'], errors='coerce')
    df = df.dropna(subset=['Vencimento_dt']).copy()
    df['Vencimento_dt'] = pd.to_datetime(df['Vencimento_dt'])
    df['Dia'] = df['Vencimento_dt'].dt.day
    
    cols_total = [i for i, col in enumerate(df.columns) if col == 'Total']
    if len(cols_total) >= 2:
        df['Entradas'] = pd.to_numeric(df.iloc[:, cols_total[0]], errors='coerce').fillna(0)
        df['Saídas'] = pd.to_numeric(df.iloc[:, cols_total[1]], errors='coerce').fillna(0)
    else:
        df['Entradas'] = 0.0
        df['Saídas'] = 0.0

    df['Saldo_Banco'] = pd.to_numeric(df['Saldo'], errors='coerce').fillna(0)
    df['Empresa'] = nome_loja
    return df

# ---------------------------------------------------------
# INTERFACE DO USUÁRIO
# ---------------------------------------------------------
st.markdown("<div class='main-title'>🍦 Gelateria Borelli - Gestão de Fluxo de Caixa</div>", unsafe_allow_html=True)
st.markdown("<div class='main-subtitle'>Acompanhamento de liquidez, governança e extrato acumulado diário</div>", unsafe_allow_html=True)

with st.sidebar:
    st.header("⚡ Integração F360 API")
    usar_api = st.toggle("Usar API F360 (Tempo Real)", value=False)
    
    if usar_api:
        jwt_token = autenticar_f360(F360_TOKEN)
        if jwt_token:
            st.success("🟢 Sessão JWT Válida!")
        else:
            st.error("🔴 Falha na autenticação JWT F360")
            
    st.divider()
    st.header("📥 Relatório ERP (Despesas / Rateio)")
    uploaded_file = st.file_uploader("Anexe o Rateio de Títulos em Excel (.xlsx)", type=["xlsx", "xls"])
    
    st.divider()
    st.header("🍦 Fluxo de Caixa Por Loja")
    file_pantanal = st.file_uploader("Fluxo Pantanal (.xlsx)", type=["xlsx", "xls"], key="p")
    file_goiabeiras = st.file_uploader("Fluxo Goiabeiras (.xlsx)", type=["xlsx", "xls"], key="g")
    file_estacao = st.file_uploader("Fluxo Estação (.xlsx)", type=["xlsx", "xls"], key="e")

if 'filtro_kpi' not in st.session_state:
    st.session_state.filtro_kpi = "PENDENTE"

# RENDERIZAÇÃO
df_desp = None

if uploaded_file is not None:
    try:
        df_desp = processar_arquivo_despesas(uploaded_file)
        st.sidebar.success(f"🟢 Rateio de Títulos Carregado com {len(df_desp)} lançamentos!")
    except Exception as e:
        st.sidebar.error(f"Erro ao ler Excel: {e}")

if df_desp is not None and not df_desp.empty:
    try:
        dfs_lojas = []
        if file_pantanal is not None:
            dfs_lojas.append(processar_fluxo_caixa_loja(file_pantanal, "4- PANTANAL"))
        if file_goiabeiras is not None:
            dfs_lojas.append(processar_fluxo_caixa_loja(file_goiabeiras, "8 - GOIABEIRAS"))
        if file_estacao is not None:
            dfs_lojas.append(processar_fluxo_caixa_loja(file_estacao, "5- ESTAÇÃO"))
            
        df_lojas_concat = pd.concat(dfs_lojas, ignore_index=True) if len(dfs_lojas) > 0 else pd.DataFrame()
        
        min_date = df_desp['Vencimento_dt'].min().date()
        max_date = df_desp['Vencimento_dt'].max().date()

        col_filtro1, col_filtro2 = st.columns([2, 1])
        
        with col_filtro1:
            st.caption("🏢 **Unidade / Loja:**")
            lojas_disponiveis = list(df_desp['Empresa'].dropna().unique())
            lojas_opcoes = ["Ver Todas as Lojas"] + lojas_disponiveis
            loja_selecionada = st.radio("", lojas_opcoes, horizontal=True)

        with col_filtro2:
            st.caption("📅 **Período de Vencimento Real:**")
            date_range = st.date_input(
                "",
                value=(min_date, max_date),
                min_value=min_date,
                max_value=max_date,
                format="DD/MM/YYYY"
            )

        df_desp_filtered = df_desp.copy()
        df_lojas_filtered = df_lojas_concat.copy()
        
        if loja_selecionada != "Ver Todas as Lojas":
            df_desp_filtered = df_desp_filtered[df_desp_filtered['Empresa'] == loja_selecionada].copy()
            if not df_lojas_filtered.empty:
                df_lojas_filtered = df_lojas_filtered[df_lojas_filtered['Empresa'] == loja_selecionada].copy()

        if isinstance(date_range, tuple) and len(date_range) == 2:
            start_date, end_date = date_range
            df_desp_filtered = df_desp_filtered[
                (df_desp_filtered['Vencimento_dt'].dt.date >= start_date) & 
                (df_desp_filtered['Vencimento_dt'].dt.date <= end_date)
            ]
            if not df_lojas_filtered.empty:
                df_lojas_filtered = df_lojas_filtered[
                    (df_lojas_filtered['Vencimento_dt'].dt.date >= start_date) & 
                    (df_lojas_filtered['Vencimento_dt'].dt.date <= end_date)
                ]

        st.divider()

        df_desp_operacional = df_desp_filtered[df_desp_filtered['Categoria_CFO'] != "7. TRANSFERÊNCIAS INTERCOMPANY / MÚTUO"].copy()
        df_desp_mutuo = df_desp_filtered[df_desp_filtered['Categoria_CFO'] == "7. TRANSFERÊNCIAS INTERCOMPANY / MÚTUO"].copy()

        tot_entradas_loja = df_lojas_filtered['Entradas'].sum() if not df_lojas_filtered.empty else 0.0
        tot_previsto = df_desp_operacional['Valor'].sum()
        tot_realizado = df_desp_operacional[df_desp_operacional['Status_Clean'] == 'REALIZADO']['Valor'].sum()
        tot_pendente = df_desp_operacional[df_desp_operacional['Status_Clean'] == 'PENDENTE']['Valor'].sum()
        tot_mutuo_realizado = df_desp_mutuo[df_desp_mutuo['Status_Clean'] == 'REALIZADO']['Valor'].sum()
        
        if not df_lojas_filtered.empty:
            saldo_atual_banco = df_lojas_filtered.sort_values('Vencimento_dt')['Saldo_Banco'].iloc[-1]
        else:
            saldo_atual_banco = 0.0

        st.caption("👇 **Clique nos botões para filtrar os títulos na tabela inferior:**")

        k1, k2, k3, k4 = st.columns(4)

        with k1:
            if st.button(f"📊 PAGAMENTOS PREVISTOS\nR$ {tot_previsto:,.2f}", use_container_width=True):
                st.session_state.filtro_kpi = "TODOS"

        with k2:
            if st.button(f"🟢 PAGAMENTOS LIQUIDADOS\nR$ {tot_realizado:,.2f}", use_container_width=True):
                st.session_state.filtro_kpi = "REALIZADO"

        with k3:
            if st.button(f"🔴 PAGAMENTOS EM ABERTO\nR$ {tot_pendente:,.2f}", use_container_width=True):
                st.session_state.filtro_kpi = "PENDENTE"

        with k4:
            delta_label = f"Entradas: R$ {tot_entradas_loja:,.2f}" if tot_entradas_loja > 0 else None
            st.metric("Saldo Real em Conta Bancária", f"R$ {saldo_atual_banco:,.2f}", delta=delta_label)

        st.markdown("<br>", unsafe_allow_html=True)

        tab1, tab2, tab3 = st.tabs(["📋 DRE de Caixa", "📅 Fluxo Diário (Extrato Banco)", "🏪 Comparativo Por Loja"])
        
        with tab1:
            st.subheader("Demonstrativo do Fluxo de Caixa (Previsto vs. Realizado)")
            
            dre_list = []
            if tot_entradas_loja > 0:
                dre_list.append({
                    "Categoria CFO": "0. RECEITAS DE VENDAS / ENTRADAS",
                    "Previsto (R$)": f"R$ {tot_entradas_loja:,.2f}",
                    "Realizado (R$)": f"R$ {tot_entradas_loja:,.2f}",
                    "Variação (R$)": "R$ 0.00",
                    "% do Total": "100.0%"
                })
                
            cats = [
                "1. FORNECEDORES / MERCADORIAS (CMV)",
                "2. IMPOSTOS SOBRE VENDAS",
                "3. DESPESAS DE OCUPAÇÃO",
                "4. FOLHA DE PAGAMENTO & ENCARGOS",
                "5. DESPESAS OPERACIONAIS & VENDAS",
                "6. AMORTIZAÇÃO DE DÍVIDAS & CAPITAL"
            ]
            
            for c in cats:
                p = df_desp_operacional[df_desp_operacional['Categoria_CFO'] == c]['Valor'].sum()
                r = df_desp_operacional[(df_desp_operacional['Categoria_CFO'] == c) & (df_desp_operacional['Status_Clean'] == 'REALIZADO')]['Valor'].sum()
                v = r - p
                pct = (p / tot_entradas_loja * 100) if tot_entradas_loja > 0 else ((p / tot_previsto * 100) if tot_previsto > 0 else 0)
                dre_list.append({
                    "Categoria CFO": f"   (-) {c}",
                    "Previsto (R$)": f"R$ {p:,.2f}",
                    "Realizado (R$)": f"R$ {r:,.2f}",
                    "Variação (R$)": f"R$ {v:,.2f}",
                    "% do Total": f"{pct:.1f}%"
                })
                
            res_operacional_prev = tot_entradas_loja - tot_previsto
            res_operacional_real = tot_entradas_loja - tot_realizado
            
            dre_list.append({
                "Categoria CFO": "(=) RESULTADO LÍQUIDO OPERACIONAL (EBITDA DA LOJA)",
                "Previsto (R$)": f"R$ {res_operacional_prev:,.2f}",
                "Realizado (R$)": f"R$ {res_operacional_real:,.2f}",
                "Variação (R$)": f"R$ {res_operacional_real - res_operacional_prev:,.2f}",
                "% do Total": f"{(res_operacional_real / tot_entradas_loja * 100) if tot_entradas_loja > 0 else 0:.1f}%"
            })
            
            p_mutuo = df_desp_mutuo['Valor'].sum()
            r_mutuo = tot_mutuo_realizado
            dre_list.append({
                "Categoria CFO": "   (-) 7. TRANSFERÊNCIAS INTERCOMPANY / MÚTUO ENTRE LOJAS",
                "Previsto (R$)": f"R$ {p_mutuo:,.2f}",
                "Realizado (R$)": f"R$ {r_mutuo:,.2f}",
                "Variação (R$)": f"R$ {r_mutuo - p_mutuo:,.2f}",
                "% do Total": f"{(p_mutuo / tot_entradas_loja * 100) if tot_entradas_loja > 0 else 0:.1f}%"
            })
            
            res_final_prev = res_operacional_prev - p_mutuo
            res_final_real = res_operacional_real - r_mutuo
            dre_list.append({
                "Categoria CFO": "(=) GERAÇÃO LÍQUIDA FINAL DE CAIXA DA CONTA",
                "Previsto (R$)": f"R$ {res_final_prev:,.2f}",
                "Realizado (R$)": f"R$ {res_final_real:,.2f}",
                "Variação (R$)": f"R$ {res_final_real - res_final_prev:,.2f}",
                "% do Total": f"{(res_final_real / tot_entradas_loja * 100) if tot_entradas_loja > 0 else 0:.1f}%"
            })
            
            st.dataframe(pd.DataFrame(dre_list), use_container_width=True, hide_index=True)
            
        with tab2:
            st.subheader("Matriz Diária com Saldo de Encerramento (Extrato Bancário)")
            
            if not df_lojas_filtered.empty:
                dias_mes = sorted([int(d) for d in df_lojas_filtered['Dia'].dropna().unique() if d > 0])
                piv_ent = df_lojas_filtered.groupby('Dia')['Entradas'].sum()
                piv_sai = df_lojas_filtered.groupby('Dia')['Saídas'].sum()
                piv_sal = df_lojas_filtered.groupby('Dia')['Saldo_Banco'].last()
            else:
                df_desp_filtered['Dia'] = pd.to_datetime(df_desp_filtered['Vencimento_dt']).dt.day
                dias_mes = sorted([int(d) for d in df_desp_filtered['Dia'].dropna().unique() if d > 0])
                piv_ent = pd.Series(0.0, index=dias_mes)
                piv_sai = df_desp_filtered[df_desp_filtered['Status_Clean'] == 'REALIZADO'].groupby('Dia')['Valor'].sum()
                piv_sal = pd.Series(0.0, index=dias_mes)
                
            row_e, row_s, row_liq, row_acum = {}, {}, {}, {}
            
            for d in dias_mes:
                e = piv_ent.get(d, 0.0)
                s = piv_sai.get(d, 0.0)
                l = e - s
                sal = piv_sal.get(d, 0.0)
                
                row_e[d] = e
                row_s[d] = s
                row_liq[d] = l
                row_acum[d] = sal
                
            df_extrato_diario = pd.DataFrame([
                {"Linha de Extrato": "1. (+) Total Entradas", **row_e},
                {"Linha de Extrato": "2. (-) Total Saídas", **row_s},
                {"Linha de Extrato": "3. (=) Resultado Líquido do Dia", **row_liq},
                {"Linha de Extrato": "4. 🏦 SALDO EM CONTA BANCÁRIA", **row_acum}
            ])
            
            cols_order = ["Linha de Extrato"] + dias_mes
            st.dataframe(
                df_extrato_diario[cols_order].style.format({d: "R$ {:,.2f}" for d in dias_mes}),
                use_container_width=True,
                hide_index=True
            )
            
        with tab3:
            st.subheader("Matriz Comparativa entre Lojas")
            if loja_selecionada != "Ver Todas as Lojas":
                st.info(f"Você está visualizando apenas a unidade **{loja_selecionada}**. Para comparar todas as unidades lado a lado, selecione **'Ver Todas as Lojas'** no topo.")
            pivot_store = df_desp_filtered.pivot_table(index='Categoria_CFO', columns='Empresa', values='Valor', aggfunc='sum', fill_value=0)
            st.dataframe(pivot_store.style.format("R$ {:,.2f}"), use_container_width=True)

        st.divider()

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
            <li>Anexe o arquivo de despesas no menu lateral <b>(📥 Relatório ERP - Rateio de Títulos em Excel)</b>.</li>
            <li>Anexe o arquivo <b>Fluxo de Caixa Pantanal / Lojas</b>.</li>
        </ol>
    </div>
    """, unsafe_allow_html=True)