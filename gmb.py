#!/usr/bin/env python3
"""
Central AGK - robo do Google Meu Negocio (so Python puro, nada para instalar).

  python gmb.py coletar   -> le perfis, avaliacoes e posts e grava dados/google.json
  python gmb.py publicar  -> publica SO o que o Adriano aprovou (fila/aprovadas.json)
  python gmb.py ranking [chave] -> mede a posicao no mapa (Places API, chave PLACES_KEY)

Chaves: variavel GOOGLE_SEGREDOS (o conteudo do segredos.json) ou o arquivo segredos.json ao lado.
Nada aqui escreve texto sozinho: quem escreve as respostas e o Claude, e so sai o que foi aprovado.
"""
import json, os, re, sys, time, urllib.parse, urllib.request, urllib.error
from datetime import datetime, timezone

PASTA = os.path.dirname(os.path.abspath(__file__))
ESTRELAS = {"ONE": 1, "TWO": 2, "THREE": 3, "FOUR": 4, "FIVE": 5}

PROIBIDO = [
    (r"(desconto|brinde|cupom|pr[eê]mio|sorteio|pix|dinheiro|gr[aá]tis)[^.!?\n]{0,40}(avalia|estrel)|(avalia|estrel)[^.!?\n]{0,40}(desconto|brinde|cupom|pr[eê]mio|sorteio|em troca)", "oferecer algo em troca de avaliacao"),
    (r"(mud|alter|tir|remov|apag|exclu)\w*\s+(a\s+|sua\s+)?(avalia|nota|estrel|coment)", "pedir para mudar ou apagar a avaliacao"),
    (r"(parceir|certificad|recomendad|aprovad|oficial)\w*\s+(d[oa]\s+|pelo\s+)?google", "dizer que e parceiro do Google"),
    (r"\b(idiota|burro|imbecil|ot[aá]rio|lixo|vagabund|mentiros)\w*", "ofender o cliente"),
    (r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b", "expor CPF"),
]


def agora():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def problema(texto):
    for padrao, motivo in PROIBIDO:
        if re.search(padrao, texto, re.I):
            return motivo
    return None


def ler(nome, padrao):
    p = os.path.join(PASTA, nome)
    if os.path.exists(p):
        with open(p, encoding="utf-8-sig") as f:
            return json.load(f)
    return padrao


def gravar(nome, dados):
    p = os.path.join(PASTA, nome)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=2)


def segredos():
    bruto = os.environ.get("GOOGLE_SEGREDOS")
    if bruto:
        return json.loads(bruto.strip().lstrip("﻿"))
    return ler("segredos.json", {})


def http(metodo, url, corpo=None, cab=None, form=False, tentativas=3):
    cab = dict(cab or {})
    dados = None
    if corpo is not None:
        if form:
            dados = urllib.parse.urlencode(corpo).encode()
            cab["Content-Type"] = "application/x-www-form-urlencoded"
        else:
            dados = json.dumps(corpo).encode()
            cab["Content-Type"] = "application/json"
    for n in range(tentativas):
        req = urllib.request.Request(url, data=dados, headers=cab, method=metodo)
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                t = r.read().decode()
                return json.loads(t) if t else {}
        except urllib.error.HTTPError as e:
            msg = e.read().decode()[:900]
            if e.code in (429, 500, 502, 503) and n < tentativas - 1:
                time.sleep(20 * (n + 1))
                continue
            raise RuntimeError(f"Google respondeu {e.code}: {msg}")
        except urllib.error.URLError as e:
            if n < tentativas - 1:
                time.sleep(10)
                continue
            raise RuntimeError(f"Sem conexao com o Google: {e}")


_token = None


def g(metodo, url, corpo=None):
    global _token
    if not _token:
        s = segredos()
        d = http("POST", "https://oauth2.googleapis.com/token", {
            "client_id": s["GOOGLE_CLIENT_ID"], "client_secret": s["GOOGLE_CLIENT_SECRET"],
            "refresh_token": s["GOOGLE_REFRESH_TOKEN"], "grant_type": "refresh_token"}, form=True)
        _token = d["access_token"]
    return http(metodo, url, corpo, {"Authorization": f"Bearer {_token}"})


