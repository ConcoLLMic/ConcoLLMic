from litellm import ChatCompletionToolParam, ChatCompletionToolParamFunctionChunk

# Define the schema for the BatchTool
BatchTool = ChatCompletionToolParam(
    type="function",
    function=ChatCompletionToolParamFunctionChunk(
        name="batch_tool",
        description="Invoke multiple other tool calls simultaneously. This tool wraps other available tools.",
        parameters={
            "type": "object",
            "properties": {
                "invocations": {
                    "type": "array",
                    "description": "The individual tool calls to invoke in parallel.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "tool_name": {
                                "type": "string",
                                "description": "The name of the tool to invoke",
                            },
                            "arguments": {
                                "type": "object",
                                "description": "The arguments for the specified tool, conforming to its input schema.",
                            },
                        },
                        "required": ["tool_name", "arguments"],
                    },
                }
            },
            "required": ["invocations"],
        },
    ),
)
