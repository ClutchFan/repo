import json
from . import PLAN_SCHEMA, CLAIMS_SCHEMA, VERDICT_SCHEMA


class LLMClient:
    def __init__(self, openai_client, model: str):
        self._c = openai_client
        self.model = model

    def complete_json(self, system: str, messages: list[dict], schema: dict,
                      tools: list[dict] | None = None) -> dict:
        resp = self._c.chat.completions.create(
            model=self.model,
            messages=[{"role": "system", "content": system}] + messages,
            response_format={"type": "json_schema", "json_schema": {
                "name": "result", "strict": True, "schema": schema}},
            tools=tools or None)
        return json.loads(resp.choices[0].message.content)