def v4(c):
    return f"https://mybusiness.googleapis.com/v4/{c['conta']}/{c['local']}"


def avaliacao(r):
    return {"id": r["reviewId"], "autor": r.get("reviewer", {}).get("displayName", "Cliente"),
            "foto": r.get("reviewer", {}).get("profilePhotoUrl", ""),
            "nota": ESTRELAS.get(r.get("starRating"), 0), "texto": (r.get("comment") or "").split("(Translated by Google)")[0].strip(),
            "data": r.get("createTime", ""), "resposta": (r.get("reviewReply") or {}).get("comment")}


def registrar(tipo, chave, texto, ok=True):
    reg = ler("dados/registro.json", [])
    reg.insert(0, {"quando": agora(), "tipo": tipo, "cliente": chave, "texto": texto, "ok": ok,
                   "onde": os.environ.get("ONDE", "nuvem")})
    gravar("dados/registro.json", reg[:300])


def coletar():
    saida = {"atualizado": agora(), "clientes": []}
    for c in ler("clientes.json", []):
        item = {"chave": c["chave"], "nome": c["nome"], "ativo": c.get("ativo", False)}
        try:
            todas, pagina = [], None
            for _ in range(4):
                url = f"{v4(c)}/reviews?pageSize=50" + (f"&pageToken={urllib.parse.quote(pagina)}" if pagina else "")
                d = g("GET", url)
                item["media"], item["total"] = d.get("averageRating"), d.get("totalReviewCount")
                todas += [avaliacao(r) for r in d.get("reviews", [])]
                pagina = d.get("nextPageToken")
                if not pagina:
                    break
            item["sem_resposta"] = [a for a in todas if not a["resposta"]]
            item["recentes"] = todas[:15]
            try:
                p = g("GET", f"{v4(c)}/localPosts?pageSize=10")
                item["posts"] = [{"id": x["name"].split("/")[-1], "texto": x.get("summary", ""), "data": x.get("createTime", ""),
                                  "link": x.get("searchUrl"), "foto": (x.get("media") or [{}])[0].get("googleUrl")}
                                 for x in p.get("localPosts", [])]
            except RuntimeError as e:
                item["posts"], item["erro_posts"] = [], str(e)
            if item["ativo"]:
                for nome, fn in (("perfil", perfil), ("fotos", fotos)):
                    try:
                        item[nome] = fn(c)
                    except Exception as e:
                        item["erro_" + nome] = str(e)
                item["_todas"] = todas
                item["saude"] = saude(item, ler("dados/ranking.json", {}).get(c["chave"]))
                item.pop("_todas")
                item["evolucao"] = historico(item)
                item["novas_30d"] = len([a for a in todas if dias_desde(a["data"]) <= 30])
        except Exception as e:
            item["erro"] = str(e)
            registrar("erro", c["chave"], f"Nao consegui ler o perfil: {e}", ok=False)
        saida["clientes"].append(item)
    gravar("dados/google.json", saida)
    painel(saida)
    novas = sum(len(x.get("sem_resposta", [])) for x in saida["clientes"] if x["ativo"])
    registrar("rodada", "todos", f"{len(saida['clientes'])} perfis lidos, {novas} avaliacoes sem resposta nos clientes ativos")
    print("Coleta ok:", novas, "sem resposta")


