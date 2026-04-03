from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
import math

app = FastAPI(title="Hotmart Negociação API", version="1.0.0")

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ── Fórmulas base ──────────────────────────────────────────────────────────────

def pmt(r, n, pv):
    if n == 1: return pv
    if r == 0: return pv / n
    return pv * (r * (1+r)**n) / ((1+r)**n - 1)

def pv_annuity(r, n, pmt_val):
    if r == 0: return pmt_val * n
    return pmt_val * (1 - (1+r)**(-n)) / r

GW_IMPLICIT_RATES = [0, 3.5654, 3.9836, 4.2172, 4.3589, 4.4501,
                     4.5089, 4.5467, 4.5702, 4.5832, 4.5895, 4.5900]

def calc_hotmart(P, fee_pct, ra_pct, rp_pct, n):
    fee, ra, rp, fix = fee_pct/100, ra_pct/100, rp_pct/100, 1.0
    base = P * (1-fee) - fix
    if n == 1:
        return {"n": 1, "parcela_aluno": round(P,2), "total_aluno": round(P,2),
                "comissao_base": round(base,2), "spread_liq": 0.0, "liquido": round(base,2)}
    pA = pmt(ra, n, P); pP = pmt(rp, n, P)
    pv_s = pv_annuity(rp, n, pA - pP)
    spread_liq = pv_s * (1-fee)
    return {"n": n, "parcela_aluno": round(pA,2), "total_aluno": round(pA*n,2),
            "comissao_base": round(base,2), "spread_liq": round(spread_liq,2),
            "liquido": round(base + spread_liq, 2)}

def calc_hubla(P, mdr_pct, fix, ra_pct, rep_pct, n):
    mdr, ra, rep = mdr_pct/100, ra_pct/100, rep_pct/100
    base = P*(1-mdr)-fix
    parcela = pmt(ra, n, P)
    juros = parcela*n - P
    liq = base + juros*rep
    return {"n": n, "parcela_aluno": round(parcela,2), "total_aluno": round(parcela*n,2),
            "juros_total": round(juros,2), "repasse": round(juros*rep,2),
            "liquido": round(liq,2), "taxa_efetiva": round((P-liq)/P*100,2)}

def calc_gateway(P, mdr_n_pct, fix, n):
    ra = GW_IMPLICIT_RATES[n-1]/100
    mdr = mdr_n_pct/100
    parcela = pmt(ra, n, P)
    total = parcela*n
    liq = total*(1-mdr)-fix
    return {"n": n, "parcela_aluno": round(parcela,2), "total_aluno": round(total,2),
            "juros_total": round(total-P,2), "liquido": round(liq,2),
            "custo_efetivo": round((P-liq)/P*100,2)}

# ── Modelos de request ─────────────────────────────────────────────────────────

class HotmartReq(BaseModel):
    preco: float
    taxa_plataforma: float = 7.9
    taxa_d30_produtor: float = 2.99
    taxa_parcelamento_aluno: float = 3.49

class HublaReq(BaseModel):
    preco: float
    mdr: float = 5.99
    taxa_fixa: float = 2.49
    repasse_pct: float = 25.0
    taxa_juros_aluno: float = 3.19

class GatewayReq(BaseModel):
    preco: float
    mdr_por_parcela: List[float] = [3.32,4.98,5.73,6.48,7.24,7.99,8.99,9.74,10.49,11.25,12.00,12.75]
    taxa_fixa: float = 0.49

class ComparativoReq(BaseModel):
    preco: float
    # Hotmart
    hm_taxa_plataforma: float = 7.9
    hm_taxa_d30_produtor: float = 2.99
    hm_taxa_parcelamento_aluno: float = 3.49
    # Hubla (opcional)
    hb_mdr: Optional[float] = None
    hb_taxa_fixa: float = 2.49
    hb_repasse_pct: float = 25.0
    hb_taxa_juros_aluno: float = 3.19
    # Gateway (opcional)
    gw_mdr_por_parcela: Optional[List[float]] = None
    gw_taxa_fixa: float = 0.49
    # Mix de parcelamento (opcional, para projeção anual)
    faturamento_anual: Optional[float] = None
    mix_cartao: Optional[List[float]] = None  # 12 valores somando 100
    pct_pix: float = 10.0
    pct_boleto: float = 0.7
    pct_cartao: float = 89.3

# ── Endpoints ──────────────────────────────────────────────────────────────────

@app.post("/hotmart", summary="Simula parcelamentos Hotmart (1x a 12x)")
def simular_hotmart(req: HotmartReq):
    tabela = [calc_hotmart(req.preco, req.taxa_plataforma, req.taxa_parcelamento_aluno,
                           req.taxa_d30_produtor, n) for n in range(1, 13)]
    liq1 = tabela[0]["liquido"]
    for r in tabela:
        r["vs_1x"] = round(r["liquido"] - liq1, 2)
    return {"preco": req.preco, "taxa_plataforma": req.taxa_plataforma,
            "taxa_d30_produtor": req.taxa_d30_produtor,
            "taxa_parcelamento_aluno": req.taxa_parcelamento_aluno,
            "spread_mensal": round(req.taxa_parcelamento_aluno - req.taxa_d30_produtor, 2),
            "tabela": tabela}

