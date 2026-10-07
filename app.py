import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, date, timedelta

# IMPORTAÇÃO DO MÓDULO F360
from f360_api import (
    autenticar_f360, 
    buscar_parcelas_f360,
    processar_fluxo_de_caixa_oficial
)

# Tenta importar o processar CSV do navegador caso esteja usando a versão mais recente do f360_api.py
try:
    from f360_api import processar_tabela_fluxo_dom
    HAS_DOM_PROCESSOR = True
except ImportError:
    HAS_DOM_PROCESSOR = False

st.set_page_config(page_title="Gelateria Borelli - Fluxo de Caixa", page_icon="🟢", layout="wide")
st.markdown("""<style>.stApp { background-color: #0E1117; color: #FFFFFF; } .main-title { font-size: 28px; font-weight: bold; color: #00875A; }</style>""", unsafe_allow_html=True)

try: F360_TOKEN = st.secrets["F360_TOKEN"]
except: F360_TOKEN = "11001cbb-792d-45e5-b2f9-03ffc46fe7ed"

MAPA_CNPJ_LOJA = {"36240923000168": "4- PANTANAL", "36240923000249": "5- ESTAÇÃO", "36240923000320": "8 - GOIABEIRAS"}

def categorizar_plano_contas(plano):
    p = str(plano).upper().strip()
    if any(k in p for k in ['MÚTUO', 'MUTUO', 'INTERCOMPANY']): return "7. TRANSFERÊNCIAS INTERCOMPANY / MÚTUO"
    if any(k in p for k in ['SÓCIO', 'SOCIO', 'LUCRO', 'DISTRIBUIÇÃO', 'DIVIDENDO', 'PRÓ-LABORE', 'PRO-LABORE']): return "7. DESPESAS DE SÓCIOS"
    if any(k in p for k in ['CMV', 'DESCARTÁVEIS', 'LEITE', 'INSUMOS', 'BOBINAS', 'FRUTAS']): return "1. FORNECEDORES / MERCADORIAS (CMV)"
    if any(k in p for k in ['ICMS', 'IMPOSTO', 'FISCAL', 'DAS', 'TAXAS MUNICIPAIS', 'PIS', 'COFINS']): return "2. IMPOSTOS SOBRE VENDAS"
    if any(k in p for k in ['ALUGUEL', 'CONDOMÍNIO', 'ENERGIA', 'ÁGUA', 'IPTU', 'LIMPEZA']): return "3. DESPESAS DE OCUPAÇÃO"
    if any(k in p for k in ['SALÁRIO', 'VALE', 'FOLHA', 'FGTS', 'FÉRIAS', 'RESCISÃO', 'FUNCIONÁRIOS']): return "4. FOLHA DE PAGAMENTO & ENCARGOS"
    if any(k in p for k in ['EMPRÉSTIMO', 'CAPITAL DE GIRO', 'JUROS', 'MULTA', 'TARIFAS']): return "6. AMORTIZAÇÃO DE DÍVIDAS & CAPITAL"
    return "5. DESPESAS OPERACIONAIS & VENDAS"

def categorizar_receita(row):
    p = str(row.get("Plano de Contas") or "").upper().strip()
    if any(k in p for k in ['MÚTUO', 'MUTUO', 'INTERCOMPANY']): return "7. TRANSFERÊNCIAS INTERCOMPANY / MÚTUO"
    return "0. RECEITAS DE VENDAS"

@st.cache_data(ttl=3600)
def carregar_fluxo_oficial(_arquivos):
    resultado = {}
    for arq in _arquivos:
        df_dias, saldo_ini, contas = processar_fluxo_de_caixa_oficial(arq)
        chave = contas[0] if len(contas) == 1 else "Ver Todas as Contas"
        resultado[chave] = {"df": df_dias, "saldo_inicial": saldo_ini, "contas": contas}
    return resultado

# Função para colorir Saldo Final na Matriz Diária
def highlight_saldo(row):
    styles = [''] * len(row)
    if row["Linha de Extrato"] == "6. 🏦 SALDO FINAL BANCÁRIO":
        for i, val in enumerate(row):
            if isinstance(val, (int, float)):
                if val < 0:
                    styles[i] = 'color: #ff4b4b; font-weight: bold;'
                elif val > 0:
                    styles[i] = 'color: #21c354; font-weight: bold;'
    return styles