def painel(saida):
    """Resumo pronto para o painel (google/estado). A tarefa do Claude so copia este arquivo."""
    cl = {c["chave"]: c for c in ler("clientes.json", [])}
    rk = ler("dados/ranking.json", {})
    cut = lambda t, n: (t or "")[:n]
    out = []
    for c in saida["clientes"]:
        o = {"chave": c["chave"], "nome": c["nome"], "ativo": c["ativo"], "media": round(c["media"], 1) if c.get("media") else None,
             "total": c.get("total"), "whatsapp": cl.get(c["chave"], {}).get("whatsapp"), "erro": c.get("erro")}
        if c["ativo"]:
            o["sem_resposta"] = [{"id": a["id"], "autor": a["autor"], "nota": a["nota"], "data": a["data"][:19], "texto": cut(a["texto"], 160)} for a in c.get("sem_resposta", [])]
            o["recentes"] = [{"autor": a["autor"], "nota": a["nota"], "data": a["data"][:19], "texto": cut(a["texto"], 150), "resposta": cut(a["resposta"], 220) or None} for a in c.get("recentes", [])[:6]]
            o["posts"] = [{"texto": cut(x["texto"], 160), "data": x["data"][:19], "link": x.get("link")} for x in c.get("posts", [])[:4]]
            p = c.get("perfil") or {}
            o["perfil"] = {k: p.get(k) for k in ["categoria", "categorias_extra", "telefone", "site", "dias_com_horario", "feriados", "status", "endereco", "area_atendida", "servicos", "mapa", "avaliar"]}
            o["perfil"]["descricao"] = cut(p.get("descricao"), 750)
            f = c.get("fotos") or {}
            o["fotos"] = {"total": f.get("total"), "ultima": f.get("ultima")}
            sd = c.get("saude")
            if sd:
                sd = dict(sd); sd["checks"] = [{k: v for k, v in x.items() if v is not None and k != "peso"} for x in sd["checks"]]
            o["saude"], o["evolucao"], o["novas_30d"] = sd, c.get("evolucao", [])[-8:], c.get("novas_30d")
            if c["chave"] in rk:
                r = rk[c["chave"]]
                o["ranking"] = {k: r.get(k) for k in ["em", "raio_km", "grade_n", "palavras"]}
                o["ranking"]["concorrentes"] = r.get("concorrentes", [])[:6]
                o["ranking"]["historico"] = r.get("historico", [])[-8:]
        out.append(o)
    gravar("dados/painel.json", {"atualizado": saida["atualizado"], "clientes": out})


def publicar():
    fila = ler("fila/aprovadas.json", [])
    feitas = ler("dados/feitas.json", {})
    clientes = {c["chave"]: c for c in ler("clientes.json", [])}
    n = 0
    for item in fila:
        if item["id"] in feitas and feitas[item["id"]].get("ok"):
            continue
        c = clientes.get(item["chave"])
        try:
            if not c:
                raise RuntimeError("cliente desconhecido")
            motivo = problema(item["texto"])
            if motivo:
                raise RuntimeError(f"texto bloqueado: parece {motivo}")
            if item["tipo"] == "resposta":
                g("PUT", f"{v4(c)}/reviews/{urllib.parse.quote(item['review_id'], safe='')}/reply", {"comment": item["texto"]})
                registrar("resposta", item["chave"], f"Respondeu {item.get('autor', 'cliente')}: {item['texto'][:120]}")
            elif item["tipo"] == "post":
                corpo = {"languageCode": "pt-BR", "summary": item["texto"], "topicType": "STANDARD"}
                if c.get("whatsapp"):
                    corpo["callToAction"] = {"actionType": "LEARN_MORE", "url": f"https://wa.me/{c['whatsapp']}"}
                if item.get("foto"):
                    corpo["media"] = [{"mediaFormat": "PHOTO", "sourceUrl": item["foto"]}]
                g("POST", f"{v4(c)}/localPosts", corpo)
                registrar("post", item["chave"], f"Post publicado: {item['texto'][:120]}")
            elif item["tipo"] == "perfil":
                campo = item.get("campo", "descricao")
                mapa = {"descricao": ("profile.description", {"profile": {"description": item["texto"]}}),
                        "site": ("websiteUri", {"websiteUri": item["texto"]})}
                if campo not in mapa:
                    raise RuntimeError(f"campo do perfil nao suportado: {campo}")
                mask, corpo = mapa[campo]
                g("PATCH", f"{INFO}/{c['local']}?updateMask={mask}", corpo)
                registrar("perfil", item["chave"], f"Perfil atualizado ({campo}): {item['texto'][:120]}")
            feitas[item["id"]] = {"ok": True, "quando": agora()}
            n += 1
        except Exception as e:
            tent = feitas.get(item["id"], {}).get("tentativas", 0) + 1
            feitas[item["id"]] = {"ok": False, "erro": str(e), "tentativas": tent, "quando": agora()}
            registrar("erro", item["chave"], f"Falhou ({tent}a tentativa): {e}", ok=False)
    gravar("dados/feitas.json", feitas)
    print("Publicados:", n)


