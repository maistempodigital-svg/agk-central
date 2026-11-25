"""
Filtro de seguranca da Central AGK: nada sai fora das regras do Google e da Meta.
Usado pelo robo do Google (gmb.py) e pelo robo da Meta (meta.py) antes de publicar.

Cada regra: (padrao, motivo, onde) onde = "todos", "google" ou "meta".
Se o texto bater em alguma regra, o item NAO e publicado e vira "erro" com o motivo.
"""
import re

REGRAS = [
    # Google: politicas de avaliacoes e conteudo
    (r"(desconto|brinde|cupom|pr[eê]mio|sorteio|pix|dinheiro|gr[aá]tis)[^.!?\n]{0,40}(avalia|estrel)|(avalia|estrel)[^.!?\n]{0,40}(desconto|brinde|cupom|pr[eê]mio|sorteio|em troca)", "oferecer algo em troca de avaliacao", "todos"),
    (r"(mud|alter|tir|remov|apag|exclu)\w*\s+(a\s+|sua\s+)?(avalia|nota|estrel|coment)", "pedir para mudar ou apagar avaliacao", "todos"),
    (r"(parceir|certificad|recomendad|aprovad|oficial)\w*\s+(d[oa]\s+|pelo\s+)?(google|meta|facebook|instagram)", "dizer que e parceiro ou aprovado pelo Google/Meta", "todos"),
    # Dados pessoais e ofensas
    (r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b", "expor CPF", "todos"),
    (r"\b(idiota|burro|imbecil|ot[aá]rio|lixo|vagabund|mentiros)\w*", "ofensa", "todos"),
    # Saude: promessa de cura e resultado garantido (Google e Meta proibem)
    (r"\b(cura|curar|curamos|cur[ae]m)\b[^.!?\n]{0,30}(definitiv|garantid|100|total|para sempre)|\bcura garantida\b", "prometer cura", "todos"),
    (r"\b(resultado|emagrecimento|perda de peso)\s+garantid", "prometer resultado garantido", "todos"),
    (r"\b(perca|emagre[çc]a|elimine)\s+\d+\s*(kg|quilos)", "promessa de perda de peso", "meta"),
    # Meta: atributos pessoais (ex.: "voce tem dor nas costas?" em anuncio e proibido)
    (r"\bvoc[eê]\s+(tem|sofre de|est[aá] com)\s+(depress|ansiedad|diabet|c[aâ]ncer|obesidad|d[ií]vida)", "afirmar condicao pessoal de quem le", "meta"),
    # Golpes e enganacao
    (r"\b(ganhe|ganhar)\s+r\$\s*\d+[^.!?\n]{0,20}(por dia|sem fazer nada|f[aá]cil)", "promessa de dinheiro facil", "todos"),
    (r"(clique|toque)\s+(aqui\s+)?para\s+(ganhar|receber)\s+(pr[eê]mio|dinheiro)", "isca de clique", "todos"),
]

LIMITE_HASHTAGS = 5          # Meta: mais que isso parece spam
LIMITE_LEGENDA_IG = 2200     # limite do Instagram
LIMITE_POST_GOOGLE = 1500    # limite do Google


def checar(texto, onde="todos"):
    """Devolve o motivo do bloqueio ou None se pode publicar."""
    t = texto or ""
    for padrao, motivo, alvo in REGRAS:
        if alvo in ("todos", onde) and re.search(padrao, t, re.I):
            return motivo
    if onde == "meta":
        if len(re.findall(r"#\w+", t)) > LIMITE_HASHTAGS:
            return f"mais de {LIMITE_HASHTAGS} hashtags"
        if len(t) > LIMITE_LEGENDA_IG:
            return "legenda maior que 2.200 letras"
    if onde == "google" and len(t) > LIMITE_POST_GOOGLE:
        return "texto maior que 1.500 letras"
    return None


# Limites de seguranca para nao bloquear contas (quantas acoes por cliente)
LIMITES = {
    "google_perfil_dia": 1,      # alteracoes no perfil por dia
    "google_perfil_semana": 3,   # alteracoes no perfil por semana
    "google_foto_dia": 5,        # fotos novas por dia
    "google_post_dia": 1,        # posts no Google por dia
    "meta_post_dia": 3,          # posts por conta do Instagram por dia
}
