import streamlit as st
import pandas as pd
import numpy as np
import json
import re
from datetime import datetime, date, timedelta

# IMPORTAÇÃO DO MÓDULO F360 ATUALIZADO E REFATORADO
from f360_api import (
    autenticar_f360, 
    buscar_parcelas_f360, 
    processar_parcelas_cartoes_arquivo
)

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

try:
    F360_TOKEN = st.secrets["F360_TOKEN"]
except Exception:
    F360_TOKEN = "11001cbb-792d-45e5-b2f9-03ffc46fe7ed"

MAPA_CNPJ_LOJA = {
    "36240923000168": "4- PANTANAL",
    "36240923000249": "5- ESTAÇÃO",
    "36240923000320": "8 - GOIABEIRAS"
}

# ---------------------------------------------------------
# CATEGORIZAÇÃO CFO & CARGA VIA API (COM LOG)
# ---------------------------------------------------------
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

def carregar_despesas_api_f360(jwt_token, d_ini, d_fim, log=None):
    df_desp = buscar_parcelas_f360(jwt_token, d_ini, d_fim, MAPA_CNPJ_LOJA, tipo="Despesa", log=log)
    if df_desp is not None and not df_desp.empty:
        df_desp["Categoria_CFO"] = df_desp["Plano de Contas"].apply(categorizar_plano_contas)
    return df_desp

def carregar_receitas_api_f360(jwt_token, d_ini, d_fim, log=None):
    df_rec = buscar_parcelas_f360(jwt_token, d_ini, d_fim, MAPA_CNPJ_LOJA, tipo="Receita", log=log)
    if df_rec is not None and not df_rec.empty:
        df_rec["Categoria_CFO"] = "0. RECEITAS DE VENDAS"
    return df_rec

@st.cache_data(ttl=3600)
def carregar_cartoes_arquivo(file):
    df = processar_parcelas_cartoes_arquivo(file, MAPA_CNPJ_LOJA)
    if not df.empty:
        df["Categoria_CFO"] = "0. RECEITAS DE VENDAS"
    return df

# ---------------------------------------------------------
# PROCESSAMENTO DE ARQUIVOS OFFLINE
# ---------------------------------------------------------
def processar_json_f360(data_json):
    df = pd.DataFrame(data_json)
    df['Valor'] = pd.to_numeric(df['ValorLcto'], errors='coerce').fillna(0)
    df['Valor_Bruto'] = df['Valor']
    df['Plano de Contas'] = df['NomePlanoDeContas'].fillna('Outros')
    df['Status_Clean'] = df['StatusTitulo'].astype(str).apply(
        lambda x: "REALIZADO" if any(s in str(x).lower() for s in ['liquidado', 'conciliado']) else "PENDENTE"
    )
    
    def extrair_vencimento(row):
        if row['Status_Clean'] == 'REALIZADO' and pd.notna(row.get('Liquidacao')):
            dt_l = pd.to_datetime(row['Liquidacao'], errors='coerce')
            if pd.notna(dt_l):
                return dt_l.tz_localize(None) if dt_l.tz is not None else dt_l
        dt_lcto = pd.to_datetime(row.get('DataDoLcto'), format='%d/%m/%Y', errors='coerce')
        if pd.notna(dt_lcto):
            return dt_lcto
        return pd.to_datetime(row.get('DataCompetencia'), format='%d/%m/%Y', errors='coerce')

    df['Vencimento_dt'] = df.apply(extrair_vencimento, axis=1)
    df['Vencimento_real'] = pd.to_datetime(df.get('DataDoLcto'), format='%d/%m/%Y', errors='coerce')
    
    df = df.dropna(subset=['Vencimento_dt']).copy()
    df['Vencimento_dt'] = pd.to_datetime(df['Vencimento_dt'])
    df['Dia'] = df['Vencimento_dt'].dt.day
    
    cnpj_limpo = df['CNPJEmpresa'].astype(str).apply(lambda x: re.sub(r'\D', '', x))
    df['Empresa'] = cnpj_limpo.map(MAPA_CNPJ_LOJA).fillna(df['CNPJEmpresa'])
    df['Categoria_CFO'] = df['Plano de Contas'].apply(categorizar_plano_contas)
    df['Cliente / Fornecedor'] = df['ComplemHistorico'].astype(str).apply(lambda x: x.split('-')[0].strip() if '-' in x else x[:30])
    df['Número'] = df['NumeroTitulo'].fillna('')
    df['Tipo_Movimento'] = 'DESPESA'
    df['Origem'] = 'Título'
    df['Detalhe'] = 'JSON ERP'
    
    df = df[~df['StatusTitulo'].astype(str).str.lower().str.contains('cancelado|baixado', na=False)].copy()
    return df

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
    df['Valor_Bruto'] = df['Valor']
    df['Vencimento_dt'] = pd.to_datetime(df['Vencimento'], errors='coerce')
    df['Vencimento_real'] = df['Vencimento_dt']
    df = df.dropna(subset=['Vencimento_dt']).copy()
    df['Vencimento_dt'] = pd.to_datetime(df['Vencimento_dt'])
    df['Dia'] = df['Vencimento_dt'].dt.day
    df['Categoria_CFO'] = df['Plano de Contas'].apply(categorizar_plano_contas)
    df['Tipo_Movimento'] = 'DESPESA'
    df['Origem'] = 'Título'
    df['Detalhe'] = 'Rateio Excel'
    
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
# INTERFACE SIDEBAR E CONSULTAS
# ---------------------------------------------------------
st.markdown("<div class='main-title'>🍦 Gelateria Borelli - Gestão de Fluxo de Caixa</div>", unsafe_allow_html=True)
st.markdown("<div class='main-subtitle'>Acompanhamento de liquidez, governança e extrato acumulado diário em tempo real</div>", unsafe_allow_html=True)