# ---------------------------------------------------------------- perfil, fotos e saude
INFO = "https://mybusinessbusinessinformation.googleapis.com/v1"
MASCARA = "title,categories,phoneNumbers,websiteUri,regularHours,specialHours,profile,latlng,openInfo,storefrontAddress,serviceArea,metadata,serviceItems"


def perfil(c):
    d = g("GET", f"{INFO}/{c['local']}?readMask={MASCARA}")
    cat = d.get("categories", {})
    horas = (d.get("regularHours") or {}).get("periods", [])
    end = d.get("storefrontAddress") or {}
    return {
        "titulo": d.get("title"), "categoria": (cat.get("primaryCategory") or {}).get("displayName"),
        "categorias_extra": [x.get("displayName") for x in cat.get("additionalCategories", [])],
        "telefone": (d.get("phoneNumbers") or {}).get("primaryPhone"), "site": d.get("websiteUri"),
        "descricao": (d.get("profile") or {}).get("description", ""),
        "dias_com_horario": len({p.get("openDay") for p in horas}), "feriados": bool((d.get("specialHours") or {}).get("specialHourPeriods")),
        "status": (d.get("openInfo") or {}).get("status"), "latlng": d.get("latlng"),
        "endereco": ", ".join(filter(None, [" ".join(end.get("addressLines", [])), end.get("sublocality"), end.get("locality")])),
        "area_atendida": len(((d.get("serviceArea") or {}).get("places") or {}).get("placeInfos", [])),
        "servicos": len(d.get("serviceItems", [])),
        "place_id": (d.get("metadata") or {}).get("placeId"), "mapa": (d.get("metadata") or {}).get("mapsUri"),
        "avaliar": (d.get("metadata") or {}).get("newReviewUri"),
    }


def fotos(c):
    d = g("GET", f"{v4(c)}/media?pageSize=100")
    itens = d.get("mediaItems", [])
    datas = sorted([m.get("createTime", "") for m in itens], reverse=True)
    return {"total": d.get("totalMediaItemCount", len(itens)), "ultima": datas[0] if datas else None,
            "recentes": [{"url": m.get("thumbnailUrl") or m.get("googleUrl"), "data": m.get("createTime")} for m in itens[:6]]}


def dias_desde(iso):
    if not iso:
        return 9999
    try:
        return (datetime.now(timezone.utc) - datetime.fromisoformat(iso.replace("Z", "+00:00"))).days
    except Exception:
        return 9999


