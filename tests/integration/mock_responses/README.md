Integration mock scenarios live here as one file per `INT-###` case.
This directory is a compatibility/replay corpus, not the canonical authoring
surface for new fixture semantics. Author new fixture meaning in typed schema
helpers and serialize it to YAML at the edge.

- Name each scenario file `INT-###.yaml`.
- Keep large `write_file` payloads in adjacent fixture files and reference them with `tool_args.content_file`.
- Every `entry_*` fixture directory must also include backend-owned
  `.manifests/current_role.json` with the active role for that node.
- When a payload matches a reusable starter template, prefer `tool_args.template_file` and store the body once in `shared/agent_templates/`; template file paths resolve relative to `shared/agent_templates/`.
- `content_file` paths resolve relative to this directory.
- The loader fails closed on invalid IDs, duplicate IDs, missing fixture files, or invalid transcript schema.
- Use `scripts/normalize_integration_mock_responses.py` to normalize deterministic derived fields in compatibility snapshots generated from typed schema helpers.
- Use `scripts/validate_integration_mock_response_preflight.py` to run transcript/schema validation plus node-entry preflight over the mock-response compatibility corpus.
