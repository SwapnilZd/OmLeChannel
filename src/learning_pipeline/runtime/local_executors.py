from typing import Any

from learning_pipeline.runtime.execution import ExecutionContext


class EmitExecutor:
    async def execute(self, context: ExecutionContext) -> dict[str, Any]:
        return {"text": context.inputs["text"]}


class ConcatExecutor:
    async def execute(self, context: ExecutionContext) -> dict[str, str]:
        return {"text": f'{context.inputs["left"]}{context.inputs["right"]}'}