def saude(item, rk):
    """Mesmas 5 areas do Avalia+: reputacao, atividade, perfil, visibilidade, concorrencia."""
    chk = []
    def ck(area, ok, peso, titulo, detalhe=None, acao=None):
        chk.append({"area": area, "ok": ok, "peso": peso, "titulo": titulo, "detalhe": detalhe if ok is not True else None, "acao": acao if ok is not True else None})
    nota, total = round(item.get("media") or 0, 1), item.get("total") or 0
    todas = item.get("_todas", [])
    neg = [a for a in todas if a["nota"] and a["nota"] <= 3 and not a["resposta"]]
    novas = len([a for a in todas if dias_desde(a["data"]) <= 30])
    conc = (rk or {}).get("concorrentes", [])[:3]
    lider = max([x.get("total") or 0 for x in conc] + [0])
    ck("reputacao", nota >= 4.5, 9, f"Nota {str(nota).replace('.', ',')}" + (": excelente" if nota >= 4.5 else ": abaixo de 4,5"), "Notas abaixo de 4,5 fazem muita gente escolher o concorrente.", "Pedir avaliações a clientes satisfeitos")
    meta = max(50, lider)
    ck("reputacao", total >= meta, 10, f"{total} avaliações", f"O 1º da região tem {lider}: faltam {lider - total}." if lider > total else f"Meta inicial: 50 (faltam {max(0, 50 - total)}).", "Pedir avaliações agora")
    ck("reputacao", not neg, 8, f"{len(neg)} avaliação(ões) de 1 a 3 estrelas sem resposta" if neg else "Nenhuma avaliação negativa sem resposta", "Responda com calma: quem lê a resposta decide se confia.", "Responder as negativas")
    ck("atividade", novas >= 4, 9, f"{novas} avaliação(ões) nova(s) no último mês", "O Google favorece perfis que recebem avaliações toda semana. Meta: 1 por semana.", "Pedir avaliações esta semana")
    posts = item.get("posts") or []
    ult_post = dias_desde(posts[0]["data"]) if posts else 9999
    ck("atividade", ult_post <= 7, 8, "Postou nos últimos 7 dias" if ult_post <= 7 else (f"Último post há {ult_post} dias" if posts else "Nenhum post no Google"), "Postar 1 vez por semana mostra ao Google que a empresa está ativa.", "Criar post")
    f = item.get("fotos") or {}
    ult_foto = dias_desde(f.get("ultima"))
    ck("atividade", ult_foto <= 30, 4, "Foto nova no último mês" if ult_foto <= 30 else "Nenhuma foto nova há mais de 1 mês", "Fotos novas todo mês ajudam no ranking e nos cliques.", "Postar fotos novas")
    p = item.get("perfil")
    if p:
        ck("perfil", bool(p.get("categoria")), 7, f"Categoria: {p.get('categoria')}" if p.get("categoria") else "Sem categoria principal", "A categoria é o fator nº 1 para aparecer nas buscas.", "Arrumar categoria")
        ck("perfil", len(p.get("categorias_extra") or []) >= 2, 3, f"{len(p.get('categorias_extra') or [])} categoria(s) extra", "Categorias extras certas fazem aparecer em mais buscas.", "Adicionar categorias")
        ck("perfil", p.get("dias_com_horario", 0) >= 5, 6, "Horário de funcionamento completo" if p.get("dias_com_horario", 0) >= 5 else "Horário incompleto", "Sem horário, o Google mostra menos a empresa.", "Arrumar horário")
        ck("perfil", p.get("feriados"), 2, "Horário de feriados cadastrado" if p.get("feriados") else "Sem horário de feriados", "O Google valoriza quem informa feriados.", "Cadastrar feriados")
        ck("perfil", bool(p.get("telefone")), 5, "Telefone cadastrado" if p.get("telefone") else "Sem telefone", "Muitos clientes ligam direto pelo Google.", "Cadastrar telefone")
        site = p.get("site") or ""
        real = bool(site) and not re.search(r"instagram|facebook|wa\.me|whatsapp|linktr", site, re.I)
        ck("perfil", real, 5, "Tem site próprio" if real else ("O site é rede social/WhatsApp" if site else "Sem site"), "Site próprio aumenta a confiança e a relevância.", "Colocar o site")
        dl = len(p.get("descricao") or "")
        ck("perfil", dl >= 250, 4, "Descrição completa" if dl >= 250 else (f"Descrição curta ({dl} letras)" if dl else "Sem descrição"), "Diga o que faz, para quem e em qual bairro, com as palavras-chave.", "Reescrever descrição")
        ck("perfil", f.get("total", 0) >= 10, 6, f"{f.get('total', 0)} fotos no perfil", "Perfis com muitas fotos recebem mais cliques e rotas.", "Postar fotos")
        ck("perfil", p.get("servicos", 0) >= 3, 3, f"{p.get('servicos', 0)} serviço(s) cadastrados", "Serviços cadastrados ajudam o Google a entender o que você faz.", "Cadastrar serviços")
        if p.get("status") == "CLOSED_TEMPORARILY":
            ck("perfil", False, 10, "Aparece como FECHADO TEMPORARIAMENTE", "Isso derruba quase todas as buscas.", "Reabrir o perfil")
    res = (rk or {}).get("palavras", [])
    if res:
        for r in res:
            pts = [min(x if x else 21, 21) for x in r["grade"]]
            top3 = round(100 * len([x for x in pts if x <= 3]) / len(pts))
            ck("visibilidade", top3 >= 50, 8, f"{top3}% da região no top 3 para “{r['palavra']}”", f"Posição média {sum(pts) / len(pts):.1f}".replace(".", ","), "Melhorar posição no mapa")
    else:
        ck("visibilidade", None, 5, "Posição no mapa ainda não medida", None, "Medir posição")
    if conc:
        mn = sum((x.get("nota") or 0) for x in conc) / len(conc)
        mt = sum((x.get("total") or 0) for x in conc) / len(conc)
        ck("concorrencia", nota >= mn, 5, f"Nota {nota} × média dos 3 primeiros {mn:.1f}".replace(".", ","))
        ck("concorrencia", total >= mt, 6, f"{total} avaliações × média dos 3 primeiros {round(mt)}", "Diminuir a diferença em avaliações.", "Pedir avaliações")
    else:
        ck("concorrencia", None, 4, "Concorrentes ainda não analisados", None, "Ver concorrentes")

    def nota_area(a):
        if a == "reputacao":
            n = max(0, min(1, (nota - 3.5) / 1.5)) * 60
            v = min(1, total / lider) * 40 if lider else min(40, (__import__("math").log10(total + 1) / __import__("math").log10(301)) * 40)
            return round(max(0, n + v - min(15, len(neg) * 5)))
        if a == "atividade":
            return round(min(100, novas / 8 * 100) * 0.6 + (40 if ult_post <= 7 else 20 if ult_post <= 30 else 0))
        if a == "visibilidade":
            if not res:
                return None
            pts = [min(x if x else 21, 21) for r in res for x in r["grade"]]
            return round(len([x for x in pts if x <= 3]) / len(pts) * 60 + (1 - min(sum(pts) / len(pts), 20) / 20) * 40)
        if a == "concorrencia":
            if not conc:
                return None
            mn = sum((x.get("nota") or 0) for x in conc) / len(conc) or 1
            mt = sum((x.get("total") or 0) for x in conc) / len(conc) or 1
            return round(min(1, nota / mn) * 50 + min(1, total / mt) * 50)
        l = [x for x in chk if x["area"] == a and x["ok"] is not None]
        tot = sum(x["peso"] for x in l)
        return round(100 * sum(x["peso"] for x in l if x["ok"]) / tot) if tot else None
    nomes = {"reputacao": "Reputação", "atividade": "Atividade", "perfil": "Perfil completo", "visibilidade": "Visibilidade", "concorrencia": "Concorrência"}
    areas = [{"id": a, "nome": n, "nota": nota_area(a)} for a, n in nomes.items()]
    val = [a["nota"] for a in areas if a["nota"] is not None]
    plano = sorted([x for x in chk if x["ok"] is False and x["acao"]], key=lambda x: -x["peso"]) + sorted([x for x in chk if x["ok"] is None and x["acao"]], key=lambda x: -x["peso"])
    return {"geral": round(sum(val) / len(val)) if val else 0, "areas": areas, "checks": chk,
            "plano": [{"titulo": x["titulo"], "detalhe": x["detalhe"], "acao": x["acao"]} for x in plano[:6]]}


