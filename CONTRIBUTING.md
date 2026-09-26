# Contribuindo

Obrigado por ajudar a melhorar o Quantum Route Core. Para mudanças maiores, abra uma issue ou discussão antes de começar, para alinhar o escopo.

## Preparar o ambiente

Use Python 3.12 e `uv`. Na raiz do repositório:

```powershell
uv sync --frozen --extra service --extra classical --extra cli
```

Configure `ORS_API_KEY` no `.env` somente se for trabalhar com planejamento viário. Nunca inclua credenciais ou dados operacionais no commit.

## Fazer uma alteração

- Crie uma branch `feat/<nome>` para funcionalidades ou `fix/<nome>` para correções. Não faça push diretamente para `main`.
- Mantenha o core independente de FastAPI, SQLAlchemy e Typer.
- Preserve custos canônicos inteiros, validação independente das rotas, capacidades heterogêneas e seleção explícita do backend.
- Não substitua falhas de consulta viária por distâncias em linha reta.
- Inclua testes de regressão para mudanças de comportamento, especialmente transições de jobs, prazos, capacidades e falhas de provedores.
- Use mocks HTTP para testes determinísticos. Chamadas reais ao openrouteservice consomem quota e só devem ser feitas quando explicitamente solicitadas.
- Atualize a documentação afetada e `docs/status.md` quando o estado do projeto mudar.

## Verificações locais

Antes de abrir o pull request, execute:

```powershell
uv run ruff check src tests migrations scripts
uv run ruff format --check src tests migrations scripts
uv run mypy src
uv run pytest --cov=quantum_route_core
uv build
```

Inclua no pull request quais verificações executou e informe qualquer limitação. Não descreva testes mockados como validação com dados viários reais.

## Pull requests e commits

Abra um pull request para `main`, descrevendo o problema, a mudança, a validação e as limitações. Inclua screenshots para mudanças no mapa. Use mensagens de commit curtas e imperativas. Todo commit deve terminar com esta linha:

```text
Co-authored-by: codex <codex@openai.com>
```

Ao submeter uma contribuição intencionalmente, você confirma que tem o direito de fazê-lo e que ela pode ser distribuída sob a licença MIT do projeto.
