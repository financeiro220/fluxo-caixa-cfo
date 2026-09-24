import requests
import pandas as pd
import re
from datetime import datetime, date, timedelta

def autenticar_f360(token_api):
    """Autentica na F360 e retorna o token JWT de sessão."""
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
    except Exception:
        return None

def buscar_parcelas_f360(jwt_token, d_inicio, d_fim, mapa_cnpjs, tipo="Despesa"):
    """
    Busca parcelas diretamente via ParcelaDeTituloPublicAPI/ListarParcelasDeTitulos.
    Realiza paginação, consulta dupla (Vencimento + Liquidação) e aplica rateio proporcional.
    """
    url = "https://financas.f360.com.br/ParcelasDeTituloPublicAPI/ListarParcelasDeTitulos"
    headers = {
        "Authorization": f"Bearer {jwt_token}",
        "Content-Type": "application/json"
    }
    
    todas_parcelas = {}
    tipos_consulta = ["Vencimento", "Liquidacao"]
    
    # Executa consulta por Vencimento e por Liquidação para garantir parcelas pagas no mês
    for t_data in tipos_consulta:
        pagina = 1
        tem_mais = True
        
        while tem_mais:
            payload = {
                "DataInicio": d_inicio.strftime("%Y-%m-%d"),
                "DataFim": d_fim.strftime("%Y-%m-%d"),
                "TipoData": t_data,
                "Pagina": pagina,
                "ItensPorPagina": 100
            }
            
            try:
                r = requests.post(url, json=payload, headers=headers, timeout=12)
                if r.status_code == 200:
                    res = r.json()
                    itens = res.get("Result", []) if isinstance(res, dict) else res
                    if isinstance(itens, list) and len(itens) > 0:
                        for p in itens:
                            # Chave única para evitar duplicidades entre a busca por Vencimento e Liquidação
                            p_id = p.get("ParcelaId") or p.get("Id") or f"{p.get('NumeroTitulo')}_{p.get('ValorBruto')}_{p.get('Vencimento')}"
                            todas_parcelas[p_id] = p
                            
                        if len(itens) < 100:
                            tem_mais = False
                        else:
                            pagina += 1
                    else:
                        tem_mais = False
                else:
                    tem_mais = False
            except Exception:
                tem_mais = False

    registros = []
    
    for p in todas_parcelas.values():
        # Descartar canceladas ou baixadas
        if p.get("Cancelada") or str(p.get("Status", "")).lower() in ["cancelado", "baixado"]:
            continue
            
        cnpj_cru = re.sub(r'\D', '', str(p.get("CnpjEmpresa") or p.get("CNPJEmpresa") or ""))
        empresa_nome = mapa_cnpjs.get(cnpj_cru, cnpj_cru)
        
        val_bruto_parcela = float(p.get("ValorBruto") or p.get("Valor") or 0.0)
        
        dt_venc = pd.to_datetime(p.get("Vencimento") or p.get("DataVencimento"), errors='coerce')
        dt_liq = pd.to_datetime(p.get("Liquidacao") or p.get("DataLiquidacao"), errors='coerce')
        
        status_st = "REALIZADO" if pd.notna(dt_liq) or any(s in str(p.get("Status", "")).lower() for s in ['liquidado', 'conciliado']) else "PENDENTE"
        
        # Data de caixa: Liquidação se pago; Vencimento se pendente
        dt_caixa = dt_liq if (status_st == "REALIZADO" and pd.notna(dt_liq)) else dt_venc
        if pd.isna(dt_caixa):
            dt_caixa = dt_venc if pd.notna(dt_venc) else pd.to_datetime('today')

        # Processamento do Rateio Proporcional
        rateios = p.get("Rateio") or p.get("Rateios") or []
        if isinstance(rateios, list) and len(rateios) > 0:
            tot_rateio = sum([float(r.get("Valor", 0.0)) for r in rateios])
            tot_rateio = tot_rateio if tot_rateio > 0 else val_bruto_parcela
            
            for r in rateios:
                val_r = float(r.get("Valor", 0.0))
                prop = (val_r / tot_rateio) if tot_rateio > 0 else (1.0 / len(rateios))
                val_efetivo = val_bruto_parcela * prop
                
                plano_nome = r.get("PlanoDeContas") or r.get("NomePlanoDeContas") or p.get("PlanoDeContas") or "Outros"
                
                registros.append({
                    "Número": p.get("NumeroTitulo") or p.get("Numero") or "",
                    "Empresa": empresa_nome,
                    "Cliente / Fornecedor": p.get("NomePessoa") or p.get("Fornecedor") or p.get("Cliente") or "",
                    "Vencimento_dt": dt_caixa,
                    "Vencimento_real": dt_venc,
                    "Valor": val_efetivo,
                    "Plano de Contas": plano_nome,
                    "Status_Clean": status_st,
                    "Dia": dt_caixa.day if pd.notna(dt_caixa) else 1
                })
        else:
            plano_nome = p.get("PlanoDeContas") or "Outros"
            registros.append({
                "Número": p.get("NumeroTitulo") or p.get("Numero") or "",
                "Empresa": empresa_nome,
                "Cliente / Fornecedor": p.get("NomePessoa") or p.get("Fornecedor") or p.get("Cliente") or "",
                "Vencimento_dt": dt_caixa,
                "Vencimento_real": dt_venc,
                "Valor": val_bruto_parcela,
                "Plano de Contas": plano_nome,
                "Status_Clean": status_st,
                "Dia": dt_caixa.day if pd.notna(dt_caixa) else 1
            })

    df = pd.DataFrame(registros)
    if not df.empty:
        df['Vencimento_dt'] = pd.to_datetime(df['Vencimento_dt'])
        if 'Vencimento_real' in df.columns:
            df['Vencimento_real'] = pd.to_datetime(df['Vencimento_real'])
    return df