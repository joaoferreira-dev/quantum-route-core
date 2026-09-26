# Integração

## Escolha da interface

Sistemas externos usam HTTP; aplicações Python podem importar o core. A CLI apoia diagnóstico e experimentos. Nenhuma integração precisa invocar a CLI para calcular uma rota.

No modo `road` (default), informe depósito e entregas em latitude/longitude, demandas inteiras positivas e veículos com capacidade inteira positiva. O perfil comum é `driving-car`; o objetivo é tempo ou distância ao longo dos caminhos viários mais rápidos. As capacidades não representam automaticamente restrições físicas de caminhões.

O [pedido de exemplo](../examples/http/road-request.json) usa pontos públicos e exige mais de um veículo. O backend omitido é `classical`; a seleção `exact` é explícita e limitada a 10 entregas. Não existe fallback para outro backend ou distância euclidiana.

## Endpoints

| Método e caminho | Uso |
| --- | --- |
| GET `/health` | Verificar API e acesso ao banco; não comprova worker ou provedor |
| GET `/v1/capabilities` | Consultar modos, backends, área e limites |
| POST `/v1/optimizations` | Criar job; retorna 202, cabeçalho Location e links |
| GET `/v1/optimizations/{job_id}` | Consultar estado, resultado e erros |
| POST `/v1/optimizations/{job_id}/cancel` | Cancelar job em fila ou solicitar cancelamento em execução |
| GET `/openapi.json` | Schemas de entrada, saída e erros |

Em rede, envie `Authorization: Bearer <token>`. O servidor associa o token a um integrador; acesso a job de outro integrador retorna 404. Configure HTTPS no proxy e proteja o host. Configure também `QROUTE_ALLOWED_HOSTS` com os nomes DNS explícitos do serviço para rejeitar hosts inesperados. Não há cadastro público ou emissão automática de tokens.

Use `Idempotency-Key` estável para repetir o mesmo pedido. A combinação integrador/chave identifica um único job enquanto ele for retido. Outro conteúdo com a mesma chave retorna 409. IDs de jobs não são mecanismos de autenticação.

## Estados

`queued → running → completed | failed`; cancelamento em fila produz `cancelled`. Durante execução, `cancel_requested` precede `cancelled`. Se conclusão já foi persistida, cancelar não a desfaz. Reinício do worker marca jobs interrompidos como falhos e preserva o snapshot, sem reexecutar automaticamente o solver.

O integrador deve consultar com intervalo moderado (por exemplo, um segundo) e parar ao chegar a um estado terminal. HTTP 202 confirma admissão, não resolução. Para enviar novamente após erro transitório como novo trabalho, use nova chave idempotente.

Separe três informações: estado do job, motivo de término do solver e estado do planejamento. Uma busca pode terminar por tempo com incumbente viável. `optimality_proven` é reservado à prova; `no_feasible_solution` não significa inviabilidade comprovada. Planejamento `ready` exige rotas validadas, métricas e geometria de todas as rotas; `partial` exige tratamento pelo integrador antes de despacho.

`objective_cost` é inteiro e recalculado sobre a matriz canônica. Distância/duração das direções podem diferir da matriz; divergências são informadas. GeoJSON usa `[longitude, latitude]`. `legs` seguem pares consecutivos de `ordered_stop_ids`; `unused_vehicle_ids` informa veículos ociosos.

## Erros e limites

400: JSON malformado; 401: token inválido; 403: serviço local; 404: job indisponível; 409: conflito idempotente; 413: payload excessivo; 422: entrada/configuração não suportada; 429: fila cheia; 503: admissão suspensa ou ORS não configurado.

Limites omitidos seguem o servidor. Um limite explícito pode reduzir, mas não aumentar o teto. Defaults de implantação: 15 entregas, 5 veículos, 100 jobs pendentes globais, 20 jobs ativos por integrador, 10 submissões por minuto, 32 MB de armazenamento retido por integrador, teto lógico global de 256 MB, snapshots até 4 MB, espera máxima de fila de 300 segundos e retenção de 24 horas após término. A admissão para quando há menos de 256 MB livres no disco. Excesso individual retorna 429 com `Retry-After`; indisponibilidade global de armazenamento retorna 503. Consulte capabilities e `.env.example`. Configure retenção conforme sensibilidade das coordenadas.

## Modos sem provedor

```json
{
  "mode": "matrix",
  "instance": {
    "depot": {"id": "d"},
    "customers": [{"id": "a", "demand": 1}],
    "vehicles": [{"id": "v", "capacity": 1}],
    "node_order": ["d", "a"],
    "cost_matrix": [[0, 10], [12, 0]]
  },
  "config": {"backend": "exact"}
}
```

`euclidean` exige coordenadas cartesianas `x/y`, sem matriz. Nenhum dos dois modos consulta ruas ou retorna geometria; seu `planning_status` é `not_applicable`.