def historico(item):
    h = ler("dados/historico.json", {})
    sem = datetime.now(timezone.utc).strftime("%G-S%V")
    lst = [x for x in h.get(item["chave"], []) if x["semana"] != sem]
    lst.append({"semana": sem, "media": round(item.get("media") or 0, 1), "total": item.get("total"), "saude": (item.get("saude") or {}).get("geral"),
                "fotos": (item.get("fotos") or {}).get("total"), "posts30": len([p for p in item.get("posts") or [] if dias_desde(p["data"]) <= 30])})
    h[item["chave"]] = lst[-26:]
    gravar("dados/historico.json", h)
    return h[item["chave"]]


# ---------------------------------------------------------------- ranking (Places API)
def places_busca(chave_api, texto, lat, lng, raio_m):
    return _places("POST", "https://places.googleapis.com/v1/places:searchText",
                {"textQuery": texto, "languageCode": "pt-BR", "regionCode": "BR", "pageSize": 20,
                 "locationBias": {"circle": {"center": {"latitude": lat, "longitude": lng}, "radius": raio_m}}},
                {"X-Goog-Api-Key": chave_api, "X-Goog-FieldMask": "places.id,places.displayName,places.rating,places.userRatingCount,places.googleMapsUri,places.formattedAddress"}).get("places", [])


