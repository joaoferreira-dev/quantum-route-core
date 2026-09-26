# Provedor viário e avaliação

Decisão da SPEC: openrouteservice Standard gratuito para avaliar o município de São Paulo, perfil `driving-car`, sem trânsito em tempo real. Data deste registro: 25/09/2026. Não houve medição real nesta rodada nem confirmação contratual atual das quotas.

O adaptador usa Snap, Matrix e Directions. A distribuição de frota é feita pelo OR-Tools. Limites locais conservadores estão em `.env.example`; eles não garantem quota disponível se a mesma chave for usada em outros sistemas. Retries também consomem quota. Cache fica desligado até confirmar condições de armazenamento; TTL e uso precisam ser habilitados explicitamente.

Fontes para conferência pelo operador antes da execução: [restrições ORS](https://openrouteservice.org/restrictions/), [documentação da API](https://giscience.github.io/openrouteservice/api-reference/), [malha municipal IBGE](https://servicodados.ibge.gov.br/api/v3/malhas/municipios/3550308?formato=application/vnd.geo+json&qualidade=maxima). O polígono distribuído em `src/quantum_route_core/data/sao-paulo.geojson` é usado com inclusão da fronteira; a área restringe pontos atendidos, não recorta trajetos.

## Avaliação preparada

O diretório `examples/road-scenarios/` contém 15 pedidos fixos: 5/10/15 entregas × 1–5 veículos. Foram gerados por `scripts/generate_road_scenarios.py`, com demandas unitárias e capacidades diferentes quando há mais de um veículo. Todos os pontos passaram pela validação do polígono municipal. São candidatos sintéticos; nenhuma acessibilidade viária foi certificada. Execute cada cenário separadamente com o runner, selecionando um diretório de saída novo por cenário/regime.

O runner `scripts/benchmark_road.py` recebe um pedido fixo, repetições e regime de cache, informa orçamento conservador e só faz chamadas com `--execute`. Salva pedidos, resultados, resumo e métricas por fase. Sem `--execute`, apenas prepara o plano local. Nunca publique resultados simulados como evidência real.

Antes das medições, defina orçamento, tempo aceitável e concorrência. Use cenários de 5, 10 e 15 entregas, de 1 a 5 veículos, capacidades diferentes e pontos públicos/minimizados de todas as regiões da capital. Confira pontos no polígono e reveja a qualidade do snapping. A lista de pontos precisa ser validada nas ruas; coordenadas sintéticas não garantem acesso.

```sh
uv run python scripts/benchmark_road.py examples/http/road-request.json --repetitions 3
# Após configurar ORS_API_KEY e aceitar o consumo informado:
uv run python scripts/benchmark_road.py examples/http/road-request.json --repetitions 3 --execute
```

Cache frio usa `off`; cache quente precisa de TTL positivo e `--cache use`, e deve registrar aquecimento separadamente. Colete p50/p95, tamanho amostral, taxa de sucesso, chamadas, erros e verificação visual. Poucas amostras não estabelecem SLA. Revise sentidos únicos, travessias de rios, limites municipais e pontos sem acesso; não descarte as falhas dos relatórios.

## Aceitação ainda pendente

- Rotas reais em múltiplos veículos com visita única, capacidade, ordem e retorno ao depósito.
- Inspeção no visualizador e comparação entre matriz e métricas das direções.
- Confirmação das condições de exibição, cache, atribuição, quotas e orçamento mensal.
- Medições de desempenho e volume aceitável documentadas.

Google Routes e OSRM próprio permanecem alternativas futuras mediante decisão explícita. A etapa estadual exige nova avaliação com interior, litoral e trajetos intermunicipais.
