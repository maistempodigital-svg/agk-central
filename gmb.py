#!/usr/bin/env python3
"""
Central AGK - robo do Google Meu Negocio (so Python puro, nada para instalar).

  python gmb.py coletar   -> le perfis, avaliacoes e posts e grava dados/google.json
  python gmb.py publicar  -> publica SO o que o Adriano aprovou (fila/aprovadas.json)

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
            msg = e.read().decode()[:300]
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
        except Exception as e:
            item["erro"] = str(e)
            registrar("erro", c["chave"], f"Nao consegui ler o perfil: {e}", ok=False)
        saida["clientes"].append(item)
    gravar("dados/google.json", saida)
    novas = sum(len(x.get("sem_resposta", [])) for x in saida["clientes"] if x["ativo"])
    registrar("rodada", "todos", f"{len(saida['clientes'])} perfis lidos, {novas} avaliacoes sem resposta nos clientes ativos")
    print("Coleta ok:", novas, "sem resposta")


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
            feitas[item["id"]] = {"ok": True, "quando": agora()}
            n += 1
        except Exception as e:
            tent = feitas.get(item["id"], {}).get("tentativas", 0) + 1
            feitas[item["id"]] = {"ok": False, "erro": str(e), "tentativas": tent, "quando": agora()}
            registrar("erro", item["chave"], f"Falhou ({tent}a tentativa): {e}", ok=False)
    gravar("dados/feitas.json", feitas)
    print("Publicados:", n)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "coletar":
        coletar()
    elif cmd == "publicar":
        publicar()
    else:
        print(__doc__)
