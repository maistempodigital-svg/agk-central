#!/usr/bin/env python3
"""
Central AGK - robo da Meta (Instagram e Facebook), direto pela API oficial, sem intermediario.

  python meta.py contas    -> lista paginas do Facebook e Instagrams que a chave alcanca (dados/meta_contas.json)
  python meta.py publicar  -> publica SO o que o Adriano aprovou (fila/meta.json), quando o horario chegar
  python meta.py coletar   -> ultimos posts de cada Instagram (dados/meta_posts.json)

Chave: segredo META_TOKEN no GitHub (chave de usuario do app "Minha Secretaria").
A chave nunca e gravada em arquivo, log ou commit.
Sabado (sexta 15h ate sabado 20h, horario de Brasilia): nada e publicado.
"""
import json, os, re, sys, time, urllib.parse, urllib.request, urllib.error
from datetime import datetime, timezone, timedelta

PASTA = os.path.dirname(os.path.abspath(__file__))
API = "https://graph.facebook.com/v24.0/"
BRT = timezone(timedelta(hours=-3))

PROIBIDO = [
    (r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b", "expor CPF"),
    (r"\b(idiota|burro|imbecil|ot[aá]rio|vagabund)\w*", "ofensa"),
]


def agora():
    return datetime.now(timezone.utc)


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


def registrar(tipo, cliente, texto, ok=True):
    reg = ler("dados/registro.json", [])
    reg.insert(0, {"quando": agora().isoformat(timespec="seconds"), "tipo": tipo, "cliente": cliente, "texto": texto, "ok": ok, "onde": "nuvem"})
    gravar("dados/registro.json", reg[:300])


def sabado():
    """Sexta 15h ate sabado 20h (Brasilia): o Adriano e adventista, nada sai."""
    h = agora().astimezone(BRT)
    return (h.weekday() == 4 and h.hour >= 15) or (h.weekday() == 5 and h.hour < 20)


TOKEN = (os.environ.get("META_TOKEN") or "").strip()


def chamar(metodo, caminho, token=None, **params):
    params["access_token"] = token or TOKEN
    url, dados = API + caminho, None
    if metodo == "GET":
        url += "?" + urllib.parse.urlencode(params)
    else:
        dados = urllib.parse.urlencode({k: (json.dumps(v) if isinstance(v, (dict, list)) else v) for k, v in params.items()}).encode()
    for n in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, data=dados, method=metodo), timeout=120) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            try:
                corpo = json.load(e)
            except Exception:
                corpo = {"error": {"message": f"HTTP {e.code}"}}
            if e.code >= 500 and n < 2:
                time.sleep(15)
                continue
            return corpo
        except urllib.error.URLError as e:
            if n < 2:
                time.sleep(10)
                continue
            return {"error": {"message": f"sem conexao: {e}"}}


def erro_txt(r):
    e = (r or {}).get("error") or {}
    return (e.get("error_user_msg") or e.get("message") or str(r))[:300]


_paginas = None


def paginas():
    """Paginas que a chave alcanca, com a chave propria de cada pagina (so em memoria)."""
    global _paginas
    if _paginas is not None:
        return _paginas
    _paginas, depois = [], None
    for _ in range(10):
        extra = {"after": depois} if depois else {}
        r = chamar("GET", "me/accounts", fields="id,name,access_token,picture{url},instagram_business_account{id,username,profile_picture_url,followers_count}", limit=100, **extra)
        if "error" in r:
            raise RuntimeError("A Meta recusou a chave: " + erro_txt(r))
        _paginas += r.get("data", [])
        depois = (r.get("paging") or {}).get("cursors", {}).get("after") if (r.get("paging") or {}).get("next") else None
        if not depois:
            break
    return _paginas


