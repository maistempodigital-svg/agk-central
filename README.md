# Central AGK

Robô do Jarvis para o Google Meu Negócio dos clientes da AGK Vendas.

- `gmb.py coletar`: lê perfis, avaliações e posts e grava em `dados/`.
- `gmb.py publicar`: publica só o que o Adriano aprovou (`fila/aprovadas.json`).
- Roda grátis no GitHub Actions 3x por dia (08:40, 12:40 e 18:40) e sempre que entra algo aprovado na fila.
- A chave do Google fica no segredo `GOOGLE_SEGREDOS` do repositório. Nunca neste código.