def _places(*a):
    try:
        return http(*a)
    except Exception as e:
        raise RuntimeError(f"[places] {e}")


def ranking(so=None):
    chave_api = os.environ.get("PLACES_KEY") or segredos().get("PLACES_KEY")
    if not chave_api:
        registrar("erro", "todos", "Ranking não medido: falta a chave PLACES_KEY no GitHub.", ok=False)
        print("Sem PLACES_KEY")
        return
    import math
    chave_api = chave_api.strip()
    print("Chave Places: tamanho", len(chave_api), "| formato de chave de API:", chave_api.startswith("AIza"))
    tudo = ler("dados/ranking.json", {})
    for c in ler("clientes.json", []):
        if not c.get("ativo") or not c.get("ranking") or (so and c["chave"] != so):
            continue
        try:
            try:
                p = perfil(c)
            except Exception as e:
                raise RuntimeError(f"[perfil] {e}")
            meu = p.get("place_id")
            if p.get("latlng"):
                lat, lng = p["latlng"]["latitude"], p["latlng"]["longitude"]
            else:
                loc = http("GET", f"https://places.googleapis.com/v1/places/{meu}", None, {"X-Goog-Api-Key": chave_api, "X-Goog-FieldMask": "location"})["location"]
                lat, lng = loc["latitude"], loc["longitude"]
            cfg = c["ranking"]; n = cfg.get("grade", 5); raio = cfg.get("raio_km", 3)
            passo = (2 * raio) / (n - 1)
            pontos = [(lat + (raio - i * passo) / 111.0, lng + (-raio + j * passo) / (111.0 * math.cos(math.radians(lat)))) for i in range(n) for j in range(n)]
            saida = {"em": agora(), "centro": {"lat": lat, "lng": lng}, "raio_km": raio, "grade_n": n, "palavras": [], "concorrentes": []}
            vistos = {}
            for palavra in cfg["palavras"]:
                grade = []
                for (a, b) in pontos:
                    res = places_busca(chave_api, palavra, a, b, max(500, passo * 1000))
                    pos = next((k + 1 for k, x in enumerate(res) if x.get("id") == meu), None)
                    grade.append(pos)
                    for k, x in enumerate(res[:5]):
                        if x.get("id") == meu:
                            continue
                        v = vistos.setdefault(x["id"], {"nome": x.get("displayName", {}).get("text"), "nota": x.get("rating"), "total": x.get("userRatingCount"),
                                                        "link": x.get("googleMapsUri"), "endereco": x.get("formattedAddress"), "vezes": 0, "soma": 0})
                        v["vezes"] += 1; v["soma"] += k + 1
                    time.sleep(0.2)
                saida["palavras"].append({"palavra": palavra, "grade": grade})
            conc = sorted(vistos.values(), key=lambda v: (-v["vezes"], v["soma"] / v["vezes"]))[:8]
            for v in conc:
                v["pos_media"] = round(v.pop("soma") / v["vezes"], 1)
            saida["concorrentes"] = conc
            hist = tudo.get(c["chave"], {}).get("historico", [])
            for r in saida["palavras"]:
                pts = [min(x or 21, 21) for x in r["grade"]]
                hist.append({"em": saida["em"][:10], "palavra": r["palavra"], "media": round(sum(pts) / len(pts), 1), "top3": round(100 * len([x for x in pts if x <= 3]) / len(pts))})
            saida["historico"] = hist[-40:]
            tudo[c["chave"]] = saida
            registrar("ranking", c["chave"], "Ranking medido: " + ", ".join(f"{h['palavra']} média {h['media']}" for h in hist[-len(cfg['palavras']):]))
        except Exception as e:
            registrar("erro", c["chave"], f"Ranking falhou: {e}", ok=False)
            print("ERRO RANKING", c["chave"], e)
    gravar("dados/ranking.json", tudo)
    print("Ranking ok")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "coletar":
        coletar()
    elif cmd == "publicar":
        publicar()
    elif cmd == "ranking":
        ranking(sys.argv[2] if len(sys.argv) > 2 else None)
    else:
        print(__doc__)
