import streamlit as st
import pandas as pd
import numpy as np
import json
import re
import unicodedata
from datetime import datetime, date, timedelta

# IMPORTAÇÃO DO MÓDULO F360
from f360_api import (
    autenticar_f360, 
    buscar_parcelas_f360, 
    processar_parcelas_cartoes_arquivo,
    processar_detalhes_fluxo_caixa,
    IDS_CONTAS_BORELLI
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

# SALDOS OFICIAIS DE FECHAMENTO EM 31/08/2026 PARA USO EM 01/09/2026
SALDOS_INICIAIS_AGOSTO = {
    "17 Pantanal Itaú": 24053.13,
    "36 MJL": 500.00,
    "51 Estação Itaú": 333.38,
    "52 RT": 3434.92,
    "61 Itaú Goiabeiras": 300.77
}

# ---------------------------------------------------------
# CATEGORIZAÇÃO DE PLANOS DE CONTAS
# ---------------------------------------------------------
def categorizar_plano_contas(plano):
    if pd.isna(plano):
        return "5. DESPESAS OPERACIONAIS & VENDAS"
    p = str(plano).upper().strip()
    if any(k in p for k in ['EMPRÉSTIMO MÚTUO', 'EMPRESTIMO MUTUO', 'MÚTUO', 'MUTUO', 'TRANSFERÊNCIA INTERCOMPANY']):
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

def categorizar_receita(row):
    plano = str(row.get("Plano de Contas") or "").upper().strip()
    if any(k in plano for k in ['EMPRÉSTIMO MÚTUO', 'EMPRESTIMO MUTUO', 'MÚTUO', 'MUTUO', 'TRANSFERÊNCIA INTERCOMPANY']):
        return "7. TRANSFERÊNCIAS INTERCOMPANY / MÚTUO"
    return "0. RECEITAS DE VENDAS"

def carregar_despesas_api_f360(jwt_token, d_ini, d_fim, log=None):
    df_desp = buscar_parcelas_f360(jwt_token, d_ini, d_fim, MAPA_CNPJ_LOJA, tipo="Despesa", log=log)
    if df_desp is not None and not df_desp.empty:
        df_desp["Categoria_CFO"] = df_desp["Plano de Contas"].apply(categorizar_plano_contas)
    return df_desp

def carregar_receitas_f360(jwt_token, d_ini, d_fim, log=None):
    df_rec = buscar_parcelas_f360(jwt_token, d_ini, d_fim, MAPA_CNPJ_LOJA, tipo="Receita", log=log)
    if df_rec is not None and not df_rec.empty:
        df_rec["Categoria_CFO"] = df_rec.apply(categorizar_receita, axis=1)
        df_rec["Tipo_Movimento"] = "RECEITA"
    return df_rec

@st.cache_data(ttl=3600)
def carregar_cartoes_arquivo(file):
    df = processar_parcelas_cartoes_arquivo(file, MAPA_CNPJ_LOJA)
    if not df.empty:
        df["Categoria_CFO"] = df.apply(categorizar_receita, axis=1)
        df["Tipo_Movimento"] = "RECEITA"
    return df

@st.cache_data(ttl=3600)
def carregar_detalhes_fluxo_caixa(_arquivos, nomes):
    return processar_detalhes_fluxo_caixa(_arquivos, MAPA_CNPJ_LOJA)

# ---------------------------------------------------------
# INTERFACE SIDEBAR
# ---------------------------------------------------------
st.markdown("<div class='main-title'>🍦 Gelateria Borelli - Gestão de Fluxo de Caixa</div>", unsafe_allow_html=True)
st.markdown("<div class='main-subtitle'>Extrato Diário por Contas Bancárias (17 Pantanal Itaú, 51 Estação Itaú, 61 Itaú Goiabeiras, 52 RT e 36 MJL)</div>", unsafe_allow_html=True)

with st.sidebar:
    st.header("⚡ Integração F360 API")
    usar_api = st.toggle("Usar API F360 (Tempo Real)", value=True)
    
    if usar_api:
        if "jwt" not in st.session_state or st.session_state.jwt is None:
            st.session_state.jwt = autenticar_f360(F360_TOKEN)
            
        if st.session_state.jwt:
            st.success("🟢 Sessão JWT válida")
            hoje = date(2026, 9, 1)
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
                    with st.spinner("Consultando despesas..."):
                        df_desp_api = carregar_despesas_api_f360(st.session_state.jwt, periodo_api[0], periodo_api[1], log)
                        st.session_state.df_api_desp = df_desp_api
                        st.success(f"🟢 {len(df_desp_api) if df_desp_api is not None else 0} despesas carregadas!")
                except Exception as e:
                    if "401" in str(e) or "Token" in str(e):
                        st.session_state.jwt = autenticar_f360(F360_TOKEN)
                        st.warning("⚠️ Sessão expirada. Token renovado! Clique no botão novamente.")
                    else:
                        st.error(f"Erro na API F360 (Despesas): {e}")

            if btn_receitas and len(periodo_api) == 2:
                try:
                    with st.spinner("Consultando parcelas de cartões e receitas..."):
                        df_rec_api = carregar_receitas_f360(st.session_state.jwt, periodo_api[0], periodo_api[1], log)
                        st.session_state.df_api_rec = df_rec_api
                        st.success(f"🟢 {len(df_rec_api) if df_rec_api is not None else 0} receitas e cartões carregados!")
                except Exception as e:
                    if "401" in str(e) or "Token" in str(e):
                        st.session_state.jwt = autenticar_f360(F360_TOKEN)
                        st.warning("⚠️ Sessão expirada. Token renovado! Clique no botão novamente.")
                    else:
                        st.error(f"Erro na API F360 (Receitas/Cartões): {e}")
                    
            with st.expander("🔍 Diagnóstico da API"):
                st.code("\n".join(log) or "sem chamadas na sessão atual")
        else:
            st.error("🔴 Falha na autenticação F360")
            
    st.divider()
    st.header("🧾 Detalhes Fluxo de Caixa (F360, fonte oficial)")
    files_detalhes = st.file_uploader(
        "Exporte em F360 > Fluxo de Caixa > Detalhes (Anexe os arquivos)",
        type=["xlsx"], accept_multiple_files=True, key="detalhes"
    )
    file_cartoes = st.file_uploader("OU Anexe o export 'Parcelas de Cartões' (.xlsx/.csv)", type=["xlsx", "xls", "csv"], key="c")

if 'filtro_kpi' not in st.session_state:
    st.session_state.filtro_kpi = "PENDENTE"

# ---------------------------------------------------------
# CARGA E PROCESSAMENTO DA FONTE DE DADOS
# ---------------------------------------------------------
df_despesas_fonte = st.session_state.get("df_api_desp")
frames_rec = []

if files_detalhes:
    try:
        df_detalhes_rec, _ = carregar_detalhes_fluxo_caixa(files_detalhes, tuple(f.name for f in files_detalhes))
        frames_rec.append(df_detalhes_rec)
        st.sidebar.success(f"🟢 Detalhes Fluxo de Caixa: {len(df_detalhes_rec)} lançamentos")
    except Exception as e:
        st.sidebar.error(f"Erro ao ler Detalhes Fluxo de Caixa: {e}")

rec_api = st.session_state.get("df_api_rec")
if rec_api is not None and not rec_api.empty:
    frames_rec.append(rec_api)

if file_cartoes is not None:
    try:
        df_c_file = carregar_cartoes_arquivo(file_cartoes)
        frames_rec.append(df_c_file)
        st.sidebar.success(f"🟢 Cartões File: {len(df_c_file)} lançamentos")
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

        col_filtro1, col_filtro2 = st.columns([2, 1])
        
        min_date = df_tudo['Vencimento_dt'].min().date()
        max_date = df_tudo['Vencimento_dt'].max().date()
        
        with col_filtro1:
            st.caption("🏦 **Pesquisar por Conta Bancária:**")
            contas_disponiveis = ["17 Pantanal Itaú", "51 Estação Itaú", "61 Itaú Goiabeiras", "52 RT", "36 MJL"]
            contas_opcoes = ["Ver Todas as Contas"] + contas_disponiveis
            conta_selecionada = st.radio("", contas_opcoes, horizontal=True)

        with col_filtro2:
            st.caption("📅 **Período de Caixa:**")
            date_range = st.date_input(
                "",
                value=(min_date, max_date),
                min_value=min_date,
                max_value=max_date,
                format="DD/MM/YYYY"
            )

        df_filtered = df_tudo.copy()
        
        if conta_selecionada != "Ver Todas as Contas":
            df_filtered = df_filtered[df_filtered['Empresa'] == conta_selecionada].copy()

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

        # ISOLAR MÚTUO/TRANSFERÊNCIAS DE VENDAS PURAS
        df_rec_vendas = df_receitas[df_receitas['Categoria_CFO'] != "7. TRANSFERÊNCIAS INTERCOMPANY / MÚTUO"].copy() if not df_receitas.empty else pd.DataFrame()
        df_rec_mutuo = df_receitas[df_receitas['Categoria_CFO'] == "7. TRANSFERÊNCIAS INTERCOMPANY / MÚTUO"].copy() if not df_receitas.empty else pd.DataFrame()

        df_desp_operacional = df_despesas[df_despesas['Categoria_CFO'] != "7. TRANSFERÊNCIAS INTERCOMPANY / MÚTUO"].copy() if not df_despesas.empty else pd.DataFrame()
        df_desp_mutuo = df_despesas[df_despesas['Categoria_CFO'] == "7. TRANSFERÊNCIAS INTERCOMPANY / MÚTUO"].copy() if not df_despesas.empty else pd.DataFrame()

        # TOTALIZADORES
        tot_receita_prevista = df_rec_vendas['Valor'].sum() if not df_rec_vendas.empty else 0.0
        tot_receita_realizada = df_rec_vendas[df_rec_vendas['Status_Clean'] == 'REALIZADO']['Valor'].sum() if not df_rec_vendas.empty else tot_receita_prevista
        
        tot_previsto = df_desp_operacional['Valor'].sum() if not df_desp_operacional.empty else 0.0
        tot_realizado = df_desp_operacional[df_desp_operacional['Status_Clean'] == 'REALIZADO']['Valor'].sum() if not df_desp_operacional.empty else 0.0
        tot_pendente = df_desp_operacional[df_desp_operacional['Status_Clean'] == 'PENDENTE']['Valor'].sum() if not df_desp_operacional.empty else 0.0

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
            st.metric("Total Receita Líquida (Vendas)", f"R$ {tot_receita_prevista:,.2f}", delta=f"Realizado: R$ {tot_receita_realizada:,.2f}")

        if st.button("👁️ Ver Lançamentos de Receita e Cartões (detalhado)", use_container_width=True):
            st.session_state.ver_lancamentos_receita = not st.session_state.get("ver_lancamentos_receita", False)

        if st.session_state.get("ver_lancamentos_receita") and not df_receitas.empty:
            st.subheader(f"Lançamentos de Receitas e Cartões ({len(df_receitas)} registros)")
            cols_disp = [c for c in ["Vencimento_dt", "Empresa", "Conta", "Origem", "Detalhe",
                                     "Cliente / Fornecedor", "Valor_Bruto", "Valor",
                                     "Categoria_CFO", "Status_Clean"] if c in df_receitas.columns]
            df_ver = df_receitas[cols_disp].copy()
            if "Vencimento_dt" in df_ver.columns:
                df_ver["Vencimento_dt"] = pd.to_datetime(df_ver["Vencimento_dt"]).dt.strftime('%d/%m/%Y')
            st.dataframe(df_ver.sort_values("Empresa"), use_container_width=True, hide_index=True)

        st.markdown("<br>", unsafe_allow_html=True)

        tab1, tab2, tab3 = st.tabs(["📋 DRE de Caixa", "📅 Fluxo Diário (Extrato Banco)", "🏪 Comparativo Por Conta"])
        
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
                "Categoria CFO": "(=) RESULTADO LÍQUIDO OPERACIONAL (EBITDA)",
                "Previsto (R$)": f"R$ {res_operacional_prev:,.2f}",
                "Realizado (R$)": f"R$ {res_operacional_real:,.2f}",
                "Variação (R$)": f"R$ {res_operacional_real - res_operacional_prev:,.2f}",
                "% do Total": f"{(res_operacional_real / tot_receita_realizada * 100) if tot_receita_realizada > 0 else 0:.1f}%"
            })
            
            st.dataframe(pd.DataFrame(dre_list), use_container_width=True, hide_index=True)
            
        with tab2:
            st.subheader("Matriz Diária com Saldo de Encerramento (Visão Extrato Bancário F360)")
            
            # GARANTE A SEQUÊNCIA DE TODOS OS DIAS DO PERÍODO SELECIONADO (EX: 1 A 30)
            if isinstance(date_range, tuple) and len(date_range) == 2:
                s_date, e_date = date_range
                dias_mes = list(range(s_date.day, e_date.day + 1))
            else:
                df_filtered['Dia'] = pd.to_datetime(df_filtered['Vencimento_dt']).dt.day
                dias_mes = sorted([int(d) for d in df_filtered['Dia'].dropna().unique() if d > 0])
            
            # 1. Vendas puras
            piv_ent_vendas = df_rec_vendas[df_rec_vendas['Status_Clean'] == 'REALIZADO'].groupby(df_rec_vendas['Vencimento_dt'].dt.day)['Valor'].sum() if not df_rec_vendas.empty else pd.Series(0.0, index=dias_mes)
            
            # 2. Transferências de Entrada (Mútuo)
            piv_transf_in = df_rec_mutuo[df_rec_mutuo['Status_Clean'] == 'REALIZADO'].groupby(df_rec_mutuo['Vencimento_dt'].dt.day)['Valor'].sum() if not df_rec_mutuo.empty else pd.Series(0.0, index=dias_mes)
            
            # 3. Saídas operacionais
            piv_sai_op = df_desp_operacional[df_desp_operacional['Status_Clean'] == 'REALIZADO'].groupby(df_desp_operacional['Vencimento_dt'].dt.day)['Valor'].sum() if not df_desp_operacional.empty else pd.Series(0.0, index=dias_mes)
            
            # 4. Transferências de Saída (Empréstimo Mútuo)
            piv_transf_out = df_desp_mutuo[df_desp_mutuo['Status_Clean'] == 'REALIZADO'].groupby(df_desp_mutuo['Vencimento_dt'].dt.day)['Valor'].sum() if not df_desp_mutuo.empty else pd.Series(0.0, index=dias_mes)

            row_s_ini, row_vendas, row_tin, row_tot_ent, row_saidas, row_tout, row_tot_sai, row_liq_op, row_saldo_final = {}, {}, {}, {}, {}, {}, {}, {}, {}

            # DETERMINA O SALDO INICIAL FIXADO DE 31/08/2026
            if conta_selecionada in SALDOS_INICIAIS_AGOSTO:
                saldo_acumulado = SALDOS_INICIAIS_AGOSTO[conta_selecionada]
            else:
                saldo_acumulado = sum(SALDOS_INICIAIS_AGOSTO.values())

            for d in dias_mes:
                s_inicial = saldo_acumulado
                
                v = piv_ent_vendas.get(d, 0.0)
                tin = piv_transf_in.get(d, 0.0)
                tot_e = v + tin
                
                s = piv_sai_op.get(d, 0.0)
                tout = piv_transf_out.get(d, 0.0)
                tot_s = s + tout
                
                liq_op = v - s
                s_final = s_inicial + tot_e - tot_s
                
                saldo_acumulado = s_final  # Transporta sem lacunas para o dia seguinte
                
                row_s_ini[d] = s_inicial
                row_vendas[d] = v
                row_tin[d] = tin
                row_tot_ent[d] = tot_e
                
                row_saidas[d] = s
                row_tout[d] = tout
                row_tot_sai[d] = tot_s
                
                row_liq_op[d] = liq_op
                row_saldo_final[d] = s_final

            df_extrato_diario = pd.DataFrame([
                {"Linha de Extrato": "0. 🏦 SALDO INICIAL DO DIA (Transportado de 31/08)", **row_s_ini},
                {"Linha de Extrato": "1. (+) Total Vendas Liquidadas", **row_vendas},
                {"Linha de Extrato": "2. (+) Transferências Recebidas (Mútuo / Entradas)", **row_tin},
                {"Linha de Extrato": "3. (=) TOTAL DE ENTRADAS (Vendas + Transferências)", **row_tot_ent},
                {"Linha de Extrato": "4. (-) Total Saídas / Despesas Liquidadas", **row_saidas},
                {"Linha de Extrato": "5. (-) Transferências Concedidas (Empréstimo Mútuo / Saídas)", **row_tout},
                {"Linha de Extrato": "6. (=) TOTAL DE SAÍDAS (Despesas + Transferências)", **row_tot_sai},
                {"Linha de Extrato": "7. (=) Resultado Líquido Operacional (Vendas - Saídas)", **row_liq_op},
                {"Linha de Extrato": "8. 🏦 SALDO FINAL EM CONTA BANCÁRIA (Inicial + Entradas - Saídas)", **row_saldo_final}
            ])
            
            cols_order = ["Linha de Extrato"] + dias_mes
            st.dataframe(
                df_extrato_diario[cols_order].style.format({d: "R$ {:,.2f}" for d in dias_mes}),
                use_container_width=True,
                hide_index=True
            )
            
        with tab3:
            st.subheader("Matriz Comparativa por Conta Bancária")
            if not df_despesas.empty:
                pivot_store = df_despesas.pivot_table(index='Categoria_CFO', columns='Empresa', values='Valor', aggfunc='sum', fill_value=0)
                st.dataframe(pivot_store.style.format("R$ {:,.2f}"), use_container_width=True)

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

    except Exception as e:
        st.error(f"Erro ao processar os dados: {e}")
else:
    st.markdown("""
    <div class='welcome-card'>
        <h3>🍦 Painel de Fluxo de Caixa Executivo - Gelateria Borelli</h3>
        <p>Aguardando carga dos relatórios no menu lateral para inicializar o processamento.</p>
        <ol>
            <li>Ative a opção <b>Usar API F360 (Tempo Real)</b> e clique em <b>📈 Buscar Receitas / Cartões (API)</b>.</li>
            <li>OU anexe o arquivo de <b>Detalhes Fluxo de Caixa (.xlsx)</b>.</li>
        </ol>
    </div>
    """, unsafe_allow_html=True)