st.markdown("<div class='main-title'>🍦 Gelateria Borelli - Gestão de Fluxo de Caixa</div>", unsafe_allow_html=True)

# INICIALIZA O CACHE DE ARQUIVOS PARA ELES NÃO SUMIREM
if 'fluxo_oficial_cache' not in st.session_state:
    st.session_state.fluxo_oficial_cache = {}

with st.sidebar:
    st.header("⚡ Sincronização API (DRE)")
    if "jwt" not in st.session_state: st.session_state.jwt = autenticar_f360(F360_TOKEN)
    
    periodo_api = st.date_input("Período DRE (API)", (date(2026, 9, 1), date(2026, 10, 31)), format="DD/MM/YYYY")
    if st.button("🚀 Sincronizar API para DRE", use_container_width=True) and len(periodo_api) == 2:
        with st.spinner("Sincronizando DRE..."):
            d_ini, d_fim = periodo_api[0].replace(day=1), periodo_api[1]
            df_desp = buscar_parcelas_f360(st.session_state.jwt, d_ini, d_fim, MAPA_CNPJ_LOJA, "Despesa")
            if not df_desp.empty: df_desp["Categoria_CFO"] = df_desp["Plano de Contas"].apply(categorizar_plano_contas)
            st.session_state.df_api_desp = df_desp
            
            df_rec = buscar_parcelas_f360(st.session_state.jwt, d_ini, d_fim, MAPA_CNPJ_LOJA, "Receita")
            if not df_rec.empty:
                df_rec["Categoria_CFO"] = df_rec.apply(categorizar_receita, axis=1)
                df_rec["Tipo_Movimento"] = "RECEITA"
            st.session_state.df_api_rec = df_rec
            st.success("🟢 API Sincronizada!")

    st.divider()
    st.header("🏦 Upload Matriz Diária")
    file_fluxo_oficial = st.file_uploader("F360 > Fluxo de Caixa > Exportar", type=["xlsx"], accept_multiple_files=True)
    
    if HAS_DOM_PROCESSOR:
        file_tabela_csv = st.file_uploader("Opção 2: CSV Automático (via Script)", type=["csv"], key="tabela_csv")
    else:
        file_tabela_csv = None

# ATUALIZA O CACHE SE O USUÁRIO FEZ UPLOAD NOVO
if file_fluxo_oficial:
    st.session_state.fluxo_oficial_cache.update(carregar_fluxo_oficial(file_fluxo_oficial))

if file_tabela_csv is not None and HAS_DOM_PROCESSOR:
    df_dom, saldo_ini_dom = processar_tabela_fluxo_dom(file_tabela_csv)
    st.session_state.fluxo_oficial_cache["CSV (via navegador)"] = {"df": df_dom, "saldo_inicial": saldo_ini_dom, "contas": []}

if 'filtro_kpi' not in st.session_state: st.session_state.filtro_kpi = "PENDENTE"
if 'show_kpi_data' not in st.session_state: st.session_state.show_kpi_data = None

fluxo_oficial = st.session_state.fluxo_oficial_cache

_lista_dfs = [d for d in [st.session_state.get("df_api_desp"), st.session_state.get("df_api_rec")] if d is not None and not d.empty]
df_api = pd.concat(_lista_dfs, ignore_index=True) if _lista_dfs else pd.DataFrame()

col1, col2 = st.columns([2, 1])
with col1: 
    opcoes_conta = ["Ver Todas as Contas", "17 Pantanal Itaú", "51 Estação Itaú", "61 Itaú Goiabeiras", "52 RT", "36 MJL"]
    if "CSV (via navegador)" in fluxo_oficial:
        opcoes_conta.append("CSV (via navegador)")
    conta_selecionada = st.radio("Conta / Loja:", opcoes_conta, horizontal=True)

with col2:
    min_d, max_d = date(2026, 9, 1), date(2026, 10, 31)
    
    # === AMPLIA OS LIMITES DE DATA COM BASE NO EXCEL OFICIAL ===
    if not df_api.empty: 
        min_d = df_api['Vencimento_dt'].min().date()
        max_d = df_api['Vencimento_dt'].max().date()
        
    for dados in fluxo_oficial.values():
        if not dados["df"].empty:
            min_d = min(min_d, dados["df"]["Data"].min().date())
            max_d = max(max_d, dados["df"]["Data"].max().date())
            
    date_range = st.date_input("Filtro de Tela:", value=(min_d, max_d), format="DD/MM/YYYY")