def contas():
    if not TOKEN:
        registrar("erro", "meta", "Falta a chave META_TOKEN no cofre do GitHub.", ok=False)
        print("Sem META_TOKEN")
        return
    info = chamar("GET", "debug_token", input_token=TOKEN)
    d = (info or {}).get("data") or {}
    exp = d.get("expires_at") or d.get("data_access_expires_at")
    lista = []
    for p in paginas():
        ig = p.get("instagram_business_account") or {}
        lista.append({"page_id": p["id"], "nome": p.get("name"), "foto": ((p.get("picture") or {}).get("data") or {}).get("url"),
                      "ig_id": ig.get("id"), "ig_user": ig.get("username"), "ig_foto": ig.get("profile_picture_url"), "seguidores": ig.get("followers_count")})
    saida = {"atualizado": agora().isoformat(timespec="seconds"), "chave_valida": bool(d.get("is_valid", True)),
             "chave_expira": datetime.fromtimestamp(exp, timezone.utc).isoformat() if exp else None,
             "permissoes": d.get("scopes", []), "contas": lista}
    gravar("dados/meta_contas.json", saida)
    print("Contas:", len(lista), "| Instagram:", len([x for x in lista if x["ig_id"]]))


def esperar(cid, token):
    for _ in range(60):
        st = chamar("GET", cid, token, fields="status_code,status")
        if st.get("status_code") in ("FINISHED", "ERROR", "EXPIRED"):
            return st
        time.sleep(10)
    return {"status_code": "DEMOROU"}


def postar_ig(ig, token, item):
    tipo, midias, legenda = item["tipo"], item.get("midias", []), item.get("legenda", "")
    eh_video = lambda u: bool(re.search(r"\.(mp4|mov)(\?|$)", u, re.I))
    if tipo == "carrossel":
        filhos = []
        for u in midias[:10]:
            c = chamar("POST", f"{ig}/media", token, is_carousel_item="true", **({"media_type": "VIDEO", "video_url": u} if eh_video(u) else {"image_url": u}))
            if "id" not in c:
                raise RuntimeError("carrossel: " + erro_txt(c))
            if eh_video(u) and esperar(c["id"], token).get("status_code") != "FINISHED":
                raise RuntimeError("um video do carrossel nao processou")
            filhos.append(c["id"])
        c = chamar("POST", f"{ig}/media", token, media_type="CAROUSEL", children=",".join(filhos), caption=legenda)
    elif tipo == "reels":
        c = chamar("POST", f"{ig}/media", token, media_type="REELS", video_url=midias[0], caption=legenda, share_to_feed="true",
                   **({"thumb_offset": str(item["capa_ms"])} if item.get("capa_ms") else {}), **({"is_ai_generated": "true"} if item.get("ia") else {}))
    elif tipo == "story":
        u = midias[0]
        c = chamar("POST", f"{ig}/media", token, media_type="STORIES", **({"video_url": u} if eh_video(u) else {"image_url": u}))
    elif tipo == "imagem":
        c = chamar("POST", f"{ig}/media", token, image_url=midias[0], caption=legenda)
    else:
        raise RuntimeError("Instagram nao aceita post so de texto")
    if "id" not in c:
        raise RuntimeError(erro_txt(c))
    st = esperar(c["id"], token)
    if True:
        if st.get("status_code") != "FINISHED":
            raise RuntimeError("a Meta nao terminou de processar: " + str(st.get("status") or st.get("status_code")))
    p = chamar("POST", f"{ig}/media_publish", token, creation_id=c["id"])
    if "id" not in p:
        raise RuntimeError(erro_txt(p))
    info = chamar("GET", p["id"], token, fields="permalink")
    return {"id": p["id"], "link": info.get("permalink")}


def postar_fb(page, token, item):
    tipo, midias, legenda = item["tipo"], item.get("midias", []), item.get("legenda", "")
    if tipo == "imagem":
        r = chamar("POST", f"{page}/photos", token, url=midias[0], message=legenda)
    elif tipo == "carrossel":
        fotos = []
        for u in midias[:10]:
            f = chamar("POST", f"{page}/photos", token, url=u, published="false")
            if "id" not in f:
                raise RuntimeError("foto: " + erro_txt(f))
            fotos.append({"media_fbid": f["id"]})
        r = chamar("POST", f"{page}/feed", token, message=legenda, attached_media=fotos)
    elif tipo in ("reels", "video"):
        r = chamar("POST", f"{page}/videos", token, file_url=midias[0], description=legenda)
    elif tipo == "texto":
        r = chamar("POST", f"{page}/feed", token, message=legenda, **({"link": item["link"]} if item.get("link") else {}))
    elif tipo == "story":
        raise RuntimeError("story do Facebook ainda nao e feito pelo robo (so o do Instagram)")
    else:
        raise RuntimeError("tipo desconhecido: " + tipo)
    pid = r.get("post_id") or r.get("id")
    if not pid:
        raise RuntimeError(erro_txt(r))
    return {"id": pid, "link": f"https://www.facebook.com/{pid}"}


