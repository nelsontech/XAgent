from typing import List
from XAgent.agent.plan_generate_agent import PlanGenerateAgent
from XAgent.utils import RequiredAbilities, LLMStatusCode
from XAgent.agent.utils import _chat_completion_request
from XAgent.message_history import Message

class PlanReferDBAgent(PlanGenerateAgent):
    abilities = set([RequiredAbilities.plan_interact_db])

    def parse(
        self,
        placeholders: dict = {},
        functions=None,
        function_call=None,
        stop=None,
        additional_messages: List[Message] = [],
        *args,
        **kwargs
    ):

        prompt_messages = self.fill_in_placeholders(placeholders)
        
        output = _chat_completion_request(
            messages=prompt_messages + additional_messages,
            functions=functions,
            function_call=function_call,
            model=self.config.model,
            stop=stop,
            *args,
            **kwargs
        )

        message = output["choices"][0]["message"]
        tokens = output["usage"]
        print(tokens)

        return LLMStatusCode.SUCCESS, message, tokens