df_kpi = df_api.copy()
if not df_kpi.empty:
    if conta_selecionada != "Ver Todas as Contas" and conta_selecionada != "CSV (via navegador)": 
        df_kpi = df_kpi[df_kpi['Empresa'] == conta_selecionada]
    if isinstance(date_range, tuple) and len(date_range) == 2: 
        df_kpi = df_kpi[(df_kpi['Vencimento_dt'].dt.date >= date_range[0]) & (df_kpi['Vencimento_dt'].dt.date <= date_range[1])]

df_rec_kpi = df_kpi[(df_kpi['Tipo_Movimento'] == 'RECEITA') & (df_kpi['Categoria_CFO'] != "7. TRANSFERÊNCIAS INTERCOMPANY / MÚTUO")] if not df_kpi.empty else pd.DataFrame()
df_desp_kpi = df_kpi[(df_kpi['Tipo_Movimento'] == 'DESPESA') & (df_kpi['Categoria_CFO'] != "7. TRANSFERÊNCIAS INTERCOMPANY / MÚTUO")] if not df_kpi.empty else pd.DataFrame()

tot_rec_prev = df_rec_kpi['Valor'].sum() if not df_rec_kpi.empty else 0.0
tot_rec_real = df_rec_kpi[df_rec_kpi['Status_Clean'] == 'REALIZADO']['Valor'].sum() if not df_rec_kpi.empty else tot_rec_prev

tot_prev, tot_real, tot_pend = 0.0, 0.0, 0.0
if not df_desp_kpi.empty:
    tot_prev = df_desp_kpi['Valor'].sum()
    tot_real = df_desp_kpi[df_desp_kpi['Status_Clean'] == 'REALIZADO']['Valor'].sum()
    tot_pend = df_desp_kpi[df_desp_kpi['Status_Clean'] == 'PENDENTE']['Valor'].sum()

st.divider()
k1, k2, k3, k4 = st.columns(4)

# REGISTRA O CLIQUE DOS BOTÕES PARA EXIBIR A TABELA
with k1: 
    if st.button(f"📊 DESPESAS PREVISTAS\nR$ {tot_prev:,.2f}", use_container_width=True):
        st.session_state.show_kpi_data = "PREVISTAS"
with k2: 
    if st.button(f"🟢 DESPESAS LIQUIDADAS\nR$ {tot_real:,.2f}", use_container_width=True):
        st.session_state.show_kpi_data = "LIQUIDADAS"
with k3: 
    if st.button(f"🔴 DESPESAS EM ABERTO\nR$ {tot_pend:,.2f}", use_container_width=True):
        st.session_state.show_kpi_data = "EM ABERTO"
with k4: 
    st.metric("Receita Líquida Títulos (API)", f"R$ {tot_rec_prev:,.2f}", delta=f"Realizado: R$ {tot_rec_real:,.2f}")

# EXIBE A TABELA DETALHADA SE UM DOS BOTÕES FOI CLICADO
if st.session_state.show_kpi_data and not df_desp_kpi.empty:
    st.markdown(f"### Detalhamento: {st.session_state.show_kpi_data}")
    cols_to_show = ['Vencimento_dt', 'Empresa', 'Cliente / Fornecedor', 'Plano de Contas', 'Valor', 'Status_Clean']
    
    if st.session_state.show_kpi_data == "PREVISTAS":
        df_show = df_desp_kpi[cols_to_show]
    elif st.session_state.show_kpi_data == "LIQUIDADAS":
        df_show = df_desp_kpi[df_desp_kpi['Status_Clean'] == 'REALIZADO'][cols_to_show]
    elif st.session_state.show_kpi_data == "EM ABERTO":
        df_show = df_desp_kpi[df_desp_kpi['Status_Clean'] == 'PENDENTE'][cols_to_show]
        
    st.dataframe(df_show.style.format({'Valor': 'R$ {:,.2f}'}), use_container_width=True, hide_index=True)
    
    if st.button("Fechar Detalhamento"):
        st.session_state.show_kpi_data = None
        st.rerun()