with st.sidebar:
    st.header("⚡ Integração F360 API")
    usar_api = st.toggle("Usar API F360 (Tempo Real)", value=False)
    
    if usar_api:
        if "jwt" not in st.session_state or st.session_state.jwt is None:
            st.session_state.jwt = autenticar_f360(F360_TOKEN)
            
        if st.session_state.jwt:
            st.success("🟢 Sessão JWT válida")
            hoje = date(2026, 9, 1) # Período base das franquias
            periodo_api = st.date_input(
                "Período de Busca", 
                (hoje.replace(day=1), hoje + timedelta(days=30)), 
                format="DD/MM/YYYY"
            )
            
            st.markdown("---")
            btn_despesas = st.button("🚀 Buscar Despesas / Parcelas (API)", use_container_width=True)
            btn_receitas = st.button("📈 Buscar Receitas / Cartões (API)", use_container_width=True)
            
            log = []
            
            if btn_despesas and len(periodo_api) == 2:
                try:
                    with st.spinner("Consultando parcelas de despesas..."):
                        df_desp_api = carregar_despesas_api_f360(st.session_state.jwt, periodo_api[0], periodo_api[1], log)
                        st.session_state.df_api_desp = df_desp_api
                        st.success(f"🟢 {len(df_desp_api) if df_desp_api is not None else 0} despesas carregadas!")
                except Exception as e:
                    st.error(f"Erro na API F360 (Despesas): {e}")

            if btn_receitas and len(periodo_api) == 2:
                try:
                    with st.spinner("Consultando parcelas de receitas e cartões..."):
                        df_rec_api = carregar_receitas_api_f360(st.session_state.jwt, periodo_api[0], periodo_api[1], log)
                        st.session_state.df_api_rec = df_rec_api
                        st.success(f"🟢 {len(df_rec_api) if df_rec_api is not None else 0} receitas carregadas!")
                except Exception as e:
                    st.error(f"Erro na API F360 (Receitas): {e}")
                    
            with st.expander("🔍 Diagnóstico da API"):
                st.code("\n".join(log) or "sem chamadas na sessão atual")
        else:
            st.error("🔴 Falha na autenticação F360")
            
    st.divider()
    st.header("📥 Relatórios ERP / F360 (Offline)")
    json_f360_file = st.file_uploader("Anexe o Ficheiro JSON F360 (.json)", type=["json"])
    uploaded_file = st.file_uploader("OU Anexe o Rateio de Despesas em Excel (.xlsx)", type=["xlsx", "xls"])
    file_cartoes = st.file_uploader("Parcelas de Cartões (export F360)", type=["xlsx", "xls", "csv"], key="c")
    
    st.divider()
    st.header("🍦 Fluxo de Caixa Por Loja")
    file_pantanal = st.file_uploader("Fluxo Pantanal (.xlsx)", type=["xlsx", "xls"], key="p")
    file_goiabeiras = st.file_uploader("Fluxo Goiabeiras (.xlsx)", type=["xlsx", "xls"], key="g")
    file_estacao = st.file_uploader("Fluxo Estação (.xlsx)", type=["xlsx", "xls"], key="e")