@app.post("/hubla", summary="Simula parcelamentos Hubla (1x a 12x)")
def simular_hubla(req: HublaReq):
    tabela = [calc_hubla(req.preco, req.mdr, req.taxa_fixa,
                         req.taxa_juros_aluno, req.repasse_pct, n) for n in range(1, 13)]
    liq1 = tabela[0]["liquido"]
    for r in tabela:
        r["vs_1x"] = round(r["liquido"] - liq1, 2)
    return {"preco": req.preco, "mdr": req.mdr, "taxa_fixa": req.taxa_fixa,
            "repasse_pct": req.repasse_pct, "tabela": tabela}

@app.post("/gateway", summary="Simula parcelamentos Gateway/PagarMe (1x a 12x)")
def simular_gateway(req: GatewayReq):
    if len(req.mdr_por_parcela) != 12:
        return {"erro": "mdr_por_parcela deve ter exatamente 12 valores"}
    tabela = [calc_gateway(req.preco, req.mdr_por_parcela[n-1], req.taxa_fixa, n)
              for n in range(1, 13)]
    liq1 = tabela[0]["liquido"]
    for r in tabela:
        r["vs_1x"] = round(r["liquido"] - liq1, 2)
    return {"preco": req.preco, "taxa_fixa": req.taxa_fixa,
            "mdr_por_parcela": req.mdr_por_parcela, "tabela": tabela}

@app.post("/comparativo", summary="Compara Hotmart vs Hubla vs Gateway com projeção anual opcional")
def comparativo(req: ComparativoReq):
    P = req.preco
    result = {"preco": P, "plataformas": {}}

    # Hotmart
    hm_tab = [calc_hotmart(P, req.hm_taxa_plataforma, req.hm_taxa_parcelamento_aluno,
                            req.hm_taxa_d30_produtor, n) for n in range(1, 13)]
    result["plataformas"]["hotmart"] = {"tabela": hm_tab}

    # Hubla
    if req.hb_mdr is not None:
        hb_tab = [calc_hubla(P, req.hb_mdr, req.hb_taxa_fixa,
                              req.hb_taxa_juros_aluno, req.hb_repasse_pct, n) for n in range(1, 13)]
        result["plataformas"]["hubla"] = {"tabela": hb_tab}

    # Gateway
    if req.gw_mdr_por_parcela is not None:
        gw_tab = [calc_gateway(P, req.gw_mdr_por_parcela[n-1], req.gw_taxa_fixa, n)
                  for n in range(1, 13)]
        result["plataformas"]["gateway"] = {"tabela": gw_tab}

    # Projeção anual
    if req.faturamento_anual and req.mix_cartao and len(req.mix_cartao) == 12:
        mix = req.mix_cartao
        weights = []
        for n in range(1, 13):
            if n == 1:
                w = (req.pct_cartao/100)*(mix[0]/100) + (req.pct_pix+req.pct_boleto)/100
            else:
                w = (req.pct_cartao/100)*(mix[n-1]/100)
            weights.append(w)

        n_vendas = req.faturamento_anual / P
        projecao = {}

        hm_avg = sum(hm_tab[n]["liquido"]*weights[n] for n in range(12))
        projecao["hotmart"] = {"liquido_medio": round(hm_avg,2),
                               "receita_anual": round(hm_avg*n_vendas,2),
                               "taxa_efetiva": round((P-hm_avg)/P*100,2)}

        if "hubla" in result["plataformas"]:
            hb_avg = sum(hb_tab[n]["liquido"]*weights[n] for n in range(12))
            projecao["hubla"] = {"liquido_medio": round(hb_avg,2),
                                 "receita_anual": round(hb_avg*n_vendas,2),
                                 "taxa_efetiva": round((P-hb_avg)/P*100,2)}

        if "gateway" in result["plataformas"]:
            gw_avg = sum(gw_tab[n]["liquido"]*weights[n] for n in range(12))
            projecao["gateway"] = {"liquido_medio": round(gw_avg,2),
                                   "receita_anual": round(gw_avg*n_vendas,2),
                                   "taxa_efetiva": round((P-gw_avg)/P*100,2)}

        # Ranking
        ranking = sorted(projecao.items(), key=lambda x: x[1]["receita_anual"], reverse=True)
        melhor = ranking[0]
        pior   = ranking[-1]
        projecao["diferenca_anual_melhor_vs_pior"] = round(
            melhor[1]["receita_anual"] - pior[1]["receita_anual"], 2)
        projecao["ranking"] = [r[0] for r in ranking]
        result["projecao_anual"] = projecao

    return result

@app.get("/health")
def health():
    return {"status": "ok", "version": "1.0.0"}