st.markdown("<br>", unsafe_allow_html=True)
tab1, tab2, tab3 = st.tabs(["📅 Fluxo Diário (Fonte Excel F360)", "📋 DRE de Caixa (Fonte API)", "🏪 Comparativo Por Loja"])

with tab1:
    st.subheader("Matriz Diária - Valores 100% Espelhados do F360")
    oficial = fluxo_oficial.get(conta_selecionada) or fluxo_oficial.get("Ver Todas as Contas") or fluxo_oficial.get("CSV (via navegador)")
    if not oficial and len(fluxo_oficial) == 1: oficial = list(fluxo_oficial.values())[0]

    if oficial:
        df_of = oficial["df"]
        if isinstance(date_range, tuple) and len(date_range) == 2:
            df_of = df_of[(df_of['Data'].dt.date >= date_range[0]) & (df_of['Data'].dt.date <= date_range[1])]
        
        if not df_of.empty:
            dias_of = sorted(df_of["Dia"].unique().tolist())
            linhas_of = [
                {"Linha de Extrato": "1. (+) Cartões", **dict(zip(df_of["Dia"], df_of.get("Cartoes", 0)))},
                {"Linha de Extrato": "2. (+) PIX / Boleto / Transferências", **dict(zip(df_of["Dia"], df_of.get("Boleto", 0) + df_of.get("Outros_Recebimentos", 0)))},
                {"Linha de Extrato": "3. (+) Orçamento (Entrada Prevista)", **dict(zip(df_of["Dia"], df_of.get("Orcamento_Entrada", 0)))},
                {"Linha de Extrato": "4. (=) Total de Entradas", **dict(zip(df_of["Dia"], df_of.get("Total_Entradas", 0)))},
                {"Linha de Extrato": "5. (-) Total de Saídas (Real + Orçamento)", **dict(zip(df_of["Dia"], df_of.get("Total_Saidas", 0)))},
                {"Linha de Extrato": "6. 🏦 SALDO FINAL BANCÁRIO", **dict(zip(df_of["Dia"], df_of.get("Saldo", 0)))},
            ]
            
            # Aplica a formatação de valores em R$ e depois a regra de cor Verde/Vermelho para a última linha
            df_display = pd.DataFrame(linhas_of)[["Linha de Extrato"] + dias_of]
            st.dataframe(df_display.style.apply(highlight_saldo, axis=1).format({d: "R$ {:,.2f}" for d in dias_of}), use_container_width=True, hide_index=True)
        else: st.warning("Sem dados para o período filtrado no Excel.")
    else:
        st.info("👈 Por favor, anexe o 'Fluxo de Caixa.xlsx' na barra lateral para gerar esta aba com os saldos bancários corretos e a visão do orçamento.")

with tab2:
    st.subheader("DRE de Caixa (Visão Gerencial por Plano de Contas)")
    if not df_api.empty:
        dre_list = [{"Categoria CFO": "0. RECEITAS DE VENDAS", "Previsto (R$)": f"R$ {tot_rec_prev:,.2f}", "Realizado (R$)": f"R$ {tot_rec_real:,.2f}", "Variação (R$)": f"R$ {tot_rec_real - tot_rec_prev:,.2f}"}]
        
        cats = [
            "1. FORNECEDORES / MERCADORIAS (CMV)", 
            "2. IMPOSTOS SOBRE VENDAS", 
            "3. DESPESAS DE OCUPAÇÃO", 
            "4. FOLHA DE PAGAMENTO & ENCARGOS", 
            "5. DESPESAS OPERACIONAIS & VENDAS", 
            "6. AMORTIZAÇÃO DE DÍVIDAS & CAPITAL",
            "7. DESPESAS DE SÓCIOS"
        ]
        
        tot_saidas_prev = 0.0
        tot_saidas_real = 0.0
        
        for c in cats:
            p = df_desp_kpi[df_desp_kpi['Categoria_CFO'] == c]['Valor'].sum() if not df_desp_kpi.empty else 0.0
            r = df_desp_kpi[(df_desp_kpi['Categoria_CFO'] == c) & (df_desp_kpi['Status_Clean'] == 'REALIZADO')]['Valor'].sum() if not df_desp_kpi.empty else 0.0
            
            tot_saidas_prev += p
            tot_saidas_real += r
            
            dre_list.append({"Categoria CFO": f"   (-) {c}", "Previsto (R$)": f"R$ {p:,.2f}", "Realizado (R$)": f"R$ {r:,.2f}", "Variação (R$)": f"R$ {r - p:,.2f}"})
        
        # Inserção da Linha 8 - Total Saídas
        dre_list.append({"Categoria CFO": "8. TOTAL SAÍDAS", "Previsto (R$)": f"R$ {tot_saidas_prev:,.2f}", "Realizado (R$)": f"R$ {tot_saidas_real:,.2f}", "Variação (R$)": f"R$ {tot_saidas_real - tot_saidas_prev:,.2f}"})
        
        # Calculo do EBITDA
        res_prev = tot_rec_prev - tot_saidas_prev
        res_real = tot_rec_real - tot_saidas_real
        dre_list.append({"Categoria CFO": "(=) EBITDA", "Previsto (R$)": f"R$ {res_prev:,.2f}", "Realizado (R$)": f"R$ {res_real:,.2f}", "Variação (R$)": f"R$ {res_real - res_prev:,.2f}"})
        
        st.dataframe(pd.DataFrame(dre_list), use_container_width=True, hide_index=True)
    else: st.warning("Sincronize a API no menu lateral para visualizar o DRE.")