if 'filtro_kpi' not in st.session_state:
    st.session_state.filtro_kpi = "PENDENTE"

# ---------------------------------------------------------
# UNIFICAÇÃO DA FONTE DE DADOS (DESPESAS + RECEITAS)
# ---------------------------------------------------------
df_despesas_fonte = None
if json_f360_file is not None:
    try:
        data_j = json.load(json_f360_file)
        df_despesas_fonte = processar_json_f360(data_j)
        st.sidebar.success(f"🟢 JSON F360: {len(df_despesas_fonte)} despesas")
    except Exception as e:
        st.sidebar.error(f"Erro ao ler JSON: {e}")
elif uploaded_file is not None:
    try:
        df_despesas_fonte = processar_arquivo_despesas(uploaded_file)
        st.sidebar.success(f"🟢 Rateio Excel: {len(df_despesas_fonte)} despesas")
    except Exception as e:
        st.sidebar.error(f"Erro ao ler Excel: {e}")
else:
    df_despesas_fonte = st.session_state.get("df_api_desp")

frames_rec = []
rec_api = st.session_state.get("df_api_rec")
if rec_api is not None and not rec_api.empty:
    frames_rec.append(rec_api)

tem_cartao_api = (rec_api is not None and not rec_api.empty and "Origem" in rec_api.columns and (rec_api["Origem"] == "Cartão").any())

if file_cartoes is not None and not tem_cartao_api:
    try:
        df_c_file = carregar_cartoes_arquivo(file_cartoes)
        frames_rec.append(df_c_file)
        st.sidebar.success(f"🟢 Cartões File: {len(df_c_file)} receitas")
    except Exception as e:
        st.sidebar.error(f"Erro ao ler arquivo de cartões: {e}")

df_receitas_fonte = pd.concat(frames_rec, ignore_index=True) if frames_rec else None

df_tudo_list = []
if df_despesas_fonte is not None and not df_despesas_fonte.empty:
    df_tudo_list.append(df_despesas_fonte)
if df_receitas_fonte is not None and not df_receitas_fonte.empty:
    df_tudo_list.append(df_receitas_fonte)

df_tudo = pd.concat(df_tudo_list, ignore_index=True) if len(df_tudo_list) > 0 else None