def publicar():
    if sabado():
        print("Sabado: nada sai ate sabado 20h.")
        return
    fila = ler("fila/meta.json", [])
    if not fila:
        print("Fila vazia")
        return
    if not TOKEN:
        registrar("erro", "meta", "Tem post aprovado, mas falta a chave META_TOKEN no cofre do GitHub.", ok=False)
        return
    feitas = ler("dados/meta_feitas.json", {})
    por_id = {p["id"]: p for p in paginas()}
    n = 0
    for item in fila:
        quando = item.get("quando")
        if quando and datetime.fromisoformat(quando.replace("Z", "+00:00")) > agora():
            continue
        for rede in item.get("redes", ["ig"]):
            chave = f"{item['id']}:{rede}"
            if feitas.get(chave, {}).get("ok") or feitas.get(chave, {}).get("tentativas", 0) >= 3:
                continue
            pg = por_id.get(str(item["page_id"]))
            try:
                if not pg:
                    raise RuntimeError("a chave nao alcanca essa pagina")
                for padrao, motivo in PROIBIDO:
                    if re.search(padrao, item.get("legenda", ""), re.I):
                        raise RuntimeError("legenda bloqueada: " + motivo)
                if rede == "ig":
                    ig = (pg.get("instagram_business_account") or {}).get("id")
                    if not ig:
                        raise RuntimeError("essa pagina nao tem Instagram profissional ligado")
                    res = postar_ig(ig, pg["access_token"], item)
                else:
                    res = postar_fb(pg["id"], pg["access_token"], item)
                feitas[chave] = {"ok": True, "quando": agora().isoformat(timespec="seconds"), **res}
                registrar("post", item.get("cliente", pg.get("name")), f"{'Instagram' if rede == 'ig' else 'Facebook'} ({item['tipo']}): {item.get('legenda', '')[:100]}")
                n += 1
            except Exception as e:
                t = feitas.get(chave, {}).get("tentativas", 0) + 1
                feitas[chave] = {"ok": False, "erro": str(e)[:300], "tentativas": t, "quando": agora().isoformat(timespec="seconds")}
                registrar("erro", item.get("cliente", "meta"), f"Post {'Instagram' if rede == 'ig' else 'Facebook'} falhou ({t}a tentativa): {e}", ok=False)
            gravar("dados/meta_feitas.json", feitas)
    print("Publicados:", n)


def coletar():
    if not TOKEN:
        return
    saida = {"atualizado": agora().isoformat(timespec="seconds"), "contas": {}}
    for p in paginas():
        ig = (p.get("instagram_business_account") or {}).get("id")
        if not ig:
            continue
        r = chamar("GET", f"{ig}/media", p["access_token"], fields="id,caption,media_type,media_product_type,thumbnail_url,media_url,permalink,timestamp,like_count,comments_count", limit=6)
        saida["contas"][p["id"]] = [{"id": m["id"], "texto": (m.get("caption") or "")[:140], "tipo": m.get("media_product_type") or m.get("media_type"),
                                    "img": m.get("thumbnail_url") or (m.get("media_url") if m.get("media_type") == "IMAGE" else None),
                                    "link": m.get("permalink"), "data": m.get("timestamp"), "curtidas": m.get("like_count"), "comentarios": m.get("comments_count")}
                                   for m in r.get("data", [])]
    gravar("dados/meta_posts.json", saida)
    c = ler("dados/meta_contas.json", {})
    gravar("dados/meta_painel.json", {"atualizado": c.get("atualizado"), "chave_expira": c.get("chave_expira"), "contas": [
        {"page_id": x["page_id"], "nome": (x["nome"] or "").strip(), "ig_user": x["ig_user"], "seguidores": x["seguidores"],
         "posts": [{"link": m["link"], "data": (m["data"] or "")[:10], "curtidas": m["curtidas"], "comentarios": m["comentarios"], "tipo": m["tipo"], "texto": m["texto"][:60]}
                   for m in saida["contas"].get(x["page_id"], [])[:3]]} for x in c.get("contas", [])]})
    print("Posts lidos de", len(saida["contas"]), "Instagrams")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    {"contas": contas, "publicar": publicar, "coletar": coletar}.get(cmd, lambda: print(__doc__))()