# === COMPARATIVO POR LOJA ===
with tab3:
    st.subheader("Comparativo Por Loja (Vendas e Despesas)")
    
    if not df_api.empty:
        df_filtered_loja = df_api.copy()
        if isinstance(date_range, tuple) and len(date_range) == 2: 
            df_filtered_loja = df_filtered_loja[(df_filtered_loja['Vencimento_dt'].dt.date >= date_range[0]) & (df_filtered_loja['Vencimento_dt'].dt.date <= date_range[1])]

        tem_loja = ('Empresa_Loja' in df_filtered_loja.columns and df_filtered_loja['Empresa_Loja'].replace('', np.nan).notna().any())
        
        if not tem_loja:
            st.warning("Sem dado de loja de origem nos lançamentos carregados. Mostrando por conta bancária de liquidação como alternativa.")
            dimensao = 'Empresa'
        else:
            dimensao = 'Empresa_Loja'
            
        df_desp_loja = df_filtered_loja[(df_filtered_loja['Tipo_Movimento'] == 'DESPESA') & (df_filtered_loja['Categoria_CFO'] != "7. TRANSFERÊNCIAS INTERCOMPANY / MÚTUO")]
        df_desp_loja = df_desp_loja[df_desp_loja[dimensao].replace('', 'N/D') != ''].copy() if not df_desp_loja.empty else pd.DataFrame()
        
        df_rec_loja = df_filtered_loja[(df_filtered_loja['Tipo_Movimento'] == 'RECEITA') & (df_filtered_loja['Categoria_CFO'] != "7. TRANSFERÊNCIAS INTERCOMPANY / MÚTUO")]
        df_rec_loja = df_rec_loja[df_rec_loja[dimensao].replace('', 'N/D') != ''].copy() if not df_rec_loja.empty else pd.DataFrame()
        
        if not df_desp_loja.empty:
            st.markdown("**Despesas por categoria**")
            pivot_desp = df_desp_loja.pivot_table(index='Categoria_CFO', columns=dimensao, values='Valor', aggfunc='sum', fill_value=0)
            st.dataframe(pivot_desp.style.format("R$ {:,.2f}"), use_container_width=True)
            
        if not df_rec_loja.empty:
            st.markdown("**Resumo Operacional (Receita x Despesa)**")
            resumo_rec = df_rec_loja.groupby(dimensao)['Valor'].sum().to_frame("Receita de Vendas")
            resumo_desp = df_desp_loja.groupby(dimensao)['Valor'].sum().to_frame("Despesas") if not df_desp_loja.empty else pd.DataFrame()
            resumo = resumo_rec.join(resumo_desp, how='outer').fillna(0)
            resumo["Resultado (Receita - Despesa)"] = resumo["Receita de Vendas"] - resumo.get("Despesas", 0)
            st.dataframe(resumo.style.format("R$ {:,.2f}"), use_container_width=True)
            
        if df_desp_loja.empty and df_rec_loja.empty:
            st.info("Nenhum lançamento com loja identificada para comparar no período selecionado.")
    else:
        st.warning("Sincronize a API para gerar o comparativo entre as lojas.")