# ---------------------------------------------------------
# RENDERIZAÇÃO DO DASHBOARD
# ---------------------------------------------------------
if df_tudo is not None and not df_tudo.empty:
    try:
        if 'Tipo_Movimento' not in df_tudo.columns:
            df_tudo['Tipo_Movimento'] = 'DESPESA'

        dfs_lojas = []
        if file_pantanal is not None:
            dfs_lojas.append(processar_fluxo_caixa_loja(file_pantanal, "4- PANTANAL"))
        if file_goiabeiras is not None:
            dfs_lojas.append(processar_fluxo_caixa_loja(file_goiabeiras, "8 - GOIABEIRAS"))
        if file_estacao is not None:
            dfs_lojas.append(processar_fluxo_caixa_loja(file_estacao, "5- ESTAÇÃO"))
            
        df_lojas_concat = pd.concat(dfs_lojas, ignore_index=True) if len(dfs_lojas) > 0 else pd.DataFrame()

        col_filtro1, col_filtro2 = st.columns([2, 1])
        
        min_date = df_tudo['Vencimento_dt'].min().date()
        max_date = df_tudo['Vencimento_dt'].max().date()
        
        with col_filtro1:
            st.caption("🏢 **Unidade / Loja:**")
            lojas_disponiveis = list(df_tudo['Empresa'].dropna().unique())
            lojas_opcoes = ["Ver Todas as Lojas"] + lojas_disponiveis
            loja_selecionada = st.radio("", lojas_opcoes, horizontal=True)

        with col_filtro2:
            st.caption("📅 **Período de Caixa (Liquidação / Vencimento):**")
            date_range = st.date_input(
                "",
                value=(min_date, max_date),
                min_value=min_date,
                max_value=max_date,
                format="DD/MM/YYYY"
            )

        df_filtered = df_tudo.copy()
        
        if loja_selecionada != "Ver Todas as Lojas":
            df_filtered = df_filtered[df_filtered['Empresa'] == loja_selecionada].copy()

        if isinstance(date_range, tuple) and len(date_range) == 2:
            start_date, end_date = date_range
            df_filtered = df_filtered[
                (df_filtered['Vencimento_dt'].dt.date >= start_date) & 
                (df_filtered['Vencimento_dt'].dt.date <= end_date)
            ]

        st.divider()

        # SEPARAÇÃO DE RECEITAS E DESPESAS
        df_receitas = df_filtered[df_filtered['Tipo_Movimento'] == 'RECEITA'].copy()
        df_despesas = df_filtered[df_filtered['Tipo_Movimento'] == 'DESPESA'].copy()

        df_desp_operacional = df_despesas[df_despesas['Categoria_CFO'] != "7. TRANSFERÊNCIAS INTERCOMPANY / MÚTUO"].copy() if not df_despesas.empty else pd.DataFrame()
        df_desp_mutuo = df_despesas[df_despesas['Categoria_CFO'] == "7. TRANSFERÊNCIAS INTERCOMPANY / MÚTUO"].copy() if not df_despesas.empty else pd.DataFrame()

        # TOTALIZADORES (RECEITA USANDO O VALOR LÍQUIDO REAIS DA CONTA)
        tot_receita_prevista = df_receitas['Valor'].sum() if not df_receitas.empty else (df_lojas_concat['Entradas'].sum() if not df_lojas_concat.empty else 0.0)
        tot_receita_realizada = df_receitas[df_receitas['Status_Clean'] == 'REALIZADO']['Valor'].sum() if not df_receitas.empty else tot_receita_prevista
        
        tot_previsto = df_desp_operacional['Valor'].sum() if not df_desp_operacional.empty else 0.0
        tot_realizado = df_desp_operacional[df_desp_operacional['Status_Clean'] == 'REALIZADO']['Valor'].sum() if not df_desp_operacional.empty else 0.0
        tot_pendente = df_desp_operacional[df_desp_operacional['Status_Clean'] == 'PENDENTE']['Valor'].sum() if not df_desp_operacional.empty else 0.0
        tot_mutuo_realizado = df_desp_mutuo[df_desp_mutuo['Status_Clean'] == 'REALIZADO']['Valor'].sum() if not df_desp_mutuo.empty else 0.0

        st.caption("👇 **Clique nos botões para filtrar as despesas na tabela inferior:**")

        k1, k2, k3, k4 = st.columns(4)

        with k1:
            if st.button(f"📊 DESPESAS PREVISTAS\nR$ {tot_previsto:,.2f}", use_container_width=True):
                st.session_state.filtro_kpi = "TODOS"

        with k2:
            if st.button(f"🟢 DESPESAS LIQUIDADAS\nR$ {tot_realizado:,.2f}", use_container_width=True):
                st.session_state.filtro_kpi = "REALIZADO"

        with k3:
            if st.button(f"🔴 DESPESAS EM ABERTO\nR$ {tot_pendente:,.2f}", use_container_width=True):
                st.session_state.filtro_kpi = "PENDENTE"

        with k4:
            st.metric("Total Receita Líquida (Caixa)", f"R$ {tot_receita_prevista:,.2f}", delta=f"Realizado: R$ {tot_receita_realizada:,.2f}")

        st.markdown("<br>", unsafe_allow_html=True)

        tab1, tab2, tab3 = st.tabs(["📋 DRE de Caixa", "📅 Fluxo Diário (Extrato Banco)", "🏪 Comparativo Por Loja"])
        
        with tab1:
            st.subheader("Demonstrativo do Fluxo de Caixa (Previsto vs. Realizado)")
            
            dre_list = []
            dre_list.append({
                "Categoria CFO": "0. RECEITAS DE VENDAS / ENTRADAS (VALOR LÍQUIDO CAIXA)",
                "Previsto (R$)": f"R$ {tot_receita_prevista:,.2f}",
                "Realizado (R$)": f"R$ {tot_receita_realizada:,.2f}",
                "Variação (R$)": f"R$ {tot_receita_realizada - tot_receita_prevista:,.2f}",
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
                p = df_desp_operacional[df_desp_operacional['Categoria_CFO'] == c]['Valor'].sum() if not df_desp_operacional.empty else 0.0
                r = df_desp_operacional[(df_desp_operacional['Categoria_CFO'] == c) & (df_desp_operacional['Status_Clean'] == 'REALIZADO')]['Valor'].sum() if not df_desp_operacional.empty else 0.0
                v = r - p
                pct = (p / tot_receita_prevista * 100) if tot_receita_prevista > 0 else 0.0
                dre_list.append({
                    "Categoria CFO": f"   (-) {c}",
                    "Previsto (R$)": f"R$ {p:,.2f}",
                    "Realizado (R$)": f"R$ {r:,.2f}",
                    "Variação (R$)": f"R$ {v:,.2f}",
                    "% do Total": f"{pct:.1f}%"
                })
                
            res_operacional_prev = tot_receita_prevista - tot_previsto
            res_operacional_real = tot_receita_realizada - tot_realizado
            
            dre_list.append({
                "Categoria CFO": "(=) RESULTADO LÍQUIDO OPERACIONAL (EBITDA DA LOJA)",
                "Previsto (R$)": f"R$ {res_operacional_prev:,.2f}",
                "Realizado (R$)": f"R$ {res_operacional_real:,.2f}",
                "Variação (R$)": f"R$ {res_operacional_real - res_operacional_prev:,.2f}",
                "% do Total": f"{(res_operacional_real / tot_receita_realizada * 100) if tot_receita_realizada > 0 else 0:.1f}%"
            })
            
            p_mutuo = df_desp_mutuo['Valor'].sum() if not df_desp_mutuo.empty else 0.0
            r_mutuo = tot_mutuo_realizado
            dre_list.append({
                "Categoria CFO": "   (-) 7. TRANSFERÊNCIAS INTERCOMPANY / MÚTUO ENTRE LOJAS",
                "Previsto (R$)": f"R$ {p_mutuo:,.2f}",
                "Realizado (R$)": f"R$ {r_mutuo:,.2f}",
                "Variação (R$)": f"R$ {r_mutuo - p_mutuo:,.2f}",
                "% do Total": f"{(p_mutuo / tot_receita_prevista * 100) if tot_receita_prevista > 0 else 0:.1f}%"
            })
            
            res_final_prev = res_operacional_prev - p_mutuo
            res_final_real = res_operacional_real - r_mutuo
            dre_list.append({
                "Categoria CFO": "(=) GERAÇÃO LÍQUIDA FINAL DE CAIXA DA CONTA",
                "Previsto (R$)": f"R$ {res_final_prev:,.2f}",
                "Realizado (R$)": f"R$ {res_final_real:,.2f}",
                "Variação (R$)": f"R$ {res_final_real - res_final_prev:,.2f}",
                "% do Total": f"{(res_final_real / tot_receita_realizada * 100) if tot_receita_realizada > 0 else 0:.1f}%"
            })
            
            st.dataframe(pd.DataFrame(dre_list), use_container_width=True, hide_index=True)
            
            # TABELA DE CONFERÊNCIA DE RECEITAS POR ORIGEM (ADQUIRENTE E TÍTULOS)
            if not df_receitas.empty and "Origem" in df_receitas.columns:
                st.markdown("<br>", unsafe_allow_html=True)
                st.subheader("🔍 Conferência de Receitas por Origem e Adquirente (Comparativo F360)")
                
                df_rec_conf = df_receitas.copy()
                if "Valor_Bruto" not in df_rec_conf.columns:
                    df_rec_conf["Valor_Bruto"] = df_rec_conf["Valor"]
                    
                orig = (df_rec_conf.groupby(["Origem", "Detalhe"])
                        .agg(Qtd=("Valor", "size"), Bruto=("Valor_Bruto", "sum"), Liquido=("Valor", "sum"))
                        .reset_index())
                orig["Taxas / Descontos"] = orig["Bruto"] - orig["Liquido"]
                
                st.dataframe(
                    orig.style.format({c: "R$ {:,.2f}" for c in ["Bruto", "Liquido", "Taxas / Descontos"]}),
                    use_container_width=True, 
                    hide_index=True
                )
            
        with tab2:
            st.subheader("Matriz Diária com Saldo de Encerramento (Fluxo de Caixa F360)")
            
            df_filtered['Dia'] = pd.to_datetime(df_filtered['Vencimento_dt']).dt.day
            dias_mes = sorted([int(d) for d in df_filtered['Dia'].dropna().unique() if d > 0])
            
            piv_ent = df_receitas.groupby('Dia')['Valor'].sum() if not df_receitas.empty else pd.Series(0.0, index=dias_mes)
            piv_sai = df_despesas[df_despesas['Status_Clean'] == 'REALIZADO'].groupby('Dia')['Valor'].sum() if not df_despesas.empty else pd.Series(0.0, index=dias_mes)
            
            row_e, row_s, row_liq = {}, {}, {}
            
            for d in dias_mes:
                e = piv_ent.get(d, 0.0)
                s = piv_sai.get(d, 0.0)
                l = e - s
                
                row_e[d] = e
                row_s[d] = s
                row_liq[d] = l
                
            df_extrato_diario = pd.DataFrame([
                {"Linha de Extrato": "1. (+) Total Receitas Liquidadas", **row_e},
                {"Linha de Extrato": "2. (-) Total Saídas Liquidadas", **row_s},
                {"Linha de Extrato": "3. (=) Resultado Líquido do Dia", **row_liq}
            ])
            
            cols_order = ["Linha de Extrato"] + dias_mes
            st.dataframe(
                df_extrato_diario[cols_order].style.format({d: "R$ {:,.2f}" for d in dias_mes}),
                use_container_width=True,
                hide_index=True
            )
            
        with tab3:
            st.subheader("Matriz Comparativa entre Lojas")
            if not df_despesas.empty:
                pivot_store = df_despesas.pivot_table(index='Categoria_CFO', columns='Empresa', values='Valor', aggfunc='sum', fill_value=0)
                st.dataframe(pivot_store.style.format("R$ {:,.2f}"), use_container_width=True)
            else:
                st.info("Nenhuma despesa para exibir a comparação por loja.")

        st.divider()

        # TABELA INFERIOR DE DESPESAS
        if st.session_state.filtro_kpi == "REALIZADO":
            df_titulos = df_despesas[df_despesas['Status_Clean'] == 'REALIZADO'].copy() if not df_despesas.empty else pd.DataFrame()
        elif st.session_state.filtro_kpi == "PENDENTE":
            df_titulos = df_despesas[df_despesas['Status_Clean'] == 'PENDENTE'].copy() if not df_despesas.empty else pd.DataFrame()
        else:
            df_titulos = df_despesas.copy() if not df_despesas.empty else pd.DataFrame()

        if not df_titulos.empty:
            df_display = df_titulos.copy()
            df_display['Data de Caixa'] = df_display['Vencimento_dt'].dt.strftime('%d/%m/%Y')
            
            st.subheader(f"📊 Exibindo Títulos de Despesas ({len(df_display)} registros)")
            st.dataframe(
                df_display[['Número', 'Empresa', 'Cliente / Fornecedor', 'Data de Caixa', 'Valor', 'Plano de Contas', 'Categoria_CFO', 'Status_Clean']],
                use_container_width=True,
                hide_index=True
            )
        else:
            st.info("Nenhum título de despesa para o filtro selecionado.")

    except Exception as e:
        st.error(f"Erro ao processar os dados: {e}")
else:
    st.markdown("""
    <div class='welcome-card'>
        <h3>🍦 Painel de Fluxo de Caixa Executivo - Gelateria Borelli</h3>
        <p>Aguardando carga dos relatórios no menu lateral para inicializar o processamento.</p>
        <ol>
            <li>Ative a opção <b>Usar API F360 (Tempo Real)</b> e busque despesas/receitas.</li>
            <li>OU anexe o arquivo de <b>Parcelas de Cartões (export F360)</b> no menu lateral para conciliação exata do V. Líquido.</li>
        </ol>
    </div>
    """, unsafe_allow_html=True)