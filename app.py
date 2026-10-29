import streamlit as st
import pandas as pd
import numpy as np
import altair as alt
import os
import pickle
import re
import base64
import requests
from datetime import datetime, date, timedelta

# IMPORTAÇÃO DO MÓDULO F360
from f360_api import (
    autenticar_f360, 
    buscar_parcelas_f360,
    processar_fluxo_de_caixa_oficial
)

try:
    from f360_api import processar_tabela_fluxo_dom
    HAS_DOM_PROCESSOR = True
except ImportError:
    HAS_DOM_PROCESSOR = False

st.set_page_config(
    page_title="Borelli | Fluxo de Caixa",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ============================================================
# FUNÇÃO BLINDADA PARA CARREGAR A LOGO LOCAL (COM CAMINHO ABSOLUTO)
# ============================================================
@st.cache_data
def carregar_logo():
    nomes_tentativas = ["logo_borelli.png", "logo_borelli.png.png", "logo_borelli"]
    
    pastas_para_tentar = [
        ".", 
        os.path.dirname(os.path.abspath(__file__)),
        os.getcwd(),
        r"C:\Users\USUARIO\OneDrive\Área de Trabalho\fluxo-caixa-cfo" # Caminho absoluto forçado
    ]

    for pasta in set(pastas_para_tentar):
        try:
            if os.path.exists(pasta):
                arquivos_na_pasta = os.listdir(pasta)
                for arquivo in arquivos_na_pasta:
                    if arquivo.lower().strip() in nomes_tentativas:
                        caminho_completo = os.path.join(pasta, arquivo)
                        with open(caminho_completo, "rb") as f:
                            return base64.b64encode(f.read()).decode()
        except Exception:
            continue
    return None

LOGO_BASE64 = carregar_logo()

if LOGO_BASE64 is None:
    st.toast("⚠️ Imagem da logo não encontrada nem no caminho absoluto do OneDrive.", icon="⚠️")

# ============================================================
# FUNÇÃO DE AUTENTICAÇÃO INCICLE
# ============================================================
def autenticar_incicle(email, senha):
    url = "https://schedule.backend.incicle.com/api/auth/authenticate"
    payload = {"email": email, "password": senha}
    try:
        resp = requests.post(url, json=payload, timeout=10)
        if resp.status_code == 200:
            dados = resp.json()
            return dados.get("access_token")
        else:
            return None
    except Exception as e:
        return None

# ============================================================
# TELA DE LOGIN E VARIÁVEIS DE SESSÃO
# ============================================================
try:
    LOGIN_USUARIO = st.secrets.get("APP_LOGIN", "financeiro")
    LOGIN_SENHA = st.secrets.get("APP_SENHA", "borelli2026")
except Exception:
    LOGIN_USUARIO, LOGIN_SENHA = "financeiro", "borelli2026"

if "autenticado" not in st.session_state:
    st.session_state.autenticado = False

if "uploader_key" not in st.session_state:
    st.session_state.uploader_key = 0

if "modulo_ativo" not in st.session_state:
    st.session_state.modulo_ativo = "Financeiro (F360)"

if not st.session_state.autenticado:
    st.markdown("""
    <style>
        .stApp { background: #0B0F14; }
        [data-testid="stHeader"] { background: rgba(11,15,20,0.96); }
    </style>
    """, unsafe_allow_html=True)

    col_esq, col_meio, col_dir = st.columns([1, 1.2, 1])
    with col_meio:
        st.markdown("<br><br><br>", unsafe_allow_html=True)
        
        if LOGO_BASE64:
            st.markdown(
                f"<div style='text-align:center;'><img src='data:image/png;base64,{LOGO_BASE64}' style='max-height:140px; margin-bottom:15px;'></div>"
                "<div style='text-align:center;color:#8F9AA8;margin-bottom:24px;font-size:16px;'>Fluxo de Caixa · Controladoria</div>",
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                "<div style='text-align:center;font-size:32px;font-weight:800;color:#F8FAFC;'>BORELLI</div>"
                "<div style='text-align:center;color:#8F9AA8;margin-bottom:24px;'>Fluxo de Caixa · Controladoria</div>",
                unsafe_allow_html=True,
            )

        with st.form("form_login"):
            usuario = st.text_input("Usuário")
            senha = st.text_input("Senha", type="password")
            entrar = st.form_submit_button("Entrar", use_container_width=True)

        if entrar:
            if usuario == LOGIN_USUARIO and senha == LOGIN_SENHA:
                st.session_state.autenticado = True
                st.rerun()
            else:
                st.error("Usuário ou senha incorretos.")

    st.stop()

# ============================================================
# ESTILOS GERAIS E CONSTANTES
# ============================================================
CACHE_API_FILE = "dados_salvos_api.pkl"
CACHE_EXCEL_FILE = "dados_salvos_excel.pkl"

st.markdown("""
<style>
    .stApp { background: #0B0F14; color: #F4F7FA; }
    [data-testid="stHeader"] { background: rgba(11,15,20,0.96); }
    [data-testid="stSidebar"] { background: #151A21; border-right: 1px solid #252C35; }
    [data-testid="stSidebar"] > div:first-child { padding-top: 1rem; }
    .hero-title { font-size: 30px; line-height: 1.05; font-weight: 800; letter-spacing: -0.8px; margin-bottom: 2px; color: #F8FAFC; }
    .hero-subtitle { color: #8F9AA8; font-size: 14px; margin-bottom: 18px; }
    .section-title { font-size: 18px; font-weight: 750; color: #F4F7FA; margin: 4px 0 10px 0; }
    .muted { color: #8994A3; font-size: 12px; }
    .status-pill { display: inline-flex; align-items: center; gap: 7px; padding: 7px 12px; border-radius: 999px; background: #123022; color: #58D68D; border: 1px solid #20583C; font-size: 12px; font-weight: 700; }
    .status-dot { width: 8px; height: 8px; border-radius: 50%; background: #35D07F; display: inline-block; box-shadow: 0 0 10px rgba(53,208,127,.45); }
    .status-pill.blue { background: #0C2138; color: #69B7FF; border: 1px solid #143A63; }
    .status-dot.blue { background: #4D9CFF; box-shadow: 0 0 10px rgba(77,156,255,.45); }
    .kpi-card { background: linear-gradient(145deg, #151B23 0%, #10151C 100%); border: 1px solid #28313C; border-radius: 12px; padding: 15px 16px 14px 16px; min-height: 112px; box-shadow: 0 8px 24px rgba(0,0,0,.12); }
    .kpi-label { color: #8F9AA8; font-size: 11px; font-weight: 700; letter-spacing: .4px; text-transform: uppercase; margin-bottom: 7px; }
    .kpi-value { color: #F8FAFC; font-size: 24px; line-height: 1.05; font-weight: 800; letter-spacing: -.5px; }
    .kpi-green { color: #45D483; }
    .kpi-red { color: #FF6262; }
    .kpi-yellow { color: #F4C95D; }
    .kpi-blue { color: #69B7FF; }
    .kpi-foot { color: #697585; font-size: 11px; margin-top: 8px; }
    .panel { background: #11161D; border: 1px solid #252D37; border-radius: 12px; padding: 16px; margin-bottom: 14px; }
    .panel-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; }
    .panel-title { font-size: 15px; font-weight: 750; color: #F4F7FA; }
    .alert-good { background: #10271D; border: 1px solid #24553C; color: #67E39A; border-radius: 10px; padding: 11px 13px; font-size: 13px; font-weight: 650; }
    .alert-warn { background: #2A2413; border: 1px solid #67531D; color: #F3D36A; border-radius: 10px; padding: 11px 13px; font-size: 13px; font-weight: 650; }
    .alert-danger { background: #2A1719; border: 1px solid #663034; color: #FF8585; border-radius: 10px; padding: 11px 13px; font-size: 13px; font-weight: 650; }
    [data-testid="stDataFrame"] { border-radius: 10px; overflow: hidden; }
    .stButton > button { border-radius: 8px; border: 1px solid #343D49; background: #171D25; color: #E9EEF3; font-weight: 650; }
    .stButton > button:hover { border-color: #00875A; color: #5CE39A; }
    hr { border-color: #252D37 !important; }
</style>
""", unsafe_allow_html=True)

try:
    F360_TOKEN = st.secrets["F360_TOKEN"]
except:
    F360_TOKEN = "11001cbb-792d-45e5-b2f9-03ffc46fe7ed"

MAPA_CNPJ_LOJA = {
    "36240923000168": "4- PANTANAL",
    "36240923000249": "5- ESTAÇÃO",
    "36240923000320": "8 - GOIABEIRAS"
}

# ============================================================
# FUNÇÕES E SISTEMA DE MEMÓRIA LOCAL
# ============================================================
if 'fluxo_oficial_cache' not in st.session_state:
    st.session_state.fluxo_oficial_cache = {}
    if os.path.exists(CACHE_EXCEL_FILE):
        try:
            with open(CACHE_EXCEL_FILE, 'rb') as f:
                st.session_state.fluxo_oficial_cache = pickle.load(f)
        except Exception:
            pass

if 'api_loaded' not in st.session_state:
    st.session_state.api_loaded = True
    if os.path.exists(CACHE_API_FILE):
        try:
            with open(CACHE_API_FILE, 'rb') as f:
                api_data = pickle.load(f)
            st.session_state.df_api_desp = api_data.get('desp', pd.DataFrame())
            st.session_state.df_api_rec = api_data.get('rec', pd.DataFrame())
            st.session_state.log_api_desp = api_data.get('log_desp', [])
            st.session_state.log_api_rec = api_data.get('log_rec', [])
            st.session_state.log_api_periodo = api_data.get('periodo', None)
        except Exception:
            pass

if 'show_kpi_data' not in st.session_state: st.session_state.show_kpi_data = None

def categorizar_plano_contas(plano):
    p = str(plano).upper().strip()
    if any(k in p for k in ['MÚTUO', 'MUTUO', 'INTERCOMPANY', 'APLICAÇÃO']): return "7. TRANSFERÊNCIAS INTERCOMPANY / MÚTUO"
    if any(k in p for k in ['SÓCIO', 'SOCIO', 'LUCRO', 'DISTRIBUIÇÃO', 'DIVIDENDO', 'PRÓ-LABORE', 'PRO-LABORE']): return "7. DESPESAS DE SÓCIOS"
    if any(k in p for k in ['SALÁRIO', 'VALE', 'FOLHA', 'FGTS', 'FÉRIAS', 'RESCISÃO', 'FUNCIONÁRIOS', 'FREELANCE', 'DIARISTA', 'MÉDICO', 'INSS', 'SINDICATO', 'VT', 'VR']): return "4. FOLHA DE PAGAMENTO & ENCARGOS"
    if any(k in p for k in ['CMV', 'DESCARTÁVEIS', 'LEITE', 'INSUMO', 'BOBINA', 'FRUTA', 'COMPRAS', 'MERCADORIA']): return "1. FORNECEDORES / MERCADORIAS (CMV)"
    if any(k in p for k in ['ICMS', 'IMPOSTO', 'FISCAL', 'DAS', 'TAXAS MUNICIPAIS', 'PIS', 'COFINS', 'ISS', 'SIMPLES']): return "2. IMPOSTOS SOBRE VENDAS"
    if any(k in p for k in ['ALUGUEL', 'CONDOMÍNIO', 'ENERGIA', 'ÁGUA', 'IPTU', 'LUZ', 'INTERNET', 'SEGURO PREDIAL', 'TELEFONE']): return "3. DESPESAS DE OCUPAÇÃO"
    if any(k in p for k in ['EMPRÉSTIMO', 'CAPITAL DE GIRO', 'JUROS', 'MULTA', 'TARIFA', 'TAXA', 'MAQUININHA', 'BANCÁRIA']): return "6. AMORTIZAÇÃO DE DÍVIDAS & CAPITAL"
    if any(k in p for k in ['LIMPEZA', 'MANUTENÇÃO', 'CONTABILIDADE', 'MARKETING', 'IFOOD', 'SISTEMA', 'HONORÁRIO', 'MATERIAL']): return "5. DESPESAS OPERACIONAIS & VENDAS"
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
        nome = getattr(arq, "name", "Arquivo")
        chave = contas[0] if len(contas) == 1 else "Ver Todas as Contas"
        
        if chave in resultado and chave == "Ver Todas as Contas":
            st.toast(f"⚠️ Aviso: O ficheiro '{nome}' substituiu a tabela do ficheiro anterior porque partilham o mesmo nível de visualização.")
            
        resultado[chave] = {"df": df_dias, "saldo_inicial": saldo_ini, "contas": contas}
    return resultado

def highlight_saldo(row):
    styles = [''] * len(row)
    if row["Linha de Extrato"] == "6. 🏦 SALDO FINAL BANCÁRIO":
        for i, val in enumerate(row):
            if isinstance(val, (int, float)):
                if val < 0:
                    styles[i] = 'color: #ff6262; font-weight: bold;'
                elif val > 0:
                    styles[i] = 'color: #45d483; font-weight: bold;'
    return styles

def brl(v):
    return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

def formatar_dataframe_brl(df):
    if df is None or df.empty: return df
    df_show = df.copy()
    for col in df_show.columns:
        if pd.api.types.is_numeric_dtype(df_show[col]):
            df_show[col] = df_show[col].apply(lambda x: f"R$ {x:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
    return df_show

def _preparar_titulos_detalhe(df, status=None):
    if df is None or df.empty: return pd.DataFrame()
    d = df.copy()
    
    if status == "REALIZADO": d = d[d["Status_Clean"].astype(str).str.upper() == "REALIZADO"]
    elif status == "PENDENTE": d = d[d["Status_Clean"].astype(str).str.upper() == "PENDENTE"]

    colunas_preferidas = ["Vencimento_dt", "Empresa", "Empresa_Loja", "Cliente / Fornecedor", "Plano de Contas", "Categoria_CFO", "Valor", "Status_Clean", "Status", "Data_Liquidacao"]
    colunas = [c for c in colunas_preferidas if c in d.columns]
    
    for c in d.columns:
        if c not in colunas and any(k in str(c).lower() for k in ["titulo", "documento", "parcela", "id", "descrição", "descricao"]):
            colunas.append(c)

    if not colunas: return d
    d = d[colunas].copy()
    d = d.loc[:, ~d.columns.duplicated(keep="first")].copy()

    if "Vencimento_dt" in d.columns:
        d["Vencimento"] = pd.to_datetime(d["Vencimento_dt"], errors="coerce").dt.strftime("%d/%m/%Y")
        d = d.drop(columns=["Vencimento_dt"])

    if "Data_Liquidacao" in d.columns:
        d["Liquidação"] = pd.to_datetime(d["Data_Liquidacao"], errors="coerce").dt.strftime("%d/%m/%Y")

    if "Valor" in d.columns:
        d["Valor"] = pd.to_numeric(d["Valor"], errors="coerce").fillna(0)

    rename = {"Empresa_Loja": "Loja", "Status_Clean": "Status"}
    d = d.rename(columns=rename)
    
    d = d.loc[:, ~d.columns.duplicated(keep="first")].copy()
    
    nomes, contagem = [], {}
    for nome in d.columns:
        nome = str(nome)
        if nome not in contagem:
            contagem[nome] = 0
            nomes.append(nome)
        else:
            contagem[nome] += 1
            nomes.append(f"{nome}_{contagem[nome]}")
    d.columns = nomes
    
    cols = d.columns.tolist()
    if "Vencimento" in cols: cols.insert(0, cols.pop(cols.index("Vencimento")))
    if "Empresa" in cols: cols.insert(1, cols.pop(cols.index("Empresa")))
    if "Loja" in cols: cols.insert(2, cols.pop(cols.index("Loja")))
    if "Cliente / Fornecedor" in cols: cols.insert(3, cols.pop(cols.index("Cliente / Fornecedor")))
    
    return d[cols]

def render_movement_cards(previsto, liquidado, aberto, titulo="Lançamentos", df_detail=None, state_prefix="mov"):
    c1, c2, c3 = st.columns(3)
    
    cards = [
        (c1, "PREVISTO", previsto, "kpi-blue", "Todos os títulos do período", "ALL"),
        (c2, "LIQUIDADO", liquidado, "kpi-green", "Valores já realizados", "REALIZADO"),
        (c3, "EM ABERTO", aberto, "kpi-yellow" if aberto > 0 else "kpi-green", "Previsto ainda não liquidado", "PENDENTE")
    ]

    for col, label, value, color_class, foot, status in cards:
        with col:
            st.markdown(f"""
            <div class="kpi-card">
                <div class="kpi-label">{"📊" if status == "ALL" else "🟢" if status == "REALIZADO" else "🟡"} {titulo} · {label}</div>
                <div class="kpi-value {color_class}">{brl(value)}</div>
                <div class="kpi-foot">{foot}</div>
            </div>
            """, unsafe_allow_html=True)

            if st.button(f"Ver títulos · {label}", key=f"btn_{state_prefix}_{status}", use_container_width=True):
                st.session_state.show_kpi_data = f"{state_prefix}:{status}"

    current = st.session_state.get("show_kpi_data")
    if isinstance(current, str) and current.startswith(f"{state_prefix}:"):
        status = current.split(":", 1)[1]
        df_show = _preparar_titulos_detalhe(df_detail, None if status == "ALL" else status)

        st.markdown("""<div style="background:#11161D; border:1px solid #303A46; border-radius:12px; padding:16px; margin:14px 0 18px 0;">""", unsafe_allow_html=True)
        h1, h2 = st.columns([5, 1])
        with h1:
            nomes = {"ALL": "Todos os títulos", "REALIZADO": "Títulos liquidados", "PENDENTE": "Títulos em aberto"}
            st.markdown(f"### 📋 {titulo} · {nomes.get(status, status)}")
        with h2:
            if st.button("✕ Fechar", key=f"fechar_box_{state_prefix}_{status}", use_container_width=True):
                st.session_state.show_kpi_data = None
                st.rerun()

        if df_show.empty:
            st.info("Nenhum título encontrado para este status no período/loja selecionados.")
        else:
            if "Valor" in df_show.columns:
                total = df_show["Valor"].sum()
                st.caption(f"{len(df_show):,} título(s) · Total: {brl(total)}")
                st.dataframe(formatar_dataframe_brl(df_show), use_container_width=True, hide_index=True)
            else:
                st.dataframe(df_show, use_container_width=True, hide_index=True)
        
        st.markdown("</div>", unsafe_allow_html=True)

# ============================================================
# MENU LATERAL - SELETOR DE MÓDULOS E MENU F360
# ============================================================
with st.sidebar:
    if LOGO_BASE64:
        st.markdown(
            f"<div style='text-align:center;'><img src='data:image/png;base64,{LOGO_BASE64}' style='max-width:160px; margin-bottom:10px;'></div>",
            unsafe_allow_html=True
        )
    else:
        st.markdown("## BORELLI")
        
    st.session_state.modulo_ativo = st.radio(
        "MÓDULO DO SISTEMA",
        ["Financeiro (F360)", "Recursos Humanos (InCicle)"],
        label_visibility="collapsed"
    )
    st.divider()

if st.session_state.modulo_ativo == "Financeiro (F360)":
    with st.sidebar:
        st.caption("Controladoria · Fluxo de Caixa")
        st.markdown("### ⚡ Sincronização F360")
        periodo_api = st.date_input("Período DRE (API)", (date(2026, 10, 1), date(2026, 10, 31)), format="DD/MM/YYYY")

        if st.button("🚀 Sincronizar API", use_container_width=True) and len(periodo_api) == 2:
            with st.spinner("Sincronizando dados do F360..."):
                st.session_state.jwt = autenticar_f360(F360_TOKEN)
                d_ini, d_fim = periodo_api[0], periodo_api[1]

                log_desp, log_rec = [], []
                
                df_desp = buscar_parcelas_f360(st.session_state.jwt, d_ini, d_fim, MAPA_CNPJ_LOJA, "Despesa", log=log_desp)
                
                if not df_desp.empty: 
                    df_desp['Valor'] = pd.to_numeric(df_desp['Valor'], errors='coerce').fillna(0)
                    
                    def corrigir_descontos(row):
                        val = row['Valor']
                        plano = str(row.get('Plano de Contas', '')).upper()
                        if "DESCONTO" in plano and val > 0:
                            return -val
                        return val
                    df_desp['Valor'] = df_desp.apply(corrigir_descontos, axis=1)
                    
                    def cat_desp(p):
                        p = str(p).upper().strip()
                        if any(k in p for k in ['MÚTUO', 'MUTUO', 'INTERCOMPANY', 'APLICAÇÃO']): return "7. TRANSFERÊNCIAS INTERCOMPANY / MÚTUO"
                        if any(k in p for k in ['SÓCIO', 'SOCIO', 'LUCRO', 'DISTRIBUIÇÃO', 'DIVIDENDO', 'PRÓ-LABORE', 'PRO-LABORE']): return "7. DESPESAS DE SÓCIOS"
                        if any(k in p for k in ['SALÁRIO', 'VALE', 'FOLHA', 'FGTS', 'FÉRIAS', 'RESCISÃO', 'FUNCIONÁRIOS', 'FREELANCE', 'DIARISTA', 'MÉDICO', 'INSS', 'SINDICATO', 'VT', 'VR']): return "4. FOLHA DE PAGAMENTO & ENCARGOS"
                        if any(k in p for k in ['CMV', 'DESCARTÁVEIS', 'LEITE', 'INSUMO', 'BOBINA', 'FRUTA', 'COMPRAS', 'MERCADORIA']): return "1. FORNECEDORES / MERCADORIAS (CMV)"
                        if any(k in p for k in ['ICMS', 'IMPOSTO', 'FISCAL', 'DAS', 'TAXAS MUNICIPAIS', 'PIS', 'COFINS', 'ISS', 'SIMPLES']): return "2. IMPOSTOS SOBRE VENDAS"
                        if any(k in p for k in ['ALUGUEL', 'CONDOMÍNIO', 'ENERGIA', 'ÁGUA', 'IPTU', 'LUZ', 'INTERNET', 'SEGURO PREDIAL', 'TELEFONE']): return "3. DESPESAS DE OCUPAÇÃO"
                        if any(k in p for k in ['EMPRÉSTIMO', 'CAPITAL DE GIRO', 'JUROS', 'MULTA', 'TARIFA', 'TAXA', 'MAQUININHA', 'BANCÁRIA']): return "6. AMORTIZAÇÃO DE DÍVIDAS & CAPITAL"
                        if any(k in p for k in ['LIMPEZA', 'MANUTENÇÃO', 'CONTABILIDADE', 'MARKETING', 'IFOOD', 'SISTEMA', 'HONORÁRIO', 'MATERIAL']): return "5. DESPESAS OPERACIONAIS & VENDAS"
                        return "5. DESPESAS OPERACIONAIS & VENDAS"
                        
                    df_desp["Categoria_CFO"] = df_desp["Plano de Contas"].apply(cat_desp)
                st.session_state.df_api_desp = df_desp
                st.session_state.log_api_desp = log_desp

                df_rec = buscar_parcelas_f360(st.session_state.jwt, d_ini, d_fim, MAPA_CNPJ_LOJA, "Receita", log=log_rec)
                
                if not df_rec.empty:
                    df_rec["Categoria_CFO"] = df_rec.apply(categorizar_receita, axis=1)
                    df_rec["Tipo_Movimento"] = "RECEITA"
                st.session_state.df_api_rec = df_rec
                st.session_state.log_api_rec = log_rec
                
                st.session_state.log_api_periodo = (d_ini, d_fim)
                
                with open(CACHE_API_FILE, 'wb') as f:
                    pickle.dump({
                        'desp': df_desp,
                        'rec': df_rec,
                        'log_desp': log_desp,
                        'log_rec': log_rec,
                        'periodo': (d_ini, d_fim)
                    }, f)
                    
                st.success(f"🟢 API sincronizada! Despesas: {len(df_desp):,} | Receitas: {len(df_rec):,}")

        with st.expander("🔎 LOG / DIAGNÓSTICO DA API F360", expanded=False):
            logs_d = st.session_state.get("log_api_desp", [])
            logs_r = st.session_state.get("log_api_rec", [])
            periodo_log = st.session_state.get("log_api_periodo")
            
            if periodo_log:
                st.caption(f"Período consultado: {periodo_log[0]:%d/%m/%Y} até {periodo_log[1]:%d/%m/%Y}")
                
            if logs_d:
                st.markdown("**DESPESAS**")
                st.code("\n".join(logs_d), language="text")
                
            if logs_r:
                st.markdown("**RECEITAS**")
                st.code("\n".join(logs_r), language="text")
                
            if not logs_d and not logs_r:
                st.info("Clique em '🚀 Sincronizar API' para gerar o log.")

        st.divider()
        st.markdown("### 🏦 Dados oficiais do caixa")
        file_fluxo_oficial = st.file_uploader(
            "F360 > Fluxo de Caixa > Exportar", 
            type=["xlsx"], 
            accept_multiple_files=True,
            key=f"fluxo_uploader_{st.session_state.uploader_key}"
        )

        file_tabela_csv = st.file_uploader(
            "CSV Automático (opcional)", 
            type=["csv"],
            key=f"csv_uploader_{st.session_state.uploader_key}"
        ) if HAS_DOM_PROCESSOR else None
        
        st.divider()
        
        if st.button("🧹 Limpar Memória", use_container_width=True):
            if os.path.exists(CACHE_API_FILE):
                os.remove(CACHE_API_FILE)
            if os.path.exists(CACHE_EXCEL_FILE):
                os.remove(CACHE_EXCEL_FILE)
                
            chaves_para_manter = ["autenticado", "uploader_key", "modulo_ativo"]
            for chave in list(st.session_state.keys()):
                if chave not in chaves_para_manter:
                    del st.session_state[chave]
                    
            st.session_state.uploader_key += 1
            st.cache_data.clear() # Limpa a memória profunda de 1 hora
            st.rerun()

        st.caption("🔐 A fonte oficial do saldo bancário continua sendo o export do Fluxo de Caixa do F360. Os dados ficam salvos até que clique em Limpar Memória.")

        st.divider()
        if st.button("🚪 Sair", use_container_width=True):
            st.session_state.autenticado = False
            st.rerun()

    # ============================================================
    # CARREGAMENTO E SALVAMENTO DE ARQUIVOS NO CACHE
    # ============================================================
    if file_fluxo_oficial: 
        st.session_state.fluxo_oficial_cache.update(carregar_fluxo_oficial(file_fluxo_oficial))
        with open(CACHE_EXCEL_FILE, 'wb') as f:
            pickle.dump(st.session_state.fluxo_oficial_cache, f)

    if file_tabela_csv is not None and HAS_DOM_PROCESSOR:
        df_dom, saldo_ini_dom = processar_tabela_fluxo_dom(file_tabela_csv)
        st.session_state.fluxo_oficial_cache["CSV (via navegador)"] = {
            "df": df_dom, 
            "saldo_inicial": saldo_ini_dom, 
            "contas": []
        }
        with open(CACHE_EXCEL_FILE, 'wb') as f:
            pickle.dump(st.session_state.fluxo_oficial_cache, f)

    fluxo_oficial = st.session_state.fluxo_oficial_cache

    _lista_dfs = [d for d in [st.session_state.get("df_api_desp"), st.session_state.get("df_api_rec")] if d is not None and not d.empty]
    df_api = pd.concat(_lista_dfs, ignore_index=True) if _lista_dfs else pd.DataFrame()

    # ============================================================
    # CABEÇALHO E FILTROS DO FINANCEIRO
    # ============================================================
    if LOGO_BASE64:
        header_html = f"""
        <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:20px; margin-bottom: 20px;">
            <div>
                <img src="data:image/png;base64,{LOGO_BASE64}" style="max-height:60px; margin-bottom:5px;">
                <div class="hero-subtitle">Fluxo de Caixa · Controladoria</div>
            </div>
            <div class="status-pill"><span class="status-dot"></span>F360 conectado</div>
        </div>
        """
    else:
        header_html = """
        <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:20px; margin-bottom: 20px;">
            <div><div class="hero-title">BORELLI</div><div class="hero-subtitle">Fluxo de Caixa · Controladoria</div></div>
            <div class="status-pill"><span class="status-dot"></span>F360 conectado</div>
        </div>
        """

    st.markdown(header_html, unsafe_allow_html=True)

    f1, f2 = st.columns([2.2, 1])
    with f1:
        opcoes_conta = ["Ver Todas as Contas", "17 Pantanal Itaú", "51 Estação Itaú", "61 Itaú Goiabeiras", "52 RT", "36 MJL"]
        if "CSV (via navegador)" in fluxo_oficial:
            opcoes_conta.append("CSV (via navegador)")
        conta_selecionada = st.radio("Conta / Loja", opcoes_conta, horizontal=True)

    with f2:
        min_d, max_d = date(2026, 10, 1), date(2026, 10, 31)
        
        if not df_api.empty:
            min_d, max_d = df_api['Vencimento_dt'].min().date(), df_api['Vencimento_dt'].max().date()
            
        for dados in fluxo_oficial.values():
            if not dados["df"].empty:
                min_d = min(min_d, dados["df"]["Data"].min().date())
                max_d = max(max_d, dados["df"]["Data"].max().date())

        date_range = st.date_input("Período", value=(min_d, max_d), format="DD/MM/YYYY")

    # ============================================================
    # FILTRO API E VARIÁVEIS GLOBAIS
    # ============================================================
    df_kpi = df_api.copy()
    if not df_kpi.empty:
        if conta_selecionada not in ("Ver Todas as Contas", "CSV (via navegador)"):
            df_kpi = df_kpi[df_kpi['Empresa'] == conta_selecionada]
            
        if isinstance(date_range, tuple) and len(date_range) == 2:
            df_kpi = df_kpi[(df_kpi['Vencimento_dt'].dt.date >= date_range[0]) & (df_kpi['Vencimento_dt'].dt.date <= date_range[1])]

    oficial = fluxo_oficial.get(conta_selecionada) or fluxo_oficial.get("Ver Todas as Contas") or fluxo_oficial.get("CSV (via navegador)")
    if not oficial and len(fluxo_oficial) == 1:
        oficial = list(fluxo_oficial.values())[0]

    df_of_exec, saldo_final_exec, entradas_oficiais, saidas_oficiais = pd.DataFrame(), None, None, None
    saldo_atual_disponivel = None

    if oficial:
        # -------------------------------------------------------------
        # CÁLCULO DO "SALDO ATUAL" (Saldo Anterior + Entradas do Dia)
        # -------------------------------------------------------------
        df_full = oficial["df"].copy().sort_values("Data")
        if not df_full.empty:
            ref_date = date_range[1] if isinstance(date_range, tuple) and len(date_range) == 2 else date.today()
            df_up_to_ref = df_full[df_full["Data"].dt.date <= ref_date]
            
            if not df_up_to_ref.empty:
                data_foco = df_up_to_ref.iloc[-1]["Data"]
                entradas_do_dia = df_up_to_ref[df_up_to_ref["Data"] == data_foco]["Total_Entradas"].sum()
                
                df_anterior = df_up_to_ref[df_up_to_ref["Data"] < data_foco]
                if not df_anterior.empty:
                    saldo_anterior = df_anterior.iloc[-1]["Saldo"]
                else:
                    saldo_anterior = oficial.get("saldo_inicial", 0.0)
                
                saldo_atual_disponivel = float(saldo_anterior + entradas_do_dia)

        # -------------------------------------------------------------
        # VARIÁVEIS NORMAIS DO FLUXO
        # -------------------------------------------------------------
        df_of_exec = oficial["df"].copy()
        
        if isinstance(date_range, tuple) and len(date_range) == 2:
            df_of_exec = df_of_exec[(df_of_exec["Data"].dt.date >= date_range[0]) & (df_of_exec["Data"].dt.date <= date_range[1])]

        if not df_of_exec.empty:
            entradas_oficiais = df_of_exec["Total_Entradas"].sum()
            saidas_oficiais = df_of_exec["Total_Saidas"].sum()
            saldo_final_exec = df_of_exec.iloc[-1]["Saldo"]
            
            # --- AJUSTE AUTOMÁTICO DAS TAXAS DE CARTÃO PARA BATER O CAIXA ---
            if not df_kpi.empty:
                despesas_api_temp = df_kpi[(df_kpi['Tipo_Movimento'] == 'DESPESA') & (df_kpi['Categoria_CFO'] != "7. TRANSFERÊNCIAS INTERCOMPANY / MÚTUO")]
                ajustes = []
                
                for d in df_of_exec["Data"].dropna().unique():
                    d_date = pd.to_datetime(d).date()
                    saida_excel = df_of_exec[df_of_exec["Data"].dt.date == d_date]["Total_Saidas"].sum()
                    saida_api = despesas_api_temp[despesas_api_temp["Vencimento_dt"].dt.date == d_date]["Valor"].sum()
                    
                    diff = round(saida_excel - saida_api, 2)
                    
                    if diff > 0.01:
                        ajustes.append({
                            "Vencimento_dt": pd.to_datetime(d),
                            "Empresa": conta_selecionada,
                            "Empresa_Loja": "Diversas" if conta_selecionada == "Ver Todas as Contas" else conta_selecionada,
                            "Cliente / Fornecedor": "Taxas de Cartões / Adquirentes (iFood, etc)",
                            "Plano de Contas": "Taxas de Cartão",
                            "Categoria_CFO": "5. DESPESAS OPERACIONAIS & VENDAS",
                            "Valor": diff,
                            "Status_Clean": "REALIZADO",
                            "Status": "Liquidado",
                            "Tipo_Movimento": "DESPESA",
                            "Data_Liquidacao": pd.to_datetime(d)
                        })

                if ajustes:
                    df_ajustes = pd.DataFrame(ajustes)
                    df_kpi = pd.concat([df_kpi, df_ajustes], ignore_index=True)

    df_rec_kpi = df_kpi[(df_kpi['Tipo_Movimento'] == 'RECEITA') & (df_kpi['Categoria_CFO'] != "7. TRANSFERÊNCIAS INTERCOMPANY / MÚTUO")] if not df_kpi.empty else pd.DataFrame()
    df_desp_kpi = df_kpi[(df_kpi['Tipo_Movimento'] == 'DESPESA') & (df_kpi['Categoria_CFO'] != "7. TRANSFERÊNCIAS INTERCOMPANY / MÚTUO")] if not df_kpi.empty else pd.DataFrame()

    tot_rec_prev = df_rec_kpi['Valor'].sum() if not df_rec_kpi.empty else 0.0
    tot_rec_real = df_rec_kpi[df_rec_kpi['Status_Clean'] == 'REALIZADO']['Valor'].sum() if not df_rec_kpi.empty else 0.0

    tot_prev = df_desp_kpi['Valor'].sum() if not df_desp_kpi.empty else 0.0
    tot_real = df_desp_kpi[df_desp_kpi['Status_Clean'] == 'REALIZADO']['Valor'].sum() if not df_desp_kpi.empty else 0.0
    tot_pend = df_desp_kpi[df_desp_kpi['Status_Clean'] == 'PENDENTE']['Valor'].sum() if not df_desp_kpi.empty else 0.0

    # ALINHAMENTO DO EXPORT OFICIAL COM A API
    if not df_of_exec.empty and not df_kpi.empty:
        for d in df_of_exec["Data"].dropna().unique():
            d_date = pd.to_datetime(d).date()
            api_desp = df_desp_kpi[df_desp_kpi["Vencimento_dt"].dt.date == d_date]["Valor"].sum()
            api_rec = df_rec_kpi[df_rec_kpi["Vencimento_dt"].dt.date == d_date]["Valor"].sum()
            
            idx = df_of_exec.index[df_of_exec["Data"].dt.date == d_date]
            if not idx.empty:
                if api_desp > df_of_exec.loc[idx[0], "Total_Saidas"]:
                    df_of_exec.loc[idx[0], "Total_Saidas"] = api_desp
                
                if api_rec > df_of_exec.loc[idx[0], "Total_Entradas"]:
                    df_of_exec.loc[idx[0], "Total_Entradas"] = api_rec
        
        entradas_oficiais = df_of_exec["Total_Entradas"].sum()
        saidas_oficiais = df_of_exec["Total_Saidas"].sum()

    entradas_exec = max((entradas_oficiais or 0), tot_rec_prev)
    saidas_exec = max((saidas_oficiais or 0), tot_prev)
    resultado_exec = entradas_exec - saidas_exec

    # ============================================================
    # ABAS DO DASHBOARD FINANCEIRO
    # ============================================================
    tabs = st.tabs(["📊 Visão Executiva", "📅 Fluxo Diário", "📋 DRE de Caixa", "🏪 Comparativo Por Loja"])

    with tabs[0]:
        st.markdown('<div class="section-title">Resumo financeiro do período</div>', unsafe_allow_html=True)

        c1, c2, c3, c4, c5, c6 = st.columns(6)

        with c1:
            st.markdown(f"""
            <div class="kpi-card">
                <div class="kpi-label">💰 Entradas Reais</div>
                <div class="kpi-value kpi-green">{brl(entradas_exec)}</div>
                <div class="kpi-foot">Dinheiro liquidado no banco</div>
            </div>
            """, unsafe_allow_html=True)
            
        with c2:
            st.markdown(f"""
            <div class="kpi-card">
                <div class="kpi-label">🔴 Saídas</div>
                <div class="kpi-value kpi-red">{brl(saidas_exec)}</div>
                <div class="kpi-foot">Caixa Pago + Pendente da API</div>
            </div>
            """, unsafe_allow_html=True)
            
        with c3:
            st.markdown(f"""
            <div class="kpi-card">
                <div class="kpi-label">📈 Resultado</div>
                <div class="kpi-value {"kpi-green" if resultado_exec >= 0 else "kpi-red"}">{brl(resultado_exec)}</div>
                <div class="kpi-foot">Entradas − saídas do período</div>
            </div>
            """, unsafe_allow_html=True)
            
        with c4:
            st.markdown(f"""
            <div class="kpi-card">
                <div class="kpi-label">💲 Saldo Atual (Hoje)</div>
                <div class="kpi-value {"kpi-green" if (saldo_atual_disponivel or 0) >= 0 else "kpi-red"}">{brl(saldo_atual_disponivel) if saldo_atual_disponivel is not None else "—"}</div>
                <div class="kpi-foot">Saldo anterior + Entradas</div>
            </div>
            """, unsafe_allow_html=True)
            
        with c5:
            st.markdown(f"""
            <div class="kpi-card">
                <div class="kpi-label">🏦 Saldo Final</div>
                <div class="kpi-value {"kpi-green" if (saldo_final_exec or 0) >= 0 else "kpi-red"}">{brl(saldo_final_exec) if saldo_final_exec is not None else "—"}</div>
                <div class="kpi-foot">Saldo do export oficial F360</div>
            </div>
            """, unsafe_allow_html=True)
            
        with c6:
            st.markdown(f"""
            <div class="kpi-card">
                <div class="kpi-label">⚠️ Em Aberto</div>
                <div class="kpi-value {"kpi-green" if tot_pend == 0 else "kpi-yellow"}">{brl(tot_pend)}</div>
                <div class="kpi-foot">{"Nenhuma despesa pendente" if tot_pend == 0 else "Despesas pendentes na API"}</div>
            </div>
            """, unsafe_allow_html=True)

        st.markdown("<br>", unsafe_allow_html=True)

        if saldo_final_exec is not None and saldo_final_exec < 0:
            st.markdown('<div class="alert-danger">🔴 Atenção: o saldo final do período está negativo. Isso indica descoberto bancário na conta/loja selecionada.</div>', unsafe_allow_html=True)
        elif tot_pend > 0:
            st.markdown(f'<div class="alert-warn">🟡 Atenção: existem {brl(tot_pend)} em despesas pendentes na API. O resultado do período considera esses pagamentos como realizados.</div>', unsafe_allow_html=True)
        else:
            st.markdown('<div class="alert-good">🟢 Caixa limpo e sem despesas pendentes identificadas na API para o período filtrado.</div>', unsafe_allow_html=True)
            
        st.markdown("<br>", unsafe_allow_html=True)

        g1, g2 = st.columns([1.75, 1])

        with g1:
            st.markdown("""
            <div class="panel">
                <div class="panel-header">
                    <div class="panel-title">Fluxo de Caixa · Entradas × Saídas</div>
                    <div class="muted">por dia</div>
                </div>
            </div>
            """, unsafe_allow_html=True)
            
            if not df_of_exec.empty:
                chart_df = df_of_exec[["Data", "Total_Entradas", "Total_Saidas"]].copy()
                chart_df.columns = ["Data", "Entradas", "Saídas"]
                
                chart_df['Data_str'] = chart_df['Data'].dt.strftime('%d/%m')
                
                df_melt = chart_df.melt(id_vars=['Data_str'], value_vars=['Entradas', 'Saídas'], var_name='Tipo', value_name='Valor')
                
                def formata_k(val):
                    if val < 100:
                        return ""
                    if val >= 1000:
                        return f"{val/1000:.1f}K".replace(".0K", "K")
                    return f"{val:.0f}"
                    
                df_melt['Rotulo'] = df_melt['Valor'].apply(formata_k)
                
                max_y = df_melt['Valor'].max()
                max_y = max_y * 1.15 if pd.notna(max_y) and max_y > 0 else 100
                
                base = alt.Chart(df_melt).encode(
                    x=alt.X("Data_str:O", title="", axis=alt.Axis(labelAngle=0)),
                    xOffset="Tipo:N",
                    y=alt.Y("Valor:Q", title="", scale=alt.Scale(domain=[0, max_y]), axis=alt.Axis(format="s", grid=True))
                )
                
                barras = base.mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3).encode(
                    color=alt.Color(
                        "Tipo:N",
                        scale=alt.Scale(domain=["Entradas", "Saídas"], range=["#45D483", "#FF6262"]),
                        legend=alt.Legend(title="", orient="bottom")
                    ),
                    tooltip=[
                        alt.Tooltip("Data_str:O", title="Data"),
                        alt.Tooltip("Tipo:N", title="Tipo"),
                        alt.Tooltip("Valor:Q", title="R$", format=",.2f")
                    ]
                )
                
                textos = base.mark_text(
                    align='center',
                    baseline='bottom',
                    dy=-8,
                    fontSize=13,
                    fontWeight="bold",
                    color="#F8FAFC"
                ).encode(
                    text=alt.Text('Rotulo:N')
                )
                
                st.altair_chart((barras + textos).properties(height=280), use_container_width=True)
            else:
                st.info("Anexe o export 'Fluxo de Caixa.xlsx' para visualizar o fluxo diário oficial.")

        with g2:
            st.markdown("""
            <div class="panel">
                <div class="panel-header">
                    <div class="panel-title">Composição das Saídas</div>
                    <div class="muted">API F360</div>
                </div>
            </div>
            """, unsafe_allow_html=True)
            
            if not df_desp_kpi.empty:
                comp = df_desp_kpi.groupby("Categoria_CFO")["Valor"].sum().sort_values(ascending=True)
                
                comp.index = [str(x).replace("1. ", "").replace("2. ", "").replace("3. ", "").replace("4. ", "").replace("5. ", "").replace("6. ", "").replace("7. ", "") for x in comp.index]
                
                comp_df = comp.reset_index()
                comp_df.columns = ["Categoria", "Valor"]
                
                def formata_k_comp(val):
                    if val < 10:
                        return ""
                    if val >= 1000:
                        return f"{val/1000:.1f}K".replace(".0K", "K")
                    return f"{val:.0f}"
                    
                comp_df['Rotulo'] = comp_df['Valor'].apply(formata_k_comp)
                
                max_x = comp_df['Valor'].max()
                max_x = max_x * 1.2 if pd.notna(max_x) and max_x > 0 else 100
                
                base_comp = alt.Chart(comp_df).encode(
                    x=alt.X("Valor:Q", title="", scale=alt.Scale(domain=[0, max_x]), axis=alt.Axis(format="s", grid=False)),
                    y=alt.Y("Categoria:N", sort="-x", title="", axis=alt.Axis(labelAngle=0, labelLimit=300))
                )
                
                barras_comp = base_comp.mark_bar(color="#69B7FF", cornerRadiusEnd=3).encode(
                    tooltip=[
                        alt.Tooltip("Categoria:N", title="Categoria"),
                        alt.Tooltip("Valor:Q", title="R$", format=",.2f")
                    ]
                )
                
                textos_comp = base_comp.mark_text(
                    align='left',
                    baseline='middle',
                    dx=5,
                    fontSize=13,
                    fontWeight="bold",
                    color="#F8FAFC"
                ).encode(
                    text=alt.Text('Rotulo:N')
                )
                
                st.altair_chart((barras_comp + textos_comp).properties(height=280), use_container_width=True)
            else:
                st.info("Sincronize a API para visualizar a composição das despesas.")

        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown('<div class="section-title">🏪 Resultado por Loja</div>', unsafe_allow_html=True)
        
        if not df_api.empty:
            df_loja_exec = df_kpi.copy()
            
            tem_loja_exec = "Empresa_Loja" in df_loja_exec.columns and df_loja_exec["Empresa_Loja"].replace("", np.nan).notna().any()
            dimensao_exec = "Empresa_Loja" if tem_loja_exec else "Empresa"
            
            rec_loja = df_loja_exec[(df_loja_exec["Tipo_Movimento"] == "RECEITA") & (df_loja_exec["Categoria_CFO"] != "7. TRANSFERÊNCIAS INTERCOMPANY / MÚTUO")].groupby(dimensao_exec)["Valor"].sum()
            desp_loja = df_loja_exec[(df_loja_exec["Tipo_Movimento"] == "DESPESA") & (df_loja_exec["Categoria_CFO"] != "7. TRANSFERÊNCIAS INTERCOMPANY / MÚTUO")].groupby(dimensao_exec)["Valor"].sum()
            
            resumo_loja = pd.concat([rec_loja.rename("Entradas"), desp_loja.rename("Saídas")], axis=1).fillna(0)
            resumo_loja["Resultado (Receita - Despesa)"] = resumo_loja["Entradas"] - resumo_loja["Saídas"]
            resumo_loja = resumo_loja.sort_values("Resultado (Receita - Despesa)", ascending=False)
            
            def formatar_tabela_loja(val):
                if isinstance(val, (int, float)):
                    if val == 0: return "—"
                    return f"R$ {val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                return val
                
            def style_loja_resultado(val):
                if isinstance(val, (int, float)):
                    if val < 0: return 'color: #FF6262; font-weight: bold;'
                    elif val > 0: return 'color: #45D483; font-weight: bold;'
                return ''
                
            try:
                st.dataframe(
                    resumo_loja.style.format(formatar_tabela_loja).map(style_loja_resultado, subset=["Resultado (Receita - Despesa)"]),
                    use_container_width=True
                )
            except Exception:
                st.dataframe(resumo_loja, use_container_width=True)
        else:
            st.info("Sincronize a API para gerar o comparativo por loja.")

        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown('<div class="section-title">📅 Projeção do Caixa</div>', unsafe_allow_html=True)
        
        if not df_of_exec.empty:
            proj = df_of_exec[["Data", "Total_Entradas", "Total_Saidas", "Saldo"]].copy()
            proj.columns = ["Data", "Entradas", "Saídas", "Saldo"]
            
            proj['Data'] = pd.to_datetime(proj['Data']).dt.strftime('%d/%m/%Y')
            
            def colorir_saldo(val):
                if isinstance(val, (int, float)):
                    if val < 0: return 'color: #FF6262; font-weight: bold;'
                    elif val > 0: return 'color: #45D483; font-weight: bold;'
                return ''

            try:
                tabela_formatada = proj.tail(10).style.format({
                    "Entradas": "R$ {:,.2f}", 
                    "Saídas": "R$ {:,.2f}", 
                    "Saldo": "R$ {:,.2f}"
                }).map(colorir_saldo, subset=['Saldo'])
                
                st.dataframe(tabela_formatada, use_container_width=True, hide_index=True)
            except Exception:
                st.dataframe(proj.tail(10), use_container_width=True, hide_index=True)
        else: 
            st.info("A projeção diária utiliza os dados do export oficial do Fluxo de Caixa F360.")

    with tabs[1]:
        if oficial:
            df_cards = oficial["df"].copy()
            if isinstance(date_range, tuple) and len(date_range) == 2:
                df_cards = df_cards[(df_cards["Data"].dt.date >= date_range[0]) & (df_cards["Data"].dt.date <= date_range[1])]

            if not df_api.empty:
                df_cards_api = df_kpi.copy()
                
                rec_cards = df_cards_api[(df_cards_api["Tipo_Movimento"] == "RECEITA") & (df_cards_api["Categoria_CFO"] != "7. TRANSFERÊNCIAS INTERCOMPANY / MÚTUO")]
                prev_rec = rec_cards["Valor"].sum() if not rec_cards.empty else 0.0
                liq_rec = rec_cards[rec_cards["Status_Clean"] == "REALIZADO"]["Valor"].sum() if not rec_cards.empty else 0.0
                aberto_rec = rec_cards[rec_cards["Status_Clean"] == "PENDENTE"]["Valor"].sum() if not rec_cards.empty else max(prev_rec - liq_rec, 0)
                
                st.markdown("#### Lançamentos do período")
                render_movement_cards(prev_rec, liq_rec, aberto_rec, "Receitas", df_detail=rec_cards, state_prefix="fluxo_receitas")
                
                st.markdown("<br>", unsafe_allow_html=True)
                
                desp_cards = df_cards_api[(df_cards_api["Tipo_Movimento"] == "DESPESA") & (df_cards_api["Categoria_CFO"] != "7. TRANSFERÊNCIAS INTERCOMPANY / MÚTUO")]
                prev_cards = desp_cards["Valor"].sum() if not desp_cards.empty else 0.0
                liq_cards = desp_cards[desp_cards["Status_Clean"] == "REALIZADO"]["Valor"].sum() if not desp_cards.empty else 0.0
                aberto_cards = desp_cards[desp_cards["Status_Clean"] == "PENDENTE"]["Valor"].sum() if not desp_cards.empty else max(prev_cards - liq_cards, 0)
                
                render_movement_cards(prev_cards, liq_cards, aberto_cards, "Despesas", df_detail=desp_cards, state_prefix="fluxo_despesas")

            else:
                entradas = df_cards["Total_Entradas"].sum() if not df_cards.empty else 0.0
                saidas = df_cards["Total_Saidas"].sum() if not df_cards.empty else 0.0
                
                st.markdown("#### Movimentação oficial do caixa")
                render_movement_cards(entradas, entradas, 0.0, "Entradas", df_detail=None, state_prefix="fluxo_oficial_ent")
                
                st.markdown("<br>", unsafe_allow_html=True)
                
                render_movement_cards(saidas, saidas, 0.0, "Saídas", df_detail=None, state_prefix="fluxo_oficial_sai")
                st.caption("Para separar previsto, liquidado e em aberto, sincronize a API F360.")
        else:
            st.info("👈 Anexe o 'Fluxo de Caixa.xlsx' para habilitar os indicadores do fluxo diário.")

        if oficial and not df_cards.empty:
            dias_of = sorted(df_cards["Dia"].unique().tolist())
            linhas_of = [
                {"Linha de Extrato": "1. (+) Cartões", **dict(zip(df_cards["Dia"], df_cards.get("Cartoes", 0)))},
                {"Linha de Extrato": "2. (+) PIX / Boleto / Transferências", **dict(zip(df_cards["Dia"], df_cards.get("Boleto", 0) + df_cards.get("Outros_Recebimentos", 0)))},
                {"Linha de Extrato": "3. (+) Orçamento (Entrada Prevista)", **dict(zip(df_cards["Dia"], df_cards.get("Orcamento_Entrada", 0)))},
                {"Linha de Extrato": "4. (=) Total de Entradas", **dict(zip(df_cards["Dia"], df_cards.get("Total_Entradas", 0)))},
                {"Linha de Extrato": "5. (-) Total de Saídas (Real + Orçamento)", **dict(zip(df_cards["Dia"], df_cards.get("Total_Saidas", 0)))},
                {"Linha de Extrato": "6. 🏦 SALDO FINAL BANCÁRIO", **dict(zip(df_cards["Dia"], df_cards.get("Saldo", 0)))},
            ]
            
            df_display = pd.DataFrame(linhas_of)[["Linha de Extrato"] + dias_of]
            
            def format_currency(val):
                if isinstance(val, (int, float)): return f"R$ {val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                return val
                
            try:
                st.dataframe(
                    df_display.style.apply(highlight_saldo, axis=1).format({d: format_currency for d in dias_of}),
                    use_container_width=True, hide_index=True
                )
            except Exception:
                st.dataframe(df_display, use_container_width=True, hide_index=True)

    with tabs[2]:
        st.subheader("DRE de Caixa — Visão Gerencial por Plano de Contas")
        if not df_api.empty:
            st.markdown("#### Lançamentos da DRE")
            
            rec_prev_dre = df_rec_kpi["Valor"].sum() if not df_rec_kpi.empty else 0.0
            rec_liq_dre = df_rec_kpi[df_rec_kpi["Status_Clean"] == "REALIZADO"]["Valor"].sum() if not df_rec_kpi.empty else 0.0
            rec_aberto_dre = df_rec_kpi[df_rec_kpi["Status_Clean"] == "PENDENTE"]["Valor"].sum() if not df_rec_kpi.empty else max(rec_prev_dre - rec_liq_dre, 0)
            
            desp_prev_dre = df_desp_kpi["Valor"].sum() if not df_desp_kpi.empty else 0.0
            desp_liq_dre = df_desp_kpi[df_desp_kpi["Status_Clean"] == "REALIZADO"]["Valor"].sum() if not df_desp_kpi.empty else 0.0
            desp_aberto_dre = df_desp_kpi[df_desp_kpi["Status_Clean"] == "PENDENTE"]["Valor"].sum() if not df_desp_kpi.empty else max(desp_prev_dre - desp_liq_dre, 0)

            render_movement_cards(rec_prev_dre, rec_liq_dre, rec_aberto_dre, "Receitas", df_detail=df_rec_kpi, state_prefix="dre_receitas")
            
            st.markdown("<br>", unsafe_allow_html=True)
            
            render_movement_cards(desp_prev_dre, desp_liq_dre, desp_aberto_dre, "Despesas", df_detail=df_desp_kpi, state_prefix="dre_despesas")
            
            st.caption("Os cards usam os lançamentos da API F360 respeitando a conta/loja e o período selecionados.")
            st.markdown("<br>", unsafe_allow_html=True)

            dre_list = []
            dre_list.append({
                "Categoria CFO": "0. RECEITAS DE VENDAS",
                "Previsto (R$)": f"R$ {tot_rec_prev:,.2f}",
                "Realizado (R$)": f"R$ {tot_rec_real:,.2f}",
                "Variação (R$)": f"R$ {tot_rec_real - tot_rec_prev:,.2f}"
            })
            
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
                if not df_desp_kpi.empty:
                    p = df_desp_kpi[df_desp_kpi["Categoria_CFO"] == c]["Valor"].sum()
                    r = df_desp_kpi[(df_desp_kpi["Categoria_CFO"] == c) & (df_desp_kpi["Status_Clean"] == "REALIZADO")]["Valor"].sum()
                else:
                    p = r = 0.0
                    
                tot_saidas_prev += p
                tot_saidas_real += r
                dre_list.append({
                    "Categoria CFO": f"   (-) {c}",
                    "Previsto (R$)": f"R$ {p:,.2f}",
                    "Realizado (R$)": f"R$ {r:,.2f}",
                    "Variação (R$)": f"R$ {r - p:,.2f}"
                })
                
            dre_list.append({
                "Categoria CFO": "8. TOTAL SAÍDAS",
                "Previsto (R$)": f"R$ {tot_saidas_prev:,.2f}",
                "Realizado (R$)": f"R$ {tot_saidas_real:,.2f}",
                "Variação (R$)": f"R$ {tot_saidas_real - tot_saidas_prev:,.2f}"
            })
            
            res_prev = tot_rec_prev - tot_saidas_prev
            res_real = tot_rec_real - tot_saidas_real
            
            dre_list.append({
                "Categoria CFO": "(=) EBITDA",
                "Previsto (R$)": f"R$ {res_prev:,.2f}",
                "Realizado (R$)": f"R$ {res_real:,.2f}",
                "Variação (R$)": f"R$ {res_real - res_prev:,.2f}"
            })

            def colorir_linha_dre(row):
                styles = [''] * len(row)
                cat = str(row.iloc[0])
                if "(=) EBITDA" in cat:
                    for i, val in enumerate(row):
                        if i > 0 and isinstance(val, str):
                            try:
                                v = float(val.replace('R$ ', '').replace('.', '').replace(',', '.'))
                                if v < 0:
                                    styles[i] = 'color: #FF6262; font-weight: bold;'
                                elif v > 0:
                                    styles[i] = 'color: #45D483; font-weight: bold;'
                            except:
                                pass
                elif "8. TOTAL SAÍDAS" in cat:
                    styles = ['font-weight: bold; border-top: 1px solid #303A46;'] * len(row)
                return styles

            try:
                df_dre_formatado = pd.DataFrame(dre_list)
                st.dataframe(df_dre_formatado.style.apply(colorir_linha_dre, axis=1), use_container_width=True, hide_index=True)
            except Exception:
                st.dataframe(pd.DataFrame(dre_list), use_container_width=True)
        else:
            st.warning("Sincronize a API no menu lateral para visualizar o DRE.")

    with tabs[3]:
        st.subheader("Comparativo Por Loja — Vendas e Despesas")
        
        if not df_api.empty:
            df_filtered_loja = df_kpi.copy()
            tem_loja = "Empresa_Loja" in df_filtered_loja.columns and df_filtered_loja["Empresa_Loja"].replace("", np.nan).notna().any()
            
            dimensao = "Empresa_Loja" if tem_loja else "Empresa"
            if not tem_loja:
                st.warning("Sem dado de loja de origem nos lançamentos carregados. Mostrando por conta bancária de liquidação.")

            df_desp_loja = df_filtered_loja[(df_filtered_loja["Tipo_Movimento"] == "DESPESA") & (df_filtered_loja["Categoria_CFO"] != "7. TRANSFERÊNCIAS INTERCOMPANY / MÚTUO")]
            df_rec_loja = df_filtered_loja[(df_filtered_loja["Tipo_Movimento"] == "RECEITA") & (df_filtered_loja["Categoria_CFO"] != "7. TRANSFERÊNCIAS INTERCOMPANY / MÚTUO")]

            def formatar_tabela_loja_sem_zero(val):
                if isinstance(val, (int, float)):
                    if val == 0: return "—"
                    return f"R$ {val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                return val

            if not df_desp_loja.empty:
                st.markdown("**Despesas por categoria**")
                pivot_desp = df_desp_loja.pivot_table(index="Categoria_CFO", columns=dimensao, values="Valor", aggfunc="sum", fill_value=0)
                
                try:
                    st.dataframe(pivot_desp.style.format(formatar_tabela_loja_sem_zero), use_container_width=True)
                except Exception:
                    st.dataframe(pivot_desp, use_container_width=True)

            if not df_rec_loja.empty:
                st.markdown("**Resumo Operacional (Receita x Despesa)**")
                resumo_rec = df_rec_loja.groupby(dimensao)["Valor"].sum().to_frame("Receita de Vendas")
                
                resumo_desp = df_desp_loja.groupby(dimensao)["Valor"].sum().to_frame("Despesas") if not df_desp_loja.empty else pd.DataFrame()
                
                resumo = resumo_rec.join(resumo_desp, how="outer").fillna(0)
                resumo["Resultado (Receita - Despesa)"] = resumo["Receita de Vendas"] - resumo.get("Despesas", 0)
                
                def style_loja_resultado(val):
                    if isinstance(val, (int, float)):
                        if val < 0: return 'color: #FF6262; font-weight: bold;'
                        elif val > 0: return 'color: #45D483; font-weight: bold;'
                    return ''
                    
                try:
                    st.dataframe(
                        resumo.style.format(formatar_tabela_loja_sem_zero).map(style_loja_resultado, subset=["Resultado (Receita - Despesa)"]),
                        use_container_width=True
                    )
                except Exception:
                    st.dataframe(resumo, use_container_width=True)
                    
            if df_desp_loja.empty and df_rec_loja.empty:
                st.info("Nenhum lançamento com loja identificada para comparar no período selecionado.")

        else:
            st.warning("Sincronize a API para gerar o comparativo entre as lojas.")

# ============================================================
# MÓDULO 2: RECURSOS HUMANOS (InCicle API)
# ============================================================
elif st.session_state.modulo_ativo == "Recursos Humanos (InCicle)":
    
    header_html = """
    <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:20px; margin-bottom: 20px;">
        <div><div class="hero-title">Recursos Humanos</div><div class="hero-subtitle">Organograma e Estrutura (Dados Reais)</div></div>
        <div class="status-pill blue"><span class="status-dot blue"></span>InCicle API Conectada</div>
    </div>
    """
    st.markdown(header_html, unsafe_allow_html=True)
    
    # Função auxiliar para ler o Company ID do token no Streamlit
    def decode_jwt_payload_app(token):
        try:
            payload = token.split(".")[1]
            padded = payload + "=" * (4 - len(payload) % 4)
            decoded = base64.b64decode(padded).decode("utf-8")
            return json.loads(decoded)
        except Exception:
            return {}
    
    with st.sidebar:
        st.markdown("### 🔑 Conexão InCicle")
        email_incicle = st.text_input("E-mail InCicle", value="rh@taldivoeferreira.com.br")
        senha_incicle = st.text_input("Senha InCicle", type="password", value="020281ia")
        
        if st.button("🚀 Sincronizar Estrutura", use_container_width=True):
            with st.spinner("A extrair dados reais da InCicle..."):
                token = autenticar_incicle(email_incicle, senha_incicle)
                if token:
                    st.session_state.incicle_token = token
                    st.session_state.rh_sync = True
                    
                    payload = decode_jwt_payload_app(token)
                    company_id = payload.get("company_id") or payload.get("companyId")
                    if not company_id and "user" in payload and "config" in payload["user"]:
                        company_id = payload["user"]["config"].get("default_company_id")
                        
                    headers = {
                        "Authorization": f"Bearer {token}",
                        "companyId": str(company_id)
                    }
                    
                    # 1. Contagem Geral (Core API)
                    r_count = requests.get("https://core.backend.incicle.com/api/v1/engineering/collaborators/count", headers=headers)
                    if r_count.status_code == 200: st.session_state.rh_count = r_count.json()
                    
                    # 2. Lojas/Unidades (Engineering API)
                    r_units = requests.get("https://engineering.backend.incicle.com/engineering/units", headers=headers)
                    if r_units.status_code == 200: st.session_state.rh_lojas = r_units.json().get("data", [])
                        
                    # 3. Pessoas e Cargos (Engineering API)
                    r_people = requests.get("https://engineering.backend.incicle.com/engineering/people?per_page=150", headers=headers)
                    if r_people.status_code == 200: st.session_state.rh_pessoas = r_people.json().get("data", [])
                        
                    st.success("✅ Organograma sincronizado com sucesso!")
                else:
                    st.error("❌ Falha na autenticação. Verifique as credenciais.")
                    
        st.divider()
        st.caption("A extração de Custos da Folha e Controle de Ponto (Timesheets) aguarda a libertação das respetivas rotas pela InCicle.")

    if st.session_state.get("rh_sync", False):
        count_dados = st.session_state.get("rh_count", {})
        pessoas = st.session_state.get("rh_pessoas", [])
        lojas = st.session_state.get("rh_lojas", [])
        
        ativos = count_dados.get("linked", 0)
        inativos = count_dados.get("unlinked", 0)
        
        st.markdown('<div class="section-title">Monitor de Estrutura e Headcount</div>', unsafe_allow_html=True)
        
        c1, c2, c3, c4 = st.columns(4)
        with c1: st.markdown(f'<div class="kpi-card"><div class="kpi-label">👥 Headcount Ativo</div><div class="kpi-value kpi-blue">{ativos}</div><div class="kpi-foot">Colaboradores vinculados</div></div>', unsafe_allow_html=True)
        with c2: st.markdown(f'<div class="kpi-card"><div class="kpi-label">⚪ Não Vinculados</div><div class="kpi-value kpi-yellow">{inativos}</div><div class="kpi-foot">Registos inativos/desligados</div></div>', unsafe_allow_html=True)
        with c3: st.markdown(f'<div class="kpi-card"><div class="kpi-label">🏪 Lojas/Unidades</div><div class="kpi-value kpi-green">{len(lojas)}</div><div class="kpi-foot">Unidades de negócio ativas</div></div>', unsafe_allow_html=True)
        with c4: st.markdown(f'<div class="kpi-card"><div class="kpi-label">⚠️ Ponto / Custos</div><div class="kpi-value kpi-red">Pendente</div><div class="kpi-foot">Aguardando API Timesheets</div></div>', unsafe_allow_html=True)

        st.markdown("<br>### Distribuição de Colaboradores por Loja", unsafe_allow_html=True)
        
        if pessoas:
            df_pessoas = pd.DataFrame(pessoas)
            
            if "unit_name" not in df_pessoas.columns: df_pessoas["unit_name"] = "Sem loja vinculada"
            else: df_pessoas["unit_name"] = df_pessoas["unit_name"].fillna("Sem loja vinculada")
                
            if "job_title" not in df_pessoas.columns: df_pessoas["job_title"] = "Sem cargo"
                
            df_lojas = df_pessoas.groupby("unit_name").size().reset_index(name="Headcount")
            df_lojas = df_lojas.rename(columns={"unit_name": "Loja / Unidade"}).sort_values("Headcount", ascending=False)
            
            col_t, col_g = st.columns([1, 1])
            with col_t:
                st.dataframe(df_lojas, use_container_width=True, hide_index=True)
            with col_g:
                grafico = alt.Chart(df_lojas).encode(
                    x=alt.X("Headcount:Q", title=""),
                    y=alt.Y("Loja / Unidade:N", sort="-x", title="")
                ).mark_bar(color="#69B7FF", cornerRadiusEnd=3)
                st.altair_chart(grafico.properties(height=250), use_container_width=True)
                
            st.markdown("### 📋 Lista de Colaboradores Ativos")
            df_display = df_pessoas[["name", "email", "job_title", "unit_name"]].copy()
            df_display.columns = ["Nome", "E-mail", "Cargo", "Loja / Unidade"]
            st.dataframe(df_display, use_container_width=True, hide_index=True)
        else:
            st.info("Nenhum colaborador encontrado na extração detalhada.")
    else:
        st.info("👈 Clique em '🚀 Sincronizar Estrutura' no menu lateral para carregar os dados ao vivo da InCicle.")